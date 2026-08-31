import os
import uuid
import shutil
import re
import html
import logging
import asyncio
from datetime import datetime, timezone
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID, DATA_DIR, BOT_TOKEN
import database
from bot_manager import bot_manager
from templates import TEMPLATES
from code_analyzer import (
    validate_python_syntax,
    extract_token_from_code,
    is_cancellation_text,
    is_menu_navigation_text
)

logger = logging.getLogger("GravixHost.User")

NAME, TOKEN, CODE = range(3)
TPL_TOKEN = 10

# ---------------------------------------------------------
# UI & Typography Helpers (Mobile-Friendly Clean Aesthetics)
# ---------------------------------------------------------

def make_header_card(title: str = "GRAVIX-HOST PRO", subtitle: str = "Next-Gen 24/7 Cloud Hosting Engine") -> str:
    """Builds a clean, single-line mobile-friendly header."""
    if subtitle:
        return (
            f"<b>⚡ {title} ⚡</b>\n"
            f"<i>{subtitle}</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
    return (
        f"<b>⚡ {title} ⚡</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━"
    )

def get_status_badge(status: str) -> str:
    """Returns a sleek formatted status badge with HTML markup."""
    s = (status or "").upper()
    if s == "RUNNING":
        return "🟢 <code>RUNNING</code>"
    elif s in ("FAILED", "CRASHED"):
        return f"🔴 <code>{html.escape(s)}</code>"
    elif s == "RESTARTING":
        return "🟡 <code>RESTARTING</code>"
    elif s == "PAUSED":
        return "⚪ <code>PAUSED</code>"
    else:
        return f"⚪ <code>{html.escape(s or 'STOPPED')}</code>"

def sanitize_token(raw_token: str) -> str:
    return raw_token.strip().strip("`").strip("'").strip('"').strip()

async def verify_telegram_token(token: str) -> tuple[bool, str, str]:
    cleaned = sanitize_token(token)
    if not re.match(r"^\d{6,14}:[a-zA-Z0-9_-]{30,45}$", cleaned):
        return False, "", "Invalid token format. Please copy the complete token string from @BotFather."

    url = f"https://api.telegram.org/bot{cleaned}/getMe"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            data = resp.json()
            if data.get("ok"):
                username = data["result"].get("username", "UnnamedBot")
                return True, username, ""
            else:
                return False, "", f"Telegram rejected token: {data.get('description', 'Unauthorized')}"
    except Exception as e:
        logger.warning(f"Could not reach Telegram API for token validation: {e}")
        return True, "Bot", ""

async def check_user_subscription(bot, user_id: int) -> tuple[bool, list]:
    if user_id == ADMIN_ID:
        return True, []

    channels = []
    if hasattr(database, "get_required_channels"):
        try:
            channels = database.get_required_channels()
        except Exception as e:
            logger.warning(f"Error fetching required channels from DB: {e}")
            channels = []

    if not channels:
        return True, []

    unjoined = []
    valid_statuses = {"member", "administrator", "creator", "owner", "restricted"}

    for ch in channels:
        raw_cid = ch.get("channel_id") if isinstance(ch, dict) else ch["channel_id"]
        try:
            cid = int(raw_cid)
        except (ValueError, TypeError):
            cid = str(raw_cid)

        try:
            member = await bot.get_chat_member(chat_id=cid, user_id=user_id)
            if member.status not in valid_statuses:
                unjoined.append(ch)
        except Exception as e:
            err_text = str(e).lower()
            if "chat not found" in err_text or "bot was kicked" in err_text or "chat_admin_required" in err_text or "admin" in err_text:
                logger.warning(f"Bot lacks access to required channel {cid}: {e}")
            else:
                logger.info(f"User {user_id} not joined in channel {cid}: {e}")
                unjoined.append(ch)

    return len(unjoined) == 0, unjoined

def get_force_sub_keyboard(unjoined_channels: list) -> InlineKeyboardMarkup:
    keyboard = []
    for ch in unjoined_channels:
        title = ch.get("title", "Channel") if isinstance(ch, dict) else ch["title"]
        link = ch.get("invite_link", "") if isinstance(ch, dict) else ch["invite_link"]
        keyboard.append([InlineKeyboardButton(f"📢 Join {title}", url=link)])

    keyboard.append([InlineKeyboardButton("✅ Verify Membership", callback_data="verify_fsub")])
    return InlineKeyboardMarkup(keyboard)

async def send_force_sub_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, unjoined_channels: list):
    header = make_header_card("MANDATORY CHANNEL JOIN", "Official Community Verification")
    text = (
        f"{header}\n\n"
        "<blockquote>To access <b>Gravix-Host</b> and deploy your Telegram bots 24/7, "
        "you must join our official community channels first.</blockquote>\n\n"
        "<b>📢 Verification Steps:</b>\n"
        "<blockquote>1. Click and join each official channel listed below.\n"
        "2. Tap the <b>✅ Verify Membership</b> button to activate your account.</blockquote>"
    )
    keyboard = get_force_sub_keyboard(unjoined_channels)
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await update.callback_query.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    elif update.message:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")

async def verify_fsub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    is_sub, unjoined = await check_user_subscription(context.bot, user_id)
    if is_sub:
        await query.answer("✅ Verification Successful! Welcome to Gravix-Host.", show_alert=True)
        await start_command(update, context)
    else:
        await query.answer("⚠️ You haven't joined all required channels yet! Please join and try again.", show_alert=True)
        await send_force_sub_prompt(update, context, unjoined)

# ---------------------------------------------------------
# Dynamic ReplyKeyboardMarkup Generators (100% Persistent Bottom Keyboards)
# ---------------------------------------------------------

