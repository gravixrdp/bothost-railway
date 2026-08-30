TEMPLATES = {
    "echo_bot": {
        "name": "📢 Simple Echo & Info Bot",
        "description": "Echoes messages back to the user and displays user/chat ID.",
        "code": """import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"👋 Hello {update.effective_user.first_name}!\nI am an Echo Bot hosted on Gravix-Host.\nSend me any message and I will echo it!")

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    await update.message.reply_text(f"ℹ️ User ID: {user.id}\nUsername: @{user.username}\nChat ID: {chat.id}\nType: {chat.type}")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text:
        await update.message.reply_text(f"🔊 Echo: {update.message.text}")

if __name__ == '__main__':
    print("Starting Echo Bot on Gravix-Host...")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    app.run_polling()
"""
    },
    "welcome_bot": {
        "name": "🛡️ Group Welcome & Admin Bot",
        "description": "Greets new members in groups and helps delete spam commands.",
        "code": """import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ChatMemberHandler, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 I am the Group Welcome Bot hosted on Gravix-Host! Add me to your group with admin rights to welcome new members.")

async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        await update.message.reply_text(f"🎉 Welcome to the group, {member.full_name} (@{member.username or 'no-username'})! Please follow the group rules.")

if __name__ == '__main__':
    print("Starting Welcome Bot on Gravix-Host...")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()
"""
    },
    "broadcast_bot": {
        "name": "📣 Channel / Admin Broadcast Bot",
        "description": "Collects user IDs and allows the bot owner to broadcast messages to all users.",
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
    await update.message.reply_text("👋 You have subscribed to broadcasts from this bot!")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📊 Total Subscribers: {len(subscribers)}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    count = 0
    for uid in list(subscribers):
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 Broadcast:\n\n{msg}")
            count += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ Sent broadcast to {count} users.")

if __name__ == '__main__':
    print("Starting Broadcast Bot on Gravix-Host...")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.run_polling()
"""
    }
}
