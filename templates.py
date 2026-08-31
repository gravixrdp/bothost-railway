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