def get_main_reply_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    keyboard = []
    if user_id == ADMIN_ID:
        keyboard.append([KeyboardButton("👑 Open Admin Panel")])
    keyboard.extend([
        [KeyboardButton("➕ Host New Bot"), KeyboardButton("🤖 My Hosted Bots")],
        [KeyboardButton("⚡ Quick Template Deploy"), KeyboardButton("📊 My Account & Slots")],
        [KeyboardButton("❓ Help & Guidelines"), KeyboardButton("🔄 Refresh")]
    ])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_my_bots_reply_keyboard(user_bots: list, page: int = 0) -> ReplyKeyboardMarkup:
    per_page = 5
    total_pages = max(1, (len(user_bots) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    curr_bots = user_bots[page * per_page : (page + 1) * per_page]

    keyboard = []
    for b in curr_bots:
        status = b.get('status', 'STOPPED')
        status_emoji = "🟢" if status == "RUNNING" else ("🔴" if status in ["FAILED", "CRASHED"] else "⚪")
        bot_name = b.get('bot_name', 'Unnamed Bot')
        bot_id = b.get('bot_id', '')
        keyboard.append([KeyboardButton(f"{status_emoji} {bot_name} [#{bot_id}]")])

    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(KeyboardButton("⬅️ Prev Bots"))
        if page < total_pages - 1:
            nav_row.append(KeyboardButton("Next Bots ➡️"))
        if nav_row:
            keyboard.append(nav_row)

    keyboard.append([KeyboardButton("➕ Host Another Bot"), KeyboardButton("🔙 Back to Main Menu")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_bot_detail_reply_keyboard(bot_id: str, status: str) -> ReplyKeyboardMarkup:
    keyboard = []
    if status == 'RUNNING':
        keyboard.append([
            KeyboardButton(f"⏹️ Stop Bot [#{bot_id}]"),
            KeyboardButton(f"🔄 Restart Bot [#{bot_id}]")
        ])
    else:
        keyboard.append([
            KeyboardButton(f"▶️ Start Bot [#{bot_id}]")
        ])
    keyboard.append([
        KeyboardButton(f"📜 View Logs [#{bot_id}]"),
        KeyboardButton(f"🗑️ Delete Bot [#{bot_id}]")
    ])
    keyboard.append([
        KeyboardButton("🔙 Back to My Bots"),
        KeyboardButton("🏠 Main Menu")
    ])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_delete_confirm_keyboard(bot_id: str) -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(f"⚠️ Confirm Delete [#{bot_id}]"),
            KeyboardButton(f"❌ Cancel Delete [#{bot_id}]")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_templates_reply_keyboard() -> ReplyKeyboardMarkup:
    keyboard = []
    for key, tinfo in TEMPLATES.items():
        keyboard.append([KeyboardButton(tinfo['name'])])
    keyboard.append([KeyboardButton("🔙 Back to Main Menu")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_back_to_main_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton("🔙 Back to Main Menu")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton("❌ Cancel")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_token_input_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("⏩ Skip (Auto-Detect Token)"), KeyboardButton("❌ Cancel")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ---------------------------------------------------------
# Screen Handlers
# ---------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = database.get_or_create_user(user.id, user.username or "", user.first_name or "")

    if db_user['is_banned']:
        msg = (
            f"{make_header_card('ACCOUNT SUSPENDED', 'Access Denied')}\n\n"
            "<blockquote>🚫 <b>Access Restricted:</b> Your account has been suspended by the administrator.</blockquote>"
        )
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
            await update.effective_message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")
        return

    is_sub, unjoined = await check_user_subscription(context.bot, user.id)
    if not is_sub:
        await send_force_sub_prompt(update, context, unjoined)
        return

    maint = database.get_setting("maintenance_mode", "0") == "1"
    maint_notice = ""
    if maint and user.id != ADMIN_ID:
        maint_notice = "\n<blockquote>⚠️ <b>Notice:</b> System maintenance is currently active. Deployments may be temporarily paused.</blockquote>\n"

    header = make_header_card("GRAVIX-HOST PRO", "Next-Gen 24/7 Cloud Hosting Engine")
    safe_name = html.escape(user.first_name or "Developer")

    text = (
        f"{header}\n\n"
        f"👋 Welcome, <b>{safe_name}</b>!\n\n"
        "<blockquote><b>Gravix-Host</b> delivers high-performance 24/7 isolated cloud runtime "
        "for your Python Telegram bots with automated watchdog monitoring and zero downtime.</blockquote>\n\n"
        "<b>🚀 Platform Capabilities:</b>\n"
        "<blockquote>• <b>Custom Python Hosting:</b> Upload scripts or raw code\n"
        "• <b>1-Click Templates:</b> Instant pre-configured bot deployment\n"
        "• <b>Live Console Engine:</b> Real-time log streaming & watchdog\n"
        "• <b>Lifecycle Control:</b> Start, stop, restart & auto-heal</blockquote>\n"
        f"{maint_notice}\n"
        "👇 <i>Select an action from the persistent menu below to manage your bots:</i>"
    )

    reply_kb = get_main_reply_keyboard(user.id)
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass
        await update.callback_query.message.reply_text(text, reply_markup=reply_kb, parse_mode="HTML")
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_kb, parse_mode="HTML")

async def show_my_bots(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    user = update.effective_user
    user_id = user.id
    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        msg = (
            f"{make_header_card('ACCOUNT SUSPENDED', 'Access Denied')}\n\n"
            "<blockquote>🚫 <b>Access Restricted:</b> Your account has been suspended by the administrator.</blockquote>"
        )
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
            await update.effective_message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")
        return

    is_sub, unjoined = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        await send_force_sub_prompt(update, context, unjoined)
        return

    context.user_data['bots_page'] = page
    user_bots = database.get_user_bots(user_id)
    per_page = 5
    total_pages = max(1, (len(user_bots) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    curr_bots = user_bots[page * per_page : (page + 1) * per_page]

    if not user_bots:
        header = make_header_card("MY HOSTED BOTS", "Cloud Instances Overview")
        text = (
            f"{header}\n\n"
            "<blockquote>You currently have no hosted bots provisioned on <b>Gravix-Host</b>.</blockquote>\n\n"
            "<b>🚀 Getting Started:</b>\n"
            "<blockquote>• Tap <b>➕ Host New Bot</b> to deploy your custom Python script.\n"
            "• Tap <b>⚡ Quick Template Deploy</b> to launch a ready-made template in seconds.</blockquote>"
        )
        keyboard = ReplyKeyboardMarkup([
            [KeyboardButton("➕ Host New Bot"), KeyboardButton("⚡ Quick Template Deploy")],
            [KeyboardButton("🔙 Back to Main Menu")]
        ], resize_keyboard=True)
        if update.callback_query:
            await update.callback_query.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
        return

    header = make_header_card("MY HOSTED BOTS", f"Page {page + 1} of {total_pages}")
    
    bot_lines = []
    for b in curr_bots:
        status_badge = get_status_badge(b.get('status', 'STOPPED'))
        b_name = html.escape(b.get('bot_name', 'Unnamed Bot'))
        b_id = html.escape(str(b.get('bot_id', '')))
        raw_status = html.escape(str(b.get('status', 'STOPPED')))
        bot_lines.append(f"• {status_badge} <b>{b_name}</b> (<code>#{b_id}</code>)\n  └ <i>Status:</i> <code>{raw_status}</code>")

    bots_block = "\n".join(bot_lines)
    text = (
        f"{header}\n\n"
        "<blockquote>Select any bot from the persistent menu below to inspect diagnostics, stream live logs, or control lifecycle.</blockquote>\n\n"
        "<b>📋 Active Instances:</b>\n"
        f"<blockquote>\n{bots_block}\n</blockquote>"
    )

    keyboard = get_my_bots_reply_keyboard(user_bots, page=page)
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")

async def show_bot_details(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id: str = None):
    user = update.effective_user
    user_id = user.id
    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        msg = (
            f"{make_header_card('ACCOUNT SUSPENDED', 'Access Denied')}\n\n"
            "<blockquote>🚫 <b>Access Restricted:</b> Your account has been suspended by the administrator.</blockquote>"
        )
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
            await update.effective_message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")
        return

    if bot_id is None and update.message and update.message.text:
        m = re.search(r"\[#([a-zA-Z0-9_-]+)\]", update.message.text)
        if m:
            bot_id = m.group(1)

    if not bot_id:
        await show_my_bots(update, context, page=0)
        return

    bot_data = database.get_bot(bot_id)
    if not bot_data or (bot_data['user_id'] != user_id and user_id != ADMIN_ID):
        msg = "⚠️ Bot not found or unauthorized access."
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        else:
            await update.message.reply_text(msg, reply_markup=get_my_bots_reply_keyboard(database.get_user_bots(user_id)))
        return

    status = bot_data['status']
    status_badge = get_status_badge(status)
    created_str = (bot_data.get('created_at') or "N/A")[:19].replace('T', ' ')
    token_raw = bot_data.get('bot_token', '')
    token_masked = f"{token_raw[:10]}...{token_raw[-4:]}" if len(token_raw) > 14 else "••••••••"

    is_running = bot_manager.is_running(bot_id)
    proc = bot_manager.active_processes.get(bot_id)
    pid_str = str(proc.pid) if (proc and proc.returncode is None) else ("Active" if is_running else "Offline")

    uptime_str = "Offline"
    if is_running:
        uptime_str = "Active"
        last_started_str = bot_data.get('last_started')
        if last_started_str:
            try:
                dt = datetime.fromisoformat(str(last_started_str).replace("Z", "+00:00"))
                now_dt = datetime.now(timezone.utc) if dt.tzinfo else datetime.utcnow()
                secs = int((now_dt - dt).total_seconds())
                if secs >= 0:
                    days, rem = divmod(secs, 86400)
                    hours, rem = divmod(rem, 3600)
                    mins, s = divmod(rem, 60)
                    parts = []
                    if days > 0:
                        parts.append(f"{days}d")
                    if hours > 0 or days > 0:
                        parts.append(f"{hours}h")
                    parts.append(f"{mins}m")
                    parts.append(f"{s}s")
                    uptime_str = " ".join(parts)
            except Exception:
                uptime_str = "Active"

    auto_restart_str = "Enabled (Watchdog Active)" if bot_data.get('auto_restart') else "Disabled"
    header = make_header_card("BOT INSPECTOR", "Instance Diagnostics & Control")
    safe_bot_name = html.escape(bot_data.get('bot_name', 'Unnamed Bot'))

    text = (
        f"{header}\n\n"
        "<b>🤖 Instance Overview:</b>\n"
        f"<blockquote>• <b>Name:</b> <b>{safe_bot_name}</b>\n"
        f"• <b>Bot ID:</b> <code>#{html.escape(bot_id)}</code>\n"
        f"• <b>Status:</b> {status_badge}\n"
        f"• <b>PID:</b> <code>{html.escape(pid_str)}</code>\n"
        f"• <b>Uptime:</b> <code>{html.escape(uptime_str)}</code></blockquote>\n\n"
        "<b>⚙️ Configuration & Metadata:</b>\n"
        f"<blockquote>• <b>API Token:</b> <code>{html.escape(token_masked)}</code>\n"
        f"• <b>Auto-Restart:</b> <code>{auto_restart_str}</code>\n"
        f"• <b>Created:</b> <code>{html.escape(created_str)}</code></blockquote>\n\n"
        "👇 <i>Use the persistent keyboard below to manage this instance:</i>"
    )

    keyboard = get_bot_detail_reply_keyboard(bot_id, status)
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")

async def handle_bot_action(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str = None, bot_id: str = None):
    user = update.effective_user
    user_id = user.id
    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        msg = (
            f"{make_header_card('ACCOUNT SUSPENDED', 'Access Denied')}\n\n"
            "<blockquote>🚫 <b>Access Restricted:</b> Your account has been suspended by the administrator.</blockquote>"
        )
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
            await update.effective_message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")
        return

    text_input = update.message.text if (update.message and update.message.text) else ""
    if bot_id is None:
        m = re.search(r"\[#([a-zA-Z0-9_-]+)\]", text_input)
        if m:
            bot_id = m.group(1)

    if not bot_id:
        await show_my_bots(update, context, page=0)
        return

    if action is None:
        if "▶️ Start Bot" in text_input:
            action = "start"
        elif "⏹️ Stop Bot" in text_input:
            action = "stop"
        elif "🔄 Restart Bot" in text_input:
            action = "restart"
        elif "📜 View Logs" in text_input:
            action = "logs"
        elif "⚠️ Confirm Delete" in text_input:
            action = "delete_execute"
        elif "❌ Cancel Delete" in text_input:
            action = "cancel_delete"
        elif "🗑️ Delete Bot" in text_input:
            action = "delete_confirm"

    bot_data = database.get_bot(bot_id)
    if not bot_data or (bot_data['user_id'] != user_id and user_id != ADMIN_ID):
        msg = "⚠️ Bot not found or unauthorized action."
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        else:
            await update.message.reply_text(msg, reply_markup=get_main_reply_keyboard(user_id))
        return

    safe_bot_name = html.escape(bot_data.get('bot_name', 'Unnamed Bot'))

    if action == "start":
        success, msg = await bot_manager.start_bot(bot_id)
        header = make_header_card("ACTION EXECUTION", "Start Instance")
        resp = (
            f"{header}\n\n"
            f"<blockquote>🟢 <b>Bot Start Result:</b>\n{html.escape(msg)}</blockquote>"
        )
        await update.effective_message.reply_text(resp, parse_mode="HTML")
        await show_bot_details(update, context, bot_id)

    elif action == "stop":
        success, msg = await bot_manager.stop_bot(bot_id)
        header = make_header_card("ACTION EXECUTION", "Stop Instance")
        resp = (
            f"{header}\n\n"
            f"<blockquote>⏹️ <b>Bot Stop Result:</b>\n{html.escape(msg)}</blockquote>"
        )
        await update.effective_message.reply_text(resp, parse_mode="HTML")
        await show_bot_details(update, context, bot_id)

    elif action == "restart":
        success, msg = await bot_manager.restart_bot(bot_id)
        header = make_header_card("ACTION EXECUTION", "Restart Instance")
        resp = (
            f"{header}\n\n"
            f"<blockquote>🔄 <b>Bot Restart Result:</b>\n{html.escape(msg)}</blockquote>"
        )
        await update.effective_message.reply_text(resp, parse_mode="HTML")
        await show_bot_details(update, context, bot_id)

    elif action == "logs":
        logs = bot_manager.get_logs(bot_id, lines=25)
        if not logs.strip():
            logs = "No console logs recorded yet for this bot instance."
        header = make_header_card("LIVE CONSOLE LOGS", f"Instance #{html.escape(bot_id)}")
        safe_logs = html.escape(logs[-3500:])
        text = (
            f"{header}\n\n"
            f"<pre><code class=\"language-log\">{safe_logs}</code></pre>\n\n"
            "<blockquote>💡 <i>Displaying the most recent 25 log lines. Live streaming is active.</i></blockquote>"
        )
        status = bot_data['status']
        await update.effective_message.reply_text(
            text,
            reply_markup=get_bot_detail_reply_keyboard(bot_id, status),
            parse_mode="HTML"
        )

    elif action == "delete_confirm":
        header = make_header_card("CONFIRM DELETION", "Permanent Instance Removal")
        text = (
            f"{header}\n\n"
            f"<blockquote>⚠️ <b>Are you sure you want to permanently delete:</b>\n"
            f"• <b>Bot:</b> <b>{safe_bot_name}</b> (<code>#{html.escape(bot_id)}</code>)\n"
            "• <b>Files:</b> Source files and execution logs will be erased.\n\n"
            "⛔ <i>This action cannot be undone.</i></blockquote>\n\n"
            "👇 <i>Tap <b>⚠️ Confirm Delete</b> to proceed or <b>❌ Cancel Delete</b> to abort:</i>"
        )
        await update.effective_message.reply_text(
            text,
            reply_markup=get_delete_confirm_keyboard(bot_id),
            parse_mode="HTML"
        )

    elif action == "delete_execute":
        await bot_manager.stop_bot(bot_id)
        script_dir = os.path.dirname(bot_data['script_path'])
        if os.path.exists(script_dir):
            shutil.rmtree(script_dir, ignore_errors=True)
        database.delete_bot_record(bot_id)
        header = make_header_card("INSTANCE DELETED", "Cleanup Complete")
        text = (
            f"{header}\n\n"
            f"<blockquote>🗑️ Bot <b>{safe_bot_name}</b> (<code>#{html.escape(bot_id)}</code>) "
            "and all associated workspace files have been permanently removed.</blockquote>"
        )
        await update.effective_message.reply_text(text, parse_mode="HTML")
        await show_my_bots(update, context, page=0)

    elif action == "cancel_delete":
        header = make_header_card("ACTION ABORTED", "Deletion Cancelled")
        text = (
            f"{header}\n\n"
            f"<blockquote>Deletion of bot <b>{safe_bot_name}</b> (<code>#{html.escape(bot_id)}</code>) was cancelled.</blockquote>"
        )
        await update.effective_message.reply_text(text, parse_mode="HTML")
        await show_bot_details(update, context, bot_id)

async def show_account_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        msg = (
            f"{make_header_card('ACCOUNT SUSPENDED', 'Access Denied')}\n\n"
            "<blockquote>🚫 <b>Access Restricted:</b> Your account has been suspended by the administrator.</blockquote>"
        )
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
            await update.effective_message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")
        return

    is_sub, unjoined = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        await send_force_sub_prompt(update, context, unjoined)
        return

    user_bots = database.get_user_bots(user_id)
    max_slots = db_user.get('max_slots', 3)
    running_cnt = sum(1 for b in user_bots if b['status'] == 'RUNNING')
    available_slots = max(0, max_slots - len(user_bots))
    username_str = f"@{html.escape(user.username)}" if user.username else "<code>N/A</code>"

    header = make_header_card("ACCOUNT QUOTA", "Resource Allocation & Limits")
    text = (
        f"{header}\n\n"
        "<b>👤 Account Identity:</b>\n"
        f"<blockquote>• <b>User ID:</b> <code>{user_id}</code>\n"
        f"• <b>Username:</b> {username_str}\n"
        "• <b>Plan Tier:</b> <code>Standard Developer</code></blockquote>\n\n"
        "<b>📦 Infrastructure Quota:</b>\n"
        f"<blockquote>• <b>Total Slots:</b> <code>{max_slots}</code>\n"
        f"• <b>Provisioned Bots:</b> <code>{len(user_bots)} / {max_slots}</code>\n"
        f"• <b>Active Instances:</b> <code>{running_cnt}</code>\n"
        f"• <b>Available Slots:</b> <code>{available_slots}</code></blockquote>\n\n"
        "<blockquote>💡 <i>Need additional bot capacity or dedicated resources? Contact platform support.</i></blockquote>"
    )
    reply_kb = get_back_to_main_keyboard()
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_kb, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=reply_kb, parse_mode="HTML")

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        msg = (
            f"{make_header_card('ACCOUNT SUSPENDED', 'Access Denied')}\n\n"
            "<blockquote>🚫 <b>Access Restricted:</b> Your account has been suspended by the administrator.</blockquote>"
        )
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
            await update.effective_message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")
        return

    is_sub, unjoined = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        await send_force_sub_prompt(update, context, unjoined)
        return

    header = make_header_card("GUIDELINES & HELP", "Quick Start & Deployment Manual")
    text = (
        f"{header}\n\n"
        "<b>🚀 4-Step Deployment Guide:</b>\n"
        "<blockquote><b>1️⃣ Obtain a Bot Token:</b>\n"
        "• Open @BotFather on Telegram.\n"
        "• Send <code>/newbot</code> and follow prompts to obtain your API Token.\n\n"
        "<b>2️⃣ Deploy Your Bot:</b>\n"
        "• Tap <b>➕ Host New Bot</b> or <b>⚡ Quick Template Deploy</b>.\n"
        "• Provide your BotFather token.\n"
        "• Upload your <code>.py</code> file or select a ready-made template.\n\n"
        "<b>3️⃣ Supported Frameworks:</b>\n"
        "• <code>python-telegram-bot</code>, <code>aiogram</code>, <code>pyTelegramBotAPI</code>\n"
        "• <code>requests</code>, <code>httpx</code>, <code>aiohttp</code>, <code>asyncio</code>\n\n"
        "<b>4️⃣ Lifecycle & Diagnostics:</b>\n"
        "• Access live logs, restart, and monitor status anytime in <b>🤖 My Hosted Bots</b>.</blockquote>\n\n"
        "<blockquote>💡 <i>For optimal stability, ensure your bot uses standard polling or webhook architectures without hardcoded local paths.</i></blockquote>"
    )
    reply_kb = get_back_to_main_keyboard()
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_kb, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=reply_kb, parse_mode="HTML")

async def show_templates_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        msg = (
            f"{make_header_card('ACCOUNT SUSPENDED', 'Access Denied')}\n\n"
            "<blockquote>🚫 <b>Access Restricted:</b> Your account has been suspended by the administrator.</blockquote>"
        )
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
            await update.effective_message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")
        return

    is_sub, unjoined = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        await send_force_sub_prompt(update, context, unjoined)
        return

    maint = database.get_setting("maintenance_mode", "0") == "1"
    if maint and user_id != ADMIN_ID:
        msg = (
            f"{make_header_card('MAINTENANCE MODE', 'Temporary System Pause')}\n\n"
            "<blockquote>⚠️ <b>Notice:</b> Platform is currently undergoing maintenance. New bot deployments are paused.</blockquote>"
        )
        if update.callback_query:
            await update.callback_query.answer("⚠️ Maintenance Mode Active", show_alert=True)
            await update.effective_message.reply_text(msg, reply_markup=get_main_reply_keyboard(user_id), parse_mode="HTML")
        else:
            await update.message.reply_text(msg, reply_markup=get_main_reply_keyboard(user_id), parse_mode="HTML")
        return

    header = make_header_card("QUICK TEMPLATES", "1-Click Ready-to-Deploy Instances")
    
    tpl_lines = []
    for key, tinfo in TEMPLATES.items():
        tname = html.escape(tinfo.get('name', 'Template'))
        tdesc = html.escape(tinfo.get('description', ''))
        tpl_lines.append(f"• <b>{tname}</b>\n  <i>{tdesc}</i>")

    tpl_block = "\n\n".join(tpl_lines)
    text = (
        f"{header}\n\n"
        "<blockquote>Deploy production-ready Telegram bots in seconds. Choose a template from the menu below:</blockquote>\n\n"
        "<b>📦 Available Quick Templates:</b>\n"
        f"<blockquote>\n{tpl_block}\n</blockquote>\n\n"
        "👇 <i>Tap a template button on the keyboard below to begin instant deployment:</i>"
    )

    keyboard = get_templates_reply_keyboard()
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")

# ---------------------------------------------------------
# Quick Template Deployment Conversation Flow
# ---------------------------------------------------------

async def template_select_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    if update.message and update.message.text:
        text = update.message.text.strip()
        if is_cancellation_text(text) or (is_menu_navigation_text(text) and not any(text == v['name'] or text.startswith(v['name']) for v in TEMPLATES.values())):
            context.user_data.pop('active_flow', None)
            context.user_data.pop('deploy_template_key', None)
            if text in ["❌ Cancel", "/cancel", "cancel"] or text.lower() in ["❌ cancel", "/cancel", "cancel"]:
                await update.message.reply_text("❌ Hosting wizard cancelled.", reply_markup=get_main_reply_keyboard(user_id), parse_mode="HTML")
            else:
                await user_text_router(update, context)
            return ConversationHandler.END

    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        msg = (
            f"{make_header_card('ACCOUNT SUSPENDED', 'Access Denied')}\n\n"
            "<blockquote>🚫 <b>Access Restricted:</b> Your account has been suspended.</blockquote>"
        )
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
            await update.effective_message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")
        return ConversationHandler.END

    is_sub, unjoined = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        if update.callback_query:
            await update.callback_query.answer()
        await send_force_sub_prompt(update, context, unjoined)
        return ConversationHandler.END

    maint = database.get_setting("maintenance_mode", "0") == "1"
    if maint and user_id != ADMIN_ID:
        msg = (
            f"{make_header_card('MAINTENANCE MODE', 'Temporary System Pause')}\n\n"
            "<blockquote>⚠️ <b>Notice:</b> Platform is currently under maintenance. New bot deployments are paused.</blockquote>"
        )
        if update.callback_query:
            await update.callback_query.answer("⚠️ Maintenance Mode Active", show_alert=True)
            await update.effective_message.reply_text(msg, reply_markup=get_main_reply_keyboard(user_id), parse_mode="HTML")
        else:
            await update.message.reply_text(msg, reply_markup=get_main_reply_keyboard(user_id), parse_mode="HTML")
        return ConversationHandler.END

    user_bots = database.get_user_bots(user_id)
    max_slots = db_user.get('max_slots', 3)
    if len(user_bots) >= max_slots:
        msg = (
            f"{make_header_card('QUOTA LIMIT REACHED', 'Resource Capacity Exceeded')}\n\n"
            f"<blockquote>⚠️ You have reached your slot limit of <code>{max_slots}</code> bots "
            f"(<code>{len(user_bots)}/{max_slots}</code>).\n\n"
            "Please delete an unused bot from <b>🤖 My Hosted Bots</b> or contact Admin for additional capacity.</blockquote>"
        )
        if update.callback_query:
            await update.callback_query.answer("⚠️ Slot Limit Reached", show_alert=True)
            await update.effective_message.reply_text(msg, reply_markup=get_main_reply_keyboard(user_id), parse_mode="HTML")
        else:
            await update.message.reply_text(msg, reply_markup=get_main_reply_keyboard(user_id), parse_mode="HTML")
        return ConversationHandler.END

    tpl_key = None
    if update.callback_query:
        await update.callback_query.answer()
        tpl_key = update.callback_query.data.replace("deploy_tpl_", "", 1)
    elif update.message and update.message.text:
        input_text = update.message.text.strip()
        for k, v in TEMPLATES.items():
            if v['name'] == input_text or input_text.startswith(v['name']):
                tpl_key = k
                break

    if not tpl_key or tpl_key not in TEMPLATES:
        await update.effective_message.reply_text(
            "<blockquote>⚠️ <b>Template Not Recognized:</b> Please select a valid template from the keyboard menu below.</blockquote>",
            reply_markup=get_templates_reply_keyboard(),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    context.user_data['deploy_template_key'] = tpl_key
    context.user_data['active_flow'] = 'tpl'
    tinfo = TEMPLATES[tpl_key]

    header = make_header_card("QUICK TEMPLATE DEPLOY", "1-Click Automated Setup")
    safe_tname = html.escape(tinfo.get('name', 'Template'))
    safe_tdesc = html.escape(tinfo.get('description', ''))

    text = (
        f"{header}\n\n"
        "<b>📦 Selected Template:</b>\n"
        f"<blockquote>• <b>Template:</b> <b>{safe_tname}</b>\n"
        f"• <b>Overview:</b> <i>{safe_tdesc}</i></blockquote>\n\n"
        "<b>🔑 Telegram Bot Token:</b>\n"
        "<blockquote>Please send your bot API token obtained from @BotFather.\n"
        "<i>Example:</i> <code>1234567890:AAH_sampleToken...</code></blockquote>\n\n"
        "👇 <i>Send the token as text or tap <b>❌ Cancel</b> below:</i>"
    )
    cancel_kb = get_cancel_keyboard()
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=cancel_kb, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=cancel_kb, parse_mode="HTML")
    return TPL_TOKEN

async def template_token_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message or not update.message.text:
        await update.effective_message.reply_text(
            "<blockquote>⚠️ Please send your bot API token as text or tap <b>❌ Cancel</b>.</blockquote>",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return TPL_TOKEN

    text = update.message.text.strip()
    if is_cancellation_text(text) or is_menu_navigation_text(text):
        context.user_data.pop('active_flow', None)
        context.user_data.pop('bot_name', None)
        context.user_data.pop('bot_token', None)
        context.user_data.pop('bot_id', None)
        context.user_data.pop('deploy_template_key', None)
        if text in ["❌ Cancel", "/cancel", "cancel"] or text.lower() in ["❌ cancel", "/cancel", "cancel"]:
            await update.message.reply_text("❌ Hosting wizard cancelled.", reply_markup=get_main_reply_keyboard(user_id), parse_mode="HTML")
        else:
            await user_text_router(update, context)
        return ConversationHandler.END

    if context.user_data.get('active_flow') != 'tpl':
        await update.message.reply_text(
            "<blockquote>⚠️ <b>Session Expired:</b> Please reopen <b>⚡ Quick Template Deploy</b> from the main menu.</blockquote>",
            reply_markup=get_main_reply_keyboard(user_id),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    token = sanitize_token(text)
    tpl_key = context.user_data.get('deploy_template_key', 'echo_bot')
    tinfo = TEMPLATES.get(tpl_key, TEMPLATES['echo_bot'])

    if token == BOT_TOKEN:
        await update.message.reply_text(
            "<blockquote>⚠️ <b>Invalid Token:</b> You cannot host a bot using this platform's own bot token. "
            "Please create a distinct bot with @BotFather and send its token:</blockquote>",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return TPL_TOKEN

    is_valid, bot_uname, err_msg = await verify_telegram_token(token)
    if not is_valid:
        await update.message.reply_text(
            f"<blockquote>⚠️ <b>Token Validation Failed:</b>\n{html.escape(err_msg)}\n\n"
            "Please copy and paste a valid Bot Token from @BotFather:</blockquote>",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return TPL_TOKEN

    bot_name = f"@{bot_uname} ({tinfo['name'].split(' ', 1)[1] if ' ' in tinfo['name'] else tinfo['name']})"
    bot_id = str(uuid.uuid4())[:8]
    bot_dir = os.path.join(DATA_DIR, "bots", f"{user_id}_{bot_id}")
    os.makedirs(bot_dir, exist_ok=True)
    script_path = os.path.join(bot_dir, "main.py")

    with open(script_path, "w", encoding="utf-8") as f:
        f.write(tinfo['code'])

    database.create_hosted_bot(bot_id, user_id, bot_name, token, script_path)
    status_msg = await update.message.reply_text("⚙️ <i>Provisioning container and launching template instance...</i>", parse_mode="HTML")

    success, msg = await bot_manager.start_bot(bot_id)
    context.user_data.clear()

    bot_status = "RUNNING" if success else "FAILED"
    status_badge = get_status_badge(bot_status)
    header = make_header_card("TEMPLATE LAUNCHED!", "1-Click Provisioning Complete")
    safe_bot_name = html.escape(bot_name)
    safe_msg = html.escape(msg)

    resp_text = (
        f"{header}\n\n"
        "<blockquote>🎉 <b>Success!</b> The pre-built template engine has been compiled and started.</blockquote>\n\n"
        "<b>📊 Instance Details:</b>\n"
        f"<blockquote>• <b>Bot Name:</b> <b>{safe_bot_name}</b>\n"
        f"• <b>Bot ID:</b> <code>#{html.escape(bot_id)}</code>\n"
        f"• <b>Status:</b> {status_badge}\n"
        f"• <b>Diagnostics:</b> {safe_msg}</blockquote>\n\n"
        "<blockquote>💡 <i>Your bot is now live and running 24/7 on <b>Gravix-Host</b>.</i></blockquote>"
    )
    await status_msg.reply_text(resp_text, reply_markup=get_bot_detail_reply_keyboard(bot_id, bot_status), parse_mode="HTML")
    return ConversationHandler.END

async def cancel_tpl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    header = make_header_card("DEPLOYMENT CANCELLED", "Template Setup Aborted")
    text = (
        f"{header}\n\n"
        "<blockquote>❌ Template deployment cancelled. No resources were provisioned.</blockquote>"
    )
    if update.callback_query:
        await update.callback_query.answer("Template deployment cancelled.")
    await update.effective_message.reply_text(text, reply_markup=get_main_reply_keyboard(user_id), parse_mode="HTML")
    return ConversationHandler.END

# ---------------------------------------------------------
# Custom Bot Hosting Conversation Flow
# ---------------------------------------------------------

async def host_bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        msg = (
            f"{make_header_card('ACCOUNT SUSPENDED', 'Access Denied')}\n\n"
            "<blockquote>🚫 <b>Access Restricted:</b> Your account has been suspended by the administrator.</blockquote>"
        )
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
            await update.effective_message.reply_text(msg, parse_mode="HTML")
        else:
            await update.message.reply_text(msg, parse_mode="HTML")
        return ConversationHandler.END

    is_sub, unjoined = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        if update.callback_query:
            await update.callback_query.answer()
        await send_force_sub_prompt(update, context, unjoined)
        return ConversationHandler.END

    maint = database.get_setting("maintenance_mode", "0") == "1"
    if maint and user_id != ADMIN_ID:
        msg = (
            f"{make_header_card('MAINTENANCE MODE', 'Temporary System Pause')}\n\n"
            "<blockquote>⚠️ <b>Notice:</b> Platform is currently undergoing maintenance. New bot deployments are paused.</blockquote>"
        )
        if update.callback_query:
            await update.callback_query.answer("⚠️ Maintenance Mode Active", show_alert=True)
            await update.effective_message.reply_text(msg, reply_markup=get_main_reply_keyboard(user_id), parse_mode="HTML")
        else:
            await update.message.reply_text(msg, reply_markup=get_main_reply_keyboard(user_id), parse_mode="HTML")
        return ConversationHandler.END

    user_bots = database.get_user_bots(user_id)
    max_slots = db_user.get('max_slots', 3)
    if len(user_bots) >= max_slots:
        msg = (
            f"{make_header_card('QUOTA LIMIT REACHED', 'Resource Capacity Exceeded')}\n\n"
            f"<blockquote>⚠️ You have reached your slot limit of <code>{max_slots}</code> bots "
            f"(<code>{len(user_bots)}/{max_slots}</code>).\n\n"
            "Please delete an existing bot from <b>🤖 My Hosted Bots</b> or contact Admin for more slots.</blockquote>"
        )
        if update.callback_query:
            await update.callback_query.answer("⚠️ Slot Limit Reached", show_alert=True)
            await update.effective_message.reply_text(msg, reply_markup=get_main_reply_keyboard(user_id), parse_mode="HTML")
        else:
            await update.message.reply_text(msg, reply_markup=get_main_reply_keyboard(user_id), parse_mode="HTML")
        return ConversationHandler.END

    if update.callback_query:
        await update.callback_query.answer()

    context.user_data['active_flow'] = 'host'
    header = make_header_card("CUSTOM BOT HOSTING", "Step 1 of 3: Instance Identification")
    text = (
        f"{header}\n\n"
        "<blockquote>Please enter a friendly <b>Display Name</b> for your bot.\n"
        "<i>Example:</i> <code>My Store Bot</code> or <code>Crypto Price Alert</code></blockquote>\n\n"
        "👇 <i>Type the name in chat or tap <b>❌ Cancel</b> below:</i>"
    )
    cancel_kb = get_cancel_keyboard()
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=cancel_kb, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=cancel_kb, parse_mode="HTML")
    return NAME

async def host_bot_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message or not update.message.text:
        await update.effective_message.reply_text(
            "<blockquote>⚠️ Please enter a text name for your bot or tap <b>❌ Cancel</b>.</blockquote>",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return NAME

    text = update.message.text.strip()
    if is_cancellation_text(text) or is_menu_navigation_text(text):
        context.user_data.pop('active_flow', None)
        context.user_data.pop('bot_name', None)
        context.user_data.pop('bot_token', None)
        context.user_data.pop('bot_id', None)
        context.user_data.pop('new_bot_name', None)
        context.user_data.pop('new_bot_token', None)
        context.user_data.pop('bot_uname', None)
        if text in ["❌ Cancel", "/cancel", "cancel"] or text.lower() in ["❌ cancel", "/cancel", "cancel"]:
            await update.message.reply_text("❌ Hosting wizard cancelled.", reply_markup=get_main_reply_keyboard(user_id), parse_mode="HTML")
        else:
            await user_text_router(update, context)
        return ConversationHandler.END

    if context.user_data.get('active_flow') != 'host':
        await update.message.reply_text(
            "<blockquote>⚠️ <b>Session Interrupted:</b> Please use /start to begin again.</blockquote>",
            reply_markup=get_main_reply_keyboard(user_id),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    bot_name = text
    if len(bot_name) < 2 or len(bot_name) > 30:
        await update.message.reply_text(
            "<blockquote>⚠️ <b>Invalid Name:</b> Name must be between 2 and 30 characters. Please enter a valid name:</blockquote>",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return NAME

    context.user_data['new_bot_name'] = bot_name
    context.user_data['bot_name'] = bot_name
    safe_bot_name = html.escape(bot_name)
    header = make_header_card("CUSTOM BOT HOSTING", "Step 2 of 3: API Authentication")
    text_resp = (
        f"{header}\n\n"
        f"<blockquote>Target Bot: <b>{safe_bot_name}</b></blockquote>\n\n"
        "<b>🔑 Telegram Bot Token:</b>\n"
        "<blockquote>Please send the API token obtained from @BotFather.\n"
        "<i>Format:</i> <code>1234567890:AAH_sampleToken...</code>\n\n"
        "💡 <i>If your token is hardcoded in your Python script, tap <b>⏩ Skip (Auto-Detect Token)</b>.</i></blockquote>\n\n"
        "👇 <i>Send your token as text or choose an option below:</i>"
    )
    await update.message.reply_text(text_resp, reply_markup=get_token_input_keyboard(), parse_mode="HTML")
    return TOKEN

async def host_bot_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message or not update.message.text:
        await update.effective_message.reply_text(
            "<blockquote>⚠️ Please send your bot API token as text or tap <b>❌ Cancel</b>.</blockquote>",
            reply_markup=get_token_input_keyboard(),
            parse_mode="HTML"
        )
        return TOKEN

    text = update.message.text.strip()
    if is_cancellation_text(text) or is_menu_navigation_text(text):
        context.user_data.pop('active_flow', None)
        context.user_data.pop('bot_name', None)
        context.user_data.pop('bot_token', None)
        context.user_data.pop('bot_id', None)
        context.user_data.pop('new_bot_name', None)
        context.user_data.pop('new_bot_token', None)
        context.user_data.pop('bot_uname', None)
        if text in ["❌ Cancel", "/cancel", "cancel"] or text.lower() in ["❌ cancel", "/cancel", "cancel"]:
            await update.message.reply_text("❌ Hosting wizard cancelled.", reply_markup=get_main_reply_keyboard(user_id), parse_mode="HTML")
        else:
            await user_text_router(update, context)
        return ConversationHandler.END

    if context.user_data.get('active_flow') != 'host':
        await update.message.reply_text(
            "<blockquote>⚠️ <b>Session Interrupted:</b> Please resend your bot token to continue.</blockquote>",
            reply_markup=get_main_reply_keyboard(user_id),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    # Check for Skip (Auto-Detect Token)
    if text == "⏩ Skip (Auto-Detect Token)" or text.lower() in ("skip", "/skip"):
        context.user_data['bot_token'] = 'AUTO_DETECT'
        context.user_data['new_bot_token'] = 'AUTO_DETECT'
        context.user_data['bot_uname'] = 'Auto-Detect'
        bot_name = context.user_data.get('new_bot_name') or context.user_data.get('bot_name', 'My Bot')

        header = make_header_card("CUSTOM BOT HOSTING", "Step 3 of 3: Source Code Provisioning")
        safe_bot_name = html.escape(bot_name)

        resp_text = (
            f"{header}\n\n"
            f"<blockquote>Target Bot: <b>{safe_bot_name}</b> (<code>Token: Auto-Detect</code>)</blockquote>\n\n"
            "<b>📤 Provide Python Source Code:</b>\n"
            "<blockquote><b>Option 1:</b> Upload your Python script as a <code>.py</code> document.\n"
            "<b>Option 2:</b> Paste your Python code directly in chat.\n\n"
            "🔍 <i>Our engine will automatically extract and validate your bot token from the script.</i></blockquote>\n\n"
            "👇 <i>Send the script file or text, or tap <b>❌ Cancel</b> to abort:</i>"
        )
        await update.message.reply_text(resp_text, reply_markup=get_cancel_keyboard(), parse_mode="HTML")
        return CODE

    token = sanitize_token(text)

    if token == BOT_TOKEN:
        await update.message.reply_text(
            "<blockquote>⚠️ <b>Invalid Token:</b> You cannot host a bot using this platform's own bot token. "
            "Create a new bot with @BotFather and send its token:</blockquote>",
            reply_markup=get_token_input_keyboard(),
            parse_mode="HTML"
        )
        return TOKEN

    is_valid, bot_uname, err_msg = await verify_telegram_token(token)
    if not is_valid:
        await update.message.reply_text(
            f"<blockquote>⚠️ <b>Token Validation Failed:</b>\n{html.escape(err_msg)}\n\n"
            "Please copy and paste a valid Bot Token from @BotFather:</blockquote>",
            reply_markup=get_token_input_keyboard(),
            parse_mode="HTML"
        )
        return TOKEN

    context.user_data['bot_token'] = token
    context.user_data['new_bot_token'] = token
    context.user_data['bot_uname'] = bot_uname
    bot_name = context.user_data.get('new_bot_name') or context.user_data.get('bot_name', 'My Bot')

    header = make_header_card("CUSTOM BOT HOSTING", "Step 3 of 3: Source Code Provisioning")
    safe_bot_name = html.escape(bot_name)
    safe_bot_uname = html.escape(bot_uname)

    resp_text = (
        f"{header}\n\n"
        f"<blockquote>Target Bot: <b>{safe_bot_name}</b> (<code>@{safe_bot_uname}</code>)</blockquote>\n\n"
        "<b>📤 Provide Python Source Code:</b>\n"
        "<blockquote><b>Option 1:</b> Upload your Python script as a <code>.py</code> document.\n"
        "<b>Option 2:</b> Paste your Python code directly in chat.</blockquote>\n\n"
        "👇 <i>Send the script file or text, or tap <b>❌ Cancel</b> to abort:</i>"
    )
    await update.message.reply_text(resp_text, reply_markup=get_cancel_keyboard(), parse_mode="HTML")
    return CODE

async def host_bot_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message or (not update.message.text and not update.message.document):
        await update.effective_message.reply_text(
            "<blockquote>⚠️ <b>Invalid Input:</b> Please send either a <code>.py</code> document or paste python code text.</blockquote>",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return CODE

    if update.message.text:
        text = update.message.text.strip()
        if is_cancellation_text(text) or is_menu_navigation_text(text):
            context.user_data.pop('active_flow', None)
            context.user_data.pop('bot_name', None)
            context.user_data.pop('bot_token', None)
            context.user_data.pop('bot_id', None)
            context.user_data.pop('new_bot_name', None)
            context.user_data.pop('new_bot_token', None)
            context.user_data.pop('bot_uname', None)
            if text in ["❌ Cancel", "/cancel", "cancel"] or text.lower() in ["❌ cancel", "/cancel", "cancel"]:
                await update.message.reply_text("❌ Hosting wizard cancelled.", reply_markup=get_main_reply_keyboard(user_id), parse_mode="HTML")
            else:
                await user_text_router(update, context)
            return ConversationHandler.END

    if context.user_data.get('active_flow') != 'host':
        await update.message.reply_text(
            "<blockquote>⚠️ <b>Session Interrupted:</b> Please use /start and try again.</blockquote>",
            reply_markup=get_main_reply_keyboard(user_id),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    code_content = None
    if update.message.document:
        doc = update.message.document
        if not doc.file_name or not doc.file_name.endswith(".py"):
            await update.message.reply_text(
                "<blockquote>⚠️ <b>Invalid File:</b> Please upload a valid Python script ending in <code>.py</code>.</blockquote>",
                reply_markup=get_cancel_keyboard(),
                parse_mode="HTML"
            )
            return CODE
        try:
            file = await doc.get_file()
            file_bytes = await file.download_as_bytearray()
            code_content = file_bytes.decode("utf-8", errors="replace")
        except Exception as e:
            logger.error(f"Error downloading script document: {e}")
            await update.message.reply_text(
                f"<blockquote>⚠️ <b>File Download Error:</b> Could not read uploaded file: {html.escape(str(e))}</blockquote>",
                reply_markup=get_cancel_keyboard(),
                parse_mode="HTML"
            )
            return CODE
    elif update.message.text:
        code_content = update.message.text
    else:
        await update.message.reply_text(
            "<blockquote>⚠️ <b>Invalid Input:</b> Please send either a <code>.py</code> document or paste python code text.</blockquote>",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return CODE

    # Validate Python Syntax via AST
    valid, err_msg, lineno, line_text = validate_python_syntax(code_content)
    if not valid:
        header = make_header_card("SYNTAX ERROR DETECTED", "Code Validation Failed")
        line_info = f"• <b>Line:</b> <code>{lineno}</code>\n" if lineno else ""
        code_snippet = f"\n<b>Error Snippet:</b>\n<pre><code class=\"language-python\">{html.escape(line_text)}</code></pre>" if line_text else ""
        safe_err = html.escape(err_msg or "Syntax error in Python script.")
        err_card = (
            f"{header}\n\n"
            "<blockquote>❌ <b>Your Python script contains a syntax error and cannot be executed:</b></blockquote>\n\n"
            "<b>🔍 Error Diagnostics:</b>\n"
            f"<blockquote>{line_info}"
            f"• <b>Description:</b> <code>{safe_err}</code></blockquote>"
            f"{code_snippet}\n\n"
            "👇 <i>Please fix the syntax error and re-upload your <code>.py</code> file or paste corrected code below:</i>"
        )
        await update.message.reply_text(err_card, reply_markup=get_cancel_keyboard(), parse_mode="HTML")
        return CODE

    user_id = update.effective_user.id
    bot_name = context.user_data.get('new_bot_name') or context.user_data.get('bot_name', 'My Bot')
    token = context.user_data.get('bot_token') or context.user_data.get('new_bot_token', '')

    # Handle AUTO_DETECT token extraction
    if token == 'AUTO_DETECT':
        detected_token = extract_token_from_code(code_content)
        if not detected_token:
            header = make_header_card("NO TOKEN DETECTED", "Token Required")
            prompt_text = (
                f"{header}\n\n"
                "<blockquote>⚠️ <b>Auto-Detection Failed:</b> We could not detect any Telegram bot token in your script.</blockquote>\n\n"
                "<blockquote>Please send your bot API token obtained from @BotFather manually:</blockquote>\n\n"
                "👇 <i>Send your token as text or tap <b>❌ Cancel</b>:</i>"
            )
            await update.message.reply_text(prompt_text, reply_markup=get_cancel_keyboard(), parse_mode="HTML")
            return TOKEN

        if detected_token == BOT_TOKEN:
            await update.message.reply_text(
                "<blockquote>⚠️ <b>Invalid Token Detected:</b> The token found in your script matches this platform's own bot token. "
                "Please use a distinct bot token from @BotFather:</blockquote>",
                reply_markup=get_cancel_keyboard(),
                parse_mode="HTML"
            )
            return CODE

        is_valid, bot_uname, v_err = await verify_telegram_token(detected_token)
        if not is_valid:
            header = make_header_card("TOKEN VALIDATION FAILED", "Auto-Detected Token Error")
            safe_verr = html.escape(v_err or "Telegram rejected token.")
            token_preview = html.escape(detected_token[:10] + "..." if len(detected_token) > 10 else detected_token)
            err_card = (
                f"{header}\n\n"
                f"<blockquote>⚠️ A token was detected in your code (<code>{token_preview}</code>), "
                f"but Telegram validation failed:\n<code>{safe_verr}</code></blockquote>\n\n"
                "👇 <i>Please update your script with a valid token or send the token manually:</i>"
            )
            await update.message.reply_text(err_card, reply_markup=get_cancel_keyboard(), parse_mode="HTML")
            return CODE

        token = detected_token
        context.user_data['bot_token'] = token
        context.user_data['new_bot_token'] = token
        context.user_data['bot_uname'] = bot_uname

    bot_id = str(uuid.uuid4())[:8]
    bot_dir = os.path.join(DATA_DIR, "bots", f"{user_id}_{bot_id}")
    os.makedirs(bot_dir, exist_ok=True)
    script_path = os.path.join(bot_dir, "main.py")

    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code_content)

    database.create_hosted_bot(bot_id, user_id, bot_name, token, script_path)

    status_msg = await update.message.reply_text("⚙️ <i>Provisioning container environment and starting bot...</i>", parse_mode="HTML")
    success, msg = await bot_manager.start_bot(bot_id)

    if success:
        await asyncio.sleep(1.5)
        if not bot_manager.is_running(bot_id):
            success = False
            msg = "Bot process crashed or exited immediately after launch."

    context.user_data.clear()

    if success:
        bot_data = database.get_bot(bot_id) or {}
        token_masked = f"{token[:10]}...{token[-4:]}" if len(token) > 14 else "••••••••"
        created_str = (bot_data.get('created_at') or "N/A")[:19].replace('T', ' ')
        proc = bot_manager.active_processes.get(bot_id)
        pid_str = str(proc.pid) if (proc and proc.returncode is None) else "Active"

        header = make_header_card("BOT INSPECTOR", "Instance Live & Active")
        safe_bot_name = html.escape(bot_name)
        safe_msg = html.escape(msg)

        resp_text = (
            f"{header}\n\n"
            "<blockquote>🎉 <b>Success!</b> Your custom bot has been provisioned and started in an isolated cloud container.</blockquote>\n\n"
            "<b>🤖 Instance Overview:</b>\n"
            f"<blockquote>• <b>Name:</b> <b>{safe_bot_name}</b>\n"
            f"• <b>Bot ID:</b> <code>#{html.escape(bot_id)}</code>\n"
            "• <b>Status:</b> 🟢 <code>RUNNING</code>\n"
            f"• <b>PID:</b> <code>{html.escape(pid_str)}</code>\n"
            "• <b>Uptime:</b> <code>Just started</code></blockquote>\n\n"
            "<b>⚙️ Configuration & Metadata:</b>\n"
            f"<blockquote>• <b>API Token:</b> <code>{html.escape(token_masked)}</code>\n"
            "• <b>Auto-Restart:</b> <code>Enabled (Watchdog Active)</code>\n"
            f"• <b>Created:</b> <code>{html.escape(created_str)}</code></blockquote>\n\n"
            "<blockquote>💡 <i>You can monitor live logs, restart, or manage this bot from the menu below.</i></blockquote>"
        )
        try:
            await status_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(resp_text, reply_markup=get_bot_detail_reply_keyboard(bot_id, "RUNNING"), parse_mode="HTML")
    else:
        header = make_header_card("STARTUP FAILURE", "Instance Error Detected")
        logs = bot_manager.get_logs(bot_id, lines=25)
        if not logs or "No console logs" in logs:
            logs = msg
        safe_logs = html.escape(logs[-3500:])
        safe_bot_name = html.escape(bot_name)
        safe_msg = html.escape(msg)

        resp_text = (
            f"{header}\n\n"
            f"<blockquote>🔴 <b>Startup Failure:</b> Bot <b>{safe_bot_name}</b> (<code>#{html.escape(bot_id)}</code>) failed to start.</blockquote>\n\n"
            "<b>⚠️ Error Summary:</b>\n"
            f"<blockquote>• <b>Reason:</b> <code>{safe_msg}</code>\n"
            "• <b>Status:</b> 🔴 <code>FAILED</code></blockquote>\n\n"
            "<b>📜 Console Traceback / Error Logs:</b>\n"
            f"<pre><code class=\"language-log\">{safe_logs}</code></pre>\n\n"
            "<blockquote>💡 <i>Inspect the error traceback above. You can fix the code and deploy again, or manage this bot below:</i></blockquote>"
        )
        try:
            await status_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(resp_text, reply_markup=get_bot_detail_reply_keyboard(bot_id, "FAILED"), parse_mode="HTML")

    return ConversationHandler.END

async def cancel_host(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    header = make_header_card("DEPLOYMENT CANCELLED", "Hosting Setup Aborted")
    text = (
        f"{header}\n\n"
        "<blockquote>❌ Bot hosting wizard cancelled. No resources were provisioned.</blockquote>"
    )
    if update.callback_query:
        await update.callback_query.answer("Action cancelled.")
    await update.effective_message.reply_text(text, reply_markup=get_main_reply_keyboard(user_id), parse_mode="HTML")
    return ConversationHandler.END

# ---------------------------------------------------------
# Callback and Text Routers (Backward Compatibility & Fallback)
# ---------------------------------------------------------

async def user_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, data_override: str = None):
    query = update.callback_query
    if not query:
        return
    user_id = query.from_user.id
    data = data_override if data_override is not None else query.data

    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        await query.answer("🚫 Account Suspended", show_alert=True)
        return

    if data == "verify_fsub":
        await verify_fsub_callback(update, context)
        return

    is_sub, unjoined = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        if data_override is None:
            await query.answer()
        await send_force_sub_prompt(update, context, unjoined)
        return

    if data_override is None:
        await query.answer()

    if data in ["user_menu", "user_start"]:
        await start_command(update, context)
    elif data == "user_account":
        await show_account_info(update, context)
    elif data == "user_help":
        await show_help(update, context)
    elif data.startswith("user_my_bots_"):
        page = int(data.split("_")[3])
        await show_my_bots(update, context, page=page)
    elif data.startswith("user_bot_view_"):
        bot_id = data.split("_")[3]
        await show_bot_details(update, context, bot_id)
    elif data.startswith("ubot_act_"):
        parts = data.split("_")
        action = parts[2]
        bot_id = parts[3]
        await handle_bot_action(update, context, action, bot_id)
    elif data.startswith("ubot_logs_"):
        bot_id = data.split("_")[2]
        await handle_bot_action(update, context, "logs", bot_id)
    elif data.startswith("ubot_del_confirm_"):
        bot_id = data.split("_")[3]
        await handle_bot_action(update, context, "delete_confirm", bot_id)
    elif data.startswith("ubot_del_execute_"):
        bot_id = data.split("_")[3]
        await handle_bot_action(update, context, "delete_execute", bot_id)
    elif data == "user_templates":
        await show_templates_menu(update, context)

async def user_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or not update.message.text:
        return False
    text = update.message.text.strip()
    user_id = update.effective_user.id

    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        msg = (
            f"{make_header_card('ACCOUNT SUSPENDED', 'Access Denied')}\n\n"
            "<blockquote>🚫 <b>Access Restricted:</b> Your account has been suspended.</blockquote>"
        )
        await update.message.reply_text(msg, parse_mode="HTML")
        return True

    # Back / Home navigation
    if text in ["🏠 Main Menu", "🔙 Back to Main Menu", "🔄 Refresh", "/start", "/menu"]:
        await start_command(update, context)
        return True

    # My Bots & Back to My Bots
    if text in ["🤖 My Hosted Bots", "🔙 Back to My Bots", "/mybots", "/bots"]:
        await show_my_bots(update, context, page=0)
        return True

    # Host New Bot
    if text in ["➕ Host New Bot", "➕ Host Custom Bot", "➕ Host Another Bot"]:
        await host_bot_start(update, context)
        return True

    # Pagination
    if text == "⬅️ Prev Bots":
        page = max(0, context.user_data.get('bots_page', 0) - 1)
        await show_my_bots(update, context, page=page)
        return True
    if text == "Next Bots ➡️":
        page = context.user_data.get('bots_page', 0) + 1
        await show_my_bots(update, context, page=page)
        return True

    # Quick Template Deploy
    if text in ["⚡ Quick Template Deploy", "/templates"]:
        await show_templates_menu(update, context)
        return True

    # Account & Slots
    if text in ["📊 My Account & Slots", "/account"]:
        await show_account_info(update, context)
        return True

    # Help & Guidelines
    if text in ["❓ Help & Guidelines", "/help"]:
        await show_help(update, context)
        return True

    # Bot Item Selection: e.g. "🟢 My Bot [#a1b2c3d4]"
    bot_select_match = re.search(r"\[#([a-zA-Z0-9_-]+)\]$", text)
    if bot_select_match and not any(k in text for k in ["Start", "Stop", "Restart", "Logs", "Delete"]):
        bot_id = bot_select_match.group(1)
        await show_bot_details(update, context, bot_id)
        return True

    # Bot Actions from keyboard buttons
    if bot_select_match:
        bot_id = bot_select_match.group(1)
        if "▶️ Start Bot" in text:
            await handle_bot_action(update, context, "start", bot_id)
            return True
        elif "⏹️ Stop Bot" in text:
            await handle_bot_action(update, context, "stop", bot_id)
            return True
        elif "🔄 Restart Bot" in text:
            await handle_bot_action(update, context, "restart", bot_id)
            return True
        elif "📜 View Logs" in text:
            await handle_bot_action(update, context, "logs", bot_id)
            return True
        elif "⚠️ Confirm Delete" in text:
            await handle_bot_action(update, context, "delete_execute", bot_id)
            return True
        elif "❌ Cancel Delete" in text:
            await handle_bot_action(update, context, "cancel_delete", bot_id)
            return True
        elif "🗑️ Delete Bot" in text:
            await handle_bot_action(update, context, "delete_confirm", bot_id)
            return True

    return False
