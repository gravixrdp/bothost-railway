import os
import uuid
import shutil
import re
import logging
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID, DATA_DIR, BOT_TOKEN
import database
from bot_manager import bot_manager
from templates import TEMPLATES

logger = logging.getLogger("GravixHost.User")

NAME, TOKEN, CODE = range(3)
TPL_TOKEN = 10

def sanitize_token(raw_token: str) -> str:
    return raw_token.strip().strip("`").strip("'").strip('"').strip()

async def verify_telegram_token(token: str) -> tuple[bool, str, str]:
    cleaned = sanitize_token(token)
    if not re.match(r"^\d{6,14}:[a-zA-Z0-9_-]{30,45}$", cleaned):
        return False, "", "Invalid token format. Please check and copy the full token from @BotFather."

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

    keyboard.append([InlineKeyboardButton("✅ I Have Joined / Verify", callback_data="verify_fsub")])
    return InlineKeyboardMarkup(keyboard)

async def send_force_sub_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, unjoined_channels: list):
    text = (
        "🔐 **Access Restricted — Mandatory Channel Join**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "To use **Gravix-Host** and host your Telegram bots 24/7, you must join our official channels first.\n\n"
        "📢 **Please join the channel(s) below:**\n"
        "Click each button below to join the channel, then tap the **Verify** button to activate your account."
    )
    keyboard = get_force_sub_keyboard(unjoined_channels)
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        except Exception:
            await update.callback_query.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

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

# ---------------------------------------------------------
# Screen Handlers
# ---------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = database.get_or_create_user(user.id, user.username or "", user.first_name or "")

    if db_user['is_banned']:
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
        else:
            await update.message.reply_text("🚫 Your account has been suspended by the administrator.")
        return

    is_sub, unjoined = await check_user_subscription(context.bot, user.id)
    if not is_sub:
        await send_force_sub_prompt(update, context, unjoined)
        return

    maint = database.get_setting("maintenance_mode", "0") == "1"
    maint_notice = "\n⚠️ *Maintenance mode is currently active.*" if (maint and user.id != ADMIN_ID) else ""

    text = (
        f"🚀 **Welcome to Gravix-Host**, {user.first_name}!\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Your all-in-one 24/7 Telegram Bot Cloud Hosting platform.\n\n"
        "✨ **What you can do:**\n"
        "• Host custom Python Telegram bots in isolated environments\n"
        "• 1-Click deploy ready-made bot templates\n"
        "• Real-time log viewer, uptime monitoring & auto-restart\n"
        "• Complete control with start, stop, restart & delete options\n"
        f"{maint_notice}\n"
        "Choose an action from the keyboard menu below to get started:"
    )

    reply_kb = get_main_reply_keyboard(user.id)
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass
        await update.callback_query.message.reply_text(text, reply_markup=reply_kb, parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_kb, parse_mode="Markdown")

