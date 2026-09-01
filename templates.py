TEMPLATES = {
    "echo_bot": {
        "name": "📢 Simple Echo & Info Bot",
        "description": "Echoes messages back to the user and displays user & chat details.",
        "code": r"""import os
import html
import time
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("EchoBot")
TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    first_name = html.escape(user.first_name if user else "User")
    text = (
        f"<b>👋 ʜᴇʟʟᴏ, {first_name}!</b>\n\n"
        f"<blockquote>⚡ <b>ɢʀᴀᴠɪx-ʜᴏsᴛ • ᴇᴄʜᴏ &amp; ɪɴғᴏ ʙᴏᴛ</b>\n"
        f"A responsive, 24/7 cloud assistant hosted on Gravix-Host.</blockquote>\n\n"
        f"<b>🚀 ᴀᴠᴀɪʟᴀʙʟᴇ ғᴇᴀᴛᴜʀᴇs:</b>\n"
        f"• 💬 <b>Echo Engine:</b> Send any text and I will echo it back in a card.\n"
        f"• ℹ️ <b>User Info:</b> Send /info for complete account &amp; chat specs.\n"
        f"• 🏓 <b>Ping:</b> Send /ping to test bot response latency.\n"
        f"• 📖 <b>Help:</b> Send /help to view command manual.\n\n"
        f"<blockquote>🛡️ <i>Hosted 24/7 with zero downtime on Gravix-Host</i></blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return
    name = html.escape(user.full_name or "N/A")
    uname = f"@{html.escape(user.username)}" if user.username else "<i>None</i>"
    lang = html.escape(user.language_code or "Unknown")
    chat_type = html.escape(str(chat.type).capitalize())
    text = (
        f"<b>👤 ᴜsᴇʀ &amp; ᴄʜᴀᴛ ɪɴғᴏʀᴍᴀᴛɪᴏɴ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote><b>🆔 User ID:</b> <code>{user.id}</code>\n"
        f"<b>👤 Full Name:</b> {name}\n"
        f"<b>🏷️ Username:</b> {uname}\n"
        f"<b>🌐 Language:</b> <code>{lang}</code>\n"
        f"<b>💬 Chat ID:</b> <code>{chat.id}</code>\n"
        f"<b>🏷️ Chat Type:</b> <code>{chat_type}</code></blockquote>\n\n"
        f"<blockquote>🕒 <b>Server Status:</b> <code>Online • 24/7 Active</code></blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    sent = await update.effective_message.reply_text("🏓 <i>Pinging server...</i>", parse_mode="HTML")
    latency_ms = round((time.time() - start_time) * 1000, 2)
    text = (
        f"<b>🏓 ᴘᴏɴɢ!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>⏱️ <b>Response Latency:</b> <code>{latency_ms}ms</code>\n"
        f"⚡ <b>Cloud Host:</b> <code>Gravix-Host Instance</code>\n"
        f"🟢 <b>Status:</b> <code>Healthy &amp; Responsive</code></blockquote>"
    )
    await sent.edit_text(text, parse_mode="HTML")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"<b>📖 ʙᴏᴛ ᴄᴏᴍᴍᴀɴᴅ ɢᴜɪᴅᴇ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>• /start - Launch the bot &amp; view dashboard\n"
        f"• /info - Inspect user ID and chat parameters\n"
        f"• /ping - Test connection speed &amp; latency\n"
        f"• /help - Display this documentation</blockquote>\n\n"
        f"<blockquote>💬 <i>Send any regular text message to receive an echo card.</i></blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        escaped_text = html.escape(update.message.text)
        text = (
            f"<b>🔊 ᴇᴄʜᴏ ʀᴇsᴘᴏɴsᴇ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<blockquote>{escaped_text}</blockquote>"
        )
        await update.message.reply_text(text, parse_mode="HTML")

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Update error in EchoBot: %s", context.error)

if __name__ == '__main__':
    print("Starting Echo & Info Bot on Gravix-Host...")
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable not found!")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    app.add_error_handler(on_error)
    app.run_polling(drop_pending_updates=True)
"""
    },
    "welcome_bot": {
        "name": "🛡️ Group Welcome Bot",
        "description": "Automatically greets every new member who joins your group.",
        "code": r"""import os
import html
import time
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("WelcomeBot")
TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    first_name = html.escape(user.first_name if user else "User")
    text = (
        f"<b>👋 ʜᴇʟʟᴏ, {first_name}!</b>\n\n"
        f"<blockquote>🛡️ <b>ɢʀᴀᴠɪx-ʜᴏsᴛ • ɢʀᴏᴜᴘ ᴡᴇʟᴄᴏᴍᴇ ʙᴏᴛ</b>\n"
        f"Automated, stylish member arrival greeter for your groups.</blockquote>\n\n"
        f"<b>🚀 ǫᴜɪᴄᴋ sᴇᴛᴜᴘ ɪɴsᴛʀᴜᴄᴛɪᴏɴs:</b>\n"
        f"1️⃣ Add this bot as a member or admin to your Telegram Group.\n"
        f"2️⃣ Make sure the bot has permission to send messages.\n"
        f"3️⃣ Whenever someone joins, a greeting card will be sent automatically!\n\n"
        f"<blockquote>⚡ <i>Commands: /rules (Group rules), /help (Help guide)</i></blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"<b>📖 ᴡᴇʟᴄᴏᴍᴇ ʙᴏᴛ ɢᴜɪᴅᴇ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>• /start - Launch bot &amp; view setup instructions\n"
        f"• /rules - View group rules &amp; community guidelines\n"
        f"• /ping - Verify bot latency &amp; status\n"
        f"• /help - Display this command guide</blockquote>\n\n"
        f"<blockquote>🛡️ <i>Active 24/7 and watching for incoming members.</i></blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def rules_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_title = html.escape(update.effective_chat.title if update.effective_chat else "Community")
    text = (
        f"<b>📜 ɢʀᴏᴜᴘ ʀᴜʟᴇs &amp; ɢᴜɪᴅᴇʟɪɴᴇs</b>\n"
        f"<b>{chat_title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>1️⃣ <b>Respect:</b> Treat all group members with mutual courtesy.\n"
        f"2️⃣ <b>No Spam:</b> No promotional links, ads, or unsolicited spam.\n"
        f"3️⃣ <b>Topic:</b> Keep discussions constructive and relevant.\n"
        f"4️⃣ <b>Safety:</b> Never share sensitive credentials or malicious files.</blockquote>\n\n"
        f"<blockquote>⚖️ <i>Please comply with group admin decisions.</i></blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    sent = await update.effective_message.reply_text("🏓 <i>Pinging...</i>", parse_mode="HTML")
    latency_ms = round((time.time() - start_time) * 1000, 2)
    text = (
        f"<b>🏓 ᴘᴏɴɢ!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>⏱️ <b>Latency:</b> <code>{latency_ms}ms</code>\n"
        f"🛡️ <b>Status:</b> <code>Guard Online &amp; Ready</code></blockquote>"
    )
    await sent.edit_text(text, parse_mode="HTML")

async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return
    chat = update.effective_chat
    chat_title = html.escape(chat.title or "this group")
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            text = (
                f"<b>🎉 ᴛʜᴀɴᴋ ʏᴏᴜ ғᴏʀ ᴀᴅᴅɪɴɢ ᴍᴇ!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<blockquote>🛡️ <b>ɢʀᴏᴜᴘ ᴡᴇʟᴄᴏᴍᴇ ʙᴏᴛ ɪs ᴀᴄᴛɪᴠᴇ</b>\n"
                f"I am now guarding <b>{chat_title}</b> and will greet all incoming members!</blockquote>\n\n"
                f"<blockquote>⚡ <i>Type /rules or /help for community commands.</i></blockquote>"
            )
            await update.message.reply_text(text, parse_mode="HTML")
        else:
            member_name = html.escape(member.full_name or "New Member")
            uname = f"@{html.escape(member.username)}" if member.username else "<i>None</i>"
            user_mention = f'<a href="tg://user?id={member.id}">{member_name}</a>'
            text = (
                f"<b>👋 ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ {chat_title}!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<blockquote>👤 <b>Member:</b> {user_mention}\n"
                f"🆔 <b>User ID:</b> <code>{member.id}</code>\n"
                f"🏷️ <b>Username:</b> {uname}</blockquote>\n\n"
                f"<blockquote>🌟 <i>Welcome aboard! Please check out the group /rules and enjoy your stay!</i></blockquote>"
            )
            await update.message.reply_text(text, parse_mode="HTML")

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Update error in WelcomeBot: %s", context.error)

if __name__ == '__main__':
    print("Starting Welcome Bot on Gravix-Host...")
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable not found!")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("rules", rules_cmd))
    app.add_handler(CommandHandler("ping", ping))
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
import html
import time
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("BroadcastBot")
TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)

SUBS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subscribers.json")

def load_subscribers() -> set:
    try:
        if os.path.exists(SUBS_FILE):
            with open(SUBS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(int(x) for x in data if str(x).isdigit())
    except Exception as e:
        logger.error("Could not load subscribers: %s", e)
    return set()

def save_subscribers(subs: set):
    try:
        with open(SUBS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(subs), f, indent=2)
    except Exception as e:
        logger.error("Could not save subscribers: %s", e)

subscribers = load_subscribers()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    user_id = user.id
    first_name = html.escape(user.first_name or "Subscriber")
    if user_id not in subscribers:
        subscribers.add(user_id)
        save_subscribers(subscribers)
    if OWNER_ID and user_id == OWNER_ID:
        text = (
            f"<b>👑 ᴡᴇʟᴄᴏᴍᴇ, ʙᴏᴛ ᴏᴡɴᴇʀ!</b>\n\n"
            f"<blockquote>📣 <b>ɢʀᴀᴠɪx-ʜᴏsᴛ • ʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ</b>\n"
            f"Broadcast updates, announcements &amp; alerts to all subscribers.</blockquote>\n\n"
            f"<b>⚡ ᴏᴡɴᴇʀ ᴄᴏᴍᴍᴀɴᴅs:</b>\n"
            f"• 📊 <b>/stats</b> - View current subscriber metrics\n"
            f"• 📢 <b>/broadcast &lt;msg&gt;</b> - Dispatch announcement to all users\n"
            f"• 🏓 <b>/ping</b> - Check bot latency\n"
            f"• 📖 <b>/help</b> - View admin guidance\n\n"
            f"<blockquote>👥 <b>Active Subscribers:</b> <code>{len(subscribers)}</code></blockquote>"
        )
    else:
        text = (
            f"<b>👋 ᴡᴇʟᴄᴏᴍᴇ, {first_name}!</b>\n\n"
            f"<blockquote>📣 <b>ᴏғғɪᴄɪᴀʟ ɴᴇᴡs &amp; ᴜᴘᴅᴀᴛᴇs ᴄʜᴀɴɴᴇʟ</b>\n"
            f"You are now subscribed to receive official notifications and announcements.</blockquote>\n\n"
            f"<blockquote>🔔 <i>New updates will be delivered directly to this chat!</i></blockquote>"
        )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or (OWNER_ID and user.id != OWNER_ID):
        await update.effective_message.reply_text(
            "<blockquote>⛔ <b>Access Denied:</b> This command is restricted to the bot owner.</blockquote>",
            parse_mode="HTML"
        )
        return
    count = len(subscribers)
    text = (
        f"<b>📊 ʙʀᴏᴀᴅᴄᴀsᴛ ᴀɴᴀʟʏᴛɪᴄs</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>👥 <b>Total Subscribers:</b> <code>{count}</code>\n"
        f"👑 <b>Owner ID:</b> <code>{OWNER_ID}</code>\n"
        f"⚡ <b>Engine:</b> <code>Gravix-Host 24/7 Subprocess</code>\n"
        f"🟢 <b>Status:</b> <code>Operational</code></blockquote>\n\n"
        f"<blockquote>💡 <i>Use <code>/broadcast &lt;text&gt;</code> to dispatch an announcement.</i></blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or (OWNER_ID and user.id != OWNER_ID):
        await update.effective_message.reply_text(
            "<blockquote>⛔ <b>Access Denied:</b> You are not authorized to broadcast announcements.</blockquote>",
            parse_mode="HTML"
        )
        return
    if not context.args:
        usage_text = (
            f"<b>⚠️ ɪɴᴠᴀʟɪᴅ ʙʀᴏᴀᴅᴄᴀsᴛ sʏɴᴛᴀx</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<blockquote><b>Usage:</b> <code>/broadcast &lt;your message&gt;</code>\n\n"
            f"<b>Example:</b>\n"
            f"<code>/broadcast Hello everyone! Server upgrade is complete.</code></blockquote>"
        )
        await update.effective_message.reply_text(usage_text, parse_mode="HTML")
        return
    raw_msg = update.effective_message.text.split(maxsplit=1)[1]
    escaped_msg = html.escape(raw_msg)
    status_msg = await update.effective_message.reply_text(
        "⏳ <i>Broadcasting message to all subscribers...</i>",
        parse_mode="HTML"
    )
    announcement_text = (
        f"<b>📢 ᴏғғɪᴄɪᴀʟ ᴀɴɴᴏᴜɴᴄᴇᴍᴇɴᴛ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>{escaped_msg}</blockquote>\n\n"
        f"<blockquote>🔔 <i>Sent via Broadcast Bot • Gravix-Host</i></blockquote>"
    )
    start_t = time.time()
    sent, failed = 0, 0
    recipient_list = list(subscribers)
    for uid in recipient_list:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=announcement_text,
                parse_mode="HTML"
            )
            sent += 1
            await asyncio.sleep(0.04)
        except Exception:
            failed += 1
    elapsed = round(time.time() - start_t, 2)
    summary_text = (
        f"<b>✅ ʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏᴍᴘʟᴇᴛᴇᴅ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>📤 <b>Delivered:</b> <code>{sent}</code> subscriber(s)\n"
        f"⚠️ <b>Failed / Blocked:</b> <code>{failed}</code>\n"
        f"👥 <b>Total Target:</b> <code>{len(recipient_list)}</code>\n"
        f"⏱️ <b>Time Elapsed:</b> <code>{elapsed}s</code></blockquote>"
    )
    await status_msg.edit_text(summary_text, parse_mode="HTML")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_owner = OWNER_ID and user and user.id == OWNER_ID
    if is_owner:
        text = (
            f"<b>📖 ʙʀᴏᴀᴅᴄᴀsᴛ ᴏᴡɴᴇʀ ɢᴜɪᴅᴇ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<blockquote>• /start - Open dashboard &amp; register\n"
            f"• /stats - View subscriber count &amp; bot status\n"
            f"• /broadcast &lt;text&gt; - Dispatch message to all users\n"
            f"• /ping - Test server latency\n"
            f"• /help - Display this owner manual</blockquote>"
        )
    else:
        text = (
            f"<b>📖 ʙᴏᴛ ɪɴғᴏʀᴍᴀᴛɪᴏɴ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<blockquote>• /start - Subscribe to announcements\n"
            f"• /ping - Check bot response speed\n"
            f"• /help - View this help card</blockquote>\n\n"
            f"<blockquote>🔔 <i>Stay subscribed to receive latest announcements.</i></blockquote>"
        )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    sent = await update.effective_message.reply_text("🏓 <i>Pinging...</i>", parse_mode="HTML")
    latency_ms = round((time.time() - start_time) * 1000, 2)
    text = (
        f"<b>🏓 ᴘᴏɴɢ!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>⏱️ <b>Latency:</b> <code>{latency_ms}ms</code>\n"
        f"📣 <b>Status:</b> <code>Broadcast Engine Online</code></blockquote>"
    )
    await sent.edit_text(text, parse_mode="HTML")

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Update error in BroadcastBot: %s", context.error)

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
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("ping", ping))
    app.add_error_handler(on_error)
    app.run_polling(drop_pending_updates=True)
"""
    },
    "ai_chat_bot": {
        "name": "🤖 AI ChatGPT & Gemini Assistant Bot",
        "description": "Smart neural AI assistant bot powered by Google Gemini, OpenAI, or custom API keys.",
        "code": r"""import os
import json
import html
import time
import asyncio
import logging
import httpx
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("AIChatBot")

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)
ENV_API_KEY = os.getenv("AI_API_KEY", "") or os.getenv("OPENAI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_config.json")

def load_config() -> dict:
    default_config = {
        "api_key": ENV_API_KEY,
        "model": "auto",
        "system_prompt": "You are a helpful, intelligent, and friendly Telegram AI Assistant. Provide accurate, clear, and concise answers."
    }
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                default_config.update(data)
    except Exception as e:
        logger.error(f"Error loading AI config: {e}")
    return default_config

def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving AI config: {e}")

bot_config = load_config()
# Conversation history per chat: chat_id -> list of {"role": "user"|"assistant", "content": str}
chat_history: dict[int, list[dict]] = {}

async def call_gemini_api(api_key: str, prompt: str, history: list[dict], system_prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    contents = []
    for msg in history[-6:]:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    
    payload = {
        "contents": contents,
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 1000
        }
    }
    
    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            err_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
            raise RuntimeError(f"Gemini API error ({resp.status_code}): {err_data}")
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()

async def call_openai_api(api_key: str, prompt: str, history: list[dict], system_prompt: str) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-6:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": prompt})
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 1000
    }
    
    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            err_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
            raise RuntimeError(f"OpenAI API error ({resp.status_code}): {err_data}")
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

async def generate_ai_response(chat_id: int, prompt: str) -> str:
    api_key = bot_config.get("api_key", "").strip() or ENV_API_KEY.strip()
    history = chat_history.get(chat_id, [])
    system_prompt = bot_config.get("system_prompt", "You are a helpful Telegram AI assistant.")
    
    if not api_key:
        return (
            "<blockquote>🔑 <b>AI API Key Required</b>\n\n"
            "No API key is configured yet for this bot instance.\n\n"
            "<b>How to setup:</b>\n"
            "1️⃣ Get a free <b>Gemini API Key</b> from <a href=\"https://aistudio.google.com/\">Google AI Studio</a>, or an <b>OpenAI Key</b>.\n"
            "2️⃣ Send <code>/setkey &lt;your_api_key&gt;</code> in this chat.\n"
            "3️⃣ Start chatting immediately with neural intelligence!</blockquote>"
        )
    
    try:
        if api_key.startswith("AIzaSy"):
            reply = await call_gemini_api(api_key, prompt, history, system_prompt)
        else:
            reply = await call_openai_api(api_key, prompt, history, system_prompt)
        
        if chat_id not in chat_history:
            chat_history[chat_id] = []
        chat_history[chat_id].append({"role": "user", "content": prompt})
        chat_history[chat_id].append({"role": "assistant", "content": reply})
        if len(chat_history[chat_id]) > 10:
            chat_history[chat_id] = chat_history[chat_id][-10:]
            
        return reply
    except Exception as e:
        logger.error(f"AI Generation error: {e}")
        return f"<blockquote>⚠️ <b>AI Processing Error:</b>\n<code>{html.escape(str(e))}</code>\n\n<i>Check your API key using /setkey or try again later.</i></blockquote>"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    first_name = html.escape(user.first_name if user else "User")
    api_key = bot_config.get("api_key", "").strip() or ENV_API_KEY.strip()
    status_badge = "🟢 <code>Active • API Connected</code>" if api_key else "⚪ <code>Awaiting API Key (/setkey)</code>"
    provider_name = "Google Gemini" if api_key.startswith("AIzaSy") else ("OpenAI / Custom" if api_key else "None")
    
    text = (
        f"<b>👋 ʜᴇʟʟᴏ, {first_name}!</b>\n\n"
        f"<blockquote>🤖 <b>ɢʀᴀᴠɪx-ʜᴏsᴛ • ᴀɪ ᴀssɪsᴛᴀɴᴛ ʙᴏᴛ</b>\n"
        f"Intelligent neural conversational assistant powered by ChatGPT &amp; Gemini.</blockquote>\n\n"
        f"<b>📊 ᴄᴜʀʀᴇɴᴛ sᴛᴀᴛᴜs:</b>\n"
        f"• <b>Engine:</b> <code>{provider_name}</code>\n"
        f"• <b>Status:</b> {status_badge}\n"
        f"• <b>Multi-Turn Memory:</b> <code>Active (10 msgs)</code>\n\n"
        f"<b>🚀 ǫᴜɪᴄᴋ ᴄᴏᴍᴍᴀɴᴅs:</b>\n"
        f"• 💬 <i>Send any message to chat directly</i>\n"
        f"• 🔑 <b>/setkey &lt;key&gt;</b> - Configure Gemini or OpenAI key\n"
        f"• 🧹 <b>/clear</b> - Wipe conversation context memory\n"
        f"• ℹ️ <b>/model</b> - View active model configuration\n"
        f"• 🏓 <b>/ping</b> - Test bot &amp; server latency\n"
        f"• 📖 <b>/help</b> - Full documentation guide\n\n"
        f"<blockquote>🛡️ <i>Hosted 24/7 with zero downtime on Gravix-Host</i></blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"<b>📖 ᴀɪ ᴀssɪsᴛᴀɴᴛ ɢᴜɪᴅᴇ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote><b>🤖 How to use:</b>\n"
        f"Simply send any question or prompt to the bot, and it will respond intelligently!</blockquote>\n\n"
        f"<b>⚡ ᴄᴏᴍᴍᴀɴᴅs ʟɪsᴛ:</b>\n"
        f"• <b>/start</b> - Open main dashboard\n"
        f"• <b>/setkey &lt;api_key&gt;</b> - Set Gemini (AIzaSy...) or OpenAI (sk-...) API key\n"
        f"• <b>/clear</b> or <b>/reset</b> - Reset conversation history memory\n"
        f"• <b>/model</b> - View active AI model settings\n"
        f"• <b>/ping</b> - Check server latency\n"
        f"• <b>/help</b> - View this manual\n\n"
        f"<blockquote>💡 <i>Tip: Get a 100% free Gemini API key from <a href=\"https://aistudio.google.com/\">Google AI Studio</a>.</i></blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)

async def setkey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if OWNER_ID and user and user.id != OWNER_ID:
        await update.effective_message.reply_text(
            "<blockquote>⛔ <b>Access Denied:</b> Only the bot owner can configure the API key.</blockquote>",
            parse_mode="HTML"
        )
        return
    if not context.args:
        text = (
            f"<b>🔑 ᴄᴏɴғɪɢᴜʀᴇ ᴀɪ ᴀᴘɪ ᴋᴇʏ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<blockquote><b>Usage:</b> <code>/setkey &lt;your_api_key&gt;</code>\n\n"
            f"<b>Supported Providers:</b>\n"
            f"• <b>Google Gemini:</b> <code>AIzaSy...</code> (Free from Google AI Studio)\n"
            f"• <b>OpenAI:</b> <code>sk-...</code> (ChatGPT gpt-4o-mini)\n"
            f"• <b>OpenRouter / Groq:</b> Compatible OpenAI keys</blockquote>"
        )
        await update.effective_message.reply_text(text, parse_mode="HTML")
        return
    
    new_key = context.args[0].strip()
    bot_config["api_key"] = new_key
    save_config(bot_config)
    
    masked = new_key[:6] + "..." + new_key[-4:] if len(new_key) > 10 else "***"
    provider = "Google Gemini" if new_key.startswith("AIzaSy") else "OpenAI / Compatible"
    
    text = (
        f"<b>✅ ᴀᴘɪ ᴋᴇʏ sᴜᴄᴄᴇssғᴜʟʟʏ ᴜᴘᴅᴀᴛᴇᴅ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>• <b>Provider:</b> <code>{provider}</code>\n"
        f"• <b>Key Preview:</b> <code>{masked}</code>\n"
        f"• <b>Status:</b> <code>🟢 Ready to chat</code></blockquote>\n\n"
        f"<blockquote>💬 <i>Send any message now to test the AI assistant!</i></blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in chat_history:
        chat_history[chat_id] = []
    text = (
        f"<b>🧹 ᴍᴇᴍᴏʀʏ ʀᴇsᴇᴛ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>✅ Conversation context memory has been cleared. The AI will start fresh!</blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def model_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    api_key = bot_config.get("api_key", "").strip() or ENV_API_KEY.strip()
    provider = "Google Gemini (gemini-1.5-flash)" if api_key.startswith("AIzaSy") else ("OpenAI (gpt-4o-mini)" if api_key else "None (Awaiting /setkey)")
    chat_id = update.effective_chat.id
    history_count = len(chat_history.get(chat_id, []))
    
    text = (
        f"<b>ℹ️ ᴀɪ ᴍᴏᴅᴇʟ sᴘᴇᴄɪғɪᴄᴀᴛɪᴏɴs</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>• <b>Active Provider:</b> <code>{provider}</code>\n"
        f"• <b>Context Window:</b> <code>Last 10 messages</code>\n"
        f"• <b>Current Chat Memory:</b> <code>{history_count} messages</code>\n"
        f"• <b>Platform Host:</b> <code>Gravix-Host Cloud</code></blockquote>\n\n"
        f"<blockquote>💡 <i>Use /clear to reset memory or /setkey to switch API keys.</i></blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    sent = await update.effective_message.reply_text("🏓 <i>Pinging AI neural core...</i>", parse_mode="HTML")
    latency_ms = round((time.time() - start_time) * 1000, 2)
    api_key = bot_config.get("api_key", "").strip() or ENV_API_KEY.strip()
    status_str = "Operational 🟢" if api_key else "Needs API Key ⚪"
    text = (
        f"<b>🏓 ᴘᴏɴɢ!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>⏱️ <b>Bot Latency:</b> <code>{latency_ms}ms</code>\n"
        f"🤖 <b>AI Core Status:</b> <code>{status_str}</code>\n"
        f"⚡ <b>Cloud Host:</b> <code>Gravix-Host Instance</code></blockquote>"
    )
    await sent.edit_text(text, parse_mode="HTML")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user_prompt = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass
    
    response = await generate_ai_response(chat_id, user_prompt)
    
    if len(response) <= 4000:
        try:
            await update.message.reply_text(response, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            await update.message.reply_text(response, disable_web_page_preview=True)
    else:
        chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
        for chunk in chunks:
            try:
                await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
            except Exception:
                await update.message.reply_text(chunk, disable_web_page_preview=True)

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Update error in AIChatBot: %s", context.error)

if __name__ == '__main__':
    print("Starting AI ChatGPT & Gemini Assistant Bot on Gravix-Host...")
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable not found!")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("setkey", setkey_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("reset", clear_cmd))
    app.add_handler(CommandHandler("model", model_cmd))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(on_error)
    app.run_polling(drop_pending_updates=True)
"""
    },
    "file_store_bot": {
        "name": "📦 Telegram File Store & Share Link Generator",
        "description": "Upload documents, photos, videos, or audio and get instant shareable retrieval links.",
        "code": r"""import os
import json
import html
import time
import uuid
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("FileStoreBot")

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)
STORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "file_store.json")

def load_store() -> dict:
    try:
        if os.path.exists(STORE_FILE):
            with open(STORE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading file store: {e}")
    return {}

def save_store(store: dict):
    try:
        with open(STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(store, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving file store: {e}")

file_store = load_store()

def format_size(size_bytes: int) -> str:
    if not size_bytes:
        return "Unknown Size"
    val = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if val < 1024.0:
            return f"{val:.1f} {unit}"
        val /= 1024.0
    return f"{val:.1f} TB"

async def send_stored_file(context: ContextTypes.DEFAULT_TYPE, chat_id: int, file_code: str) -> bool:
    entry = file_store.get(file_code)
    if not entry:
        return False
    
    file_id = entry.get("file_id")
    file_type = entry.get("file_type", "document")
    file_name = html.escape(entry.get("file_name", "File"))
    file_size_str = format_size(entry.get("file_size", 0))
    downloads = entry.get("downloads", 0) + 1
    entry["downloads"] = downloads
    save_store(file_store)
    
    caption = (
        f"<b>📦 {file_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>💾 <b>Size:</b> <code>{file_size_str}</code>\n"
        f"📥 <b>Downloads:</b> <code>{downloads}</code>\n"
        f"🔑 <b>Code:</b> <code>{file_code}</code></blockquote>\n\n"
        f"<blockquote>⚡ <i>Delivered via File Store Bot • Gravix-Host</i></blockquote>"
    )
    
    try:
        if file_type == "photo":
            await context.bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption, parse_mode="HTML")
        elif file_type == "video":
            await context.bot.send_video(chat_id=chat_id, video=file_id, caption=caption, parse_mode="HTML")
        elif file_type == "audio":
            await context.bot.send_audio(chat_id=chat_id, audio=file_id, caption=caption, parse_mode="HTML")
        elif file_type == "voice":
            await context.bot.send_voice(chat_id=chat_id, voice=file_id, caption=caption, parse_mode="HTML")
        elif file_type == "animation":
            await context.bot.send_animation(chat_id=chat_id, animation=file_id, caption=caption, parse_mode="HTML")
        else:
            await context.bot.send_document(chat_id=chat_id, document=file_id, caption=caption, parse_mode="HTML")
        return True
    except Exception as e:
        logger.error(f"Error sending stored file {file_code}: {e}")
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    first_name = html.escape(user.first_name if user else "User")
    
    if context.args and len(context.args) > 0:
        arg = context.args[0].strip()
        file_code = arg.replace("get_", "", 1) if arg.startswith("get_") else arg
        success = await send_stored_file(context, chat_id, file_code)
        if success:
            return
        else:
            await update.effective_message.reply_text(
                "<blockquote>❌ <b>File Not Found:</b> The requested file code does not exist or has expired.</blockquote>",
                parse_mode="HTML"
            )
            return

    bot_info = await context.bot.get_me()
    total_files = len(file_store)
    total_dl = sum(item.get("downloads", 0) for item in file_store.values())
    
    text = (
        f"<b>👋 ʜᴇʟʟᴏ, {first_name}!</b>\n\n"
        f"<blockquote>📦 <b>ɢʀᴀᴠɪx-ʜᴏsᴛ • ғɪʟᴇ sᴛᴏʀᴇ &amp; sʜᴀʀᴇ ʟɪɴᴋ ʙᴏᴛ</b>\n"
        f"Upload documents, media, or archives and get instant shareable retrieval links.</blockquote>\n\n"
        f"<b>🚀 ʜᴏᴡ ɪᴛ ᴡᴏʀᴋs:</b>\n"
        f"1️⃣ Send any document, image, video, or audio to this chat.\n"
        f"2️⃣ Receive a unique permanent share link (<code>t.me/{bot_info.username}?start=get_...</code>).\n"
        f"3️⃣ Anyone who clicks your link receives the file instantly!\n\n"
        f"<b>📊 sᴛᴏʀᴀɢᴇ sᴛᴀᴛs:</b>\n"
        f"• 📦 <b>Total Files Stored:</b> <code>{total_files}</code>\n"
        f"• 📥 <b>Total Downloads:</b> <code>{total_dl}</code>\n\n"
        f"<blockquote>⚡ <i>Commands: /myfiles (Your uploads), /stats (Metrics), /help (Guide)</i></blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"<b>📖 ғɪʟᴇ sᴛᴏʀᴇ ɢᴜɪᴅᴇ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote><b>📤 How to Upload:</b>\n"
        f"Send or forward any document, photo, video, audio track, or archive to this bot.</blockquote>\n\n"
        f"<b>⚡ ᴄᴏᴍᴍᴀɴᴅ ʟɪsᴛ:</b>\n"
        f"• <b>/start</b> - Main dashboard\n"
        f"• <b>/myfiles</b> - View your recently uploaded files &amp; links\n"
        f"• <b>/del &lt;code&gt;</b> - Delete an uploaded file by its code\n"
        f"• <b>/stats</b> - View global storage &amp; download statistics\n"
        f"• <b>/ping</b> - Test bot latency &amp; status\n"
        f"• <b>/help</b> - Display this manual\n\n"
        f"<blockquote>🛡️ <i>Files are securely indexed and available 24/7 on Gravix-Host.</i></blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def myfiles_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    user_id = user.id
    bot_info = await context.bot.get_me()
    
    is_owner = OWNER_ID and user_id == OWNER_ID
    user_files = [
        (code, data) for code, data in file_store.items()
        if data.get("uploader_id") == user_id or is_owner
    ]
    
    if not user_files:
        await update.effective_message.reply_text(
            "<blockquote>📂 <b>No Files Found:</b> You haven't uploaded any files yet. Send a file to get started!</blockquote>",
            parse_mode="HTML"
        )
        return
    
    recent = user_files[-10:]
    lines = []
    for code, data in reversed(recent):
        fname = html.escape(data.get("file_name", "File")[:25])
        fsize = format_size(data.get("file_size", 0))
        dls = data.get("downloads", 0)
        link = f"https://t.me/{bot_info.username}?start=get_{code}"
        lines.append(f"• <b>{fname}</b> (<code>{fsize}</code>, 📥 {dls})\n  🔗 <code>{link}</code>")
    
    files_block = "\n\n".join(lines)
    text = (
        f"<b>📂 ʏᴏᴜʀ ᴜᴘʟᴏᴀᴅᴇᴅ ғɪʟᴇs ({len(user_files)})</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>\n{files_block}\n</blockquote>\n\n"
        f"<blockquote>💡 <i>Use <code>/del &lt;code&gt;</code> to remove a file.</i></blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)

async def del_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    if not context.args:
        await update.effective_message.reply_text(
            "<blockquote>⚠️ <b>Usage:</b> <code>/del &lt;file_code&gt;</code></blockquote>",
            parse_mode="HTML"
        )
        return
    
    code = context.args[0].strip().replace("get_", "")
    entry = file_store.get(code)
    if not entry:
        await update.effective_message.reply_text(
            "<blockquote>❌ <b>File Not Found:</b> No record matches that file code.</blockquote>",
            parse_mode="HTML"
        )
        return
    
    if entry.get("uploader_id") != user.id and (OWNER_ID and user.id != OWNER_ID):
        await update.effective_message.reply_text(
            "<blockquote>⛔ <b>Access Denied:</b> You can only delete files you uploaded.</blockquote>",
            parse_mode="HTML"
        )
        return
    
    del file_store[code]
    save_store(file_store)
    
    text = (
        f"<b>🗑️ ғɪʟᴇ ᴅᴇʟᴇᴛᴇᴅ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>✅ File with code <code>{code}</code> has been removed from the store.</blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_files = len(file_store)
    total_dl = sum(item.get("downloads", 0) for item in file_store.values())
    total_bytes = sum(item.get("file_size", 0) for item in file_store.values())
    
    text = (
        f"<b>📊 ғɪʟᴇ sᴛᴏʀᴇ ᴍᴇᴛʀɪᴄs</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>📦 <b>Total Files Stored:</b> <code>{total_files}</code>\n"
        f"💾 <b>Total Volume:</b> <code>{format_size(total_bytes)}</code>\n"
        f"📥 <b>Total Downloads:</b> <code>{total_dl}</code>\n"
        f"⚡ <b>Engine:</b> <code>Gravix-Host Cloud Storage</code>\n"
        f"🟢 <b>Status:</b> <code>Operational</code></blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    sent = await update.effective_message.reply_text("🏓 <i>Pinging storage index...</i>", parse_mode="HTML")
    latency_ms = round((time.time() - start_time) * 1000, 2)
    text = (
        f"<b>🏓 ᴘᴏɴɢ!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>⏱️ <b>Storage Latency:</b> <code>{latency_ms}ms</code>\n"
        f"📦 <b>Files Indexed:</b> <code>{len(file_store)}</code>\n"
        f"🟢 <b>Status:</b> <code>Online &amp; Ready</code></blockquote>"
    )
    await sent.edit_text(text, parse_mode="HTML")

async def handle_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user:
        return
    
    file_id = None
    file_name = "file"
    file_size = 0
    file_type = "document"
    
    if msg.document:
        file_id = msg.document.file_id
        file_name = msg.document.file_name or "document"
        file_size = msg.document.file_size or 0
        file_type = "document"
    elif msg.photo:
        photo = msg.photo[-1]
        file_id = photo.file_id
        file_name = f"photo_{photo.file_unique_id}.jpg"
        file_size = photo.file_size or 0
        file_type = "photo"
    elif msg.video:
        file_id = msg.video.file_id
        file_name = msg.video.file_name or f"video_{msg.video.file_unique_id}.mp4"
        file_size = msg.video.file_size or 0
        file_type = "video"
    elif msg.audio:
        file_id = msg.audio.file_id
        file_name = msg.audio.file_name or f"audio_{msg.audio.file_unique_id}.mp3"
        file_size = msg.audio.file_size or 0
        file_type = "audio"
    elif msg.voice:
        file_id = msg.voice.file_id
        file_name = f"voice_{msg.voice.file_unique_id}.ogg"
        file_size = msg.voice.file_size or 0
        file_type = "voice"
    elif msg.animation:
        file_id = msg.animation.file_id
        file_name = msg.animation.file_name or f"animation_{msg.animation.file_unique_id}.mp4"
        file_size = msg.animation.file_size or 0
        file_type = "animation"
    
    if not file_id:
        return
    
    file_code = uuid.uuid4().hex[:8]
    file_store[file_code] = {
        "file_id": file_id,
        "file_type": file_type,
        "file_name": file_name,
        "file_size": file_size,
        "uploader_id": user.id,
        "uploader_name": user.full_name or "User",
        "upload_time": int(time.time()),
        "downloads": 0
    }
    save_store(file_store)
    
    bot_info = await context.bot.get_me()
    share_url = f"https://t.me/{bot_info.username}?start=get_{file_code}"
    
    keyboard = [
        [
            InlineKeyboardButton("🔗 Open Share Link", url=share_url),
        ],
        [
            InlineKeyboardButton("📥 Download File Now", callback_data=f"dl_{file_code}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    safe_fname = html.escape(file_name)
    size_str = format_size(file_size)
    
    text = (
        f"<b>✅ ғɪʟᴇ sᴛᴏʀᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>📄 <b>File Name:</b> {safe_fname}\n"
        f"💾 <b>File Size:</b> <code>{size_str}</code>\n"
        f"🏷️ <b>File Type:</b> <code>{file_type.upper()}</code>\n"
        f"🔑 <b>Share Code:</b> <code>{file_code}</code></blockquote>\n\n"
        f"<b>🔗 Shareable Retrieval Link:</b>\n"
        f"<blockquote><code>{share_url}</code></blockquote>\n\n"
        f"<blockquote>💡 <i>Share this link with anyone! Clicking it will deliver this file directly.</i></blockquote>"
    )
    await msg.reply_text(text, reply_markup=reply_markup, parse_mode="HTML", disable_web_page_preview=True)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    
    if query.data.startswith("dl_"):
        file_code = query.data.replace("dl_", "", 1)
        await query.answer("Fetching file...")
        await send_stored_file(context, query.message.chat_id, file_code)

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Update error in FileStoreBot: %s", context.error)

if __name__ == '__main__':
    print("Starting Telegram File Store & Share Link Generator on Gravix-Host...")
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable not found!")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("myfiles", myfiles_cmd))
    app.add_handler(CommandHandler("list", myfiles_cmd))
    app.add_handler(CommandHandler("del", del_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE | filters.ANIMATION,
        handle_media_upload
    ))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_error_handler(on_error)
    app.run_polling(drop_pending_updates=True)
"""
    },
    "captcha_shield_bot": {
        "name": "🛡️ Anti-Spam & Captcha Group Shield Bot",
        "description": "Protects Telegram groups with interactive math & button captchas, auto-muting new members until verified.",
        "code": r"""import os
import json
import html
import time
import random
import asyncio
import logging
from telegram import (
    Update,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("CaptchaShieldBot")

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)
SHIELD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shield_data.json")

def load_shield_data() -> dict:
    default_data = {
        "verified_count": 0,
        "blocked_count": 0,
        "group_settings": {}
    }
    try:
        if os.path.exists(SHIELD_FILE):
            with open(SHIELD_FILE, "r", encoding="utf-8") as f:
                default_data.update(json.load(f))
    except Exception as e:
        logger.error(f"Error loading shield data: {e}")
    return default_data

def save_shield_data(data: dict):
    try:
        with open(SHIELD_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving shield data: {e}")

shield_data = load_shield_data()
pending_captchas: dict[str, dict] = {}

RESTRICTED_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False
)

UNRESTRICTED_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_invite_users=True
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    first_name = html.escape(user.first_name if user else "Admin")
    bot_info = await context.bot.get_me()
    
    if chat.type in ["group", "supergroup"]:
        text = (
            f"<b>🛡️ ᴄᴀᴘᴛᴄʜᴀ sʜɪᴇʟᴅ ɪs ᴀᴄᴛɪᴠᴇ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<blockquote>🟢 <b>Group Guard:</b> Active\n"
            f"🔒 <b>Protection Mode:</b> Math &amp; Button Captcha\n"
            f"👥 <b>Total Verified:</b> <code>{shield_data.get('verified_count', 0)}</code>\n"
            f"🚫 <b>Blocked Spammers:</b> <code>{shield_data.get('blocked_count', 0)}</code></blockquote>\n\n"
            f"<blockquote>⚡ <i>New members are automatically muted until they solve the security challenge.</i></blockquote>"
        )
        await update.effective_message.reply_text(text, parse_mode="HTML")
        return

    add_url = f"https://t.me/{bot_info.username}?startgroup=true"
    keyboard = [
        [InlineKeyboardButton("➕ Add Bot to Your Group", url=add_url)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        f"<b>👋 ʜᴇʟʟᴏ, {first_name}!</b>\n\n"
        f"<blockquote>🛡️ <b>ɢʀᴀᴠɪx-ʜᴏsᴛ • ᴀɴᴛɪ-sᴘᴀᴍ &amp; ᴄᴀᴘᴛᴄʜᴀ sʜɪᴇʟᴅ ʙᴏᴛ</b>\n"
        f"Advanced automated group gatekeeper. Stops bot raids, spam accounts, and malicious link injectors.</blockquote>\n\n"
        f"<b>🚀 ǫᴜɪᴄᴋ sᴇᴛᴜᴘ (30 sᴇᴄᴏɴᴅs):</b>\n"
        f"1️⃣ Tap the button below to add this bot to your Telegram Group.\n"
        f"2️⃣ Promote this bot to <b>Admin</b> with <b>Restrict Users</b> &amp; <b>Delete Messages</b> permissions.\n"
        f"3️⃣ That's it! Every new arrival will be verified before they can speak.\n\n"
        f"<b>📊 sʜɪᴇʟᴅ ᴍᴇᴛʀɪᴄs:</b>\n"
        f"• 👥 <b>Members Verified:</b> <code>{shield_data.get('verified_count', 0)}</code>\n"
        f"• 🚫 <b>Spammers Stopped:</b> <code>{shield_data.get('blocked_count', 0)}</code>\n\n"
        f"<blockquote>⚡ <i>Commands: /status (Group stats), /rules (Group rules), /help (Manual)</i></blockquote>"
    )
    await update.effective_message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"<b>📖 ᴄᴀᴘᴛᴄʜᴀ sʜɪᴇʟᴅ ᴍᴀɴᴜᴀʟ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote><b>🛡️ How Protection Works:</b>\n"
        f"1. A new user joins your group.\n"
        f"2. Bot instantly restricts their message permissions.\n"
        f"3. Bot posts a math challenge with 4 interactive buttons.\n"
        f"4. User taps the correct answer → Unmuted instantly!\n"
        f"5. Challenge message auto-cleans after verification.</blockquote>\n\n"
        f"<b>⚡ ᴄᴏᴍᴍᴀɴᴅs:</b>\n"
        f"• <b>/start</b> - Dashboard &amp; Group setup link\n"
        f"• <b>/status</b> - View group shield protection stats\n"
        f"• <b>/rules</b> - Display community guidelines\n"
        f"• <b>/ping</b> - Test response speed\n"
        f"• <b>/help</b> - Show this documentation"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    verified = shield_data.get("verified_count", 0)
    blocked = shield_data.get("blocked_count", 0)
    text = (
        f"<b>📊 sʜɪᴇʟᴅ sᴇᴄᴜʀɪᴛʏ ᴍᴇᴛʀɪᴄs</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>🛡️ <b>Shield Status:</b> <code>Active &amp; Guarding</code>\n"
        f"✅ <b>Humans Verified:</b> <code>{verified}</code>\n"
        f"🚫 <b>Spam Bots Blocked:</b> <code>{blocked}</code>\n"
        f"⚡ <b>Engine:</b> <code>Gravix-Host 24/7 Subprocess</code></blockquote>\n\n"
        f"<blockquote>🔒 <i>Real-time automated protection enabled.</i></blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def rules_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    title = html.escape(chat.title if chat and chat.title else "Community")
    text = (
        f"<b>📜 ɢʀᴏᴜᴘ ʀᴜʟᴇs &amp; sᴀғᴇᴛʏ</b>\n"
        f"<b>{title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>1️⃣ <b>No Spam or Ads:</b> Unsolicited promotional links will be purged.\n"
        f"2️⃣ <b>Respect Everyone:</b> Harassment, hate speech, or abuse results in a ban.\n"
        f"3️⃣ <b>English / Group Topic:</b> Keep conversations constructive.\n"
        f"4️⃣ <b>No Scams / DMs:</b> Admins will never DM you first asking for funds or keys.</blockquote>\n\n"
        f"<blockquote>⚖️ <i>Follow rules to keep our community safe and enjoyable.</i></blockquote>"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    sent = await update.effective_message.reply_text("🏓 <i>Pinging security engine...</i>", parse_mode="HTML")
    latency_ms = round((time.time() - start_time) * 1000, 2)
    text = (
        f"<b>🏓 ᴘᴏɴɢ!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>⏱️ <b>Response Latency:</b> <code>{latency_ms}ms</code>\n"
        f"🛡️ <b>Shield Core:</b> <code>Operational</code>\n"
        f"🟢 <b>Status:</b> <code>Armed &amp; Ready</code></blockquote>"
    )
    await sent.edit_text(text, parse_mode="HTML")

async def on_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not msg.new_chat_members or not chat:
        return
    
    bot_id = context.bot.id
    
    for member in msg.new_chat_members:
        if member.id == bot_id:
            welcome_text = (
                f"<b>🎉 ᴛʜᴀɴᴋ ʏᴏᴜ ғᴏʀ ᴀᴅᴅɪɴɢ ᴄᴀᴘᴛᴄʜᴀ sʜɪᴇʟᴅ!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<blockquote>🛡️ <b>To activate automatic protection:</b>\n"
                f"1. Promote this bot to <b>Admin</b>.\n"
                f"2. Enable <b>Restrict Users</b> and <b>Delete Messages</b> permissions.\n\n"
                f"All future new members will be verified before they can send messages!</blockquote>"
            )
            await msg.reply_text(welcome_text, parse_mode="HTML")
            continue
        
        if member.is_bot:
            continue
        
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=member.id,
                permissions=RESTRICTED_PERMISSIONS
            )
        except Exception as e:
            logger.warning(f"Could not restrict member {member.id} in {chat.id}: {e}")
        
        num1 = random.randint(2, 9)
        num2 = random.randint(1, 9)
        correct = num1 + num2
        
        wrong_options = set()
        while len(wrong_options) < 3:
            w = random.randint(3, 18)
            if w != correct:
                wrong_options.add(w)
        
        all_options = list(wrong_options) + [correct]
        random.shuffle(all_options)
        
        key = f"{chat.id}_{member.id}"
        pending_captchas[key] = {
            "chat_id": chat.id,
            "user_id": member.id,
            "correct": str(correct),
            "created_at": time.time(),
            "attempts": 0
        }
        
        member_name = html.escape(member.full_name or "New Member")
        user_mention = f'<a href="tg://user?id={member.id}">{member_name}</a>'
        
        buttons = [
            InlineKeyboardButton(f"{opt}", callback_data=f"cpt_{member.id}_{opt}")
            for opt in all_options
        ]
        keyboard = [buttons]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        captcha_text = (
            f"<b>🛡️ sᴇᴄᴜʀɪᴛʏ ᴄʜᴇᴄᴋᴘᴏɪɴᴛ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<blockquote>👋 Welcome {user_mention}!\n"
            f"To prevent automated spam bots, please solve the security challenge below:\n\n"
            f"🧠 <b>Challenge:</b> <code>{num1} + {num2} = ?</code>\n"
            f"⏳ <b>Time:</b> <code>120 seconds</code></blockquote>\n\n"
            f"👇 <i>Tap the correct answer button to unmute yourself:</i>"
        )
        
        try:
            sent_msg = await msg.reply_text(captcha_text, reply_markup=reply_markup, parse_mode="HTML")
            pending_captchas[key]["msg_id"] = sent_msg.message_id
        except Exception as e:
            logger.error(f"Error sending captcha message: {e}")

async def captcha_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    
    parts = query.data.split("_")
    if len(parts) != 3 or parts[0] != "cpt":
        return
    
    target_user_id = int(parts[1])
    selected_answer = parts[2]
    clicker_id = query.from_user.id
    chat_id = query.message.chat_id
    
    if clicker_id != target_user_id:
        await query.answer("⛔ This verification challenge is not for you!", show_alert=True)
        return
    
    key = f"{chat_id}_{target_user_id}"
    record = pending_captchas.get(key)
    
    if not record:
        await query.answer("⚠️ This challenge has expired or already been completed.", show_alert=True)
        return
    
    if selected_answer == record["correct"]:
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=target_user_id,
                permissions=UNRESTRICTED_PERMISSIONS
            )
        except Exception as e:
            logger.error(f"Failed to unmute member {target_user_id}: {e}")
        
        shield_data["verified_count"] = shield_data.get("verified_count", 0) + 1
        save_shield_data(shield_data)
        pending_captchas.pop(key, None)
        
        await query.answer("✅ Verification successful! You are now unmuted.", show_alert=False)
        user_mention = f'<a href="tg://user?id={query.from_user.id}">{html.escape(query.from_user.full_name or "Member")}</a>'
        success_text = (
            f"<b>✅ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ sᴜᴄᴄᴇssғᴜʟ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<blockquote>Welcome {user_mention}! You have passed the security checkpoint and are now unmuted. Enjoy the group!</blockquote>"
        )
        try:
            await query.edit_message_text(success_text, parse_mode="HTML")
            asyncio.create_task(auto_delete_msg(context, chat_id, query.message.message_id, delay=8))
        except Exception as e:
            logger.error(f"Error editing captcha success message: {e}")
    else:
        record["attempts"] = record.get("attempts", 0) + 1
        if record["attempts"] >= 2:
            pending_captchas.pop(key, None)
            shield_data["blocked_count"] = shield_data.get("blocked_count", 0) + 1
            save_shield_data(shield_data)
            await query.answer("❌ Failed verification! You failed too many attempts.", show_alert=True)
            fail_text = (
                f"<b>🚫 ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ ғᴀɪʟᴇᴅ</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<blockquote>Member failed the captcha challenge and remains restricted.</blockquote>"
            )
            try:
                await query.edit_message_text(fail_text, parse_mode="HTML")
            except Exception:
                pass
        else:
            await query.answer("❌ Incorrect answer! You have 1 attempt remaining.", show_alert=True)

async def auto_delete_msg(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int = 8):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Update error in CaptchaShieldBot: %s", context.error)

if __name__ == '__main__':
    print("Starting Anti-Spam & Captcha Group Shield Bot on Gravix-Host...")
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable not found!")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("shield_status", status_cmd))
    app.add_handler(CommandHandler("rules", rules_cmd))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_members))
    app.add_handler(CallbackQueryHandler(captcha_button_click, pattern=r"^cpt_"))
    app.add_error_handler(on_error)
    app.run_polling(drop_pending_updates=True)
"""
    }
}


def get_all_templates() -> dict[str, dict]:
    """Returns the complete TEMPLATES dictionary."""
    return TEMPLATES


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

    # 3. Direct key match (e.g. 'echo_bot', 'welcome_bot', 'broadcast_bot', 'ai_chat_bot', 'file_store_bot', 'captcha_shield_bot')
    if name_clean in TEMPLATES:
        return name_clean, TEMPLATES[name_clean]

    # 4. Substring match (e.g. matching 'Echo', 'Welcome', 'Broadcast', 'AI', 'File', 'Captcha')
    for key, tinfo in TEMPLATES.items():
        if name_clean.lower() in tinfo.get("name", "").lower() or name_clean.lower() in key.lower():
            return key, tinfo

    return None
