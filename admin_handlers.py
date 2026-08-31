import os
import re
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

logger = logging.getLogger("GravixHost.Admin")

# States for admin conversation handlers
A_WAIT_BROADCAST, A_WAIT_SLOTS_UID, A_WAIT_SLOTS_NUM = range(10, 13)
A_FSUB_ID, A_FSUB_TITLE, A_FSUB_LINK = range(20, 23)

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

async def _send_admin_msg(update: Update, text: str, reply_markup=None):
    """Helper to send reply keyboard response cleanly."""
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass
        if update.callback_query.message:
            await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

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
        await _send_admin_msg(update, "⛔ Access Denied: You are not authorized to view the Admin Panel.")
        return

    maint = database.get_setting("maintenance_mode", "0") == "1"
    maint_status = "🔴 ON" if maint else "🟢 OFF"

    text = (
        "👑 **Gravix-Host — Central Admin Panel**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Admin ID:** `{user_id}`\n"
        f"⚙️ **Maintenance Mode:** {maint_status}\n\n"
        "Select an option below to manage the platform:"
    )
    reply_markup = get_admin_reply_keyboard(maint_status)
    await _send_admin_msg(update, text, reply_markup=reply_markup)

async def admin_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ Access Denied.")
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

    text = (
        "📊 **Gravix-Host Real-Time System Metrics**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 **Total Registered Users:** `{len(users)}`\n"
        f"🤖 **Total Hosted Bots:** `{len(bots)}`\n"
        f"   ├ 🟢 Running: `{running_bots}`\n"
        f"   ├ ⚪ Stopped: `{stopped_bots}`\n"
        f"   └ 🔴 Failed/Crashed: `{failed_bots}`\n\n"
        "🖥️ **Host Server Resources:**\n"
        f"   ├ ⚡ CPU Usage: `{cpu_percent}%`\n"
        f"   ├ 💾 RAM Usage: `{mem.percent}%` ({mem.used // (1024*1024)}MB / {mem.total // (1024*1024)}MB)\n"
        f"   └ 💽 Disk Space: `{disk.percent}%` ({disk.free // (1024*1024*1024)}GB Free)\n"
    )
    reply_markup = ReplyKeyboardMarkup([[KeyboardButton("🔙 Back to Admin")]], resize_keyboard=True)
    await _send_admin_msg(update, text, reply_markup=reply_markup)

async def admin_users_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ Access Denied.")
        return

    users = database.get_all_users()
    per_page = 5
    total_pages = max(1, (len(users) + per_page - 1) // per_page)
    curr_page = max(0, min(page, total_pages - 1))
    context.user_data['admin_users_page'] = curr_page
    curr_users = users[curr_page * per_page : (curr_page + 1) * per_page]

    text = f"👥 **User Directory** (Page {curr_page + 1}/{total_pages})\n━━━━━━━━━━━━━━━━━━━━━━\n"
    if not users:
        text += "ℹ️ *No users registered yet.*\n"
    else:
        for idx, u in enumerate(curr_users, start=curr_page * per_page + 1):
            banned_tag = " `[BANNED]`" if u.get('is_banned') else ""
            uname = f"@{u['username']}" if u.get('username') else (u.get('first_name') or "No-Name")
            slots = u.get('max_slots', 3)
            text += f"{idx}. **{uname}** (UID: `{u['user_id']}`){banned_tag}\n   └ Slots: `{slots}` | Joined: `{u.get('joined_at', 'N/A')[:10]}`\n"

    text += "\n💡 Tap a user button below to view details and manage permissions:"
    reply_markup = get_admin_users_reply_keyboard(users, curr_page)
    await _send_admin_msg(update, text, reply_markup=reply_markup)

async def admin_user_detail_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int = None):
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await _send_admin_msg(update, "⛔ Access Denied.")
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

    banned_str = "🔴 Yes (Banned)" if target_user.get('is_banned') else "🟢 No (Active)"
    text = (
        f"👤 **User Detail: {target_user.get('first_name') or target_user.get('username') or target_user['user_id']}**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **User ID:** `{target_user['user_id']}`\n"
        f"🏷️ **Username:** @{target_user.get('username') or 'N/A'}\n"
        f"🚫 **Banned:** {banned_str}\n"
        f"📦 **Slot Limit:** `{target_user.get('max_slots', 3)}` bots\n"
        f"🤖 **Hosted Bots:** `{len(user_bots)}`\n"
        f"📅 **Joined At:** `{target_user.get('joined_at', 'N/A')}`\n"
    )
    reply_markup = get_admin_user_detail_keyboard(user_id, bool(target_user.get('is_banned')))
    await _send_admin_msg(update, text, reply_markup=reply_markup)