async def show_my_bots(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    user = update.effective_user
    user_id = user.id
    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
        else:
            await update.message.reply_text("🚫 Your account has been suspended.")
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
        text = (
            "🤖 **My Hosted Bots**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "You haven't hosted any bots yet!\n\n"
            "Deploy a custom script or a 1-click template to get started:"
        )
        keyboard = ReplyKeyboardMarkup([
            [KeyboardButton("➕ Host New Bot"), KeyboardButton("⚡ Quick Template Deploy")],
            [KeyboardButton("🔙 Back to Main Menu")]
        ], resize_keyboard=True)
        if update.callback_query:
            await update.callback_query.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return

    text = (
        f"🤖 **My Hosted Bots** (Page {page + 1}/{total_pages})\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select a bot from the keyboard menu below to view details, restart, or check logs:\n"
    )
    for b in curr_bots:
        status_emoji = "🟢" if b['status'] == "RUNNING" else ("🔴" if b['status'] in ["FAILED", "CRASHED"] else "⚪")
        text += f"\n• {status_emoji} **{b['bot_name']}** (`#{b['bot_id']}`)\n  Status: `{b['status']}`"

    keyboard = get_my_bots_reply_keyboard(user_bots, page=page)
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

async def show_bot_details(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id: str = None):
    user = update.effective_user
    user_id = user.id
    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
        else:
            await update.message.reply_text("🚫 Your account has been suspended.")
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
    status_emoji = "🟢" if status == "RUNNING" else ("🔴" if status in ["FAILED", "CRASHED"] else "⚪")
    created_str = bot_data['created_at'][:19].replace('T', ' ') if bot_data.get('created_at') else "N/A"
    token_masked = f"{bot_data['bot_token'][:10]}...{bot_data['bot_token'][-4:]}" if len(bot_data['bot_token']) > 14 else "••••••••"

    text = (
        f"🤖 **Bot Details: {bot_data['bot_name']}**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 **Status:** {status_emoji} `{status}`\n"
        f"🆔 **Bot ID:** `{bot_data['bot_id']}`\n"
        f"🔑 **Token:** `{token_masked}`\n"
        f"📅 **Created:** `{created_str}`\n"
        f"🔄 **Auto-Restart:** `{'Enabled' if bot_data.get('auto_restart') else 'Disabled'}`\n\n"
        "Use the keyboard menu below to control this bot:"
    )

    keyboard = get_bot_detail_reply_keyboard(bot_id, status)
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

async def handle_bot_action(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str = None, bot_id: str = None):
    user = update.effective_user
    user_id = user.id
    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
        else:
            await update.message.reply_text("🚫 Your account has been suspended.")
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

    if action == "start":
        success, msg = await bot_manager.start_bot(bot_id)
        icon = "🟢" if success else "⚠️"
        await update.effective_message.reply_text(f"{icon} **Start Bot Result:** {msg}", parse_mode="Markdown")
        await show_bot_details(update, context, bot_id)

    elif action == "stop":
        success, msg = await bot_manager.stop_bot(bot_id)
        icon = "⏹️" if success else "⚠️"
        await update.effective_message.reply_text(f"{icon} **Stop Bot Result:** {msg}", parse_mode="Markdown")
        await show_bot_details(update, context, bot_id)

    elif action == "restart":
        success, msg = await bot_manager.restart_bot(bot_id)
        icon = "🔄" if success else "⚠️"
        await update.effective_message.reply_text(f"{icon} **Restart Bot Result:** {msg}", parse_mode="Markdown")
        await show_bot_details(update, context, bot_id)

    elif action == "logs":
        logs = bot_manager.get_logs(bot_id, lines=25)
        if not logs.strip():
            logs = "No console logs recorded yet for this bot instance."
        text = f"📜 **Live Console Logs (`{bot_id}`):**\n\n```\n{logs[-3500:]}\n```"
        status = bot_data['status']
        await update.effective_message.reply_text(
            text,
            reply_markup=get_bot_detail_reply_keyboard(bot_id, status),
            parse_mode="Markdown"
        )

    elif action == "delete_confirm":
        text = (
            f"⚠️ **Confirm Bot Deletion: {bot_data['bot_name']}**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Are you sure you want to permanently delete bot `#{bot_id}` and all its files?\n\n"
            "⛔ *This action cannot be undone.*"
        )
        await update.effective_message.reply_text(
            text,
            reply_markup=get_delete_confirm_keyboard(bot_id),
            parse_mode="Markdown"
        )

    elif action == "delete_execute":
        await bot_manager.stop_bot(bot_id)
        script_dir = os.path.dirname(bot_data['script_path'])
        if os.path.exists(script_dir):
            shutil.rmtree(script_dir, ignore_errors=True)
        database.delete_bot_record(bot_id)
        await update.effective_message.reply_text(f"🗑️ Bot `{bot_data['bot_name']}` (`#{bot_id}`) was successfully deleted.")
        await show_my_bots(update, context, page=0)

    elif action == "cancel_delete":
        await update.effective_message.reply_text("❌ Deletion cancelled.")
        await show_bot_details(update, context, bot_id)

async def show_account_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
        else:
            await update.message.reply_text("🚫 Your account has been suspended.")
        return

    is_sub, unjoined = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        await send_force_sub_prompt(update, context, unjoined)
        return

    user_bots = database.get_user_bots(user_id)
    max_slots = db_user.get('max_slots', 3)
    running_cnt = sum(1 for b in user_bots if b['status'] == 'RUNNING')

    text = (
        "📊 **My Account & Resource Quota**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **User ID:** `{user_id}`\n"
        f"🏷️ **Username:** @{user.username or 'N/A'}\n"
        f"📦 **Total Slots:** `{max_slots}`\n"
        f"🤖 **Hosted Bots:** `{len(user_bots)} / {max_slots}`\n"
        f"🟢 **Active Bots:** `{running_cnt}`\n"
        f"⚪ **Available Slots:** `{max(0, max_slots - len(user_bots))}`\n\n"
        "💡 Need extra bot slots? Contact the platform administrator."
    )
    reply_kb = get_back_to_main_keyboard()
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_kb, parse_mode="Markdown")

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
        else:
            await update.message.reply_text("🚫 Your account has been suspended.")
        return

    is_sub, unjoined = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        await send_force_sub_prompt(update, context, unjoined)
        return

    text = (
        "❓ **Gravix-Host Guidelines & Help**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ **Get a Bot Token:**\n"
        "   • Open @BotFather on Telegram.\n"
        "   • Send `/newbot` and follow instructions to get your API Token.\n\n"
        "2️⃣ **How to Host a Bot:**\n"
        "   • Tap **➕ Host New Bot** or **⚡ Quick Template Deploy** in the keyboard menu.\n"
        "   • Enter your Bot Token from @BotFather.\n"
        "   • Upload your Python `.py` script or select a pre-built template.\n\n"
        "3️⃣ **Supported Python Libraries:**\n"
        "   • `python-telegram-bot`, `telebot (pyTelegramBotAPI)`, `aiogram`, `requests`, `aiohttp`, `httpx`.\n\n"
        "4️⃣ **Managing Bots:**\n"
        "   • Access logs, restart, and monitor status in **🤖 My Hosted Bots**."
    )
    reply_kb = get_back_to_main_keyboard()
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_kb, parse_mode="Markdown")

