TEMPLATES = {
    "echo_bot": {
        "name": "📢 Simple Echo & Info Bot",
        "description": "Echoes messages back to the user and displays user & chat details.",
        "code": r"""import os
import logging
from telegram import Update
from telegram.helpers import escape_markdown
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("EchoBot")
TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Hello {user.first_name}!\n\n"
        "I am an Echo & Info Bot hosted 24/7 on Gravix-Host.\n"
        "• Send me any text and I will echo it back\n"
        "• Send /info to view your Telegram details"
    )

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    name = escape_markdown(user.full_name or "", version=1)
    uname = escape_markdown(user.username, version=1) if user.username else "None"
    await update.message.reply_text(
        f"ℹ️ *User Information:*\n"
        f"• User ID: `{user.id}`\n"
        f"• Name: {name}\n"
        f"• Username: @{uname}\n"
        f"• Chat ID: `{chat.id}`",
        parse_mode="Markdown"
    )

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        await update.message.reply_text(f"🔊 Echo: {update.message.text}")

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Update error: %s", context.error)

if __name__ == '__main__':
    print("Starting Echo Bot on Gravix-Host...")
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable not found!")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    app.add_error_handler(on_error)
    app.run_polling(drop_pending_updates=True)
"""
    },
    "welcome_bot": {
        "name": "🛡️ Group Welcome Bot",
        "description": "Automatically greets every new member who joins your group.",
        "code": r"""import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("WelcomeBot")
TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hello! I am a Group Welcome Bot hosted on Gravix-Host.\n"
        "Add me to your group and I will automatically welcome every new member!"
    )

async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            await update.message.reply_text("🎉 Thanks for adding me! I will now welcome new members here.")
        else:
            uname = f" (@{member.username})" if member.username else ""
            await update.message.reply_text(f"👋 Welcome, {member.full_name}{uname}! Glad to have you here.")

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Update error: %s", context.error)

if __name__ == '__main__':
    print("Starting Welcome Bot on Gravix-Host...")
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable not found!")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members))
    app.add_error_handler(on_error)
    app.run_polling(drop_pending_updates=True)
"""
    },
    "broadcast_bot": {
        "name": "📣 Broadcast Bot (Owner-Only)",
        "description": "Collects subscribers and lets the bot owner broadcast a message to everyone.",
        "code": r"""import os
import json
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("BroadcastBot")
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)

SUBS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subscribers.json")

def load_subscribers():
    try:
        with open(SUBS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_subscribers(subs):
    try:
        with open(SUBS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(subs), f)
    except Exception as e:
        logger.error("Could not save subscribers: %s", e)

subscribers = load_subscribers()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in subscribers:
        subscribers.add(user_id)
        save_subscribers(subscribers)
    if user_id == OWNER_ID:
        await update.message.reply_text(
            "👋 Welcome, owner! You are subscribed.\n"
            "• Broadcast to everyone: /broadcast <message>\n"
            "• Subscriber count: /stats"
        )
    else:
        await update.message.reply_text(
            "👋 Welcome! You are now subscribed and will receive updates from this bot."
        )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔ This command is for the bot owner only.")
        return
    await update.message.reply_text(f"📊 Total active subscribers: {len(subscribers)}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔ You are not authorized to broadcast.")
        return
    if not context.args:
        await update.message.reply_text("⚠️ Usage: /broadcast <message>")
        return
    msg = " ".join(context.args)
    sent, failed = 0, 0
    for uid in list(subscribers):
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 Broadcast:\n\n{msg}")
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"✅ Broadcast sent to {sent} subscriber(s). Failed: {failed}.")

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Update error: %s", context.error)

if __name__ == '__main__':
    print("Starting Broadcast Bot on Gravix-Host...")
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable not found!")
    if not OWNER_ID:
        print("WARNING: OWNER_ID not set; the broadcast command will be locked for everyone.")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_error_handler(on_error)
    app.run_polling(drop_pending_updates=True)
"""
    }
}


def get_template_by_name(display_name: str) -> tuple[str, dict] | None:
    """Lookup a template by its display name, emoji/title substring, or key.
    Returns (key, template_dict) or None if not found.
    """
    if not display_name or not isinstance(display_name, str):
        return None
    name_clean = display_name.strip()

    # 1. Exact match on display name
    for key, tinfo in TEMPLATES.items():
        if tinfo.get("name") == name_clean:
            return key, tinfo

    # 2. Case-insensitive / whitespace-stripped display name match
    for key, tinfo in TEMPLATES.items():
        if tinfo.get("name", "").strip().lower() == name_clean.lower():
            return key, tinfo

    # 3. Direct key match (e.g. 'echo_bot', 'welcome_bot', 'broadcast_bot')
    if name_clean in TEMPLATES:
        return name_clean, TEMPLATES[name_clean]

    # 4. Substring match (e.g. matching 'Echo' or 'Welcome' or 'Broadcast')
    for key, tinfo in TEMPLATES.items():
        if name_clean.lower() in tinfo.get("name", "").lower() or name_clean.lower() in key.lower():
            return key, tinfo

    return None