async def admin_user_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str = None, target_uid: int = None):
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await _send_admin_msg(update, "⛔ Access Denied.")
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
            await _send_admin_msg(update, f"🚫 **User `{target_uid}` has been BANNED.** All active bots stopped.")
        else:
            await _send_admin_msg(update, f"🔓 **User `{target_uid}` has been UNBANNED.**")

    elif action == "inc_slots":
        new_slots = target_user.get('max_slots', 3) + 2
        database.set_user_slots(target_uid, new_slots)
        await _send_admin_msg(update, f"➕ **Slot Limit increased to `{new_slots}` bots** for User `{target_uid}`.")

    await admin_user_detail_handler(update, context, target_uid)

async def admin_bots_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ Access Denied.")
        return

    all_bots = database.get_all_hosted_bots()
    per_page = 5
    total_pages = max(1, (len(all_bots) + per_page - 1) // per_page)
    curr_page = max(0, min(page, total_pages - 1))
    context.user_data['admin_bots_page'] = curr_page
    curr_bots = all_bots[curr_page * per_page : (curr_page + 1) * per_page]

    text = f"🤖 **All Platform Bots** (Page {curr_page + 1}/{total_pages})\n━━━━━━━━━━━━━━━━━━━━━━\n"
    if not all_bots:
        text += "ℹ️ *No bots hosted on the platform yet.*\n"
    else:
        for idx, b in enumerate(curr_bots, start=curr_page * per_page + 1):
            status_emoji = "🟢" if b.get('status') == "RUNNING" else ("🔴" if b.get('status') in ["FAILED", "CRASHED"] else "⚪")
            text += f"{idx}. {status_emoji} **{b.get('bot_name', 'Bot')}** `[#{b.get('bot_id')}]`\n   └ Owner: `{b.get('user_id')}` | Status: `{b.get('status')}`\n"

    text += "\n💡 Tap a bot button below to manage operations (start, stop, logs, delete):"
    reply_markup = get_admin_bots_reply_keyboard(all_bots, curr_page)
    await _send_admin_msg(update, text, reply_markup=reply_markup)

async def admin_bot_detail_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id: str = None):
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await _send_admin_msg(update, "⛔ Access Denied.")
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
        await _send_admin_msg(update, f"⚠️ Bot `#{bot_id}` not found in database.")
        await admin_bots_list_handler(update, context, 0)
        return

    status = bot_data.get('status', 'STOPPED')
    status_emoji = "🟢" if status == "RUNNING" else ("🔴" if status in ["FAILED", "CRASHED"] else "⚪")
    token = bot_data.get('bot_token', '')
    masked_token = f"{token[:10]}...{token[-5:]}" if len(token) > 15 else "******"

    text = (
        f"🤖 **Bot Manager: {bot_data.get('bot_name')}**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **Bot ID:** `{bot_data['bot_id']}`\n"
        f"👤 **Owner ID:** `{bot_data['user_id']}`\n"
        f"📊 **Status:** {status_emoji} `{status}`\n"
        f"🔑 **Token (masked):** `{masked_token}`\n"
        f"🕒 **Created:** `{bot_data.get('created_at', 'N/A')}`\n"
    )
    reply_markup = get_admin_bot_detail_keyboard(bot_id, status)
    await _send_admin_msg(update, text, reply_markup=reply_markup)

async def admin_bot_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str = None, bot_id: str = None):
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await _send_admin_msg(update, "⛔ Access Denied.")
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
        icon = "✅" if success else "❌"
        await _send_admin_msg(update, f"{icon} **Start Result:** {msg}")
        await admin_bot_detail_handler(update, context, bot_id)

    elif action == "stop":
        success, msg = await bot_manager.stop_bot(bot_id)
        icon = "✅" if success else "❌"
        await _send_admin_msg(update, f"{icon} **Stop Result:** {msg}")
        await admin_bot_detail_handler(update, context, bot_id)

    elif action == "restart":
        success, msg = await bot_manager.restart_bot(bot_id)
        icon = "✅" if success else "❌"
        await _send_admin_msg(update, f"{icon} **Restart Result:** {msg}")
        await admin_bot_detail_handler(update, context, bot_id)

    elif action == "logs":
        logs = bot_manager.get_logs(bot_id, lines=30)
        log_snippet = logs[-3500:] if logs else "No logs recorded yet."
        text = f"📜 **Logs for Bot `{bot_id}`:**\n\n```\n{log_snippet}\n```"
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
        await _send_admin_msg(update, f"🗑️ **Bot `#{bot_id}` has been permanently deleted.**")
        await admin_bots_list_handler(update, context, 0)

