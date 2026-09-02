import os
import re
import html
import shutil
import psutil
import asyncio
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ChatAction
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)
from config import ADMIN_ID, DATA_DIR
import database
from bot_manager import bot_manager
from code_analyzer import (
    is_cancellation_text,
    to_bold_sans,
    from_bold_sans,
    normalize_user_input
)

logger = logging.getLogger("GravixHost.Admin")

# States for admin conversation handlers
A_WAIT_BROADCAST, A_WAIT_SLOTS_UID, A_WAIT_SLOTS_NUM = range(10, 13)
A_FSUB_ID, A_FSUB_TITLE, A_FSUB_LINK = range(20, 23)
A_SET_SLOTS_NUM = 40

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

def make_header_card(title: str = "GRAVIX-HOST PRO", subtitle: str = "Platform Administration") -> str:
    title = to_bold_sans(title)
    if subtitle:
        subtitle = to_bold_sans(subtitle)
        return (
            f"<b>⚡ {title} ⚡</b>\n"
            f"<i>{subtitle}</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
    return (
        f"<b>⚡ {title} ⚡</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━"
    )

def make_progress_bar(percent: float, length: int = 10) -> str:
    """Generates an ultra-clean progress bar."""
    filled = int(round((max(0.0, min(100.0, percent)) / 100.0) * length))
    return "▰" * filled + "▱" * (length - filled)

async def _send_admin_msg(
    update: Update,
    text: str,
    reply_markup=None,
    context: ContextTypes.DEFAULT_TYPE = None,
    parse_mode: str = "HTML",
    keep_count: int = 3
):
    user_id = update.effective_user.id if update.effective_user else None
    chat_id = update.effective_chat.id if update.effective_chat else user_id
    if not chat_id or not context:
        return None

    if update.effective_message:
        database.record_chat_message(chat_id, update.effective_message.message_id)

    sent = None
    try:
        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except Exception as e:
        logger.warning(f"Admin HTML send failed, falling back to plain text: {e}")
        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=re.sub(r"<[^>]+>", "", text),
            reply_markup=reply_markup
        )

    if sent:
        database.record_chat_message(chat_id, sent.message_id)

    old_mids = database.get_old_chat_messages(chat_id, keep_count=keep_count)
    for mid in old_mids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass
    if old_mids:
        database.delete_chat_message_records(chat_id, old_mids)

    return sent

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Admin Keyboard Generators
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_user_display_name(u: dict) -> str:
    first = (u.get('first_name') or '').strip()
    uname = (u.get('username') or '').strip().lstrip('@')
    if first and uname:
        return f"{first} (@{uname})"
    elif first:
        return first
    elif uname:
        return f"@{uname}"
    else:
        return f"User {u['user_id']}"

async def resolve_user_profile(bot, u: dict) -> dict:
    uid = u.get('user_id')
    if not uid:
        return u
    if u.get('first_name') and u.get('username'):
        return u
    try:
        chat = await bot.get_chat(chat_id=uid)
        first_name = (chat.first_name or '').strip()
        last_name = (chat.last_name or '').strip()
        full_name = f"{first_name} {last_name}".strip() or first_name
        username = (chat.username or '').strip().lstrip('@')
        if full_name or username:
            updated = database.get_or_create_user(uid, username=username, first_name=full_name)
            u['first_name'] = updated.get('first_name') or full_name
            u['username'] = updated.get('username') or username
    except Exception as e:
        logger.debug(f"Could not resolve Telegram chat for UID {uid}: {e}")
    return u

