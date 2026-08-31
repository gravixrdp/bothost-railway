import os
import re
import html
import shutil
import psutil
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
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
from code_analyzer import is_cancellation_text

logger = logging.getLogger("GravixHost.Admin")

# States for admin conversation handlers
A_WAIT_BROADCAST, A_WAIT_SLOTS_UID, A_WAIT_SLOTS_NUM = range(10, 13)
A_FSUB_ID, A_FSUB_TITLE, A_FSUB_LINK = range(20, 23)

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

def make_progress_bar(percent: float, length: int = 10) -> str:
    """Generates an ultra-clean progress bar."""
    filled = int(round((max(0.0, min(100.0, percent)) / 100.0) * length))
    return "▰" * filled + "▱" * (length - filled)

async def _send_admin_msg(update: Update, text: str, reply_markup=None):
    """Helper to send reply keyboard response cleanly with HTML formatting."""
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    elif update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass
        if update.callback_query.message:
            await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Admin Keyboard Generators
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_admin_reply_keyboard(maint_status: str) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("📊 System Stats"), KeyboardButton("👥 User Manager")],
        [KeyboardButton("🤖 All Hosted Bots"), KeyboardButton("📢 Force-Sub Channels")],
        [KeyboardButton("📢 Broadcast Announcement"), KeyboardButton(f"⚙️ Toggle Maintenance ({maint_status})")],
        [KeyboardButton("🔄 Refresh Admin"), KeyboardButton("🏠 Exit Admin")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_users_reply_keyboard(users: list, page: int = 0) -> ReplyKeyboardMarkup:
    per_page = 5
    total_pages = max(1, (len(users) + per_page - 1) // per_page)
    curr_page = max(0, min(page, total_pages - 1))
    curr_users = users[curr_page * per_page : (curr_page + 1) * per_page]

    keyboard = []
    for u in curr_users:
        display_name = u.get('username') or u.get('first_name') or f"User_{u['user_id']}"
        keyboard.append([KeyboardButton(f"👤 {display_name} (UID: {u['user_id']})")])

    nav_row = []
    if curr_page > 0:
        nav_row.append(KeyboardButton("⬅️ Prev Users"))
    if curr_page < total_pages - 1:
        nav_row.append(KeyboardButton("Next Users ➡️"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([KeyboardButton("🔙 Back to Admin")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_user_detail_keyboard(target_uid: int, is_banned: bool) -> ReplyKeyboardMarkup:
    ban_label = "🔓 Unban User" if is_banned else "🚫 Ban User"
    keyboard = [
        [KeyboardButton(f"{ban_label} [UID: {target_uid}]"), KeyboardButton(f"➕ Add +2 Slots [UID: {target_uid}]")],
        [KeyboardButton("🔙 Back to Users"), KeyboardButton("🏠 Back to Admin")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_bots_reply_keyboard(bots: list, page: int = 0) -> ReplyKeyboardMarkup:
    per_page = 5
    total_pages = max(1, (len(bots) + per_page - 1) // per_page)
    curr_page = max(0, min(page, total_pages - 1))
    curr_bots = bots[curr_page * per_page : (curr_page + 1) * per_page]

    keyboard = []
    for b in curr_bots:
        status_emoji = "🟢" if b.get('status') == "RUNNING" else ("🔴" if b.get('status') in ["FAILED", "CRASHED"] else "⚪")
        keyboard.append([KeyboardButton(f"{status_emoji} {b.get('bot_name', 'Bot')} [#{b.get('bot_id', '')}]")])

    nav_row = []
    if curr_page > 0:
        nav_row.append(KeyboardButton("⬅️ Prev All Bots"))
    if curr_page < total_pages - 1:
        nav_row.append(KeyboardButton("Next All Bots ➡️"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([KeyboardButton("🔙 Back to Admin")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_bot_detail_keyboard(bot_id: str, status: str) -> ReplyKeyboardMarkup:
    state_label = "⏹️ Stop" if status == "RUNNING" else "▶️ Force Start"
    keyboard = [
        [KeyboardButton(f"{state_label} [#{bot_id}]"), KeyboardButton(f"🔄 Restart [#{bot_id}]")],
        [KeyboardButton(f"📜 View Logs [#{bot_id}]"), KeyboardButton(f"🗑️ Force Delete [#{bot_id}]")],
        [KeyboardButton("🔙 Back to All Bots"), KeyboardButton("🏠 Back to Admin")]
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
        keyboard.append([KeyboardButton(f"🗑️ Remove {title} [{cid}]")])

    nav_row = []
    if curr_page > 0:
        nav_row.append(KeyboardButton("⬅️ Prev FSub"))
    if curr_page < total_pages - 1:
        nav_row.append(KeyboardButton("Next FSub ➡️"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([KeyboardButton("➕ Add Force-Sub Channel")])
    keyboard.append([KeyboardButton("🔙 Back to Admin")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Text Command / Button Handlers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied:</b> You are not authorized to view the Admin Panel.")
        return

    maint = database.get_setting("maintenance_mode", "0") == "1"
    maint_status = "🔴 ON" if maint else "🟢 OFF"

    users = database.get_all_users()
    bots = database.get_all_hosted_bots()
    running_bots = sum(1 for b in bots if b.get('status') == 'RUNNING')

    text = (
        "<b>👑 GRAVIX-HOST CENTRAL ADMIN</b>\n"
        "<i>Platform Management & Telemetry</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        f"👑 <b>Master Admin ID:</b> <code>{user_id}</code>\n"
        f"⚙️ <b>Maintenance Mode:</b> <code>{maint_status}</code>\n"
        f"👥 <b>Registered Users:</b> <code>{len(users)}</code>\n"
        f"🤖 <b>Platform Bots:</b> <code>{running_bots} Active / {len(bots)} Total</code>"
        "</blockquote>\n\n"
        "⚡ <b>Control Panel Navigation</b>\n"
        "Select an administrative module from the keyboard menu below to inspect infrastructure, govern users, or manage child bot processes."
    )
    reply_markup = get_admin_reply_keyboard(maint_status)
    await _send_admin_msg(update, text, reply_markup=reply_markup)

async def admin_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>")
        return

    users = database.get_all_users()
    bots = database.get_all_hosted_bots()

    running_bots = sum(1 for b in bots if b.get('status') == 'RUNNING')
    stopped_bots = sum(1 for b in bots if b.get('status') == 'STOPPED')
    failed_bots = sum(1 for b in bots if b.get('status') in ['FAILED', 'CRASHED'])

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
        "<b>📊 SYSTEM TELEMETRY &amp; METRICS</b>\n"
        "<i>Real-time Platform Infrastructure Status</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        "📊 <b>Platform Overview</b>\n"
        f"👥 <b>Total Users:</b> <code>{len(users)}</code>\n"
        f"🤖 <b>Total Hosted Bots:</b> <code>{len(bots)}</code>\n"
        f"   ├ 🟢 Active: <code>{running_bots}</code>\n"
        f"   ├ ⚪ Stopped: <code>{stopped_bots}</code>\n"
        f"   └ 🔴 Failed/Crashed: <code>{failed_bots}</code>\n\n"
        "🖥️ <b>Host Server Resources</b>\n"
        f"⚡ <b>CPU Load:</b> <code>{cpu_bar} {cpu_percent}%</code>\n"
        f"💾 <b>RAM Usage:</b> <code>{ram_bar} {mem.percent}%</code>\n"
        f"   └ <code>{ram_used_mb} MB / {ram_total_mb} MB</code>\n"
        f"💽 <b>Disk Allocation:</b> <code>{disk_bar} {disk.percent}%</code>\n"
        f"   └ Free: <code>{disk_free_gb} GB</code> | Total: <code>{disk_total_gb} GB</code>"
        "</blockquote>\n\n"
        "💡 <i>Telemetry metrics sampled in real-time from the master container environment.</i>"
    )
    reply_markup = ReplyKeyboardMarkup([[KeyboardButton("🔙 Back to Admin")]], resize_keyboard=True)
    await _send_admin_msg(update, text, reply_markup=reply_markup)

async def admin_users_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>")
        return

    users = database.get_all_users()
    per_page = 5
    total_pages = max(1, (len(users) + per_page - 1) // per_page)
    curr_page = max(0, min(page, total_pages - 1))
    context.user_data['admin_users_page'] = curr_page
    curr_users = users[curr_page * per_page : (curr_page + 1) * per_page]

    text = (
        f"<b>👥 USER DIRECTORY</b> (Page {curr_page + 1}/{total_pages})\n"
        "<i>Platform User Database & Privilege Controls</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    if not users:
        text += "<blockquote><i>No registered users found in the database.</i></blockquote>\n"
    else:
        text += "<blockquote>"
        entries = []
        for idx, u in enumerate(curr_users, start=curr_page * per_page + 1):
            banned_badge = " <code>[BANNED]</code>" if u.get('is_banned') else ""
            raw_uname = u.get('username')
            if raw_uname:
                uname = f"@{html.escape(raw_uname)}"
            else:
                raw_fname = u.get('first_name') or f"User_{u['user_id']}"
                uname = html.escape(raw_fname)
            slots = u.get('max_slots', 3)
            joined = html.escape(str(u.get('joined_at', 'N/A'))[:10])
            entries.append(
                f"<b>{idx}. {uname}</b> (UID: <code>{u['user_id']}</code>){banned_badge}\n"
                f"   └ Slots: <code>{slots}</code> | Joined: <code>{joined}</code>"
            )
        text += "\n\n".join(entries) + "</blockquote>\n"

    text += "\n💡 <i>Select a user button from the keyboard below to inspect details and manage privileges:</i>"
    reply_markup = get_admin_users_reply_keyboard(users, curr_page)
    await _send_admin_msg(update, text, reply_markup=reply_markup)

async def admin_user_detail_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int = None):
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>")
        return

    if user_id is None and update.message and update.message.text:
        m = re.search(r"\(UID:\s*(\d+)\)", update.message.text)
        if m:
            user_id = int(m.group(1))

    if user_id is None:
        await admin_users_list_handler(update, context, 0)
        return

    target_user = database.get_or_create_user(user_id)
    user_bots = database.get_user_bots(user_id)
    running_count = sum(1 for b in user_bots if b.get('status') == 'RUNNING')

    is_banned = bool(target_user.get('is_banned'))
    banned_str = "🔴 <b>Banned (Suspended)</b>" if is_banned else "🟢 <b>Active (Authorized)</b>"

    display_name = target_user.get('first_name') or target_user.get('username') or f"User_{target_user['user_id']}"
    username_str = f"@{html.escape(target_user['username'])}" if target_user.get('username') else "<i>None</i>"

    text = (
        "<b>👤 USER PROFILE INSPECTOR</b>\n"
        f"<i>Account Details & Quota for UID {target_user['user_id']}</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        f"🆔 <b>User ID:</b> <code>{target_user['user_id']}</code>\n"
        f"👤 <b>Name:</b> <b>{html.escape(str(display_name))}</b>\n"
        f"🏷️ <b>Username:</b> {username_str}\n"
        f"🛡️ <b>Account Status:</b> {banned_str}\n"
        f"📦 <b>Slot Allocation:</b> <code>{target_user.get('max_slots', 3)}</code> bots\n"
        f"🤖 <b>Hosted Instances:</b> <code>{len(user_bots)}</code> (<code>{running_count}</code> Active)\n"
        f"📅 <b>Registration Date:</b> <code>{html.escape(str(target_user.get('joined_at', 'N/A')))}</code>"
        "</blockquote>\n\n"
        "⚡ <b>Account Actions</b>\n"
        "Use the keyboard options below to toggle account access or grant additional slot capacity."
    )
    reply_markup = get_admin_user_detail_keyboard(user_id, is_banned)
    await _send_admin_msg(update, text, reply_markup=reply_markup)

async def admin_user_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str = None, target_uid: int = None):
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>")
        return

    text_input = update.message.text if (update.message and update.message.text) else ""
    if target_uid is None:
        m = re.search(r"\[UID:\s*(\d+)\]", text_input)
        if m:
            target_uid = int(m.group(1))

    if target_uid is None:
        await admin_users_list_handler(update, context, 0)
        return

    if action is None:
        if "Ban User" in text_input or "Unban User" in text_input:
            action = "toggle_ban"
        elif "Add +2 Slots" in text_input:
            action = "inc_slots"

    target_user = database.get_or_create_user(target_uid)

    if action == "toggle_ban":
        new_ban = not target_user.get('is_banned')
        database.set_user_ban(target_uid, new_ban)
        if new_ban:
            for b in database.get_user_bots(target_uid):
                await bot_manager.stop_bot(b['bot_id'])
            await _send_admin_msg(
                update,
                f"🚫 <b>USER BANNED</b>\nUser <code>{target_uid}</code> has been banned. All active child subprocesses terminated."
            )
        else:
            await _send_admin_msg(
                update,
                f"🔓 <b>USER UNBANNED</b>\nUser <code>{target_uid}</code> has been restored to active status."
            )

    elif action == "inc_slots":
        new_slots = target_user.get('max_slots', 3) + 2
        database.set_user_slots(target_uid, new_slots)
        await _send_admin_msg(
            update,
            f"➕ <b>SLOTS UPGRADED</b>\nHosting capacity increased to <code>{new_slots}</code> bots for User <code>{target_uid}</code>."
        )

    await admin_user_detail_handler(update, context, target_uid)

async def admin_bots_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>")
        return

    all_bots = database.get_all_hosted_bots()
    per_page = 5
    total_pages = max(1, (len(all_bots) + per_page - 1) // per_page)
    curr_page = max(0, min(page, total_pages - 1))
    context.user_data['admin_bots_page'] = curr_page
    curr_bots = all_bots[curr_page * per_page : (curr_page + 1) * per_page]

    text = (
        f"<b>🤖 ALL PLATFORM BOTS</b> (Page {curr_page + 1}/{total_pages})\n"
        "<i>Active Subprocesses & Instance Registry</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    if not all_bots:
        text += "<blockquote><i>No hosted bot instances found on the platform.</i></blockquote>\n"
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
                f"   └ Owner: <code>{u_id}</code> | Status: <code>{st}</code>"
            )
        text += "\n\n".join(entries) + "</blockquote>\n"

    text += "\n💡 <i>Select a bot button below to inspect configuration, read execution logs, or manage lifecycle states:</i>"
    reply_markup = get_admin_bots_reply_keyboard(all_bots, curr_page)
    await _send_admin_msg(update, text, reply_markup=reply_markup)

async def admin_bot_detail_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id: str = None):
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>")
        return

    if bot_id is None and update.message and update.message.text:
        m = re.search(r"\[#([a-zA-Z0-9_-]+)\]", update.message.text)
        if m:
            bot_id = m.group(1)

    if not bot_id:
        await admin_bots_list_handler(update, context, 0)
        return

    bot_data = database.get_bot(bot_id)
    if not bot_data:
        await _send_admin_msg(update, f"⚠️ <b>Bot <code>#{html.escape(bot_id)}</code> not found in database.</b>")
        await admin_bots_list_handler(update, context, 0)
        return

    status = bot_data.get('status', 'STOPPED')
    status_emoji = "🟢" if status == "RUNNING" else ("🔴" if status in ["FAILED", "CRASHED"] else "⚪")
    token = bot_data.get('bot_token', '')
    masked_token = f"{token[:10]}...{token[-5:]}" if len(token) > 15 else "******"
    script_path = bot_data.get('script_path') or f"{DATA_DIR}/bots/{bot_data['user_id']}_{bot_id}/main.py"
    created_at = bot_data.get('created_at', 'N/A')

    text = (
        "<b>⚙️ PLATFORM BOT INSPECTOR</b>\n"
        "<i>Instance Diagnostics & Process Control</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        f"🤖 <b>Bot Name:</b> <b>{html.escape(bot_data.get('bot_name', 'Unnamed Bot'))}</b>\n"
        f"🆔 <b>Bot ID:</b> <code>#{html.escape(bot_id)}</code>\n"
        f"👤 <b>Owner UID:</b> <code>{bot_data['user_id']}</code>\n"
        f"📊 <b>Status:</b> {status_emoji} <code>{status}</code>\n"
        f"🔑 <b>Token (Masked):</b> <code>{html.escape(masked_token)}</code>\n"
        f"📁 <b>Script Path:</b> <code>{html.escape(script_path)}</code>\n"
        f"🕒 <b>Provisioned:</b> <code>{html.escape(str(created_at))}</code>"
        "</blockquote>\n\n"
        "⚡ <b>Process Control</b>\n"
        "Select a command below to start, stop, restart, stream execution logs, or force delete."
    )
    reply_markup = get_admin_bot_detail_keyboard(bot_id, status)
    await _send_admin_msg(update, text, reply_markup=reply_markup)

async def admin_bot_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str = None, bot_id: str = None):
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>")
        return

    text_input = update.message.text if (update.message and update.message.text) else ""
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
        elif "Force Delete" in text_input or "🗑️" in text_input:
            action = "del"

    if action == "start":
        success, msg = await bot_manager.start_bot(bot_id)
        if success:
            await _send_admin_msg(update, f"✅ <b>PROCESS STARTED</b>\n<code>{html.escape(msg)}</code>")
        else:
            await _send_admin_msg(update, f"❌ <b>START FAILED</b>\n<code>{html.escape(msg)}</code>")
        await admin_bot_detail_handler(update, context, bot_id)

    elif action == "stop":
        success, msg = await bot_manager.stop_bot(bot_id)
        if success:
            await _send_admin_msg(update, f"⏹️ <b>PROCESS STOPPED</b>\n<code>{html.escape(msg)}</code>")
        else:
            await _send_admin_msg(update, f"❌ <b>STOP FAILED</b>\n<code>{html.escape(msg)}</code>")
        await admin_bot_detail_handler(update, context, bot_id)

    elif action == "restart":
        success, msg = await bot_manager.restart_bot(bot_id)
        if success:
            await _send_admin_msg(update, f"🔄 <b>PROCESS RESTARTED</b>\n<code>{html.escape(msg)}</code>")
        else:
            await _send_admin_msg(update, f"❌ <b>RESTART FAILED</b>\n<code>{html.escape(msg)}</code>")
        await admin_bot_detail_handler(update, context, bot_id)

    elif action == "logs":
        logs = bot_manager.get_logs(bot_id, lines=30)
        log_snippet = logs[-3500:] if logs else "No execution logs recorded yet."
        text = (
            "<b>📜 BOT EXECUTION LOGS</b>\n"
            f"<i>Live Subprocess Output for #{html.escape(bot_id)}</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🤖 <b>Target Bot:</b> <code>#{html.escape(bot_id)}</code>\n\n"
            f"<pre><code>{html.escape(log_snippet)}</code></pre>"
        )
        reply_markup = ReplyKeyboardMarkup([
            [KeyboardButton(f"📜 View Logs [#{bot_id}]"), KeyboardButton(f"🔄 Restart [#{bot_id}]")],
            [KeyboardButton("🔙 Back to All Bots"), KeyboardButton("🏠 Back to Admin")]
        ], resize_keyboard=True)
        await _send_admin_msg(update, text, reply_markup=reply_markup)

    elif action == "del":
        await bot_manager.stop_bot(bot_id)
        bot_data = database.get_bot(bot_id)
        if bot_data and bot_data.get('script_path'):
            script_dir = os.path.dirname(bot_data['script_path'])
            if os.path.exists(script_dir):
                shutil.rmtree(script_dir, ignore_errors=True)
        database.delete_bot_record(bot_id)
        await _send_admin_msg(
            update,
            f"🗑️ <b>BOT PERMANENTLY DELETED</b>\nBot instance <code>#{html.escape(bot_id)}</code> and disk assets have been purged."
        )
        await admin_bots_list_handler(update, context, 0)

async def admin_fsub_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>")
        return

    channels = database.get_required_channels()
    per_page = 5
    total_pages = max(1, (len(channels) + per_page - 1) // per_page)
    curr_page = max(0, min(page, total_pages - 1))
    context.user_data['admin_fsub_page'] = curr_page
    curr_channels = channels[curr_page * per_page : (curr_page + 1) * per_page]

    text = (
        f"<b>📢 FORCE-SUB CHANNELS</b> (Page {curr_page + 1}/{total_pages})\n"
        "<i>Mandatory Subscription Membership Gateways</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    if not channels:
        text += "<blockquote><i>No mandatory force-sub channels configured yet.</i></blockquote>\n"
    else:
        text += "<blockquote>"
        entries = []
        for idx, ch in enumerate(curr_channels, start=curr_page * per_page + 1):
            ch_title = html.escape(ch.get('title', 'Channel'))
            ch_id = html.escape(str(ch.get('channel_id', '')))
            ch_link = html.escape(ch.get('invite_link', ''))
            entries.append(
                f"{idx}. <b>{ch_title}</b>\n"
                f"   ├ 🆔 ID: <code>{ch_id}</code>\n"
                f"   └ 🔗 Link: <a href=\"{ch_link}\">{ch_link}</a>"
            )
        text += "\n\n".join(entries) + "</blockquote>\n"

    text += "\n💡 <i>Users must join all listed channels before accessing platform features. Tap a channel button below to remove it or add a new channel:</i>"
    reply_markup = get_admin_fsub_reply_keyboard(channels, curr_page)
    await _send_admin_msg(update, text, reply_markup=reply_markup)

async def admin_fsub_del_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: str = None):
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>")
        return

    if channel_id is None and update.message and update.message.text:
        m = re.search(r"\[(.+)\]", update.message.text)
        if m:
            channel_id = m.group(1).strip()

    if channel_id:
        database.delete_required_channel(channel_id)
        await _send_admin_msg(
            update,
            f"✅ <b>CHANNEL REMOVED</b>\nForce-Sub Channel <code>{html.escape(channel_id)}</code> has been deleted successfully."
        )

    await admin_fsub_list_handler(update, context, 0)

async def admin_toggle_maint_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>")
        return

    current = database.get_setting("maintenance_mode", "0") == "1"
    new_val = "0" if current else "1"
    database.set_setting("maintenance_mode", new_val)

    status_str = "ENABLED (🔴 ON)" if new_val == "1" else "DISABLED (🟢 OFF)"
    await _send_admin_msg(
        update,
        f"⚙️ <b>MAINTENANCE MODE UPDATED</b>\nPlatform maintenance status is now <code>{status_str}</code>."
    )
    await admin_panel(update, context)

async def admin_broadcast_prompt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied.</b>")
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
    reply_markup = ReplyKeyboardMarkup([[KeyboardButton("🔙 Back to Admin")]], resize_keyboard=True)
    await _send_admin_msg(update, text, reply_markup=reply_markup)

async def admin_exit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        from user_handlers import get_main_reply_keyboard
        reply_kb = get_main_reply_keyboard(user_id)
    except Exception:
        reply_kb = ReplyKeyboardMarkup([[KeyboardButton("🤖 My Hosted Bots"), KeyboardButton("➕ Host New Bot")]], resize_keyboard=True)

    text = (
        "<b>🏠 EXITED ADMIN CONSOLE</b>\n"
        "<i>Returned to User Dashboard</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Returned to user dashboard."
    )
    await _send_admin_msg(update, text, reply_markup=reply_kb)

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ <b>Access Denied.</b>", parse_mode="HTML")
        return

    if not context.args:
        await update.message.reply_text("⚠️ <b>Usage:</b> <code>/broadcast &lt;Your message&gt;</code>", parse_mode="HTML")
        return

    broadcast_text = " ".join(context.args)
    users = database.get_all_users()
    total = len(users)
    success = 0
    failed = 0

    progress_msg = await update.message.reply_text(f"⏳ <b>Broadcasting to <code>{total}</code> users...</b>", parse_mode="HTML")

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
            success += 1
        except Exception:
            failed += 1

    await progress_msg.edit_text(
        "<b>✅ BROADCAST COMPLETION REPORT</b>\n"
        "<i>Global Announcement Delivery Telemetry</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>"
        f"👥 <b>Target Users:</b> <code>{total}</code>\n"
        f"✔️ <b>Successfully Delivered:</b> <code>{success}</code>\n"
        f"❌ <b>Delivery Failures:</b> <code>{failed}</code> (Blocked/Deleted)"
        "</blockquote>",
        parse_mode="HTML"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. Force-Sub Add Channel Conversation Flow
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FSUB_CANCEL_KEYBOARD = ReplyKeyboardMarkup([[KeyboardButton("❌ Cancel")]], resize_keyboard=True)

async def admin_fsub_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ <b>Access Denied:</b> You are not authorized.")
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
        "<i>(Send Channel ID or tap ❌ Cancel below to abort)</i>"
    )
    await _send_admin_msg(update, text, reply_markup=FSUB_CANCEL_KEYBOARD)
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
        await update.message.reply_text("⚠️ <i>This session expired. Please use /admin to start again.</i>", parse_mode="HTML")
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
            "<i>(Send Channel ID or tap ❌ Cancel to abort)</i>"
        )
        await update.message.reply_text(text_resp, reply_markup=FSUB_CANCEL_KEYBOARD, parse_mode="HTML")
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
        "<i>(Send Title or tap ❌ Cancel to abort)</i>"
    )
    await update.message.reply_text(text_resp, reply_markup=FSUB_CANCEL_KEYBOARD, parse_mode="HTML")
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
        await update.message.reply_text("⚠️ <i>This session expired. Please use /admin to start again.</i>", parse_mode="HTML")
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
            "<i>(Send Title or tap ❌ Cancel to abort)</i>"
        )
        await update.message.reply_text(text_resp, reply_markup=FSUB_CANCEL_KEYBOARD, parse_mode="HTML")
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
        "<i>(Send Link or tap ❌ Cancel to abort)</i>"
    )
    await update.message.reply_text(text_resp, reply_markup=FSUB_CANCEL_KEYBOARD, parse_mode="HTML")
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
        await update.message.reply_text("⚠️ <i>This session expired. Please use /admin to start again.</i>", parse_mode="HTML")
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
            "<i>(Send Link or tap ❌ Cancel to abort)</i>"
        )
        await update.message.reply_text(text_resp, reply_markup=FSUB_CANCEL_KEYBOARD, parse_mode="HTML")
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
    await update.message.reply_text(text_resp, reply_markup=reply_markup, parse_mode="HTML")
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
        "The channel addition wizard was aborted."
    )
    await admin_fsub_list_handler(update, context, 0)
    return ConversationHandler.END

admin_cancel_filter = filters.Regex(r"(?i)^(❌\s*Cancel|/cancel|cancel|🔙\s*Back to Admin|🏠\s*Back to Admin|🏠\s*Exit Admin)$")

admin_fsub_conv = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("^➕ Add Force-Sub Channel$"), admin_fsub_add_start),
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
        MessageHandler(filters.Regex(r"(?i)^(❌\s*Cancel|/cancel|cancel|🔙\s*Back to Admin|🏠\s*Back to Admin|🏠\s*Exit Admin)$"), admin_fsub_cancel),
        CallbackQueryHandler(admin_fsub_cancel, pattern="^(admin_fsub_cancel|admin_panel)$")
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

    text = update.message.text.strip() if (update.message and update.message.text) else ""
    if not text:
        return False

    # Main / Navigation
    if text in ["👑 Open Admin Panel", "🔄 Refresh Admin", "🔙 Back to Admin", "🏠 Back to Admin"]:
        await admin_panel(update, context)
        return True
    elif text == "🏠 Exit Admin":
        await admin_exit_handler(update, context)
        return True
    elif text == "📊 System Stats":
        await admin_stats_handler(update, context)
        return True
    elif text.startswith("⚙️ Toggle Maintenance"):
        await admin_toggle_maint_handler(update, context)
        return True
    elif text in ["📢 Broadcast Announcement", "📢 Broadcast Message"]:
        await admin_broadcast_prompt_handler(update, context)
        return True

    # User Management
    elif text in ["👥 User Manager", "🔙 Back to Users"]:
        page = context.user_data.get('admin_users_page', 0) if text == "🔙 Back to Users" else 0
        await admin_users_list_handler(update, context, page)
        return True
    elif text == "⬅️ Prev Users":
        curr_page = max(0, context.user_data.get('admin_users_page', 0) - 1)
        await admin_users_list_handler(update, context, curr_page)
        return True
    elif text == "Next Users ➡️":
        curr_page = context.user_data.get('admin_users_page', 0) + 1
        await admin_users_list_handler(update, context, curr_page)
        return True
    elif re.match(r"^👤\s+.+\s+\(UID:\s*(\d+)\)$", text):
        m = re.match(r"^👤\s+.+\s+\(UID:\s*(\d+)\)$", text)
        await admin_user_detail_handler(update, context, int(m.group(1)))
        return True
    elif re.match(r"^(?:🔓 Unban User|🚫 Ban User)\s+\[UID:\s*(\d+)\]$", text):
        m = re.match(r"^(?:🔓 Unban User|🚫 Ban User)\s+\[UID:\s*(\d+)\]$", text)
        await admin_user_action_handler(update, context, action="toggle_ban", target_uid=int(m.group(1)))
        return True
    elif re.match(r"^➕ Add \+2 Slots\s+\[UID:\s*(\d+)\]$", text):
        m = re.match(r"^➕ Add \+2 Slots\s+\[UID:\s*(\d+)\]$", text)
        await admin_user_action_handler(update, context, action="inc_slots", target_uid=int(m.group(1)))
        return True

    # Bot Management
    elif text in ["🤖 All Hosted Bots", "🔙 Back to All Bots"]:
        page = context.user_data.get('admin_bots_page', 0) if text == "🔙 Back to All Bots" else 0
        await admin_bots_list_handler(update, context, page)
        return True
    elif text == "⬅️ Prev All Bots":
        curr_page = max(0, context.user_data.get('admin_bots_page', 0) - 1)
        await admin_bots_list_handler(update, context, curr_page)
        return True
    elif text == "Next All Bots ➡️":
        curr_page = context.user_data.get('admin_bots_page', 0) + 1
        await admin_bots_list_handler(update, context, curr_page)
        return True
    elif re.match(r"^[🟢🔴⚪]\s+.+\s+\[#([a-zA-Z0-9_-]+)\]$", text):
        m = re.match(r"^[🟢🔴⚪]\s+.+\s+\[#([a-zA-Z0-9_-]+)\]$", text)
        await admin_bot_detail_handler(update, context, bot_id=m.group(1))
        return True
    elif re.match(r"^▶️ Force Start\s+\[#([a-zA-Z0-9_-]+)\]$", text):
        m = re.match(r"^▶️ Force Start\s+\[#([a-zA-Z0-9_-]+)\]$", text)
        await admin_bot_action_handler(update, context, action="start", bot_id=m.group(1))
        return True
    elif re.match(r"^⏹️ Stop\s+\[#([a-zA-Z0-9_-]+)\]$", text):
        m = re.match(r"^⏹️ Stop\s+\[#([a-zA-Z0-9_-]+)\]$", text)
        await admin_bot_action_handler(update, context, action="stop", bot_id=m.group(1))
        return True
    elif re.match(r"^🔄 Restart\s+\[#([a-zA-Z0-9_-]+)\]$", text):
        m = re.match(r"^🔄 Restart\s+\[#([a-zA-Z0-9_-]+)\]$", text)
        await admin_bot_action_handler(update, context, action="restart", bot_id=m.group(1))
        return True
    elif re.match(r"^📜 View Logs\s+\[#([a-zA-Z0-9_-]+)\]$", text):
        m = re.match(r"^📜 View Logs\s+\[#([a-zA-Z0-9_-]+)\]$", text)
        await admin_bot_action_handler(update, context, action="logs", bot_id=m.group(1))
        return True
    elif re.match(r"^🗑️ Force Delete\s+\[#([a-zA-Z0-9_-]+)\]$", text):
        m = re.match(r"^🗑️ Force Delete\s+\[#([a-zA-Z0-9_-]+)\]$", text)
        await admin_bot_action_handler(update, context, action="del", bot_id=m.group(1))
        return True

    # Force-Sub Management
    elif text in ["📢 Force-Sub Channels", "🔙 Back to Force-Sub"]:
        page = context.user_data.get('admin_fsub_page', 0) if text == "🔙 Back to Force-Sub" else 0
        await admin_fsub_list_handler(update, context, page)
        return True
    elif text == "⬅️ Prev FSub":
        curr_page = max(0, context.user_data.get('admin_fsub_page', 0) - 1)
        await admin_fsub_list_handler(update, context, curr_page)
        return True
    elif text == "Next FSub ➡️":
        curr_page = context.user_data.get('admin_fsub_page', 0) + 1
        await admin_fsub_list_handler(update, context, curr_page)
        return True
    elif re.match(r"^🗑️ Remove\s+.+\s+\[(.+)\]$", text):
        m = re.match(r"^🗑️ Remove\s+.+\s+\[(.+)\]$", text)
        await admin_fsub_del_handler(update, context, channel_id=m.group(1).strip())
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


