TEMPLATES = {
    "echo_bot": {
        "name": "📢 Simple Echo & Info Bot",
        "description": "Echoes messages back to the user and displays user & chat details.",
        "code": """import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Hello {user.first_name}!\n\n"
        "I am an Echo & Info Bot hosted 24/7 on Gravix-Host.\n"
        "• Send me any text to echo it\n"
        "• Send /info to view your Telegram ID"
    )

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    await update.message.reply_text(
        f"ℹ️ **User Information:**\n"
        f"• User ID: `{user.id}`\n"
        f"• Name: {user.full_name}\n"
        f"• Username: @{user.username or 'None'}\n"
        f"• Chat ID: `{chat.id}`",
        parse_mode="Markdown"
    )

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        await update.message.reply_text(f"🔊 Echo: {update.message.text}")

if __name__ == '__main__':
    print("Starting Echo Bot on Gravix-Host...")
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable not found!")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    app.run_polling(drop_pending_updates=True)
"""
    },
    "welcome_bot": {
        "name": "🛡️ Group Welcome & Admin Bot",
        "description": "Greets new members in groups and helps moderate chat.",
        "code": """import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hello! I am the Group Welcome & Guard Bot hosted on Gravix-Host.\n"
        "Add me to your group with admin rights to automatically welcome new members!"
    )

async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            await update.message.reply_text("🎉 Thanks for adding me to the group! Make sure to give me admin permissions.")
        else:
            uname = f"(@{member.username})" if member.username else ""
            await update.message.reply_text(f"👋 Welcome to the group, {member.full_name} {uname}! Enjoy your stay.")

if __name__ == '__main__':
    print("Starting Welcome Bot on Gravix-Host...")
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable not found!")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members))
    app.run_polling(drop_pending_updates=True)
"""
    },
    "broadcast_bot": {
        "name": "📣 Channel / Admin Broadcast Bot",
        "description": "Collects user IDs and allows the bot owner to broadcast messages to all subscribers.",
        "code": """import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
TOKEN = os.getenv("BOT_TOKEN")
subscribers = set()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    subscribers.add(user_id)
    await update.message.reply_text(
        "👋 Welcome! You are now subscribed to broadcasts from this bot.\n"
        "• Owner Command: `/broadcast <message>`\n"
        "• View Count: `/stats`",
        parse_mode="Markdown"
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📊 Total Active Subscribers: `{len(subscribers)}`", parse_mode="Markdown")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/broadcast <message>`", parse_mode="Markdown")
        return
    msg = " ".join(context.args)
    count = 0
    for uid in list(subscribers):
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 **Broadcast:**\n\n{msg}", parse_mode="Markdown")
            count += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ Broadcast delivered to `{count}` subscribers.", parse_mode="Markdown")

if __name__ == '__main__':
    print("Starting Broadcast Bot on Gravix-Host...")
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable not found!")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.run_polling(drop_pending_updates=True)
"""
    }
}
