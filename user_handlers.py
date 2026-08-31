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

def get_main_reply_keyboard(user_id: int):
    keyboard = []
    if user_id == ADMIN_ID:
        keyboard.append([KeyboardButton("👑 Open Admin Panel")])
    keyboard.extend([
        [KeyboardButton("➕ Host New Bot"), KeyboardButton("🤖 My Hosted Bots")],
        [KeyboardButton("⚡ Quick Template Deploy"), KeyboardButton("📊 My Account & Slots")],
        [KeyboardButton("❓ Help & Guidelines"), KeyboardButton("🔄 Refresh")]
    ])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_main_menu_keyboard(user_id: int):
    keyboard = [
        [
            InlineKeyboardButton("➕ Host New Bot", callback_data="user_host_start"),
            InlineKeyboardButton("🤖 My Hosted Bots", callback_data="user_my_bots_0")
        ],
        [
            InlineKeyboardButton("⚡ Quick Template Deploy", callback_data="user_templates"),
            InlineKeyboardButton("📊 My Account & Slots", callback_data="user_account")
        ],
        [
            InlineKeyboardButton("❓ Help & Guidelines", callback_data="user_help"),
            InlineKeyboardButton("🔄 Refresh", callback_data="user_menu")
        ]
    ]
    if user_id == ADMIN_ID:
        keyboard.insert(0, [InlineKeyboardButton("👑 Open Admin Panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = database.get_or_create_user(user.id, user.username or "", user.first_name or "")

    if db_user['is_banned']:
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
        else:
            await update.message.reply_text("🚫 Your account has been suspended by the administrator.")
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
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, reply_markup=reply_kb, parse_mode="Markdown")
    else:
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

    user_bots = database.get_user_bots(user_id)
    per_page = 5
    total_pages = max(1, (len(user_bots) + per_page - 1) // per_page)
    curr_bots = user_bots[page * per_page : (page + 1) * per_page]

    if not user_bots:
        text = (
            "🤖 **My Hosted Bots**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "You haven't hosted any bots yet!\n\n"
            "Deploy a custom script or a 1-click template to get started:"
        )
        keyboard = [
            [
                InlineKeyboardButton("➕ Host Custom Bot", callback_data="user_host_start"),
                InlineKeyboardButton("⚡ Quick Template", callback_data="user_templates")
            ]
        ]
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    text = f"🤖 **My Hosted Bots** (Page {page + 1}/{total_pages})\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    for b in curr_bots:
        status_emoji = "🟢" if b['status'] == "RUNNING" else ("🔴" if b['status'] in ["FAILED", "CRASHED"] else "⚪")
        keyboard.append([InlineKeyboardButton(f"{status_emoji} {b['bot_name']}", callback_data=f"user_bot_view_{b['bot_id']}")])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"user_my_bots_{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"user_my_bots_{page + 1}"))
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("➕ Host Another Bot", callback_data="user_host_start")])

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

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
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

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

    text = (
        "❓ **Gravix-Host Guidelines & Help**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ **Get a Bot Token:**\n"
        "   • Open @BotFather on Telegram.\n"
        "   • Send `/newbot` and follow instructions to get your API Token.\n\n"
        "2️⃣ **How to Host a Bot:**\n"
        "   • Click **➕ Host New Bot** or **⚡ Quick Template Deploy** in the keyboard menu.\n"
        "   • Enter your Bot Token from @BotFather.\n"
        "   • Upload your Python `.py` script or select a pre-built template.\n\n"
        "3️⃣ **Supported Python Libraries:**\n"
        "   • `python-telegram-bot`, `telebot (pyTelegramBotAPI)`, `aiogram`, `requests`, `aiohttp`, `httpx`.\n\n"
        "4️⃣ **Managing Bots:**\n"
        "   • Access logs, restart, and monitor status in **🤖 My Hosted Bots**."
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

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

    maint = database.get_setting("maintenance_mode", "0") == "1"
    if maint and user_id != ADMIN_ID:
        msg = "⚠️ Platform is under maintenance. New bot deployments are paused."
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        else:
            await update.message.reply_text(msg)
        return

    text = (
        "⚡ **Quick 1-Click Bot Templates**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select a pre-built bot template below to instantly deploy:\n"
    )
    keyboard = []
    for key, tinfo in TEMPLATES.items():
        keyboard.append([InlineKeyboardButton(tinfo['name'], callback_data=f"deploy_tpl_{key}")])

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def user_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, data_override: str = None):
    query = update.callback_query
    user_id = query.from_user.id
    data = data_override if data_override is not None else query.data

    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        await query.answer("🚫 Account Suspended", show_alert=True)
        return

    if data_override is None:
        await query.answer()

    if data == "user_menu":
        await start_command(update, context)
        return

    elif data == "user_account":
        await show_account_info(update, context)
        return

    elif data == "user_help":
        await show_help(update, context)
        return

    elif data.startswith("user_my_bots_"):
        page = int(data.split("_")[3])
        await show_my_bots(update, context, page=page)
        return

    elif data.startswith("user_bot_view_"):
        bot_id = data.split("_")[3]
        bot_data = database.get_bot(bot_id)
        if not bot_data or (bot_data['user_id'] != user_id and user_id != ADMIN_ID):
            await query.answer("Bot not found or unauthorized!", show_alert=True)
            return

        status_emoji = "🟢" if bot_data['status'] == "RUNNING" else ("🔴" if bot_data['status'] in ["FAILED", "CRASHED"] else "⚪")
        created_str = bot_data['created_at'][:19].replace('T', ' ') if bot_data.get('created_at') else "N/A"
        text = (
            f"🤖 **Bot Details: {bot_data['bot_name']}**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 **Status:** {status_emoji} `{bot_data['status']}`\n"
            f"🆔 **Bot ID:** `{bot_data['bot_id']}`\n"
            f"🔑 **Token:** `{bot_data['bot_token'][:10]}...{bot_data['bot_token'][-4:]}`\n"
            f"📅 **Created:** `{created_str}`\n"
            f"🔄 **Auto-Restart:** `{'Enabled' if bot_data.get('auto_restart') else 'Disabled'}`\n"
        )

        controls = []
        if bot_data['status'] == 'RUNNING':
            controls.append(InlineKeyboardButton("⏹️ Stop Bot", callback_data=f"ubot_act_stop_{bot_id}"))
            controls.append(InlineKeyboardButton("🔄 Restart Bot", callback_data=f"ubot_act_restart_{bot_id}"))
        else:
            controls.append(InlineKeyboardButton("▶️ Start Bot", callback_data=f"ubot_act_start_{bot_id}"))

        keyboard = [
            controls,
            [
                InlineKeyboardButton("📜 View Logs", callback_data=f"ubot_logs_{bot_id}"),
                InlineKeyboardButton("🗑️ Delete Bot", callback_data=f"ubot_del_confirm_{bot_id}")
            ],
            [InlineKeyboardButton("🔙 Back to My Bots", callback_data="user_my_bots_0")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("ubot_act_"):
        parts = data.split("_")
        action = parts[2]
        bot_id = parts[3]
        bot_data = database.get_bot(bot_id)

        if not bot_data or (bot_data['user_id'] != user_id and user_id != ADMIN_ID):
            await query.answer("Unauthorized action.", show_alert=True)
            return

        if action == "start":
            success, msg = await bot_manager.start_bot(bot_id)
            await query.answer(msg, show_alert=True)
        elif action == "stop":
            success, msg = await bot_manager.stop_bot(bot_id)
            await query.answer(msg, show_alert=True)
        elif action == "restart":
            success, msg = await bot_manager.restart_bot(bot_id)
            await query.answer(msg, show_alert=True)

        await user_callback_handler(update, context, data_override=f"user_bot_view_{bot_id}")

    elif data.startswith("ubot_logs_"):
        bot_id = data.split("_")[2]
        logs = bot_manager.get_logs(bot_id, lines=25)
        text = f"📜 **Live Console Logs (`{bot_id}`):**\n\n```\n{logs[-3500:]}\n```"
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh Logs", callback_data=f"ubot_logs_{bot_id}")],
            [InlineKeyboardButton("🔙 Back to Bot", callback_data=f"user_bot_view_{bot_id}")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("ubot_del_confirm_"):
        bot_id = data.split("_")[3]
        text = "⚠️ **Are you sure you want to permanently delete this bot and its files?**"
        keyboard = [
            [
                InlineKeyboardButton("❌ Cancel", callback_data=f"user_bot_view_{bot_id}"),
                InlineKeyboardButton("🗑️ Yes, Delete", callback_data=f"ubot_del_execute_{bot_id}")
            ]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("ubot_del_execute_"):
        bot_id = data.split("_")[3]
        bot_data = database.get_bot(bot_id)
        if bot_data and (bot_data['user_id'] == user_id or user_id == ADMIN_ID):
            await bot_manager.stop_bot(bot_id)
            script_dir = os.path.dirname(bot_data['script_path'])
            if os.path.exists(script_dir):
                shutil.rmtree(script_dir, ignore_errors=True)
            database.delete_bot_record(bot_id)
            await query.answer("Bot deleted successfully.", show_alert=True)

        await user_callback_handler(update, context, data_override="user_my_bots_0")

    elif data == "user_templates":
        text = (
            "⚡ **Quick 1-Click Bot Templates**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Select a pre-built bot template to instantly deploy:\n"
        )
        keyboard = []
        for key, tinfo in TEMPLATES.items():
            keyboard.append([InlineKeyboardButton(tinfo['name'], callback_data=f"deploy_tpl_{key}")])
        keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="user_menu")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# Quick Template Deployment Conversation Flow
async def template_select_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    tpl_key = query.data.split("deploy_tpl_")[1]

    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        await query.answer("🚫 Account Suspended", show_alert=True)
        return ConversationHandler.END

    maint = database.get_setting("maintenance_mode", "0") == "1"
    if maint and user_id != ADMIN_ID:
        await query.answer("⚠️ Platform is under maintenance. New bot deployments are paused.", show_alert=True)
        return ConversationHandler.END

    user_bots = database.get_user_bots(user_id)
    max_slots = db_user.get('max_slots', 3)
    if len(user_bots) >= max_slots:
        await query.answer(f"⚠️ Slot Limit Reached ({len(user_bots)}/{max_slots} bots).", show_alert=True)
        return ConversationHandler.END

    if tpl_key not in TEMPLATES:
        await query.answer("Template not found.", show_alert=True)
        return ConversationHandler.END

    await query.answer()
    context.user_data['deploy_template_key'] = tpl_key
    context.user_data['active_flow'] = 'tpl'
    tinfo = TEMPLATES[tpl_key]

    text = (
        f"⚡ **Deploy: {tinfo['name']}**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"ℹ️ {tinfo['description']}\n\n"
        "Please send your **Telegram Bot Token** from @BotFather:\n"
        "*(Example: `1234567890:AAH_sampleToken...`)*\n\n"
        "Send token as a text message or /cancel to abort."
    )
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_tpl")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return TPL_TOKEN

async def template_token_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('active_flow') != 'tpl':
        await update.message.reply_text("⚠️ This template session expired. Please open ⚡ Quick Template Deploy again from /start.")
        return ConversationHandler.END

    user_id = update.effective_user.id
    raw_token = update.message.text.strip()
    token = sanitize_token(raw_token)
    tpl_key = context.user_data.get('deploy_template_key', 'echo_bot')
    tinfo = TEMPLATES.get(tpl_key, TEMPLATES['echo_bot'])

    if token == BOT_TOKEN:
        await update.message.reply_text("⚠️ You cannot host a bot using this platform's own token. Create a new bot with @BotFather and send its token:")
        return TPL_TOKEN

    is_valid, bot_uname, err_msg = await verify_telegram_token(token)
    if not is_valid:
        await update.message.reply_text(f"⚠️ {err_msg}\n\nPlease enter a valid Bot Token from @BotFather:")
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
    keyboard = [
        [InlineKeyboardButton("📜 View Logs", callback_data=f"ubot_logs_{bot_id}")],
        [InlineKeyboardButton("🤖 My Hosted Bots", callback_data="user_my_bots_0")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="user_menu")]
    ]
    await status_msg.edit_text(resp_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return ConversationHandler.END

async def cancel_tpl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    if update.callback_query:
        await update.callback_query.answer("Template deployment cancelled.")
        await start_command(update, context)
    else:
        await update.message.reply_text("❌ Template deployment cancelled.", reply_markup=get_main_reply_keyboard(user_id))
    return ConversationHandler.END

# Custom Bot Hosting Flow
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

    maint = database.get_setting("maintenance_mode", "0") == "1"
    if maint and user_id != ADMIN_ID:
        if update.callback_query:
            await update.callback_query.answer("⚠️ Platform is under maintenance. New bot deployments are paused.", show_alert=True)
        else:
            await update.message.reply_text("⚠️ Platform is under maintenance. New bot deployments are paused.")
        return ConversationHandler.END

    user_bots = database.get_user_bots(user_id)
    max_slots = db_user.get('max_slots', 3)
    if len(user_bots) >= max_slots:
        msg = f"⚠️ Slot Limit Reached ({len(user_bots)}/{max_slots} bots). Please delete an existing bot or contact Admin."
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        else:
            await update.message.reply_text(msg)
        return ConversationHandler.END

    if update.callback_query:
        await update.callback_query.answer()

    context.user_data['active_flow'] = 'host'
    text = (
        "➕ **Host a New Bot (Step 1/3)**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Please enter a **Name** for your bot (e.g. `My Store Bot` or `Music Downloader`):\n\n"
        "*(Send text or /cancel to abort)*"
    )
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_host")]]
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return NAME

async def host_bot_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('active_flow') != 'host':
        await update.message.reply_text("⚠️ This step was interrupted by another action. Please use /start and try again.")
        return ConversationHandler.END

    bot_name = update.message.text.strip()
    if len(bot_name) < 2 or len(bot_name) > 30:
        await update.message.reply_text("⚠️ Name must be between 2 and 30 characters. Please enter a valid name:")
        return NAME

    context.user_data['new_bot_name'] = bot_name
    text = (
        f"➕ **Host: {bot_name} (Step 2/3)**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Now send your **Telegram Bot Token** from @BotFather:\n"
        "(Example: `1234567890:AAH_sampleToken...`)\n\n"
        "*(Send token or /cancel to abort)*"
    )
    await update.message.reply_text(text, parse_mode="Markdown")
    return TOKEN

async def host_bot_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('active_flow') != 'host':
        await update.message.reply_text("⚠️ This step was interrupted by another action. Please resend your bot token to continue.")
        return ConversationHandler.END

    raw_token = update.message.text.strip()
    token = sanitize_token(raw_token)

    if token == BOT_TOKEN:
        await update.message.reply_text("⚠️ You cannot host a bot using this platform's own token. Create a new bot with @BotFather and send its token:")
        return TOKEN

    is_valid, bot_uname, err_msg = await verify_telegram_token(token)
    if not is_valid:
        await update.message.reply_text(f"⚠️ {err_msg}\n\nPlease enter a valid Bot Token from @BotFather:")
        return TOKEN

    context.user_data['new_bot_token'] = token
    context.user_data['bot_uname'] = bot_uname

    text = (
        "➕ **Upload Bot Code (Step 3/3)**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "How would you like to provide your bot code?\n\n"
        "1. **Upload a `.py` file** (Send the Python script as a document)\n"
        "2. **Paste Python code directly** in chat\n"
        "3. Or type `/cancel` to abort."
    )
    await update.message.reply_text(text, parse_mode="Markdown")
    return CODE

async def host_bot_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('active_flow') != 'host':
        await update.message.reply_text("⚠️ This step was interrupted by another action. Please use /start and try again.")
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
            await update.message.reply_text("⚠️ Please upload a valid `.py` Python script.")
            return CODE
        file = await doc.get_file()
        await file.download_to_drive(custom_path=script_path)
    elif update.message.text:
        code_content = update.message.text
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code_content)
    else:
        await update.message.reply_text("⚠️ Please send either a `.py` document or python code text.")
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
    keyboard = [
        [InlineKeyboardButton("📜 View Logs", callback_data=f"ubot_logs_{bot_id}")],
        [InlineKeyboardButton("🤖 Go to My Bots", callback_data="user_my_bots_0")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="user_menu")]
    ]
    await status_msg.edit_text(resp_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return ConversationHandler.END

async def cancel_host(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    if update.callback_query:
        await update.callback_query.answer("Action cancelled.")
        await start_command(update, context)
    else:
        await update.message.reply_text("❌ Bot hosting process cancelled.", reply_markup=get_main_reply_keyboard(user_id))
    return ConversationHandler.END
