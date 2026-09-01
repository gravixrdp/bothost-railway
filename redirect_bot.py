"""
Gravix-Host Redirect & Migration Bot
Runs on @gravixvpsbot to direct all users to the main hosting platform @gravixhostbot.
"""

import os
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Fallback to provided token if not in environment
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8318430595:AAFXAXhOwZyIS7oEXgGyXULTGWvomuVwGGU")

MESSAGE_TEXT = (
    "<b>⚡ GRAVIX-HOST — PLATFORM UPGRADE</b>\n"
    "<i>100% Free Cloud Telegram Bot Hosting</i>\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "👋 <b>Looking to Host Your Telegram Bot?</b>\n\n"
    "<blockquote>We have upgraded our platform to <b>@gravixhostbot</b>!\n"
    "Deploy and run your Python Telegram bots 24/7 on high-speed cloud infrastructure — completely free forever.</blockquote>\n\n"
    "<b>🚀 Key Platform Features:</b>\n"
    "<blockquote>• ⚡ <b>100% Free 24/7 Hosting</b> (Zero cost, 99.9% uptime)\n"
    "• 🔄 <b>Watchdog Auto-Healing</b> (Auto-restarts crashed bots)\n"
    "• 📦 <b>1-Click Templates</b> (Ready-to-use bot templates)\n"
    "• 💾 <b>Live Console Logs & .env Manager</b>\n"
    "• 🎁 <b>Referral Rewards</b> (Earn extra permanent slots)</blockquote>\n\n"
    "👉 <b>Start Hosting Your Bot Here:</b>\n"
    "🔗 <a href=\"https://t.me/gravixhostbot\">@gravixhostbot</a>"
)

def get_redirect_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🚀 Open @gravixhostbot 🚀", url="https://t.me/gravixhostbot")],
        [
            InlineKeyboardButton("📢 Community Channel", url="https://t.me/GravixRDP"),
            InlineKeyboardButton("💬 Support Desk", url="https://t.me/Dravonnbot")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /start, /help and initial greetings."""
    if update.message:
        await update.message.reply_text(
            text=MESSAGE_TEXT,
            parse_mode="HTML",
            reply_markup=get_redirect_keyboard(),
            disable_web_page_preview=True
        )

async def any_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responds to any text/media message with the redirect card."""
    if update.message:
        await update.message.reply_text(
            text=MESSAGE_TEXT,
            parse_mode="HTML",
            reply_markup=get_redirect_keyboard(),
            disable_web_page_preview=True
        )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gracefully handles callback queries."""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text=MESSAGE_TEXT,
            parse_mode="HTML",
            reply_markup=get_redirect_keyboard(),
            disable_web_page_preview=True
        )

def main():
    if not BOT_TOKEN:
        logger.error("No BOT_TOKEN provided!")
        return

    logger.info("Starting Gravix Redirect Bot for @gravixvpsbot...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler(["start", "help", "info", "host"], start_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, any_message_handler))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