async def show_templates_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
        else:
            await update.message.reply_text("🚫 Your account has been suspended.")
        return

    is_sub, unjoined = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        await send_force_sub_prompt(update, context, unjoined)
        return

    maint = database.get_setting("maintenance_mode", "0") == "1"
    if maint and user_id != ADMIN_ID:
        msg = "⚠️ Platform is under maintenance. New bot deployments are paused."
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        else:
            await update.message.reply_text(msg, reply_markup=get_main_reply_keyboard(user_id))
        return

    text = (
        "⚡ **Quick 1-Click Bot Templates**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select a pre-built bot template from the keyboard menu below to deploy instantly:\n"
    )
    for key, tinfo in TEMPLATES.items():
        text += f"\n• **{tinfo['name']}**\n  _{tinfo['description']}_\n"

    keyboard = get_templates_reply_keyboard()
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

# ---------------------------------------------------------
# Quick Template Deployment Conversation Flow
# ---------------------------------------------------------

async def template_select_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
        else:
            await update.message.reply_text("🚫 Your account has been suspended.")
        return ConversationHandler.END

    is_sub, unjoined = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        if update.callback_query:
            await update.callback_query.answer()
        await send_force_sub_prompt(update, context, unjoined)
        return ConversationHandler.END

    maint = database.get_setting("maintenance_mode", "0") == "1"
    if maint and user_id != ADMIN_ID:
        msg = "⚠️ Platform is under maintenance. New bot deployments are paused."
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        else:
            await update.message.reply_text(msg, reply_markup=get_main_reply_keyboard(user_id))
        return ConversationHandler.END

    user_bots = database.get_user_bots(user_id)
    max_slots = db_user.get('max_slots', 3)
    if len(user_bots) >= max_slots:
        msg = f"⚠️ Slot Limit Reached ({len(user_bots)}/{max_slots} bots)."
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        else:
            await update.message.reply_text(msg, reply_markup=get_main_reply_keyboard(user_id))
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
            "⚠️ Template not recognized. Please choose a valid template from the menu below:",
            reply_markup=get_templates_reply_keyboard()
        )
        return ConversationHandler.END

    context.user_data['deploy_template_key'] = tpl_key
    context.user_data['active_flow'] = 'tpl'
    tinfo = TEMPLATES[tpl_key]

    text = (
        f"⚡ **Deploy: {tinfo['name']}**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"ℹ️ {tinfo['description']}\n\n"
        "Please send your **Telegram Bot Token** from @BotFather:\n"
        "*(Example: `1234567890:AAH_sampleToken...`)*\n\n"
        "Send token as text or tap **❌ Cancel** below to abort."
    )
    cancel_kb = get_cancel_keyboard()
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=cancel_kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=cancel_kb, parse_mode="Markdown")
    return TPL_TOKEN