async def admin_fsub_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ Access Denied.")
        return

    channels = database.get_required_channels()
    per_page = 5
    total_pages = max(1, (len(channels) + per_page - 1) // per_page)
    curr_page = max(0, min(page, total_pages - 1))
    context.user_data['admin_fsub_page'] = curr_page
    curr_channels = channels[curr_page * per_page : (curr_page + 1) * per_page]

    text = (
        f"📢 **Force-Sub Required Channels** (Page {curr_page + 1}/{total_pages})\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Users must join all configured channels before using the bot.\n\n"
    )
    if not channels:
        text += "ℹ️ *No required channels configured yet.*\n"
    else:
        for idx, ch in enumerate(curr_channels, start=curr_page * per_page + 1):
            text += (
                f"{idx}. **{ch['title']}**\n"
                f"   ├ 🆔 ID: `{ch['channel_id']}`\n"
                f"   └ 🔗 Link: {ch['invite_link']}\n\n"
            )

    reply_markup = get_admin_fsub_reply_keyboard(channels, curr_page)
    await _send_admin_msg(update, text, reply_markup=reply_markup)

async def admin_fsub_del_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: str = None):
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await _send_admin_msg(update, "⛔ Access Denied.")
        return

    if channel_id is None and update.message and update.message.text:
        m = re.search(r"\[(.+)\]", update.message.text)
        if m:
            channel_id = m.group(1).strip()

    if channel_id:
        database.delete_required_channel(channel_id)
        await _send_admin_msg(update, f"✅ **Force-Sub Channel `{channel_id}` removed successfully!**")

    await admin_fsub_list_handler(update, context, 0)

async def admin_toggle_maint_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ Access Denied.")
        return

    current = database.get_setting("maintenance_mode", "0") == "1"
    new_val = "0" if current else "1"
    database.set_setting("maintenance_mode", new_val)

    status_str = "ENABLED (🔴 ON)" if new_val == "1" else "DISABLED (🟢 OFF)"
    await _send_admin_msg(update, f"⚙️ **Maintenance mode is now {status_str}.**")
    await admin_panel(update, context)

async def admin_broadcast_prompt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ Access Denied.")
        return

    text = (
        "📢 **Send Global Broadcast Announcement**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "To send a broadcast to all registered users, use the command:\n\n"
        "`/broadcast Your announcement message here...`\n\n"
        "Markdown formatting is supported."
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

    text = "🏠 **Exited Admin Panel.**\n\nReturned to user menu."
    await _send_admin_msg(update, text, reply_markup=reply_kb)

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Access Denied.")
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/broadcast <Your message>`", parse_mode="Markdown")
        return

    broadcast_text = " ".join(context.args)
    users = database.get_all_users()
    total = len(users)
    success = 0
    failed = 0

    progress_msg = await update.message.reply_text(f"⏳ Broadcasting to {total} users...")

    for u in users:
        try:
            await context.bot.send_message(
                chat_id=u['user_id'],
                text=f"📢 **Global Announcement from Gravix-Host**\n━━━━━━━━━━━━━━━━━━━━━━\n\n{broadcast_text}",
                parse_mode="Markdown"
            )
            success += 1
        except Exception:
            failed += 1

    await progress_msg.edit_text(
        f"✅ **Broadcast Completed!**\n\n"
        f"👥 Total Target Users: `{total}`\n"
        f"✔️ Successfully Sent: `{success}`\n"
        f"❌ Failed (Blocked/Deleted): `{failed}`",
        parse_mode="Markdown"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. Force-Sub Add Channel Conversation Flow
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FSUB_CANCEL_KEYBOARD = ReplyKeyboardMarkup([[KeyboardButton("❌ Cancel")]], resize_keyboard=True)

async def admin_fsub_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await _send_admin_msg(update, "⛔ Access Denied: You are not authorized.")
        return ConversationHandler.END

    context.user_data['active_flow'] = 'fsub_add'
    text = (
        "➕ **Add Required Channel (Step 1/3)**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Please enter the **Telegram Channel ID / Username**:\n\n"
        "• Public Channel: `@ChannelUsername`\n"
        "• Private Channel: `-1001234567890`\n\n"
        "⚠️ *Make sure the bot is added as an Administrator in this channel.*\n\n"
        "*(Send Channel ID or tap Cancel below to abort)*"
    )
    await _send_admin_msg(update, text, reply_markup=FSUB_CANCEL_KEYBOARD)
    return A_FSUB_ID

async def admin_fsub_get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('active_flow') != 'fsub_add':
        await update.message.reply_text("⚠️ This session expired. Please use /admin to start again.")
        return ConversationHandler.END

    raw_id = update.message.text.strip()
    is_valid = False
    if raw_id.startswith("@") and len(raw_id) >= 4 and re.match(r"^@[a-zA-Z0-9_]+$", raw_id):
        is_valid = True
    elif re.match(r"^-100\d+$", raw_id):
        is_valid = True

    if not is_valid:
        text = (
            "⚠️ **Invalid Channel ID format.**\n\n"
            "Please provide a valid public handle (e.g. `@GravixRDP`) or private channel ID (e.g. `-1001234567890`):\n\n"
            "*(Send Channel ID or tap Cancel to abort)*"
        )
        await update.message.reply_text(text, reply_markup=FSUB_CANCEL_KEYBOARD, parse_mode="Markdown")
        return A_FSUB_ID

    context.user_data['fsub_channel_id'] = raw_id
    text = (
        "➕ **Add Required Channel (Step 2/3)**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Channel ID: `{raw_id}`\n\n"
        "Please enter a display **Title** for this channel:\n"
        "*(Example: `Gravix Official Channel`)*\n\n"
        "*(Send Title or tap Cancel to abort)*"
    )
    await update.message.reply_text(text, reply_markup=FSUB_CANCEL_KEYBOARD, parse_mode="Markdown")
    return A_FSUB_TITLE

async def admin_fsub_get_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('active_flow') != 'fsub_add':
        await update.message.reply_text("⚠️ This session expired. Please use /admin to start again.")
        return ConversationHandler.END

    title = update.message.text.strip()
    if not title or len(title) < 2 or len(title) > 64:
        text = (
            "⚠️ **Invalid Title length.**\n\n"
            "Please enter a title between 2 and 64 characters:\n\n"
            "*(Send Title or tap Cancel to abort)*"
        )
        await update.message.reply_text(text, reply_markup=FSUB_CANCEL_KEYBOARD, parse_mode="Markdown")
        return A_FSUB_TITLE

    context.user_data['fsub_title'] = title
    cid = context.user_data.get('fsub_channel_id', '')
    text = (
        "➕ **Add Required Channel (Step 3/3)**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Channel ID: `{cid}`\n"
        f"Title: **{title}**\n\n"
        "Please enter the **Invite Link** for this channel:\n"
        "*(Example: `https://t.me/GravixRDP` or `https://t.me/+joinhash`)*\n\n"
        "*(Send Link or tap Cancel to abort)*"
    )
    await update.message.reply_text(text, reply_markup=FSUB_CANCEL_KEYBOARD, parse_mode="Markdown")
    return A_FSUB_LINK