def get_admin_reply_keyboard(maint_status: str) -> ReplyKeyboardMarkup:
    clean_status = re.sub(r"[^\w\s\(\)]", "", str(maint_status)).strip() if maint_status else "OFF"
    keyboard = [
        [KeyboardButton("⇋ 𝗦𝘆𝘀𝘁𝗲𝗺 𝗦𝘁𝗮𝘁𝘀 ⇋"), KeyboardButton("⇋ 𝗨𝘀𝗲𝗿 𝗗𝗶𝗿𝗲𝗰𝘁𝗼𝗿𝘆 ⇋")],
        [KeyboardButton("⇋ 𝗔𝗹𝗹 𝗛𝗼𝘀𝘁𝗲𝗱 𝗕𝗼𝘁𝘀 ⇋"), KeyboardButton("⇋ 𝗙𝗼𝗿𝗰𝗲-𝗦𝘂𝗯 𝗖𝗵𝗮𝗻𝗻𝗲𝗹𝘀 ⇋")],
        [KeyboardButton("⇋ 𝗕𝗿𝗼𝗮𝗱𝗰𝗮𝘀𝘁 ⇋"), KeyboardButton("⇋ 𝗖𝗵𝗲𝗰𝗸 𝗕𝗹𝗼𝗰𝗸𝗲𝗱 𝗨𝘀𝗲𝗿𝘀 ⇋")],
        [KeyboardButton(f"⇋ 𝗧𝗼𝗴𝗴𝗹𝗲 𝗠𝗮𝗶𝗻𝘁𝗲𝗻𝗮𝗻𝗰𝗲 ({clean_status}) ⇋")],
        [KeyboardButton("⇋ 𝗥𝗲𝗳𝗿𝗲𝘀𝗵 𝗔𝗱𝗺𝗶𝗻 ⇋"), KeyboardButton("⇋ 𝗘𝘅𝗶𝘁 𝗔𝗱𝗺𝗶𝗻 ⇋")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_users_reply_keyboard(users: list, page: int = 0) -> ReplyKeyboardMarkup:
    per_page = 5
    total_pages = max(1, (len(users) + per_page - 1) // per_page)
    curr_page = max(0, min(page, total_pages - 1))
    curr_users = users[curr_page * per_page : (curr_page + 1) * per_page]

    keyboard = []
    for u in curr_users:
        display_name = get_user_display_name(u)
        keyboard.append([KeyboardButton(f"⇋ {display_name} [UID: {u['user_id']}] ⇋")])

    nav_row = []
    if curr_page > 0:
        nav_row.append(KeyboardButton("⇋ 𝗣𝗿𝗲𝘃 𝗨𝘀𝗲𝗿𝘀 ⇋"))
    if curr_page < total_pages - 1:
        nav_row.append(KeyboardButton("⇋ 𝗡𝗲𝘅𝘁 𝗨𝘀𝗲𝗿𝘀 ⇋"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([KeyboardButton("⇋ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗔𝗱𝗺𝗶𝗻 ⇋")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_user_detail_keyboard(target_uid: int, is_banned: bool, user_bots: list = None) -> ReplyKeyboardMarkup:
    ban_label = "𝗨𝗻𝗯𝗮𝗻 𝗨𝘀𝗲𝗿" if is_banned else "𝗕𝗮𝗻 𝗨𝘀𝗲𝗿"
    keyboard = [
        [KeyboardButton(f"⇋ {ban_label} [UID: {target_uid}] ⇋")],
        [KeyboardButton(f"⇋ +1 𝗦𝗹𝗼𝘁 [UID: {target_uid}] ⇋"), KeyboardButton(f"⇋ -1 𝗦𝗹𝗼𝘁 [UID: {target_uid}] ⇋")],
        [KeyboardButton(f"⇋ 𝗦𝗲𝘁 𝗖𝘂𝘀𝘁𝗼𝗺 𝗦𝗹𝗼𝘁𝘀 [UID: {target_uid}] ⇋")]
    ]
    if user_bots:
        for b in user_bots[:5]:
            b_name = b.get('bot_name', 'Bot')[:15]
            b_id = b.get('bot_id', '')
            keyboard.append([KeyboardButton(f"⇋ {b_name} [#{b_id}] ⇋")])
    keyboard.append([KeyboardButton("⇋ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗨𝘀𝗲𝗿𝘀 ⇋"), KeyboardButton("⇋ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗔𝗱𝗺𝗶𝗻 ⇋")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_bots_reply_keyboard(bots: list, page: int = 0) -> ReplyKeyboardMarkup:
    per_page = 5
    total_pages = max(1, (len(bots) + per_page - 1) // per_page)
    curr_page = max(0, min(page, total_pages - 1))
    curr_bots = bots[curr_page * per_page : (curr_page + 1) * per_page]

    keyboard = []
    for b in curr_bots:
        b_name = b.get('bot_name', 'Bot')
        b_id = b.get('bot_id', '')
        keyboard.append([KeyboardButton(f"⇋ {b_name} [#{b_id}] ⇋")])

    nav_row = []
    if curr_page > 0:
        nav_row.append(KeyboardButton("⇋ 𝗣𝗿𝗲𝘃 𝗔𝗹𝗹 𝗕𝗼𝘁𝘀 ⇋"))
    if curr_page < total_pages - 1:
        nav_row.append(KeyboardButton("⇋ 𝗡𝗲𝘅𝘁 𝗔𝗹𝗹 𝗕𝗼𝘁𝘀 ⇋"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([KeyboardButton("⇋ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗔𝗱𝗺𝗶𝗻 ⇋")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_bot_detail_keyboard(bot_id: str, status: str) -> ReplyKeyboardMarkup:
    state_label = "𝗦𝘁𝗼𝗽" if status == "RUNNING" else "𝗙𝗼𝗿𝗰𝗲 𝗦𝘁𝗮𝗿𝘁"
    keyboard = [
        [KeyboardButton(f"⇋ {state_label} [#{bot_id}] ⇋"), KeyboardButton(f"⇋ 𝗥𝗲𝘀𝘁𝗮𝗿𝘁 [#{bot_id}] ⇋")],
        [KeyboardButton(f"⇋ 𝗩𝗶𝗲𝘄 𝗟𝗼𝗴𝘀 [#{bot_id}] ⇋"), KeyboardButton(f"⇋ 𝗚𝗲𝘁 𝗕𝗼𝘁 𝗖𝗼𝗱𝗲 [#{bot_id}] ⇋")],
        [KeyboardButton(f"⇋ 🤖 𝗔𝗜 𝗗𝗶𝗮𝗴𝗻𝗼𝘀𝗲 & 𝗙𝗶𝘅 [#{bot_id}] ⇋")],
        [KeyboardButton(f"⇋ 𝗙𝗼𝗿𝗰𝗲 𝗗𝗲𝗹𝗲𝘁𝗲 [#{bot_id}] ⇋")],
        [KeyboardButton("⇋ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗔𝗹𝗹 𝗕𝗼𝘁𝘀 ⇋"), KeyboardButton("⇋ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗔𝗱𝗺𝗶𝗻 ⇋")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_fsub_reply_keyboard(channels: list, page: int = 0) -> ReplyKeyboardMarkup:
    per_page = 5
    total_pages = max(1, (len(channels) + per_page - 1) // per_page)
    curr_page = max(0, min(page, total_pages - 1))
    curr_channels = channels[curr_page * per_page : (curr_page + 1) * per_page]

    keyboard = []
    for ch in curr_channels:
        title = ch.get('title', 'Channel')[:15]
        cid = ch.get('channel_id', '')
        keyboard.append([KeyboardButton(f"⇋ 𝗥𝗲𝗺𝗼𝘃𝗲 {title} [{cid}] ⇋")])

    nav_row = []
    if curr_page > 0:
        nav_row.append(KeyboardButton("⇋ 𝗣𝗿𝗲𝘃 𝗙𝗦𝘂𝗯 ⇋"))
    if curr_page < total_pages - 1:
        nav_row.append(KeyboardButton("⇋ 𝗡𝗲𝘅𝘁 𝗙𝗦𝘂𝗯 ⇋"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([
        KeyboardButton("⇋ 𝗧𝗲𝘀𝘁 𝗕𝗼𝘁 𝗔𝗱𝗺𝗶𝗻 𝗦𝘁𝗮𝘁𝘂𝘀 ⇋"),
        KeyboardButton("⇋ 𝗔𝗱𝗱 𝗙𝗼𝗿𝗰𝗲-𝗦𝘂𝗯 𝗖𝗵𝗮𝗻𝗻𝗲𝗹 ⇋")
    ])
    keyboard.append([KeyboardButton("⇋ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗔𝗱𝗺𝗶𝗻 ⇋")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Text Command / Button Handlers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>", context=context)
        return

    maint = database.get_setting("maintenance_mode", "0") == "1"
    maint_status = "🔴 ON" if maint else "🟢 OFF"

    user_stats = database.get_user_stats_summary()
    total_users = user_stats['total']
    active_users = user_stats['active']
    blocked_users = user_stats['blocked']

    bots = database.get_all_hosted_bots()
    running_bots = sum(1 for b in bots if b.get('status') == 'RUNNING')

    text = (
        "<b>👑 CENTRAL ADMIN</b>\n"
        "<i>Platform Telemetry</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        f"👑 <b>Admin:</b> <code>{user_id}</code>\n"
        f"⚙️ <b>Maintenance:</b> <code>{maint_status}</code>\n"
        f"👥 <b>Users:</b> <code>{total_users}</code> (🟢 <code>{active_users}</code> Active | 🔴 <code>{blocked_users}</code> Blocked)\n"
        f"🤖 <b>Bots:</b> <code>{running_bots} Active / {len(bots)} Total</code>"
        "</blockquote>\n\n"
        "👇 <i>Select an option below:</i>"
    )
    reply_markup = get_admin_reply_keyboard(maint_status)
    await _send_admin_msg(update, text, reply_markup=reply_markup, context=context)

async def admin_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>", context=context)
        return

    user_stats = database.get_user_stats_summary()
    total_users = user_stats['total']
    active_users = user_stats['active']
    blocked_users = user_stats['blocked']

    bots = database.get_all_hosted_bots()
    running_bots = sum(1 for b in bots if b.get('status') == 'RUNNING')

    cpu_percent = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    data_path = DATA_DIR if os.path.exists(DATA_DIR) else "."
    disk = psutil.disk_usage(data_path)

    cpu_bar = make_progress_bar(cpu_percent)
    ram_bar = make_progress_bar(mem.percent)
    disk_bar = make_progress_bar(disk.percent)

    ram_used_mb = mem.used // (1024 * 1024)
    ram_total_mb = mem.total // (1024 * 1024)
    disk_free_gb = disk.free // (1024 * 1024 * 1024)
    disk_total_gb = disk.total // (1024 * 1024 * 1024)

    text = (
        "<b>📊 SYSTEM STATS</b>\n"
        "<i>Server & Infrastructure Metrics</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        f"👥 <b>Users:</b> <code>{total_users}</code> (🟢 <code>{active_users}</code> Active | 🔴 <code>{blocked_users}</code> Blocked)\n"
        f"🤖 <b>Bots:</b> <code>{len(bots)}</code> (🟢 <code>{running_bots}</code> Active)\n\n"
        f"⚡ <b>CPU:</b> <code>{cpu_bar} {cpu_percent}%</code>\n"
        f"💾 <b>RAM:</b> <code>{ram_bar} {mem.percent}%</code> (<code>{ram_used_mb}MB / {ram_total_mb}MB</code>)\n"
        f"💽 <b>Disk:</b> <code>{disk_bar} {disk.percent}%</code> (<code>{disk_free_gb}GB Free / {disk_total_gb}GB</code>)"
        "</blockquote>"
    )
    reply_markup = ReplyKeyboardMarkup([
        [KeyboardButton("⇋ 𝗖𝗵𝗲𝗰𝗸 𝗕𝗹𝗼𝗰𝗸𝗲𝗱 𝗨𝘀𝗲𝗿𝘀 ⇋"), KeyboardButton("⇋ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗔𝗱𝗺𝗶𝗻 ⇋")]
    ], resize_keyboard=True)
    await _send_admin_msg(update, text, reply_markup=reply_markup, context=context)

async def admin_users_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>", context=context)
        return

    users = database.get_all_users()
    per_page = 5
    total_pages = max(1, (len(users) + per_page - 1) // per_page)
    curr_page = max(0, min(page, total_pages - 1))
    context.user_data['admin_users_page'] = curr_page
    curr_users = users[curr_page * per_page : (curr_page + 1) * per_page]

    # Resolve any missing user profile info from Telegram API
    for u in curr_users:
        if not u.get('first_name') or not u.get('username'):
            await resolve_user_profile(context.bot, u)

    text = (
        f"<b>👥 USER DIRECTORY</b> (Page {curr_page + 1}/{total_pages})\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    if not users:
        text += "<blockquote><i>No registered users found.</i></blockquote>\n"
    else:
        text += "<blockquote>"
        entries = []
        for idx, u in enumerate(curr_users, start=curr_page * per_page + 1):
            badge = ""
            if u.get('is_banned'):
                badge = " <code>[BANNED]</code>"
            elif u.get('is_blocked'):
                badge = " <code>[BLOCKED BOT]</code>"
            display_name = html.escape(get_user_display_name(u))
            slots = u.get('max_slots', 3)
            entries.append(
                f"<b>{idx}. {display_name}</b> (UID: <code>{u['user_id']}</code>){badge}\n"
                f"   └ Slots: <code>{slots}</code>"
            )
        text += "\n\n".join(entries) + "</blockquote>\n"

    text += "\n👇 <i>Tap a user button below to manage:</i>"
    reply_markup = get_admin_users_reply_keyboard(users, curr_page)
    await _send_admin_msg(update, text, reply_markup=reply_markup, context=context)

async def admin_user_detail_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int = None):
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>", context=context)
        return

    if user_id is None and update.message and update.message.text:
        clean_text = normalize_user_input(update.message.text)
        m = re.search(r"(?:\[UID:\s*(\d+)\]|\(UID:\s*(\d+)\))", clean_text)
        if m:
            user_id = int(m.group(1) or m.group(2))

    if user_id is None:
        await admin_users_list_handler(update, context, 0)
        return

    target_user = database.get_or_create_user(user_id)
    if not target_user.get('first_name') or not target_user.get('username'):
        target_user = await resolve_user_profile(context.bot, dict(target_user))

    user_bots = database.get_user_bots(user_id)
    running_count = sum(1 for b in user_bots if b.get('status') == 'RUNNING')

    is_banned = bool(target_user.get('is_banned'))
    banned_str = "🔴 <b>Banned (Suspended)</b>" if is_banned else "🟢 <b>Active (Authorized)</b>"

    is_blocked = bool(target_user.get('is_blocked'))
    reach_str = "🔴 <b>Blocked Bot</b>" if is_blocked else "🟢 <b>Reachable</b>"

    raw_first = (target_user.get('first_name') or '').strip()
    raw_uname = (target_user.get('username') or '').strip().lstrip('@')
    name_display = html.escape(raw_first) if raw_first else '<i>None</i>'
    username_display = f"@{html.escape(raw_uname)}" if raw_uname else '<i>None</i>'

    text = (
        f"<b>👤 USER DETAIL</b>\n"
        f"<i>UID: <code>{target_user['user_id']}</code></i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        f"👤 <b>Name:</b> {name_display} ({username_display})\n"
        f"🛡️ <b>Status:</b> {banned_str}\n"
        f"⚡ <b>Reachability:</b> {reach_str}\n"
        f"📦 <b>Slots:</b> <code>{target_user.get('max_slots', 3)}</code>\n"
        f"🤖 <b>Bots:</b> <code>{len(user_bots)}</code> (<code>{running_count}</code> Active)"
        "</blockquote>\n\n"
        "👇 <i>Choose action below:</i>"
    )
    reply_markup = get_admin_user_detail_keyboard(user_id, is_banned, user_bots)
    await _send_admin_msg(update, text, reply_markup=reply_markup, context=context)

async def admin_user_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str = None, target_uid: int = None):
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>", context=context)
        return

    raw_text = update.message.text if (update.message and update.message.text) else ""
    text_input = normalize_user_input(raw_text)
    if target_uid is None:
        m = re.search(r"(?:\[UID:\s*(\d+)\]|\(UID:\s*(\d+)\))", text_input)
        if m:
            target_uid = int(m.group(1) or m.group(2))

    if target_uid is None:
        await admin_users_list_handler(update, context, 0)
        return

    if action is None:
        if "Ban User" in text_input or "Unban User" in text_input:
            action = "toggle_ban"
        elif "+1 Slot" in text_input or "+2 Slots" in text_input:
            action = "inc_slots"
        elif "-1 Slot" in text_input:
            action = "dec_slots"

    target_user = database.get_or_create_user(target_uid)

    if action == "toggle_ban":
        new_ban = not target_user.get('is_banned')
        database.set_user_ban(target_uid, new_ban)
        if new_ban:
            for b in database.get_user_bots(target_uid):
                await bot_manager.stop_bot(b['bot_id'])
            await _send_admin_msg(
                update,
                f"🚫 <b>USER BANNED</b>\nUser <code>{target_uid}</code> has been banned. Subprocesses stopped.",
                context=context
            )
        else:
            await _send_admin_msg(
                update,
                f"🔓 <b>USER UNBANNED</b>\nUser <code>{target_uid}</code> has been unbanned.",
                context=context
            )

    elif action == "inc_slots":
        new_slots = database.adjust_user_slots(target_uid, 1)
        await _send_admin_msg(
            update,
            f"➕ <b>SLOTS INCREASED</b>\nSlots: <code>{new_slots}</code> for User <code>{target_uid}</code>.",
            context=context
        )

    elif action == "dec_slots":
        new_slots = database.adjust_user_slots(target_uid, -1)
        await _send_admin_msg(
            update,
            f"➖ <b>SLOTS DECREASED</b>\nSlots: <code>{new_slots}</code> for User <code>{target_uid}</code>.",
            context=context
        )

    await admin_user_detail_handler(update, context, target_uid)

async def admin_bots_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>", context=context)
        return

    all_bots = database.get_all_hosted_bots()
    per_page = 5
    total_pages = max(1, (len(all_bots) + per_page - 1) // per_page)
    curr_page = max(0, min(page, total_pages - 1))
    context.user_data['admin_bots_page'] = curr_page
    curr_bots = all_bots[curr_page * per_page : (curr_page + 1) * per_page]

    text = (
        f"<b>🤖 HOSTED BOTS</b> (Page {curr_page + 1}/{total_pages})\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    if not all_bots:
        text += "<blockquote><i>No hosted bot instances found.</i></blockquote>\n"
    else:
        text += "<blockquote>"
        entries = []
        for idx, b in enumerate(curr_bots, start=curr_page * per_page + 1):
            st = b.get('status', 'STOPPED')
            status_emoji = "🟢" if st == "RUNNING" else ("🔴" if st in ["FAILED", "CRASHED"] else "⚪")
            b_name = html.escape(b.get('bot_name', 'Bot'))
            b_id = html.escape(str(b.get('bot_id', '')))
            u_id = b.get('user_id')
            entries.append(
                f"{idx}. {status_emoji} <b>{b_name}</b> [<code>#{b_id}</code>]\n"
                f"   └ 👤 Owner: <code>{u_id}</code> | ⚡ Status: <code>{st}</code>"
            )
        text += "\n\n".join(entries) + "</blockquote>\n"

    text += "\n👇 <i>Tap a bot button below to manage:</i>"
    reply_markup = get_admin_bots_reply_keyboard(all_bots, curr_page)
    await _send_admin_msg(update, text, reply_markup=reply_markup, context=context)

async def admin_bot_detail_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id: str = None):
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>", context=context)
        return

    if bot_id is None and update.message and update.message.text:
        clean_text = normalize_user_input(update.message.text)
        m = re.search(r"\[#([a-zA-Z0-9_-]+)\]", clean_text)
        if m:
            bot_id = m.group(1)

    if not bot_id:
        await admin_bots_list_handler(update, context, 0)
        return

    bot_data = database.get_bot(bot_id)
    if not bot_data:
        await _send_admin_msg(update, f"⚠️ <b>Bot <code>#{html.escape(bot_id)}</code> not found in database.</b>", context=context)
        await admin_bots_list_handler(update, context, 0)
        return

    status = bot_data.get('status', 'STOPPED')
    status_emoji = "🟢" if status == "RUNNING" else ("🔴" if status in ["FAILED", "CRASHED"] else "⚪")
    token = bot_data.get('bot_token', '')
    masked_token = f"{token[:10]}...{token[-5:]}" if len(token) > 15 else "******"
    auto_restart = "🟢 On" if bot_data.get('auto_restart', 1) else "🔴 Off"

    metrics = bot_manager.get_bot_process_metrics(bot_id)
    cpu_percent = metrics.get('cpu_percent', 0.0)
    ram_mb = metrics.get('ram_mb', 0.0)

    text = (
        f"<b>🤖 BOT DETAIL [<code>#{html.escape(bot_id)}</code>]</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        f"🤖 <b>Name:</b> <b>{html.escape(bot_data.get('bot_name', 'Unnamed Bot'))}</b>\n"
        f"👤 <b>Owner:</b> <code>{bot_data['user_id']}</code>\n"
        f"⚡ <b>Status:</b> {status_emoji} <code>{status}</code>\n"
        f"⚡ <b>RAM:</b> <code>{ram_mb} MB</code> | <b>CPU:</b> <code>{cpu_percent}%</code>\n"
        f"🔄 <b>Auto-Restart:</b> <code>{auto_restart}</code>\n"
        f"🔑 <b>Token:</b> <code>{html.escape(masked_token)}</code>"
        "</blockquote>\n\n"
        "👇 <i>Select process action below:</i>"
    )
    reply_markup = get_admin_bot_detail_keyboard(bot_id, status)
    await _send_admin_msg(update, text, reply_markup=reply_markup, context=context)

async def admin_bot_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str = None, bot_id: str = None):
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>", context=context)
        return

    raw_text = update.message.text if (update.message and update.message.text) else ""
    text_input = normalize_user_input(raw_text)
    if bot_id is None:
        m = re.search(r"\[#([a-zA-Z0-9_-]+)\]", text_input)
        if m:
            bot_id = m.group(1)

    if not bot_id:
        await admin_bots_list_handler(update, context, 0)
        return

    if action is None:
        if "Force Start" in text_input or "▶️" in text_input:
            action = "start"
        elif "Stop" in text_input or "⏹️" in text_input:
            action = "stop"
        elif "Restart" in text_input or "🔄" in text_input:
            action = "restart"
        elif "View Logs" in text_input or "📜" in text_input:
            action = "logs"
        elif "Get Bot Code" in text_input or "Download Code" in text_input or "View Code" in text_input or "Get Code" in text_input or "Export Code" in text_input or "Code" in text_input:
            action = "code"
        elif "AI Diagnose" in text_input or "Diagnose" in text_input or "AI Fix" in text_input or "diagnose" in text_input.lower():
            action = "ai_diagnose"
        elif "Force Delete" in text_input or "🗑️" in text_input:
            action = "del"

    if action == "start":
        success, msg = await bot_manager.start_bot(bot_id)
        if success:
            header = make_header_card("𝗣𝗥𝗢𝗖𝗘𝗦𝗦 𝗦𝗧𝗔𝗥𝗧𝗘𝗗", f"Instance #{bot_id}")
            await _send_admin_msg(update, f"{header}\n\n<code>{html.escape(msg)}</code>", context=context)
        else:
            header = make_header_card("𝗦𝗧𝗔𝗥𝗧 𝗙𝗔𝗜𝗟𝗘𝗗", f"Instance #{bot_id}")
            await _send_admin_msg(update, f"{header}\n\n<code>{html.escape(msg)}</code>", context=context)
        await admin_bot_detail_handler(update, context, bot_id)

    elif action == "stop":
        success, msg = await bot_manager.stop_bot(bot_id)
        if success:
            header = make_header_card("𝗣𝗥𝗢𝗖𝗘𝗦𝗦 𝗦𝗧𝗢𝗣𝗣𝗘𝗗", f"Instance #{bot_id}")
            await _send_admin_msg(update, f"{header}\n\n<code>{html.escape(msg)}</code>", context=context)
        else:
            header = make_header_card("𝗦𝗧𝗢𝗣 𝗙𝗔𝗜𝗟𝗘𝗗", f"Instance #{bot_id}")
            await _send_admin_msg(update, f"{header}\n\n<code>{html.escape(msg)}</code>", context=context)
        await admin_bot_detail_handler(update, context, bot_id)

    elif action == "restart":
        success, msg = await bot_manager.restart_bot(bot_id)
        if success:
            header = make_header_card("𝗣𝗥𝗢𝗖𝗘𝗦𝗦 𝗥𝗘𝗦𝗧𝗔𝗥𝗧𝗘𝗗", f"Instance #{bot_id}")
            await _send_admin_msg(update, f"{header}\n\n<code>{html.escape(msg)}</code>", context=context)
        else:
            header = make_header_card("𝗥𝗘𝗦𝗧𝗔𝗥𝗧 𝗙𝗔𝗜𝗟𝗘𝗗", f"Instance #{bot_id}")
            await _send_admin_msg(update, f"{header}\n\n<code>{html.escape(msg)}</code>", context=context)
        await admin_bot_detail_handler(update, context, bot_id)

    elif action == "logs":
        bot_data = database.get_bot(bot_id)
        logs = bot_manager.get_logs(bot_id, lines=30)
        log_snippet = logs[-3500:] if logs else "No execution logs recorded yet."
        header = make_header_card("𝗕𝗢𝗧 𝗘𝗫𝗘𝗖𝗨𝗧𝗜𝗢𝗡 𝗟𝗢𝗚𝗦", f"Live Subprocess Output for #{html.escape(bot_id)}")
        text = (
            f"{header}\n\n"
            f"🤖 <b>Target Bot:</b> <code>#{html.escape(bot_id)}</code>\n\n"
            f"<pre><code>{html.escape(log_snippet)}</code></pre>\n\n"
            "💡 <i>Displaying the most recent 30 log lines.</i>"
        )
        reply_markup = get_admin_bot_detail_keyboard(bot_id, bot_data.get('status', 'STOPPED') if bot_data else 'STOPPED')
        await _send_admin_msg(update, text, reply_markup=reply_markup, context=context)

    elif action == "code":
        await admin_bot_get_code_handler(update, context, bot_id)

    elif action == "ai_diagnose":
        from ai_diagnostics import run_ai_diagnostics
        bot_data = database.get_bot(bot_id)
        await _send_admin_msg(
            update,
            f"⏳ <b>Gravix AI analyzing instance <code>#{bot_id}</code> status, logs & code...</b>",
            context=context
        )
        report = await run_ai_diagnostics(bot_id, admin_id, is_admin_caller=True)
        status = bot_data.get('status', 'STOPPED') if bot_data else 'STOPPED'
        reply_markup = get_admin_bot_detail_keyboard(bot_id, status)
        await _send_admin_msg(
            update,
            report,
            reply_markup=reply_markup,
            context=context
        )

    elif action == "del":
        await bot_manager.stop_bot(bot_id)
        bot_data = database.get_bot(bot_id)
        if bot_data and bot_data.get('script_path'):
            script_dir = os.path.dirname(bot_data['script_path'])
            if os.path.exists(script_dir):
                shutil.rmtree(script_dir, ignore_errors=True)
        database.delete_bot_record(bot_id)
        header = make_header_card("𝗕𝗢𝗧 𝗣𝗘𝗥𝗠𝗔𝗡𝗘𝗡𝗧𝗟𝗬 𝗗𝗘𝗟𝗘𝗧𝗘𝗗", f"Purged Instance #{html.escape(bot_id)}")
        await _send_admin_msg(
            update,
            f"{header}\n\nBot instance <code>#{html.escape(bot_id)}</code> and disk assets have been purged.",
            context=context
        )
        await admin_bots_list_handler(update, context, 0)

async def admin_bot_get_code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id: str):
    """Allows Master Admin to inspect and download any user's hosted bot source code & zip archive."""
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>", context=context)
        return

    bot_data = database.get_bot(bot_id)
    if not bot_data:
        await _send_admin_msg(update, f"⚠️ <b>Bot <code>#{html.escape(bot_id)}</code> not found in database.</b>", context=context)
        return

    owner_id = bot_data['user_id']
    bot_name = bot_data.get('bot_name', 'bot')
    clean_name = re.sub(r'[^a-zA-Z0-9_-]', '_', bot_name)
    script_path = bot_data.get('script_path') or os.path.join(DATA_DIR, "bots", f"{owner_id}_{bot_id}", "main.py")

    sent_any = False

    # 1. Send single main.py if present
    if os.path.exists(script_path) and os.path.isfile(script_path):
        try:
            with open(script_path, "rb") as f:
                caption = (
                    f"<b>📁 BOT SOURCE CODE FILE</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🤖 <b>Bot:</b> {html.escape(bot_name)} (<code>#{bot_id}</code>)\n"
                    f"👤 <b>Owner UID:</b> <code>{owner_id}</code>\n"
                    f"📄 <b>File:</b> <code>main.py</code>"
                )
                await context.bot.send_document(
                    chat_id=admin_id,
                    document=f,
                    filename=f"{clean_name}_{bot_id}_main.py",
                    caption=caption,
                    parse_mode="HTML"
                )
                sent_any = True
        except Exception as e:
            logger.error(f"Error sending main.py to admin: {e}")

    # 2. Package and send complete workspace zip
    zip_path = bot_manager.create_bot_backup_zip(bot_id, owner_id)
    if zip_path and os.path.exists(zip_path):
        try:
            with open(zip_path, "rb") as zf:
                caption = (
                    f"<b>💾 COMPLETE BOT WORKSPACE ARCHIVE</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🤖 <b>Bot:</b> {html.escape(bot_name)} (<code>#{bot_id}</code>)\n"
                    f"👤 <b>Owner UID:</b> <code>{owner_id}</code>\n"
                    f"📦 <b>Archive:</b> Complete project workspace directory"
                )
                await context.bot.send_document(
                    chat_id=admin_id,
                    document=zf,
                    filename=f"{clean_name}_{bot_id}_workspace.zip",
                    caption=caption,
                    parse_mode="HTML"
                )
                sent_any = True
        except Exception as e:
            logger.error(f"Error sending workspace zip to admin: {e}")

    if not sent_any:
        await _send_admin_msg(
            update,
            f"❌ <b>Source Code Not Found:</b> No files found on disk for bot <code>#{bot_id}</code>.",
            context=context
        )
    else:
        status = bot_data.get('status', 'STOPPED')
        reply_markup = get_admin_bot_detail_keyboard(bot_id, status)
        await _send_admin_msg(
            update,
            f"✅ <b>Source files for <code>{html.escape(bot_name)} [#{bot_id}]</code> sent above.</b>\n"
            "<i>Files are saved directly in chat.</i>",
            reply_markup=reply_markup,
            context=context
        )

async def check_channel_bot_admin_status(bot, channel_id: str) -> tuple[bool, str, str]:
    """
    Checks if the master bot is an administrator in the specified channel.
    Returns: (is_admin, status_badge, details_str)
    """
    cid_str = str(channel_id).strip()
    target_chat = None

    if cid_str.startswith("-100") or (cid_str.startswith("-") and cid_str[1:].isdigit()):
        target_chat = int(cid_str)
    elif cid_str.isdigit():
        target_chat = int(f"-100{cid_str}")
    elif cid_str.startswith("@"):
        target_chat = cid_str
    elif "t.me/" in cid_str:
        slug = cid_str.split("t.me/")[-1].strip().lstrip("@")
        if not slug.startswith("+") and not slug.startswith("joinchat/") and "/" not in slug and slug:
            target_chat = f"@{slug}"

    if not target_chat:
        return False, "⚪ <code>Raw Invite Link</code>", "Private invite link without numeric ID. Add bot to channel as Admin to capture real ID."

    try:
        chat = await bot.get_chat(chat_id=target_chat)
        member = await bot.get_chat_member(chat_id=target_chat, user_id=bot.id)
        if member.status in ("administrator", "creator"):
            chat_title = html.escape(chat.title or "Channel")
            return True, "🟢 <code>ADMIN CONFIRMED</code>", f"Bot is verified Admin in <b>{chat_title}</b> (Can enforce verification 100%)."
        else:
            chat_title = html.escape(chat.title or "Channel")
            return False, "🟡 <code>MEMBER (NOT ADMIN)</code>", f"Bot is in <b>{chat_title}</b> but lacks Admin privileges."
    except Exception as e:
        err = str(e).lower()
        if "chat not found" in err:
            return False, "🔴 <code>CHAT NOT FOUND</code>", "Telegram cannot resolve this chat. Check username or add bot."
        elif "bot is not a member" in err:
            return False, "🔴 <code>BOT NOT IN CHANNEL</code>", "Master bot is not present in this channel."
        elif "chat_admin_required" in err or "not enough rights" in err:
            return False, "🟡 <code>ADMIN RIGHTS REQUIRED</code>", "Bot needs Administrator rights with Invite Users permission."
        else:
            return False, "🔴 <code>UNREACHABLE</code>", html.escape(str(e))

async def admin_fsub_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>", context=context)
        return

    channels = database.get_required_channels()
    per_page = 5
    total_pages = max(1, (len(channels) + per_page - 1) // per_page)
    curr_page = max(0, min(page, total_pages - 1))
    context.user_data['admin_fsub_page'] = curr_page
    curr_channels = channels[curr_page * per_page : (curr_page + 1) * per_page]

    text = (
        f"<b>📢 FORCE-SUB CHANNELS</b> (Page {curr_page + 1}/{total_pages})\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    if not channels:
        text += "<blockquote><i>No force-sub channels configured yet.</i></blockquote>\n"
    else:
        text += "<blockquote>"
        entries = []
        for idx, ch in enumerate(curr_channels, start=curr_page * per_page + 1):
            ch_title = html.escape(ch.get('title', 'Channel'))
            ch_id = html.escape(str(ch.get('channel_id', '')))
            is_adm, badge, _ = await check_channel_bot_admin_status(context.bot, ch.get('channel_id', ''))
            entries.append(
                f"{idx}. <b>{ch_title}</b> (<code>{ch_id}</code>)\n"
                f"   └ ⚡ Admin: {badge}"
            )
        text += "\n\n".join(entries) + "</blockquote>\n"

    text += "\n👇 <i>Tap below to test or remove channels:</i>"
    reply_markup = get_admin_fsub_reply_keyboard(channels, curr_page)
    await _send_admin_msg(update, text, reply_markup=reply_markup, context=context)

async def admin_fsub_test_admin_status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deep diagnostic probe that checks Bot Admin status and permissions across all required channels."""
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>", context=context)
        return

    channels = database.get_required_channels()
    if not channels:
        await _send_admin_msg(update, "⚠️ <i>No force-sub channels configured to test.</i>", context=context)
        return

    results = []
    for idx, ch in enumerate(channels, start=1):
        cid = ch.get('channel_id', '')
        title = ch.get('title', 'Channel')
        is_adm, badge, detail = await check_channel_bot_admin_status(context.bot, cid)
        results.append(
            f"{idx}. <b>{html.escape(title)}</b> (<code>{html.escape(str(cid))}</code>)\n"
            f"   ├ ⚡ <b>Status:</b> {badge}\n"
            f"   └ 📋 <b>Diagnostics:</b> <i>{detail}</i>"
        )

    header = (
        "<b>🔍 BOT ADMIN STATUS DIAGNOSTIC REPORT</b>\n"
        "<i>Live Telegram API Channel Probe</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    text = f"{header}<blockquote>" + "\n\n".join(results) + "</blockquote>\n\n"
    text += "💡 <i>Ensure @gravixhostbot is added as Administrator in each channel for 100% reliable automated member verification.</i>"

    reply_markup = get_admin_fsub_reply_keyboard(channels, 0)
    await _send_admin_msg(update, text, reply_markup=reply_markup, context=context)

async def admin_fsub_del_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: str = None):
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>", context=context)
        return

    if channel_id is None and update.message and update.message.text:
        clean_text = normalize_user_input(update.message.text)
        m = re.search(r"\[(.+)\]", clean_text)
        if m:
            channel_id = m.group(1).strip()

    if channel_id:
        database.delete_required_channel(channel_id)
        await _send_admin_msg(
            update,
            f"✅ <b>CHANNEL REMOVED</b>\nForce-Sub Channel <code>{html.escape(channel_id)}</code> has been deleted successfully.",
            context=context
        )

    await admin_fsub_list_handler(update, context, 0)

async def admin_toggle_maint_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>", context=context)
        return

    current = database.get_setting("maintenance_mode", "0") == "1"
    new_val = "0" if current else "1"
    database.set_setting("maintenance_mode", new_val)

    status_str = "ENABLED (🔴 ON)" if new_val == "1" else "DISABLED (🟢 OFF)"
    await _send_admin_msg(
        update,
        f"⚙️ <b>MAINTENANCE MODE UPDATED</b>\nPlatform maintenance status is now <code>{status_str}</code>.",
        context=context
    )
    await admin_panel(update, context)

async def admin_broadcast_prompt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>", context=context)
        return

    text = (
        "<b>📢 GLOBAL BROADCAST</b>\n"
        "<i>Platform-Wide Announcement Dispatcher</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        "To broadcast an announcement to all registered users, send the command:\n\n"
        "<code>/broadcast Your message content here...</code>\n\n"
        "HTML formatting is supported in broadcast messages."
        "</blockquote>\n\n"
        "💡 <i>Tap Back to Admin below to return to the central console.</i>"
    )
    reply_markup = ReplyKeyboardMarkup([[KeyboardButton("⇋ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗔𝗱𝗺𝗶𝗻 ⇋")]], resize_keyboard=True)
    await _send_admin_msg(update, text, reply_markup=reply_markup, context=context)

async def admin_broadcast_get_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip() if (update.message and update.message.text) else ""
    if is_cancellation_text(text):
        return await admin_broadcast_cancel(update, context)

    users = database.get_all_users()
    total = len(users)
    success = 0
    failed = 0
    progress_msg = await _send_admin_msg(update, f"⏳ <b>Broadcasting to <code>{total}</code> users...</b>", context=context)

    formatted_msg = (
        "<b>📢 GRAVIX-HOST ANNOUNCEMENT</b>\n"
        "<i>Official Platform Update</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<blockquote>{html.escape(text)}</blockquote>"
    )

    for u in users:
        try:
            await context.bot.send_message(
                chat_id=u['user_id'],
                text=formatted_msg,
                parse_mode="HTML"
            )
            database.set_user_blocked(u['user_id'], False)
            success += 1
        except Exception as e:
            failed += 1
            err = str(e).lower()
            if "blocked by the user" in err or "bot was blocked" in err or "user is deactivated" in err:
                database.set_user_blocked(u['user_id'], True)

    report_text = (
        "<b>✅ BROADCAST COMPLETION REPORT</b>\n"
        "<i>Global Announcement Delivery Telemetry</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        f"👥 <b>Target Users:</b> <code>{total}</code>\n"
        f"✔️ <b>Successfully Delivered:</b> <code>{success}</code>\n"
        f"❌ <b>Delivery Failures:</b> <code>{failed}</code> (Blocked/Deleted)"
        "</blockquote>"
    )
    if progress_msg:
        try:
            await progress_msg.edit_text(report_text, parse_mode="HTML")
        except Exception:
            await _send_admin_msg(update, report_text, context=context)
    else:
        await _send_admin_msg(update, report_text, context=context)
    await admin_panel(update, context)
    return ConversationHandler.END

async def admin_broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_admin_msg(
        update,
        "<b>❌ BROADCAST CANCELLED</b>\nGlobal broadcast cancelled.",
        context=context
    )
    await admin_panel(update, context)
    return ConversationHandler.END

async def admin_exit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        from user_handlers import get_main_reply_keyboard
        reply_kb = get_main_reply_keyboard(user_id)
    except Exception:
        reply_kb = ReplyKeyboardMarkup([[KeyboardButton("⇋ 𝗠𝘆 𝗛𝗼𝘀𝘁𝗲𝗱 𝗕𝗼𝘁𝘀 ⇋"), KeyboardButton("⇋ 𝗛𝗼𝘀𝘁 𝗡𝗲𝘄 𝗕𝗼𝘁 ⇋")]], resize_keyboard=True)

    text = (
        "<b>🏠 EXITED ADMIN CONSOLE</b>\n"
        "<i>Returned to User Dashboard</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Returned to user dashboard."
    )
    await _send_admin_msg(update, text, reply_markup=reply_kb, context=context)

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>", context=context)
        return

    if not context.args:
        await _send_admin_msg(update, "⚠️ <b>Usage:</b> <code>/broadcast &lt;Your message&gt;</code>", context=context)
        return

    broadcast_text = " ".join(context.args)
    users = database.get_all_users()
    total = len(users)
    success = 0
    failed = 0

    progress_msg = await _send_admin_msg(update, f"⏳ <b>Broadcasting to <code>{total}</code> users...</b>", context=context)

    formatted_msg = (
        "<b>📢 GRAVIX-HOST ANNOUNCEMENT</b>\n"
        "<i>Official Platform Update</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<blockquote>{html.escape(broadcast_text)}</blockquote>"
    )

    for u in users:
        try:
            await context.bot.send_message(
                chat_id=u['user_id'],
                text=formatted_msg,
                parse_mode="HTML"
            )
            database.set_user_blocked(u['user_id'], False)
            success += 1
        except Exception as e:
            failed += 1
            err = str(e).lower()
            if "blocked by the user" in err or "bot was blocked" in err or "user is deactivated" in err:
                database.set_user_blocked(u['user_id'], True)

    report_text = (
        "<b>✅ BROADCAST COMPLETION REPORT</b>\n"
        "<i>Global Announcement Delivery Telemetry</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        f"👥 <b>Target Users:</b> <code>{total}</code>\n"
        f"✔️ <b>Successfully Delivered:</b> <code>{success}</code>\n"
        f"❌ <b>Delivery Failures:</b> <code>{failed}</code> (Blocked/Deleted)"
        "</blockquote>"
    )
    if progress_msg:
        try:
            await progress_msg.edit_text(report_text, parse_mode="HTML")
        except Exception:
            await _send_admin_msg(update, report_text, context=context)
    else:
        await _send_admin_msg(update, report_text, context=context)

async def admin_check_blocked_users_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deep live Telegram API probe checking how many users have blocked the bot."""
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>", context=context)
        return

    users = database.get_all_users()
    total = len(users)
    if total == 0:
        await _send_admin_msg(update, "<blockquote>No registered users found in database.</blockquote>", context=context)
        return

    prog_msg = await _send_admin_msg(update, f"⏳ <b>Testing reachability for <code>{total}</code> users via Telegram API...</b>", context=context)

    active_cnt = 0
    blocked_cnt = 0
    banned_cnt = 0
    deactivated_cnt = 0

    for u in users:
        uid = u['user_id']
        if u.get('is_banned'):
            banned_cnt += 1
            continue

        try:
            # send_chat_action silently checks if bot is blocked without sending a message
            await context.bot.send_chat_action(chat_id=uid, action=ChatAction.TYPING)
            database.set_user_blocked(uid, False)
            active_cnt += 1
        except Exception as e:
            err = str(e).lower()
            if "blocked by the user" in err or "bot was blocked" in err:
                database.set_user_blocked(uid, True)
                blocked_cnt += 1
            elif "user is deactivated" in err or "chat not found" in err:
                database.set_user_blocked(uid, True)
                deactivated_cnt += 1
            else:
                active_cnt += 1
        await asyncio.sleep(0.04)

    retention_rate = (active_cnt / total * 100.0) if total > 0 else 0.0

    report = (
        "<b>👥 AUDIENCE HEALTH & BLOCK REPORT</b>\n"
        "<i>Real-time Reachability Diagnostics</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        f"👥 <b>Total Users:</b> <code>{total}</code>\n"
        f"🟢 <b>Active (Reachable):</b> <code>{active_cnt}</code> ({retention_rate:.1f}%)\n"
        f"🔴 <b>Blocked Bot:</b> <code>{blocked_cnt}</code>\n"
        f"⚫ <b>Deactivated Accounts:</b> <code>{deactivated_cnt}</code>\n"
        f"🚫 <b>Banned Users:</b> <code>{banned_cnt}</code>"
        "</blockquote>\n\n"
        "💡 <i>User reachability telemetry updated live in database.</i>"
    )

    reply_markup = ReplyKeyboardMarkup([
        [KeyboardButton("⇋ 𝗖𝗵𝗲𝗰𝗸 𝗕𝗹𝗼𝗰𝗸𝗲𝗱 𝗨𝘀𝗲𝗿𝘀 ⇋"), KeyboardButton("⇋ 𝗨𝘀𝗲𝗿 𝗗𝗶𝗿𝗲𝗰𝘁𝗼𝗿𝘆 ⇋")],
        [KeyboardButton("⇋ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗔𝗱𝗺𝗶𝗻 ⇋")]
    ], resize_keyboard=True)

    if prog_msg:
        try:
            await prog_msg.edit_text(report, parse_mode="HTML", reply_markup=reply_markup)
        except Exception:
            await _send_admin_msg(update, report, reply_markup=reply_markup, context=context)
    else:
        await _send_admin_msg(update, report, reply_markup=reply_markup, context=context)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. Force-Sub Add Channel Conversation Flow
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FSUB_CANCEL_KEYBOARD = ReplyKeyboardMarkup([[KeyboardButton("⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋")]], resize_keyboard=True)

async def admin_fsub_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied:</b> You are not authorized.", context=context)
        return ConversationHandler.END

    context.user_data['active_flow'] = 'fsub_add'
    text = (
        "<b>➕ ADD FORCE-SUB CHANNEL (1/3)</b>\n"
        "<i>Step 1 of 3: Channel ID or Handle</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        "Please send the <b>Telegram Channel ID / Public Handle</b>:\n\n"
        "• Public Channel: <code>@ChannelUsername</code>\n"
        "• Private Channel: <code>-1001234567890</code>\n\n"
        "⚠️ <i>Make sure the master bot is added as an Administrator in this channel.</i>"
        "</blockquote>\n\n"
        "<i>(Send Channel ID or tap ⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋ below to abort)</i>"
    )
    await _send_admin_msg(update, text, reply_markup=FSUB_CANCEL_KEYBOARD, context=context)
    return A_FSUB_ID

async def admin_fsub_get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip() if (update.message and update.message.text) else ""
    if is_cancellation_text(text):
        context.user_data.pop('fsub_channel_id', None)
        context.user_data.pop('fsub_title', None)
        context.user_data.pop('active_flow', None)
        if not await handle_admin_text(update, context):
            await admin_panel(update, context)
        return ConversationHandler.END

    if context.user_data.get('active_flow') != 'fsub_add':
        await _send_admin_msg(update, "⚠️ <i>This session expired. Please use /admin to start again.</i>", context=context)
        return ConversationHandler.END

    raw_id = text
    is_valid = False
    if raw_id.startswith("@") and len(raw_id) >= 4 and re.match(r"^@[a-zA-Z0-9_]+$", raw_id):
        is_valid = True
    elif re.match(r"^-100\d+$", raw_id):
        is_valid = True

    if not is_valid:
        text_resp = (
            "<b>⚠️ INVALID CHANNEL ID FORMAT</b>\n"
            "<i>Verification Failed</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<blockquote>"
            "Please provide a valid public handle (e.g. <code>@GravixRDP</code>) or numeric private channel ID (e.g. <code>-1001234567890</code>)."
            "</blockquote>\n\n"
            "<i>(Send Channel ID or tap ⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋ to abort)</i>"
        )
        await _send_admin_msg(update, text_resp, reply_markup=FSUB_CANCEL_KEYBOARD, context=context)
        return A_FSUB_ID

    context.user_data['fsub_channel_id'] = raw_id
    text_resp = (
        "<b>➕ ADD FORCE-SUB CHANNEL (2/3)</b>\n"
        "<i>Step 2 of 3: Channel Title</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        f"Channel ID: <code>{html.escape(raw_id)}</code>\n\n"
        "Please send a display <b>Title</b> for this channel:\n"
        "<i>(Example: Gravix Official Channel)</i>"
        "</blockquote>\n\n"
        "<i>(Send Title or tap ⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋ to abort)</i>"
    )
    await _send_admin_msg(update, text_resp, reply_markup=FSUB_CANCEL_KEYBOARD, context=context)
    return A_FSUB_TITLE

async def admin_fsub_get_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip() if (update.message and update.message.text) else ""
    if is_cancellation_text(text):
        context.user_data.pop('fsub_channel_id', None)
        context.user_data.pop('fsub_title', None)
        context.user_data.pop('active_flow', None)
        if not await handle_admin_text(update, context):
            await admin_panel(update, context)
        return ConversationHandler.END

    if context.user_data.get('active_flow') != 'fsub_add':
        await _send_admin_msg(update, "⚠️ <i>This session expired. Please use /admin to start again.</i>", context=context)
        return ConversationHandler.END

    title = text
    if not title or len(title) < 2 or len(title) > 64:
        text_resp = (
            "<b>⚠️ INVALID TITLE LENGTH</b>\n"
            "<i>Verification Failed</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<blockquote>"
            "Please enter a channel title between 2 and 64 characters."
            "</blockquote>\n\n"
            "<i>(Send Title or tap ⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋ to abort)</i>"
        )
        await _send_admin_msg(update, text_resp, reply_markup=FSUB_CANCEL_KEYBOARD, context=context)
        return A_FSUB_TITLE

    context.user_data['fsub_title'] = title
    cid = context.user_data.get('fsub_channel_id', '')
    text_resp = (
        "<b>➕ ADD FORCE-SUB CHANNEL (3/3)</b>\n"
        "<i>Step 3 of 3: Channel Invite Link</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        f"Channel ID: <code>{html.escape(cid)}</code>\n"
        f"Title: <b>{html.escape(title)}</b>\n\n"
        "Please enter the <b>Invite Link</b> for this channel:\n"
        "<i>(Example: https://t.me/GravixRDP or https://t.me/+joinhash)</i>"
        "</blockquote>\n\n"
        "<i>(Send Link or tap ⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋ to abort)</i>"
    )
    await _send_admin_msg(update, text_resp, reply_markup=FSUB_CANCEL_KEYBOARD, context=context)
    return A_FSUB_LINK

async def admin_fsub_get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip() if (update.message and update.message.text) else ""
    if is_cancellation_text(text):
        context.user_data.pop('fsub_channel_id', None)
        context.user_data.pop('fsub_title', None)
        context.user_data.pop('active_flow', None)
        if not await handle_admin_text(update, context):
            await admin_panel(update, context)
        return ConversationHandler.END

    if context.user_data.get('active_flow') != 'fsub_add':
        await _send_admin_msg(update, "⚠️ <i>This session expired. Please use /admin to start again.</i>", context=context)
        return ConversationHandler.END

    link = text
    if not re.match(r"^https?://(t\.me|telegram\.me)/.+$", link):
        text_resp = (
            "<b>⚠️ INVALID INVITE LINK</b>\n"
            "<i>Verification Failed</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<blockquote>"
            "The invite link must start with <code>https://t.me/...</code>"
            "</blockquote>\n\n"
            "<i>(Send Link or tap ⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋ to abort)</i>"
        )
        await _send_admin_msg(update, text_resp, reply_markup=FSUB_CANCEL_KEYBOARD, context=context)
        return A_FSUB_LINK

    cid = context.user_data.get('fsub_channel_id', '')
    title = context.user_data.get('fsub_title', '')

    database.add_required_channel(cid, title, link)
    context.user_data.pop('fsub_channel_id', None)
    context.user_data.pop('fsub_title', None)
    context.user_data.pop('active_flow', None)

    text_resp = (
        "<b>✅ CHANNEL ADDED SUCCESSFULLY</b>\n"
        "<i>Mandatory Subscription Updated</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        f"📢 <b>Title:</b> {html.escape(title)}\n"
        f"🆔 <b>Channel ID:</b> <code>{html.escape(cid)}</code>\n"
        f"🔗 <b>Invite Link:</b> <a href=\"{html.escape(link)}\">{html.escape(link)}</a>"
        "</blockquote>\n\n"
        "Users are now required to join this channel."
    )
    channels = database.get_required_channels()
    reply_markup = get_admin_fsub_reply_keyboard(channels, 0)
    await _send_admin_msg(update, text_resp, reply_markup=reply_markup, context=context)
    return ConversationHandler.END

async def admin_fsub_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop('fsub_channel_id', None)
    context.user_data.pop('fsub_title', None)
    context.user_data.pop('active_flow', None)

    await _send_admin_msg(
        update,
        "<b>❌ ADD CHANNEL CANCELLED</b>\n"
        "<i>Wizard Aborted</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "The channel addition wizard was aborted.",
        context=context
    )
    await admin_fsub_list_handler(update, context, 0)
    return ConversationHandler.END

admin_cancel_filter = filters.Regex(
    r"(?i)^(?:⇋\s*)?(?:❌\s*Cancel|/cancel|cancel|🔙\s*Back to Admin|🏠\s*Back to Admin|🏠\s*Exit Admin|🔙\s*Back to Users|🔙\s*𝗕𝗮𝗰𝗸\s*𝘁𝗼\s*𝗔𝗱𝗺𝗶𝗻|🏠\s*𝗕𝗮𝗰𝗸\s*𝘁𝗼\s*𝗔𝗱𝗺𝗶𝗻|🏠\s*𝗘𝘅𝗶𝘁\s*𝗔𝗱𝗺𝗶𝗻|🔙\s*𝗕𝗮𝗰𝗸\s*𝘁𝗼\s*𝗨𝘀𝗲𝗿𝘀|𝗕𝗮𝗰𝗸\s*𝘁𝗼\s*𝗔𝗱𝗺𝗶𝗻|𝗕𝗮𝗰𝗸\s*𝘁𝗼\s*𝗨𝘀𝗲𝗿𝘀|𝗘𝘅𝗶𝘁\s*𝗔𝗱𝗺𝗶𝗻|𝗖𝗮𝗻𝗰𝗲𝗹)(?:\s*⇋)?$"
)

admin_fsub_conv = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex(r"^(?:⇋\s*)?(?:➕\s*)?(?:Add Force-Sub Channel|𝗔𝗱𝗱 𝗙𝗼𝗿𝗰𝗲-𝗦𝘂𝗯 𝗖𝗵𝗮𝗻𝗻𝗲𝗹)(?:\s*⇋)?$"), admin_fsub_add_start),
        CallbackQueryHandler(admin_fsub_add_start, pattern="^admin_fsub_add_start$"),
        CommandHandler("addchannel", admin_fsub_add_start)
    ],
    states={
        A_FSUB_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~admin_cancel_filter, admin_fsub_get_id)],
        A_FSUB_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~admin_cancel_filter, admin_fsub_get_title)],
        A_FSUB_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~admin_cancel_filter, admin_fsub_get_link)],
    },
    fallbacks=[
        CommandHandler("cancel", admin_fsub_cancel),
        MessageHandler(admin_cancel_filter, admin_fsub_cancel),
        CallbackQueryHandler(admin_fsub_cancel, pattern="^(admin_fsub_cancel|admin_panel)$")
    ],
    conversation_timeout=600,
    per_message=False
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3.1. Admin Set Custom Slots Conversation Flow
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SLOTS_CANCEL_KEYBOARD = ReplyKeyboardMarkup([[KeyboardButton("⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋")]], resize_keyboard=True)

async def admin_slots_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied:</b> You are not authorized.", context=context)
        return ConversationHandler.END

    raw_text = update.message.text.strip() if (update.message and update.message.text) else ""
    clean_text = normalize_user_input(raw_text)
    m = re.search(r"\[UID:\s*(\d+)\]|\(UID:\s*(\d+)\)", clean_text)
    if not m:
        await admin_users_list_handler(update, context, 0)
        return ConversationHandler.END

    target_uid = int(m.group(1) or m.group(2))
    context.user_data['active_flow'] = 'set_slots'
    context.user_data['target_slot_uid'] = target_uid

    target_user = database.get_or_create_user(target_uid)
    curr_slots = target_user.get('max_slots', 3)

    msg_text = (
        "<b>✏️ SET CUSTOM BOT SLOTS</b>\n"
        f"<i>Adjust Slot Allocation for UID {target_uid}</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        f"👤 <b>Target User ID:</b> <code>{target_uid}</code>\n"
        f"📦 <b>Current Slots:</b> <code>{curr_slots}</code>\n\n"
        "Please send the new slot allocation number (<b>1 to 100</b>):"
        "</blockquote>\n\n"
        "<i>(Enter an integer from 1 to 100, or tap ⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋ below to abort)</i>"
    )
    await _send_admin_msg(update, msg_text, reply_markup=SLOTS_CANCEL_KEYBOARD, context=context)
    return A_SET_SLOTS_NUM

async def admin_slots_get_num(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip() if (update.message and update.message.text) else ""
    target_uid = context.user_data.get('target_slot_uid')

    if is_cancellation_text(text):
        context.user_data.pop('target_slot_uid', None)
        context.user_data.pop('active_flow', None)
        if target_uid:
            await admin_user_detail_handler(update, context, target_uid)
        else:
            if not await handle_admin_text(update, context):
                await admin_panel(update, context)
        return ConversationHandler.END

    if context.user_data.get('active_flow') != 'set_slots' or not target_uid:
        await _send_admin_msg(update, "⚠️ <i>This session expired. Please use /admin to start again.</i>", context=context)
        return ConversationHandler.END

    if not text.isdigit():
        err_msg = (
            "<b>⚠️ INVALID INPUT FORMAT</b>\n"
            "<i>Integer Required</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<blockquote>"
            "Please provide a valid integer number between <b>1</b> and <b>100</b>."
            "</blockquote>\n\n"
            "<i>(Enter a number between 1-100 or tap ⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋ to abort)</i>"
        )
        await _send_admin_msg(update, err_msg, reply_markup=SLOTS_CANCEL_KEYBOARD, context=context)
        return A_SET_SLOTS_NUM

    slots = int(text)
    if slots < 1 or slots > 100:
        err_msg = (
            "<b>⚠️ OUT OF PERMITTED RANGE</b>\n"
            "<i>Slot Limit Bounds</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<blockquote>"
            "Custom slot limit must be between <b>1</b> and <b>100</b>."
            "</blockquote>\n\n"
            "<i>(Enter a number between 1-100 or tap ⇋ 𝗖𝗮𝗻𝗰𝗲 proposal to abort)</i>"
        )
        await _send_admin_msg(update, err_msg, reply_markup=SLOTS_CANCEL_KEYBOARD, context=context)
        return A_SET_SLOTS_NUM

    database.set_user_slots(target_uid, slots)
    context.user_data.pop('target_slot_uid', None)
    context.user_data.pop('active_flow', None)

    await _send_admin_msg(
        update,
        f"✅ <b>SLOTS UPDATED</b>\nHosting capacity set to <code>{slots}</code> bots for User <code>{target_uid}</code>.",
        context=context
    )
    await admin_user_detail_handler(update, context, target_uid)
    return ConversationHandler.END

admin_slots_get_count = admin_slots_get_num

async def admin_slots_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_uid = context.user_data.pop('target_slot_uid', None)
    context.user_data.pop('active_flow', None)

    await _send_admin_msg(
        update,
        "<b>❌ SET SLOTS CANCELLED</b>\n"
        "<i>Operation Aborted</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Custom slot configuration was cancelled.",
        context=context
    )
    if target_uid:
        await admin_user_detail_handler(update, context, target_uid)
    else:
        await admin_users_list_handler(update, context, 0)
    return ConversationHandler.END

admin_slots_conv = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex(r"^(?:⇋\s*)?(?:✏️\s*)?(?:Set Custom Slots|𝗦𝗲𝘁 𝗖𝘂𝘀𝘁𝗼𝗺 𝗦𝗹𝗼𝘁𝘀)\s+\[UID:\s*(\d+)\](?:\s*⇋)?$"), admin_slots_start)
    ],
    states={
        A_SET_SLOTS_NUM: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~admin_cancel_filter, admin_slots_get_num)]
    },
    fallbacks=[
        CommandHandler("cancel", admin_slots_cancel),
        MessageHandler(admin_cancel_filter, admin_slots_cancel),
        CallbackQueryHandler(admin_slots_cancel, pattern="^(admin_slots_cancel|admin_panel)$")
    ],
    conversation_timeout=600,
    per_message=False
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. Central Dispatchers / Legacy Compatibility
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Dispatches any incoming admin button text to its corresponding handler."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return False

    raw_text = update.message.text.strip() if (update.message and update.message.text) else ""
    if not raw_text:
        return False

    clean_text = normalize_user_input(raw_text)
    stripped = clean_text.strip("⇋ ").strip()

    # 1. Main Navigation
    if stripped in ["System Stats", "📊 System Stats"] or clean_text in ["System Stats", "📊 System Stats"]:
        await admin_stats_handler(update, context)
        return True

    if stripped in ["User Manager", "👥 User Manager", "User Directory", "👥 User Directory"] or clean_text in ["User Manager", "👥 User Manager", "User Directory", "👥 User Directory"]:
        await admin_users_list_handler(update, context, 0)
        return True

    if (
        stripped in ["Check Blocked Users", "Blocked Users", "Audience Health", "Check Audience", "🔍 Check Blocked Users", "𝗖𝗵𝗲𝗰𝗸 𝗕𝗹𝗼𝗰𝗸𝗲𝗱 𝗨𝘀𝗲𝗿𝘀"]
        or "Check Blocked Users" in stripped
        or "Blocked Users" in stripped
        or "Check Blocked" in clean_text
    ):
        await admin_check_blocked_users_handler(update, context)
        return True

    if stripped in ["All Hosted Bots", "🤖 All Hosted Bots"] or clean_text in ["All Hosted Bots", "🤖 All Hosted Bots"]:
        await admin_bots_list_handler(update, context, 0)
        return True

    if stripped in ["Force-Sub Channels", "📢 Force-Sub Channels"] or clean_text in ["Force-Sub Channels", "📢 Force-Sub Channels"]:
        await admin_fsub_list_handler(update, context, 0)
        return True

    if stripped in ["Broadcast", "Broadcast Announcement", "Broadcast Message", "📢 Broadcast", "📢 Broadcast Announcement", "📢 Broadcast Message"] or clean_text in ["Broadcast", "Broadcast Announcement", "Broadcast Message", "📢 Broadcast", "📢 Broadcast Announcement", "📢 Broadcast Message"]:
        await admin_broadcast_prompt_handler(update, context)
        return True

    if stripped.startswith("Toggle Maintenance") or clean_text.startswith("Toggle Maintenance") or clean_text.startswith("⚙️ Toggle Maintenance") or "Toggle Maintenance" in stripped:
        await admin_toggle_maint_handler(update, context)
        return True

    if stripped in ["Refresh Admin", "Open Admin Panel", "Back to Admin", "👑 Open Admin Panel", "🔄 Refresh Admin", "🔙 Back to Admin", "🏠 Back to Admin"] or clean_text in ["Refresh Admin", "Open Admin Panel", "Back to Admin", "👑 Open Admin Panel", "🔄 Refresh Admin", "🔙 Back to Admin", "🏠 Back to Admin"]:
        await admin_panel(update, context)
        return True

    if stripped in ["Exit Admin", "🏠 Exit Admin"] or clean_text in ["Exit Admin", "🏠 Exit Admin"]:
        await admin_exit_handler(update, context)
        return True

    # 2. User Management Navigation & Actions
    if stripped in ["Back to Users", "🔙 Back to Users"] or clean_text in ["Back to Users", "🔙 Back to Users"]:
        page = context.user_data.get('admin_users_page', 0)
        await admin_users_list_handler(update, context, page)
        return True

    if stripped in ["Prev Users", "⬅️ Prev Users"] or clean_text in ["Prev Users", "⬅️ Prev Users"]:
        curr_page = max(0, context.user_data.get('admin_users_page', 0) - 1)
        await admin_users_list_handler(update, context, curr_page)
        return True

    if stripped in ["Next Users", "Next Users ➡️"] or clean_text in ["Next Users", "Next Users ➡️"]:
        curr_page = context.user_data.get('admin_users_page', 0) + 1
        await admin_users_list_handler(update, context, curr_page)
        return True

    if "Ban User" in stripped or "Unban User" in stripped or "Ban User" in clean_text or "Unban User" in clean_text:
        m = re.search(r"\[UID:\s*(\d+)\]|\(UID:\s*(\d+)\)", clean_text)
        if m:
            uid = int(m.group(1) or m.group(2))
            await admin_user_action_handler(update, context, action="toggle_ban", target_uid=uid)
            return True

    if "+1 Slot" in stripped or "+2 Slots" in stripped or "+1 Slot" in clean_text or "+2 Slots" in clean_text:
        m = re.search(r"\[UID:\s*(\d+)\]|\(UID:\s*(\d+)\)", clean_text)
        if m:
            uid = int(m.group(1) or m.group(2))
            await admin_user_action_handler(update, context, action="inc_slots", target_uid=uid)
            return True

    if "-1 Slot" in stripped or "-1 Slot" in clean_text:
        m = re.search(r"\[UID:\s*(\d+)\]|\(UID:\s*(\d+)\)", clean_text)
        if m:
            uid = int(m.group(1) or m.group(2))
            await admin_user_action_handler(update, context, action="dec_slots", target_uid=uid)
            return True

    if "Set Custom Slots" in stripped or "Set Custom Slots" in clean_text:
        m = re.search(r"\[UID:\s*(\d+)\]|\(UID:\s*(\d+)\)", clean_text)
        if m:
            await admin_slots_start(update, context)
            return True

    # User select button from user list (e.g. "⇋ Bob (@bob) [UID: 12345] ⇋")
    m_user = re.search(r"(?:\[UID:\s*(\d+)\]|\(UID:\s*(\d+)\))", clean_text)
    if m_user and not any(k in stripped for k in ["Slot", "Slots", "Ban", "Unban"]):
        uid = int(m_user.group(1) or m_user.group(2))
        await admin_user_detail_handler(update, context, user_id=uid)
        return True

    # 3. Bot Management Navigation & Actions
    if stripped in ["Back to All Bots", "🔙 Back to All Bots"] or clean_text in ["Back to All Bots", "🔙 Back to All Bots"]:
        page = context.user_data.get('admin_bots_page', 0)
        await admin_bots_list_handler(update, context, page)
        return True

    if stripped in ["Prev All Bots", "⬅️ Prev All Bots", "Prev Bots"] or clean_text in ["Prev All Bots", "⬅️ Prev All Bots", "Prev Bots"]:
        curr_page = max(0, context.user_data.get('admin_bots_page', 0) - 1)
        await admin_bots_list_handler(update, context, curr_page)
        return True

    if stripped in ["Next All Bots", "Next All Bots ➡️", "Next Bots"] or clean_text in ["Next All Bots", "Next All Bots ➡️", "Next Bots"]:
        curr_page = context.user_data.get('admin_bots_page', 0) + 1
        await admin_bots_list_handler(update, context, curr_page)
        return True

    m_bot = re.search(r"\[#([a-zA-Z0-9_-]+)\]", clean_text)
    if m_bot:
        bot_id = m_bot.group(1)
        if "Force Start" in stripped or "▶️ Force Start" in stripped or stripped.startswith("Start ") or stripped.startswith("Start [") or stripped == "Start":
            await admin_bot_action_handler(update, context, action="start", bot_id=bot_id)
            return True
        elif "Stop" in stripped or "⏹️ Stop" in stripped:
            await admin_bot_action_handler(update, context, action="stop", bot_id=bot_id)
            return True
        elif "Restart" in stripped or "🔄 Restart" in stripped:
            await admin_bot_action_handler(update, context, action="restart", bot_id=bot_id)
            return True
        elif "View Logs" in stripped or "📜 View Logs" in stripped or stripped.startswith("Logs"):
            await admin_bot_action_handler(update, context, action="logs", bot_id=bot_id)
            return True
        elif (
            "Get Bot Code" in stripped
            or "Download Code" in stripped
            or "View Code" in stripped
            or "Get Code" in stripped
            or "Export Code" in stripped
            or stripped.startswith("Code")
            or "𝗚𝗲𝘁 𝗕𝗼𝘁 𝗖𝗼𝗱𝗲" in clean_text
        ):
            await admin_bot_action_handler(update, context, action="code", bot_id=bot_id)
            return True
        elif "Force Delete" in stripped or "🗑️ Force Delete" in stripped or stripped.startswith("Delete"):
            await admin_bot_action_handler(update, context, action="del", bot_id=bot_id)
            return True
        else:
            # Selected bot from list
            await admin_bot_detail_handler(update, context, bot_id=bot_id)
            return True

    # 4. Force-Sub Navigation & Actions
    if stripped in ["Back to Force-Sub", "🔙 Back to Force-Sub"] or clean_text in ["Back to Force-Sub", "🔙 Back to Force-Sub"]:
        page = context.user_data.get('admin_fsub_page', 0)
        await admin_fsub_list_handler(update, context, page)
        return True

    if stripped in ["Prev FSub", "⬅️ Prev FSub"] or clean_text in ["Prev FSub", "⬅️ Prev FSub"]:
        curr_page = max(0, context.user_data.get('admin_fsub_page', 0) - 1)
        await admin_fsub_list_handler(update, context, curr_page)
        return True

    if stripped in ["Next FSub", "Next FSub ➡️"] or clean_text in ["Next FSub", "Next FSub ➡️"]:
        curr_page = context.user_data.get('admin_fsub_page', 0) + 1
        await admin_fsub_list_handler(update, context, curr_page)
        return True

    if stripped in ["Add Force-Sub Channel", "➕ Add Force-Sub Channel", "Add Channel", "➕ Add Channel"] or clean_text in ["Add Force-Sub Channel", "➕ Add Force-Sub Channel", "Add Channel", "➕ Add Channel"]:
        await admin_fsub_add_start(update, context)
        return True

    if (
        stripped in ["Test Bot Admin Status", "Check Bot Admin Status", "Test Admin Status", "Bot Admin Status", "Test Channels", "Check Channels"]
        or "Test Bot Admin Status" in stripped
        or "Check Bot Admin Status" in stripped
        or "Test Admin Status" in stripped
    ):
        await admin_fsub_test_admin_status_handler(update, context)
        return True

    if "Remove" in stripped and ("[" in clean_text and "]" in clean_text):
        m_cid = re.search(r"\[(.+)\]", clean_text)
        if m_cid:
            await admin_fsub_del_handler(update, context, channel_id=m_cid.group(1).strip())
            return True

    return False

async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data_override: str = None):
    """Legacy callback query handler for graceful backward compatibility."""
    query = update.callback_query
    user_id = query.from_user.id
    data = data_override if data_override is not None else query.data

    if not is_admin(user_id):
        await query.answer("⛔ Access Denied", show_alert=True)
        return

    if data_override is None:
        try:
            await query.answer()
        except Exception:
            pass

    if data in ["admin_refresh", "admin_panel"]:
        await admin_panel(update, context)
    elif data == "admin_stats":
        await admin_stats_handler(update, context)
    elif data.startswith("admin_users_"):
        page = int(data.split("_")[2])
        await admin_users_list_handler(update, context, page=page)
    elif data.startswith("admin_uinfo_"):
        target_uid = int(data.split("_")[2])
        await admin_user_detail_handler(update, context, user_id=target_uid)
    elif data.startswith("admin_toggle_ban_"):
        target_uid = int(data.split("_")[3])
        await admin_user_action_handler(update, context, action="toggle_ban", target_uid=target_uid)
    elif data.startswith("admin_inc_slot_"):
        target_uid = int(data.split("_")[3])
        await admin_user_action_handler(update, context, action="inc_slots", target_uid=target_uid)
    elif data.startswith("admin_dec_slot_"):
        target_uid = int(data.split("_")[3])
        await admin_user_action_handler(update, context, action="dec_slots", target_uid=target_uid)
    elif data.startswith("admin_bots_"):
        page = int(data.split("_")[2])
        await admin_bots_list_handler(update, context, page=page)
    elif data.startswith("admin_binfo_"):
        bot_id = data.split("_")[2]
        await admin_bot_detail_handler(update, context, bot_id=bot_id)
    elif data.startswith("admin_baction_"):
        parts = data.split("_")
        action = parts[2]
        bot_id = parts[3]
        await admin_bot_action_handler(update, context, action=action, bot_id=bot_id)
    elif data.startswith("admin_blogs_"):
        bot_id = data.split("_")[2]
        await admin_bot_action_handler(update, context, action="logs", bot_id=bot_id)
    elif data == "admin_toggle_maint":
        await admin_toggle_maint_handler(update, context)
    elif data == "admin_broadcast_prompt":
        await admin_broadcast_prompt_handler(update, context)
    elif data.startswith("admin_fsub_list_"):
        page = int(data.split("_")[3])
        await admin_fsub_list_handler(update, context, page=page)
    elif data.startswith("admin_fsub_del_"):
        target_cid = data.replace("admin_fsub_del_", "", 1)
        await admin_fsub_del_handler(update, context, channel_id=target_cid)
    elif data == "admin_fsub_cancel":
        await admin_fsub_cancel(update, context)