async def template_token_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('active_flow') != 'tpl':
        await update.message.reply_text(
            "⚠️ This template session expired. Please open ⚡ Quick Template Deploy again from /start.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id)
        )
        return ConversationHandler.END

    user_id = update.effective_user.id
    raw_token = update.message.text.strip()
    token = sanitize_token(raw_token)
    tpl_key = context.user_data.get('deploy_template_key', 'echo_bot')
    tinfo = TEMPLATES.get(tpl_key, TEMPLATES['echo_bot'])

    if token == BOT_TOKEN:
        await update.message.reply_text(
            "⚠️ You cannot host a bot using this platform's own token. Create a new bot with @BotFather and send its token:",
            reply_markup=get_cancel_keyboard()
        )
        return TPL_TOKEN

    is_valid, bot_uname, err_msg = await verify_telegram_token(token)
    if not is_valid:
        await update.message.reply_text(
            f"⚠️ {err_msg}\n\nPlease enter a valid Bot Token from @BotFather:",
            reply_markup=get_cancel_keyboard()
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
    status_msg = await update.message.reply_text("⚙️ Provisioning template and launching bot instance...")

    success, msg = await bot_manager.start_bot(bot_id)
    context.user_data.clear()

    status_icon = "🟢 RUNNING" if success else "🔴 FAILED TO START"
    resp_text = (
        f"🎉 **Template Bot Successfully Launched!**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 **Bot Name:** `{bot_name}`\n"
        f"🆔 **Bot ID:** `{bot_id}`\n"
        f"📊 **Status:** {status_icon}\n"
        f"ℹ️ **Details:** {msg}\n\n"
        "Your bot is now live and running 24/7 on Gravix-Host."
    )
    bot_status = "RUNNING" if success else "FAILED"
    await status_msg.reply_text(resp_text, reply_markup=get_bot_detail_reply_keyboard(bot_id, bot_status), parse_mode="Markdown")
    return ConversationHandler.END

async def cancel_tpl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    if update.callback_query:
        await update.callback_query.answer("Template deployment cancelled.")
    await update.effective_message.reply_text("❌ Template deployment cancelled.", reply_markup=get_main_reply_keyboard(user_id))
    return ConversationHandler.END

# ---------------------------------------------------------
# Custom Bot Hosting Conversation Flow
# ---------------------------------------------------------

async def host_bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
        else:
            await update.message.reply_text("🚫 Your account has been suspended by the administrator.")
        return ConversationHandler.END

    is_sub, unjoined = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        if update.callback_query:
            await update.callback_query.answer()
        await send_force_sub_prompt(update, context, unjoined)
        return ConversationHandler.END

    maint = database.get_setting("maintenance_mode", "0") == "1"
    if maint and user_id != ADMIN_ID:
        msg = "⚠️ Platform is under maintenance. New bot deployments are paused."
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        else:
            await update.message.reply_text(msg, reply_markup=get_main_reply_keyboard(user_id))
        return ConversationHandler.END

    user_bots = database.get_user_bots(user_id)
    max_slots = db_user.get('max_slots', 3)
    if len(user_bots) >= max_slots:
        msg = f"⚠️ Slot Limit Reached ({len(user_bots)}/{max_slots} bots). Please delete an existing bot or contact Admin."
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        else:
            await update.message.reply_text(msg, reply_markup=get_main_reply_keyboard(user_id))
        return ConversationHandler.END

    if update.callback_query:
        await update.callback_query.answer()

    context.user_data['active_flow'] = 'host'
    text = (
        "➕ **Host a New Bot (Step 1/3)**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Please enter a **Name** for your bot (e.g. `My Store Bot` or `Music Downloader`):\n\n"
        "*(Tap ❌ Cancel below or send /cancel to abort)*"
    )
    cancel_kb = get_cancel_keyboard()
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=cancel_kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=cancel_kb, parse_mode="Markdown")
    return NAME