async def admin_fsub_get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('active_flow') != 'fsub_add':
        await update.message.reply_text("⚠️ This session expired. Please use /admin to start again.")
        return ConversationHandler.END

    link = update.message.text.strip()
    if not re.match(r"^https?://(t\.me|telegram\.me)/.+$", link):
        text = (
            "⚠️ **Invalid Invite Link format.**\n\n"
            "The link must start with `https://t.me/...`\n\n"
            "*(Send Link or tap Cancel to abort)*"
        )
        await update.message.reply_text(text, reply_markup=FSUB_CANCEL_KEYBOARD, parse_mode="Markdown")
        return A_FSUB_LINK

    cid = context.user_data.get('fsub_channel_id', '')
    title = context.user_data.get('fsub_title', '')

    database.add_required_channel(cid, title, link)
    context.user_data.pop('fsub_channel_id', None)
    context.user_data.pop('fsub_title', None)
    context.user_data.pop('active_flow', None)

    text = (
        "✅ **Force-Sub Channel Added Successfully!**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 **Title:** {title}\n"
        f"🆔 **Channel ID:** `{cid}`\n"
        f"🔗 **Invite Link:** {link}\n\n"
        "Users are now required to join this channel."
    )
    channels = database.get_required_channels()
    reply_markup = get_admin_fsub_reply_keyboard(channels, 0)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return ConversationHandler.END

async def admin_fsub_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop('fsub_channel_id', None)
    context.user_data.pop('fsub_title', None)
    context.user_data.pop('active_flow', None)

    await _send_admin_msg(update, "❌ **Add channel process cancelled.**")
    await admin_fsub_list_handler(update, context, 0)
    return ConversationHandler.END

admin_fsub_conv = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("^➕ Add Force-Sub Channel$"), admin_fsub_add_start),
        CallbackQueryHandler(admin_fsub_add_start, pattern="^admin_fsub_add_start$"),
        CommandHandler("addchannel", admin_fsub_add_start)
    ],
    states={
        A_FSUB_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_fsub_get_id)],
        A_FSUB_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_fsub_get_title)],
        A_FSUB_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_fsub_get_link)],
    },
    fallbacks=[
        CommandHandler("cancel", admin_fsub_cancel),
        MessageHandler(filters.Regex("^(❌ Cancel|/cancel|cancel|🔙 Back to Admin)$"), admin_fsub_cancel),
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


