import os
import sys
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Token is injected automatically by Gravix-Host or loaded from environment
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_name = user.first_name if user else "Friend"
    
    keyboard = [
        [
            InlineKeyboardButton("⚡ Ping Server", callback_data="btn_ping"),
            InlineKeyboardButton("📊 System Info", callback_data="btn_info")
        ],
        [
            InlineKeyboardButton("🚀 Gravix-Host", url="https://t.me/GravixRDP")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        f"👋 <b>Hello, {user_name}!</b>\n\n"
        "🎉 <i>Your custom Telegram Bot (@automation_reel_robot) is running 24/7 on Gravix Dedicated Cloud Hosting!</i>\n\n"
        "<b>Available Commands:</b>\n"
        "• /start - Launch this interactive menu\n"
        "• /ping - Measure response latency\n"
        "• /info - View runtime environment data\n"
        "• <i>Or simply send any text message to test instant echo!</i>"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏓 <b>Pong!</b> <i>Server is live and healthy with ultra-low latency.</i>", parse_mode="HTML")

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import platform
    py_ver = platform.python_version()
    os_info = platform.system()
    text = (
        "<b>📊 Host Telemetry & Environment:</b>\n\n"
        f"• <b>Python Version:</b> <code>{py_ver}</code>\n"
        f"• <b>Platform OS:</b> <code>{os_info}</code>\n"
        f"• <b>Process PID:</b> <code>{os.getpid()}</code>\n"
        "• <b>Status:</b> 🟢 <code>ONLINE (Watchdog Active)</code>"
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "btn_ping":
        await query.edit_message_text("🏓 <b>Pong!</b> Response latency: <i>Fast & Reactive!</i>", parse_mode="HTML")
    elif query.data == "btn_info":
        import platform
        py_ver = platform.python_version()
        text = (
            "<b>📊 Bot Instance Diagnostics:</b>\n\n"
            f"• <b>Engine:</b> Python {py_ver}\n"
            f"• <b>PID:</b> {os.getpid()}\n"
            "• <b>Hosting:</b> Gravix Dedicated Cloud"
        )
        await query.edit_message_text(text, parse_mode="HTML")

async def echo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text
    await update.message.reply_text(f"🤖 <b>Echo:</b> {text}", parse_mode="HTML")

def main():
    if not BOT_TOKEN:
        logger.error("No BOT_TOKEN found!")
        sys.exit(1)
        
    logger.info("Starting Custom Test Bot on Gravix Cloud...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping_command))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_handler))
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