async def host_bot_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('active_flow') != 'host':
        await update.message.reply_text(
            "⚠️ This step was interrupted by another action. Please use /start and try again.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id)
        )
        return ConversationHandler.END

    bot_name = update.message.text.strip()
    if len(bot_name) < 2 or len(bot_name) > 30:
        await update.message.reply_text("⚠️ Name must be between 2 and 30 characters. Please enter a valid name:", reply_markup=get_cancel_keyboard())
        return NAME

    context.user_data['new_bot_name'] = bot_name
    text = (
        f"➕ **Host: {bot_name} (Step 2/3)**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Now send your **Telegram Bot Token** from @BotFather:\n"
        "(Example: `1234567890:AAH_sampleToken...`)\n\n"
        "*(Tap ❌ Cancel below or send /cancel to abort)*"
    )
    await update.message.reply_text(text, reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
    return TOKEN

async def host_bot_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('active_flow') != 'host':
        await update.message.reply_text(
            "⚠️ This step was interrupted by another action. Please resend your bot token to continue.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id)
        )
        return ConversationHandler.END

    raw_token = update.message.text.strip()
    token = sanitize_token(raw_token)

    if token == BOT_TOKEN:
        await update.message.reply_text(
            "⚠️ You cannot host a bot using this platform's own token. Create a new bot with @BotFather and send its token:",
            reply_markup=get_cancel_keyboard()
        )
        return TOKEN

    is_valid, bot_uname, err_msg = await verify_telegram_token(token)
    if not is_valid:
        await update.message.reply_text(f"⚠️ {err_msg}\n\nPlease enter a valid Bot Token from @BotFather:", reply_markup=get_cancel_keyboard())
        return TOKEN

    context.user_data['new_bot_token'] = token
    context.user_data['bot_uname'] = bot_uname

    text = (
        "➕ **Upload Bot Code (Step 3/3)**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "How would you like to provide your bot code?\n\n"
        "1. **Upload a `.py` file** (Send the Python script as a document)\n"
        "2. **Paste Python code directly** in chat\n"
        "3. Or tap **❌ Cancel** below to abort."
    )
    await update.message.reply_text(text, reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
    return CODE

async def host_bot_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('active_flow') != 'host':
        await update.message.reply_text(
            "⚠️ This step was interrupted by another action. Please use /start and try again.",
            reply_markup=get_main_reply_keyboard(update.effective_user.id)
        )
        return ConversationHandler.END

    user_id = update.effective_user.id
    bot_name = context.user_data.get('new_bot_name', 'My Bot')
    bot_token = context.user_data.get('new_bot_token', '')

    bot_id = str(uuid.uuid4())[:8]
    bot_dir = os.path.join(DATA_DIR, "bots", f"{user_id}_{bot_id}")
    os.makedirs(bot_dir, exist_ok=True)
    script_path = os.path.join(bot_dir, "main.py")

    if update.message.document:
        doc = update.message.document
        if not doc.file_name.endswith(".py"):
            await update.message.reply_text("⚠️ Please upload a valid `.py` Python script.", reply_markup=get_cancel_keyboard())
            return CODE
        file = await doc.get_file()
        await file.download_to_drive(custom_path=script_path)
    elif update.message.text:
        code_content = update.message.text
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code_content)
    else:
        await update.message.reply_text("⚠️ Please send either a `.py` document or python code text.", reply_markup=get_cancel_keyboard())
        return CODE

    database.create_hosted_bot(bot_id, user_id, bot_name, bot_token, script_path)

    status_msg = await update.message.reply_text("⚙️ Provisioning environment and starting bot...")
    success, msg = await bot_manager.start_bot(bot_id)
    context.user_data.clear()

    status_icon = "🟢 RUNNING" if success else "🔴 FAILED TO START"
    resp_text = (
        f"🎉 **Bot Successfully Hosted!**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 **Bot Name:** `{bot_name}`\n"
        f"🆔 **Bot ID:** `{bot_id}`\n"
        f"📊 **Status:** {status_icon}\n"
        f"ℹ️ **Message:** {msg}\n\n"
        "You can manage your bot, view real-time logs, or restart it in the **My Hosted Bots** menu."
    )
    bot_status = "RUNNING" if success else "FAILED"
    await status_msg.reply_text(resp_text, reply_markup=get_bot_detail_reply_keyboard(bot_id, bot_status), parse_mode="Markdown")
    return ConversationHandler.END

async def cancel_host(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    if update.callback_query:
        await update.callback_query.answer("Action cancelled.")
    await update.effective_message.reply_text("❌ Bot hosting process cancelled.", reply_markup=get_main_reply_keyboard(user_id))
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

async def user_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    user_id = update.effective_user.id

    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        await update.message.reply_text("🚫 Your account has been suspended.")
        return

    # Back / Home navigation
    if text in ["🏠 Main Menu", "🔙 Back to Main Menu", "🔄 Refresh"]:
        await start_command(update, context)
        return

    # My Bots & Back to My Bots
    if text in ["🤖 My Hosted Bots", "🔙 Back to My Bots"]:
        await show_my_bots(update, context, page=0)
        return

    # Pagination
    if text == "⬅️ Prev Bots":
        page = max(0, context.user_data.get('bots_page', 0) - 1)
        await show_my_bots(update, context, page=page)
        return
    if text == "Next Bots ➡️":
        page = context.user_data.get('bots_page', 0) + 1
        await show_my_bots(update, context, page=page)
        return

    # Quick Template Deploy
    if text == "⚡ Quick Template Deploy":
        await show_templates_menu(update, context)
        return

    # Account & Slots
    if text == "📊 My Account & Slots":
        await show_account_info(update, context)
        return

    # Help & Guidelines
    if text == "❓ Help & Guidelines":
        await show_help(update, context)
        return

    # Bot Item Selection: e.g. "🟢 My Bot [#a1b2c3d4]"
    bot_select_match = re.search(r"\[#([a-zA-Z0-9_-]+)\]$", text)
    if bot_select_match and not any(k in text for k in ["Start", "Stop", "Restart", "Logs", "Delete"]):
        bot_id = bot_select_match.group(1)
        await show_bot_details(update, context, bot_id)
        return

    # Bot Actions from keyboard buttons
    if bot_select_match:
        bot_id = bot_select_match.group(1)
        if "▶️ Start Bot" in text:
            await handle_bot_action(update, context, "start", bot_id)
            return
        elif "⏹️ Stop Bot" in text:
            await handle_bot_action(update, context, "stop", bot_id)
            return
        elif "🔄 Restart Bot" in text:
            await handle_bot_action(update, context, "restart", bot_id)
            return
        elif "📜 View Logs" in text:
            await handle_bot_action(update, context, "logs", bot_id)
            return
        elif "⚠️ Confirm Delete" in text:
            await handle_bot_action(update, context, "delete_execute", bot_id)
            return
        elif "❌ Cancel Delete" in text:
            await handle_bot_action(update, context, "cancel_delete", bot_id)
            return
        elif "🗑️ Delete Bot" in text:
            await handle_bot_action(update, context, "delete_confirm", bot_id)
            return

    # Fallback response
    await update.message.reply_text(
        "💡 Please select an option from the keyboard menu below, or use /start.",
        reply_markup=get_main_reply_keyboard(user_id)
    )


