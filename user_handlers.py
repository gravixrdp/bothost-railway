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
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters
)
from config import ADMIN_ID, DATA_DIR, BOT_TOKEN
import database
from bot_manager import bot_manager
from templates import TEMPLATES
from code_analyzer import (
    validate_python_syntax,
    extract_token_from_code,
    extract_bot_token,
    extract_and_validate_zip,
    is_cancellation_text,
    is_menu_navigation_text,
    to_bold_sans,
    from_bold_sans,
    normalize_user_input
)

logger = logging.getLogger("GravixHost.User")

NAME, TOKEN, CODE = range(3)
TPL_TOKEN = 10
U_ENV_CHOICE, U_ENV_ADD_KEY, U_ENV_ADD_VAL, U_ENV_DEL_KEY = range(20, 24)

# ---------------------------------------------------------
# UI & Typography Helpers (Mobile-Friendly Clean Aesthetics)
# ---------------------------------------------------------

def make_header_card(title: str = "GRAVIX-HOST PRO", subtitle: str = "100% Free Forever Cloud Hosting") -> str:
    title = to_bold_sans(title)
    if subtitle:
        subtitle = to_bold_sans(subtitle)
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

async def send_clean_screen(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup=None,
    photo_path: str = None,
    parse_mode: str = "HTML"
):
    """Sends screen with automatic SQLite-backed message tracking and deletes all older messages keeping only 2 messages."""
    user_id = update.effective_user.id if update.effective_user else None
    chat_id = update.effective_chat.id if update.effective_chat else user_id
    if not chat_id:
        return None

    # 1. Track incoming message if present
    if update.effective_message:
        database.record_chat_message(chat_id, update.effective_message.message_id)

    # 2. Send the message or photo
    sent = None
    if photo_path and os.path.exists(photo_path):
        try:
            with open(photo_path, "rb") as pf:
                sent = await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=pf,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
        except Exception as e:
            logger.warning(f"Failed to send photo: {e}")
            sent = await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
    else:
        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )

    # 3. Track sent message
    if sent:
        database.record_chat_message(chat_id, sent.message_id)

    # 4. Immediately delete all older messages keeping max 2
    old_mids = database.get_old_chat_messages(chat_id, keep_count=2)
    for mid in old_mids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass
    if old_mids:
        database.delete_chat_message_records(chat_id, old_mids)

    return sent

# Backward compatibility alias
_send_user_screen = send_clean_screen

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
        cid_str = str(raw_cid).strip()

        # Check if this channel has a verifiable Telegram identifier (@username or numeric ID)
        is_verifiable = False
        target_chat = None

        if cid_str.startswith("-100") or (cid_str.startswith("-") and cid_str[1:].isdigit()):
            is_verifiable = True
            target_chat = int(cid_str)
        elif cid_str.isdigit():
            is_verifiable = True
            target_chat = int(f"-100{cid_str}")
        elif cid_str.startswith("@"):
            is_verifiable = True
            target_chat = cid_str
        elif "t.me/" in cid_str:
            slug = cid_str.split("t.me/")[-1].strip().lstrip("@")
            if not slug.startswith("+") and not slug.startswith("joinchat/") and "/" not in slug and slug:
                is_verifiable = True
                target_chat = f"@{slug}"

        if is_verifiable and target_chat:
            try:
                member = await bot.get_chat_member(chat_id=target_chat, user_id=user_id)
                if member.status in valid_statuses:
                    continue
                else:
                    unjoined.append(ch)
            except Exception as e:
                err_text = str(e).lower()
                logger.info(f"FSub check for user {user_id} in {target_chat}: {e}")
                if "chat not found" in err_text or "bot is not a member" in err_text or "chat_admin_required" in err_text or "not enough rights" in err_text:
                    logger.warning(f"Chat {target_chat} not accessible by bot. Ensure bot is admin in channel.")
                    continue
                else:
                    unjoined.append(ch)
        else:
            # Channel is an invite link (e.g. https://t.me/+...)
            # It is displayed on the join keyboard for users, but cannot be verified via get_chat_member directly
            pass

    return len(unjoined) == 0, unjoined

def get_force_sub_keyboard(unjoined_channels: list = None) -> InlineKeyboardMarkup:
    all_channels = database.get_required_channels() if hasattr(database, "get_required_channels") else []
    if not all_channels:
        all_channels = [
            {"channel_id": "@GravixRDP", "title": "GravixRDP Official", "invite_link": "https://t.me/GravixRDP"},
            {"channel_id": "https://t.me/+lD-MufapiQVhMGFl", "title": "Gravix Updates", "invite_link": "https://t.me/+lD-MufapiQVhMGFl"}
        ]
    channels_to_display = unjoined_channels if (unjoined_channels is not None and len(unjoined_channels) > 0) else all_channels
    keyboard = []
    for ch in channels_to_display:
        title = ch.get("title", "Channel") if isinstance(ch, dict) else ch["title"]
        link = ch.get("invite_link", "") if isinstance(ch, dict) else ch["invite_link"]
        if not link:
            raw_cid = ch.get("channel_id", "") if isinstance(ch, dict) else ch["channel_id"]
            if str(raw_cid).startswith("@"):
                link = f"https://t.me/{str(raw_cid).lstrip('@')}"
            else:
                link = str(raw_cid)
        keyboard.append([InlineKeyboardButton(f"📢 Join {title}", url=link)])

    keyboard.append([InlineKeyboardButton("✅ Verify Membership", callback_data="verify_fsub")])
    return InlineKeyboardMarkup(keyboard)

async def send_force_sub_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, unjoined_channels: list = None):
    all_channels = database.get_required_channels() if hasattr(database, "get_required_channels") else []
    channels_to_display = unjoined_channels if (unjoined_channels is not None and len(unjoined_channels) > 0) else all_channels

    channel_list_text = ""
    for ch in channels_to_display:
        title = ch.get("title", "Channel") if isinstance(ch, dict) else ch["title"]
        channel_list_text += f"• <b>{html.escape(title)}</b>\n"

    text = (
        "<b>🔒 JOIN REQUIRED CHANNELS</b>\n"
        "<i>Quick Verification</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>Please join our official channel(s) to access <b>Gravix-Host</b>:</blockquote>\n\n"
        f"<b>📢 Pending Channels:</b>\n"
        f"<blockquote>{channel_list_text}</blockquote>\n"
        "👇 <i>Join the channel(s) below and tap <b>Verify Membership</b>:</i>"
    )
    keyboard = get_force_sub_keyboard(channels_to_display)
    await send_clean_screen(update, context, text, reply_markup=keyboard)

async def verify_fsub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    is_sub, unjoined = await check_user_subscription(context.bot, user_id)
    if is_sub:
        if hasattr(database, "reward_referral_if_pending"):
            try:
                database.reward_referral_if_pending(user_id, context.bot)
            except Exception as e:
                logger.warning(f"Error rewarding pending referral for user {user_id}: {e}")
        await query.answer("✅ Verification Successful! Welcome to Gravix-Host.", show_alert=True)
        await start_command(update, context)
    else:
        await query.answer("⚠️ Please join all pending channels first!", show_alert=True)
        await send_force_sub_prompt(update, context, unjoined)

# ---------------------------------------------------------
# Dynamic ReplyKeyboardMarkup Generators (100% Persistent Bottom Keyboards)
# Design Pattern: ⇋ 𝗧𝗘𝗫𝗧 ⇋ (No Emojis on Buttons)
# ---------------------------------------------------------

def get_main_reply_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    keyboard = []
    if user_id == ADMIN_ID:
        keyboard.append([KeyboardButton("⇋ 𝗢𝗽𝗲𝗻 𝗔𝗱𝗺𝗶𝗻 𝗣𝗮𝗻𝗲𝗹 ⇋")])
    keyboard.extend([
        [KeyboardButton("⇋ 𝗛𝗼𝘀𝘁 𝗡𝗲𝘄 𝗕𝗼𝘁 ⇋"), KeyboardButton("⇋ 𝗠𝘆 𝗛𝗼𝘀𝘁𝗲𝗱 𝗕𝗼𝘁𝘀 ⇋")],
        [KeyboardButton("⇋ 𝗤𝘂𝗶𝗰𝗸 𝗧𝗲𝗺𝗽𝗹𝗮𝘁𝗲𝘀 ⇋"), KeyboardButton("⇋ 𝗠𝘆 𝗔𝗰𝗰𝗼𝘂𝗻𝘁 & 𝗦𝗹𝗼𝘁𝘀 ⇋")],
        [KeyboardButton("⇋ 𝗥𝗲𝗳𝗲𝗿 & 𝗘𝗮𝗿𝗻 𝗦𝗹𝗼𝘁𝘀 ⇋"), KeyboardButton("⇋ 𝗖𝗵𝗮𝗻𝗻𝗲𝗹 𝗣𝗿𝗼𝗺𝗼𝘁𝗶𝗼𝗻 ⇋")],
        [KeyboardButton("⇋ 𝗖𝘂𝘀𝘁𝗼𝗺𝗲𝗿 𝗦𝘂𝗽𝗽𝗼𝗿𝘁 ⇋"), KeyboardButton("⇋ 𝗛𝗲𝗹𝗽 & 𝗚𝘂𝗶𝗱𝗲𝗹𝗶𝗻𝗲𝘀 ⇋")],
        [KeyboardButton("⇋ 𝗥𝗲𝗳𝗿𝗲𝘀𝗵 ⇋")]
    ])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_my_bots_reply_keyboard(user_bots: list, page: int = 0) -> ReplyKeyboardMarkup:
    per_page = 5
    total_pages = max(1, (len(user_bots) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    curr_bots = user_bots[page * per_page : (page + 1) * per_page]

    keyboard = []
    for b in curr_bots:
        bot_name = b.get('bot_name', 'Unnamed Bot')
        bot_id = b.get('bot_id', '')
        clean_bname = re.sub(r'^[^\w\s]+', '', bot_name).strip()
        keyboard.append([KeyboardButton(f"⇋ {clean_bname} [#{bot_id}] ⇋")])

    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(KeyboardButton("⇋ 𝗣𝗿𝗲𝘃 𝗕𝗼𝘁𝘀 ⇋"))
        if page < total_pages - 1:
            nav_row.append(KeyboardButton("⇋ 𝗡𝗲𝘅𝘁 𝗕𝗼𝘁𝘀 ⇋"))
        if nav_row:
            keyboard.append(nav_row)

    keyboard.append([KeyboardButton("⇋ 𝗛𝗼𝘀𝘁 𝗔𝗻𝗼𝘁𝗵𝗲𝗿 𝗕𝗼𝘁 ⇋"), KeyboardButton("⇋ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂 ⇋")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_bot_detail_reply_keyboard(bot_id: str, status: str) -> ReplyKeyboardMarkup:
    keyboard = []
    if status == 'RUNNING':
        keyboard.append([
            KeyboardButton(f"⇋ 𝗦𝘁𝗼𝗽 𝗕𝗼𝘁 [#{bot_id}] ⇋"),
            KeyboardButton(f"⇋ 𝗥𝗲𝘀𝘁𝗮𝗿𝘁 𝗕𝗼𝘁 [#{bot_id}] ⇋")
        ])
    else:
        keyboard.append([
            KeyboardButton(f"⇋ 𝗦𝘁𝗮𝗿𝘁 𝗕𝗼𝘁 [#{bot_id}] ⇋")
        ])
    keyboard.append([
        KeyboardButton(f"⇋ 𝗩𝗶𝗲𝘄 𝗟𝗼𝗴𝘀 [#{bot_id}] ⇋"),
        KeyboardButton(f"⇋ 𝗗𝗲𝗹𝗲𝘁𝗲 𝗕𝗼𝘁 [#{bot_id}] ⇋")
    ])
    keyboard.append([
        KeyboardButton(f"⇋ 𝗠𝗮𝗻𝗮𝗴𝗲 𝗘𝗻𝘃 𝗩𝗮𝗿𝘀 [#{bot_id}] ⇋"),
        KeyboardButton(f"⇋ 𝗘𝘅𝗽𝗼𝗿𝘁 𝗕𝗮𝗰𝗸𝘂𝗽 [#{bot_id}] ⇋")
    ])
    keyboard.append([
        KeyboardButton("⇋ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝘆 𝗕𝗼𝘁𝘀 ⇋"),
        KeyboardButton("⇋ 𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂 ⇋")
    ])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_env_menu_keyboard(has_vars: bool = False) -> ReplyKeyboardMarkup:
    top_row = [KeyboardButton("⇋ 𝗔𝗱𝗱 𝗩𝗮𝗿𝗶𝗮𝗯𝗹𝗲 ⇋")]
    if has_vars:
        top_row.append(KeyboardButton("⇋ 𝗗𝗲𝗹𝗲𝘁𝗲 𝗩𝗮𝗿𝗶𝗮𝗯𝗹𝗲 ⇋"))
    keyboard = [
        top_row,
        [
            KeyboardButton("⇋ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗕𝗼𝘁 ⇋"),
            KeyboardButton("⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_delete_confirm_keyboard(bot_id: str) -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(f"⇋ 𝗖𝗼𝗻𝗳𝗶𝗿𝗺 𝗗𝗲𝗹𝗲𝘁𝗲 [#{bot_id}] ⇋"),
            KeyboardButton(f"⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 𝗗𝗲𝗹𝗲𝘁𝗲 [#{bot_id}] ⇋")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_templates_reply_keyboard() -> ReplyKeyboardMarkup:
    keyboard = []
    for key, tinfo in TEMPLATES.items():
        raw_name = tinfo.get('name', key)
        clean_name = re.sub(r'^[^\w\s]+', '', raw_name).strip()
        keyboard.append([KeyboardButton(f"⇋ {clean_name} ⇋")])
    keyboard.append([KeyboardButton("⇋ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂 ⇋")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_back_to_main_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton("⇋ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂 ⇋")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton("⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_token_input_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("⇋ 𝗦𝗸𝗶𝗽 (𝗔𝘂𝘁𝗼-𝗗𝗲𝘁𝗲𝗰𝘁 𝗧𝗼𝗸𝗲𝗻) ⇋"), KeyboardButton("⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ---------------------------------------------------------
# Screen Handlers
# ---------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = database.get_or_create_user(user.id, user.username or "", user.first_name or "")

    # Record referral payload if present (/start ref_<id>)
    if context.args and len(context.args) > 0:
        arg = str(context.args[0]).strip()
        if arg.startswith("ref_"):
            try:
                referrer_id = int(arg[4:])
                if referrer_id != user.id and hasattr(database, "record_referral"):
                    database.record_referral(referrer_id, user.id)
            except Exception as e:
                logger.warning(f"Error handling referral argument {arg}: {e}")

    if db_user['is_banned']:
        msg = (
            f"{make_header_card('ACCOUNT SUSPENDED', 'Access Denied')}\n\n"
            "<blockquote>🚫 <b>Access Restricted:</b> Your account has been suspended by the administrator.</blockquote>"
        )
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
        await send_clean_screen(update, context, msg)
        return

    is_sub, unjoined = await check_user_subscription(context.bot, user.id)
    if not is_sub:
        await send_force_sub_prompt(update, context, unjoined)
        return

    # If user is subscribed / verified, reward pending referral to referrer
    if hasattr(database, "reward_referral_if_pending"):
        try:
            database.reward_referral_if_pending(user.id, context.bot)
        except Exception as e:
            logger.warning(f"Error rewarding pending referral for user {user.id}: {e}")

    maint = database.get_setting("maintenance_mode", "0") == "1"
    maint_notice = ""
    if maint and user.id != ADMIN_ID:
        maint_notice = "\n<blockquote>⚠️ <b>Notice:</b> System maintenance is currently active. Deployments may be temporarily paused.</blockquote>\n"

    header = make_header_card("GRAVIX-HOST PRO", "Free 24/7 Cloud Bot Hosting")
    safe_name = html.escape(user.first_name or "Developer")

    text = (
        f"{header}\n\n"
        f"👋 Welcome, <b>{safe_name}</b>!\n\n"
        "<blockquote>⚡ <b>100% Free 24/7 Cloud Hosting</b>\n"
        "Deploy & run your Python Telegram bots with 99.9% uptime and zero cost.</blockquote>\n"
        f"{maint_notice}\n"
        "👇 <i>Choose an option from the menu below:</i>"
    )

    photo_path = os.path.join(os.path.dirname(__file__), "wp14967960.webp")
    reply_kb = get_main_reply_keyboard(user.id)
    await send_clean_screen(update, context, text, reply_markup=reply_kb, photo_path=photo_path)

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
        await send_clean_screen(update, context, msg)
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
            "<blockquote>• Tap <b>⇋ 𝗛𝗼𝘀𝘁 𝗡𝗲𝘄 𝗕𝗼𝘁 ⇋</b> to deploy your custom Python script.\n"
            "• Tap <b>⇋ 𝗤𝘂𝗶𝗰𝗸 𝗧𝗲𝗺𝗽𝗹𝗮𝘁𝗲𝘀 ⇋</b> to launch a ready-made template in seconds.</blockquote>"
        )
        keyboard = ReplyKeyboardMarkup([
            [KeyboardButton("⇋ 𝗛𝗼𝘀𝘁 𝗡𝗲𝘄 𝗕𝗼𝘁 ⇋"), KeyboardButton("⇋ 𝗤𝘂𝗶𝗰𝗸 𝗧𝗲𝗺𝗽𝗹𝗮𝘁𝗲𝘀 ⇋")],
            [KeyboardButton("⇋ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂 ⇋")]
        ], resize_keyboard=True)
        await send_clean_screen(update, context, text, reply_markup=keyboard)
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
    await send_clean_screen(update, context, text, reply_markup=keyboard)

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
        await send_clean_screen(update, context, msg)
        return

    if bot_id is None and update.message and update.message.text:
        raw_msg_text = update.message.text
        clean_msg_text = normalize_user_input(raw_msg_text)
        m = re.search(r"\[#([a-zA-Z0-9_-]+)\]", clean_msg_text) or re.search(r"\[#([a-zA-Z0-9_-]+)\]", raw_msg_text)
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
        await send_clean_screen(update, context, msg, reply_markup=get_my_bots_reply_keyboard(database.get_user_bots(user_id)))
        return

    if user_id == ADMIN_ID and (context.user_data.get('admin_bots_page') is not None or bot_data['user_id'] != user_id):
        from admin_handlers import admin_bot_detail_handler
        return await admin_bot_detail_handler(update, context, bot_id=bot_id)

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

    metrics = bot_manager.get_bot_process_metrics(bot_id)
    auto_restart_str = "Enabled (Watchdog Active)" if bot_data.get('auto_restart') else "Disabled"
    header = make_header_card("BOT INSPECTOR", "Instance Diagnostics & Control")
    safe_bot_name = html.escape(bot_data.get('bot_name', 'Unnamed Bot'))

    text = (
        f"{header}\n\n"
        "<b>🤖 Instance Overview:</b>\n"
        f"<blockquote>• <b>Name:</b> <b>{safe_bot_name}</b>\n"
        f"• <b>𝗕𝗼𝘁 𝗜𝗗:</b> <code>#{html.escape(bot_id)}</code>\n"
        f"• <b>𝗦𝘁𝗮𝘁𝘂𝘀:</b> {status_badge}\n"
        f"• <b>PID:</b> <code>{html.escape(pid_str)}</code>\n"
        f"• <b>𝗨𝗽𝘁𝗶𝗺𝗲:</b> <code>{html.escape(uptime_str)}</code>\n"
        f"• ⚡ <b>𝗖𝗣𝗨 𝗟𝗼𝗮𝗱:</b> <code>{metrics['cpu_percent']}%</code>\n"
        f"• 💾 <b>𝗥𝗔𝗠 𝗨𝘀𝗮𝗴𝗲:</b> <code>{metrics['ram_mb']} MB</code></blockquote>\n\n"
        "<b>⚙️ Configuration & Metadata:</b>\n"
        f"<blockquote>• <b>API Token:</b> <code>{html.escape(token_masked)}</code>\n"
        f"• <b>𝗔𝘂𝘁𝗼-𝗥𝗲𝘀𝘁𝗮𝗿𝘁:</b> <code>{auto_restart_str}</code>\n"
        f"• <b>Created:</b> <code>{html.escape(created_str)}</code></blockquote>\n\n"
        "👇 <i>Use the persistent keyboard below to manage this instance:</i>"
    )

    keyboard = get_bot_detail_reply_keyboard(bot_id, status)
    await send_clean_screen(update, context, text, reply_markup=keyboard)

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
        await send_clean_screen(update, context, msg)
        return

    raw_input = update.message.text if (update.message and update.message.text) else ""
    clean_input = normalize_user_input(raw_input).replace("⇋", "").strip()
    if bot_id is None:
        m = re.search(r"\[#([a-zA-Z0-9_-]+)\]", clean_input) or re.search(r"\[#([a-zA-Z0-9_-]+)\]", raw_input)
        if m:
            bot_id = m.group(1)

    if not bot_id:
        await show_my_bots(update, context, page=0)
        return

    if action is None:
        c_low = clean_input.lower()
        if "start bot" in c_low or ("start" in c_low and "bot" in c_low):
            action = "start"
        elif "stop bot" in c_low or ("stop" in c_low and "bot" in c_low):
            action = "stop"
        elif "restart bot" in c_low or ("restart" in c_low and "bot" in c_low):
            action = "restart"
        elif "view logs" in c_low or "logs" in c_low:
            action = "logs"
        elif "confirm delete" in c_low:
            action = "delete_execute"
        elif "cancel delete" in c_low:
            action = "cancel_delete"
        elif "delete bot" in c_low:
            action = "delete_confirm"
        elif "manage env vars" in c_low or "env vars" in c_low:
            action = "env"
        elif "export backup" in c_low or "backup" in c_low:
            action = "backup"

    bot_data = database.get_bot(bot_id)
    if not bot_data or (bot_data['user_id'] != user_id and user_id != ADMIN_ID):
        msg = "⚠️ Bot not found or unauthorized action."
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        await send_clean_screen(update, context, msg, reply_markup=get_main_reply_keyboard(user_id))
        return

    safe_bot_name = html.escape(bot_data.get('bot_name', 'Unnamed Bot'))

    if action == "start":
        success, msg = await bot_manager.start_bot(bot_id)
        header = make_header_card("ACTION EXECUTION", "Start Instance")
        resp = (
            f"{header}\n\n"
            f"<blockquote>🟢 <b>Bot Start Result:</b>\n{html.escape(msg)}</blockquote>"
        )
        await send_clean_screen(update, context, resp)
        await show_bot_details(update, context, bot_id)

    elif action == "stop":
        success, msg = await bot_manager.stop_bot(bot_id)
        header = make_header_card("ACTION EXECUTION", "Stop Instance")
        resp = (
            f"{header}\n\n"
            f"<blockquote>⏹️ <b>Bot Stop Result:</b>\n{html.escape(msg)}</blockquote>"
        )
        await send_clean_screen(update, context, resp)
        await show_bot_details(update, context, bot_id)

    elif action == "restart":
        success, msg = await bot_manager.restart_bot(bot_id)
        header = make_header_card("ACTION EXECUTION", "Restart Instance")
        resp = (
            f"{header}\n\n"
            f"<blockquote>🔄 <b>Bot Restart Result:</b>\n{html.escape(msg)}</blockquote>"
        )
        await send_clean_screen(update, context, resp)
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
        await send_clean_screen(
            update,
            context,
            text,
            reply_markup=get_bot_detail_reply_keyboard(bot_id, status)
        )

    elif action == "delete_confirm":
        header = make_header_card("CONFIRM DELETION", "Permanent Instance Removal")
        text = (
            f"{header}\n\n"
            f"<blockquote>⚠️ <b>Are you sure you want to permanently delete:</b>\n"
            f"• <b>Bot:</b> <b>{safe_bot_name}</b> (<code>#{html.escape(bot_id)}</code>)\n"
            "• <b>Files:</b> Source files and execution logs will be erased.\n\n"
            "⛔ <i>This action cannot be undone.</i></blockquote>\n\n"
            "👇 <i>Tap <b>⇋ 𝗖𝗼𝗻𝗳𝗶𝗿𝗺 𝗗𝗲𝗹𝗲𝘁𝗲 ⇋</b> to proceed or <b>⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 𝗗𝗲𝗹𝗲𝘁𝗲 ⇋</b> to abort:</i>"
        )
        await send_clean_screen(
            update,
            context,
            text,
            reply_markup=get_delete_confirm_keyboard(bot_id)
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
        await send_clean_screen(update, context, text)
        await show_my_bots(update, context, page=0)

    elif action == "cancel_delete":
        header = make_header_card("ACTION ABORTED", "Deletion Cancelled")
        text = (
            f"{header}\n\n"
            f"<blockquote>Deletion of bot <b>{safe_bot_name}</b> (<code>#{html.escape(bot_id)}</code>) was cancelled.</blockquote>"
        )
        await send_clean_screen(update, context, text)
        await show_bot_details(update, context, bot_id)

    elif action == "backup":
        await export_bot_data_handler(update, context, bot_id)

    elif action == "env":
        await user_env_start(update, context, bot_id)

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
        await send_clean_screen(update, context, msg)
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

    bot_username = context.bot.username
    if not bot_username:
        try:
            bot_me = await context.bot.get_me()
            bot_username = bot_me.username
        except Exception:
            bot_username = "GravixHostBot"

    ref_stats = database.get_referral_stats(user_id) if hasattr(database, "get_referral_stats") else {'total_invited': 0, 'rewarded_slots': 0}
    total_invited = ref_stats.get('total_invited', 0)
    rewarded_slots = ref_stats.get('rewarded_slots', 0)
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    header = make_header_card("MY ACCOUNT & SLOTS", "Resource Quota")
    text = (
        f"{header}\n\n"
        f"👤 <b>User:</b> <code>{user_id}</code> ({username_str})\n"
        f"📦 <b>Slots:</b> <code>{len(user_bots)}/{max_slots} Used</code> (<code>{running_cnt} Running</code>)\n"
        f"🎁 <b>Referrals:</b> <code>{total_invited} Invited (+{rewarded_slots} Slots)</code>\n\n"
        f"🔗 <b>Your Referral Link:</b>\n<code>{ref_link}</code>"
    )
    reply_kb = get_back_to_main_keyboard()
    await send_clean_screen(update, context, text, reply_markup=reply_kb)

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
        await send_clean_screen(update, context, msg)
        return

    is_sub, unjoined = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        await send_force_sub_prompt(update, context, unjoined)
        return

    header = make_header_card("HELP & GUIDELINES", "Quick Start Manual")
    text = (
        f"{header}\n\n"
        "<b>🚀 How to Host Your Bot:</b>\n"
        "<blockquote>1️⃣ Get a Bot Token from @BotFather\n"
        "2️⃣ Tap <b>⇋ 𝗛𝗼𝘀𝘁 𝗡𝗲𝘄 𝗕𝗼𝘁 ⇋</b> or <b>⇋ 𝗤𝘂𝗶𝗰𝗸 𝗧𝗲𝗺𝗽𝗹𝗮𝘁𝗲𝘀 ⇋</b>\n"
        "3️⃣ Send token and upload your <code>.py</code> file\n"
        "4️⃣ Manage & view logs in <b>⇋ 𝗠𝘆 𝗛𝗼𝘀𝘁𝗲𝗱 𝗕𝗼𝘁𝘀 ⇋</b></blockquote>\n\n"
        "💬 <b>Support:</b> @Dravonnbot"
    )
    reply_kb = get_back_to_main_keyboard()
    await send_clean_screen(update, context, text, reply_markup=reply_kb)

async def show_support_desk(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await send_clean_screen(update, context, msg)
        return

    is_sub, unjoined = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        await send_force_sub_prompt(update, context, unjoined)
        return

    text = (
        "<b>💬 CUSTOMER SUPPORT</b>\n"
        "<i>24/7 Technical Assistance</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>Need help with bot hosting or extra slots?</blockquote>\n\n"
        "👉 <b>DM Support:</b> @Dravonnbot\n"
        "🔗 <a href=\"https://t.me/Dravonnbot\">t.me/Dravonnbot</a>"
    )
    reply_kb = get_back_to_main_keyboard()
    await send_clean_screen(update, context, text, reply_markup=reply_kb)

async def show_channel_promotion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the official Channel Promotion & Mandatory Join Advertising desk."""
    user = update.effective_user
    user_id = user.id if user else 0
    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        msg = (
            f"{make_header_card('ACCOUNT SUSPENDED', 'Access Denied')}\n\n"
            "<blockquote>🚫 <b>Access Restricted:</b> Your account has been suspended by the administrator.</blockquote>"
        )
        if update.callback_query:
            await update.callback_query.answer("🚫 Account Suspended", show_alert=True)
        await send_clean_screen(update, context, msg)
        return

    is_sub, unjoined = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        await send_force_sub_prompt(update, context, unjoined)
        return

    header = make_header_card("CHANNEL PROMOTION", "Mandatory Join Advertising")
    text = (
        f"{header}\n\n"
        "<blockquote>Promote your Telegram channel with <b>Guaranteed Organic Reach</b> & Mandatory Join Lock!</blockquote>\n\n"
        "💬 <b>Book Promotion Slot:</b>\n"
        "<blockquote>👉 <b>DM:</b> @Dravonnbot\n"
        "🔗 <a href=\"https://t.me/Dravonnbot\">t.me/Dravonnbot</a></blockquote>\n\n"
        "💡 <i>DM for current rates and availability.</i>"
    )
    reply_kb = get_back_to_main_keyboard()
    await send_clean_screen(update, context, text, reply_markup=reply_kb)

async def show_referral_hub(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await send_clean_screen(update, context, msg)
        return

    is_sub, unjoined = await check_user_subscription(context.bot, user_id)
    if not is_sub:
        await send_force_sub_prompt(update, context, unjoined)
        return

    bot_username = context.bot.username
    if not bot_username:
        try:
            bot_me = await context.bot.get_me()
            bot_username = bot_me.username
        except Exception:
            bot_username = "GravixHostBot"

    ref_stats = database.get_referral_stats(user_id) if hasattr(database, "get_referral_stats") else {'total_invited': 0, 'rewarded_slots': 0}
    total_invited = ref_stats.get('total_invited', 0)
    rewarded_slots = ref_stats.get('rewarded_slots', 0)

    text = (
        "<b>🎁 REFER & EARN SLOTS</b>\n"
        "<i>Get +1 Free Slot Per Invite</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<blockquote>Invite friends and earn <b>+1 Permanent Bot Slot</b> per verified invite!</blockquote>\n\n"
        "🔗 <b>Your Referral Link:</b>\n"
        f"<code>https://t.me/{bot_username}?start=ref_{user_id}</code>\n\n"
        f"👥 <b>Invited:</b> <code>{total_invited}</code>  |  🎁 <b>Slots Earned:</b> <code>+{rewarded_slots}</code>"
    )

    reply_kb = get_back_to_main_keyboard()
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass
    await send_clean_screen(update, context, text, reply_markup=reply_kb)

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
        await send_clean_screen(update, context, msg)
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
        await send_clean_screen(update, context, msg, reply_markup=get_main_reply_keyboard(user_id))
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
    await send_clean_screen(update, context, text, reply_markup=keyboard)

# ---------------------------------------------------------
# Quick Template Deployment Conversation Flow
# ---------------------------------------------------------

async def template_select_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    if update.message and update.message.text:
        text = update.message.text.strip()
        norm_t = normalize_user_input(text).replace("⇋", "").strip().lower()
        if is_cancellation_text(text) or norm_t in ["cancel", "back to main menu", "main menu"]:
            context.user_data.pop('active_flow', None)
            context.user_data.pop('deploy_template_key', None)
            await send_clean_screen(update, context, "❌ Hosting wizard cancelled.", reply_markup=get_main_reply_keyboard(user_id))
            return ConversationHandler.END
        elif is_menu_navigation_text(text):
            context.user_data.pop('active_flow', None)
            context.user_data.pop('deploy_template_key', None)
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
        await send_clean_screen(update, context, msg)
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
        await send_clean_screen(update, context, msg, reply_markup=get_main_reply_keyboard(user_id))
        return ConversationHandler.END

    user_bots = database.get_user_bots(user_id)
    max_slots = db_user.get('max_slots', 3)
    if len(user_bots) >= max_slots:
        msg = (
            f"{make_header_card('QUOTA LIMIT REACHED', 'Resource Capacity Exceeded')}\n\n"
            f"<blockquote>⚠️ You have reached your slot limit of <code>{max_slots}</code> bots "
            f"(<code>{len(user_bots)}/{max_slots}</code>).\n\n"
            "Please delete an unused bot from <b>⇋ 𝗠𝘆 𝗛𝗼𝘀𝘁𝗲𝗱 𝗕𝗼𝘁𝘀 ⇋</b> or contact Admin for additional capacity.</blockquote>"
        )
        if update.callback_query:
            await update.callback_query.answer("⚠️ Slot Limit Reached", show_alert=True)
        await send_clean_screen(update, context, msg, reply_markup=get_main_reply_keyboard(user_id))
        return ConversationHandler.END

    tpl_key = None
    if update.callback_query:
        await update.callback_query.answer()
        tpl_key = update.callback_query.data.replace("deploy_tpl_", "", 1)
    elif update.message and update.message.text:
        input_text = update.message.text.strip()
        clean_input = normalize_user_input(input_text).replace("⇋", "").strip().lower()
        for k, v in TEMPLATES.items():
            t_clean = normalize_user_input(v['name']).replace("⇋", "").strip().lower()
            t_raw_clean = re.sub(r'^[^\w\s]+', '', v['name']).strip().lower()
            if clean_input in (t_clean, t_raw_clean) or t_clean in clean_input or t_raw_clean in clean_input or k in clean_input:
                tpl_key = k
                break

    if not tpl_key or tpl_key not in TEMPLATES:
        await send_clean_screen(
            update,
            context,
            "<blockquote>⚠️ <b>Template Not Recognized:</b> Please select a valid template from the keyboard menu below.</blockquote>",
            reply_markup=get_templates_reply_keyboard()
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
        "👇 <i>Send the token as text or tap <b>⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋</b> below:</i>"
    )
    cancel_kb = get_cancel_keyboard()
    await send_clean_screen(update, context, text, reply_markup=cancel_kb)
    return TPL_TOKEN

async def template_token_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message or not update.message.text:
        await send_clean_screen(
            update,
            context,
            "<blockquote>⚠️ Please send your bot API token as text or tap <b>⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋</b>.</blockquote>",
            reply_markup=get_cancel_keyboard()
        )
        return TPL_TOKEN

    text = update.message.text.strip()
    norm_t = normalize_user_input(text).replace("⇋", "").strip().lower()
    if is_cancellation_text(text) or norm_t in ["cancel", "back to main menu", "main menu"]:
        context.user_data.pop('active_flow', None)
        context.user_data.pop('bot_name', None)
        context.user_data.pop('bot_token', None)
        context.user_data.pop('bot_id', None)
        context.user_data.pop('deploy_template_key', None)
        await send_clean_screen(update, context, "❌ Hosting wizard cancelled.", reply_markup=get_main_reply_keyboard(user_id))
        return ConversationHandler.END
    elif is_menu_navigation_text(text):
        context.user_data.pop('active_flow', None)
        context.user_data.pop('bot_name', None)
        context.user_data.pop('bot_token', None)
        context.user_data.pop('bot_id', None)
        context.user_data.pop('deploy_template_key', None)
        await user_text_router(update, context)
        return ConversationHandler.END

    if context.user_data.get('active_flow') != 'tpl':
        await send_clean_screen(
            update,
            context,
            "<blockquote>⚠️ <b>Session Expired:</b> Please reopen <b>⇋ 𝗤𝘂𝗶𝗰𝗸 𝗧𝗲𝗺𝗽𝗹𝗮𝘁𝗲𝘀 ⇋</b> from the main menu.</blockquote>",
            reply_markup=get_main_reply_keyboard(user_id)
        )
        return ConversationHandler.END

    token = sanitize_token(text)
    tpl_key = context.user_data.get('deploy_template_key', 'echo_bot')
    tinfo = TEMPLATES.get(tpl_key, TEMPLATES['echo_bot'])

    if token == BOT_TOKEN:
        await send_clean_screen(
            update,
            context,
            "<blockquote>⚠️ <b>Invalid Token:</b> You cannot host a bot using this platform's own bot token. "
            "Please create a distinct bot with @BotFather and send its token:</blockquote>",
            reply_markup=get_cancel_keyboard()
        )
        return TPL_TOKEN

    is_valid, bot_uname, err_msg = await verify_telegram_token(token)
    if not is_valid:
        await send_clean_screen(
            update,
            context,
            f"<blockquote>⚠️ <b>Token Validation Failed:</b>\n{html.escape(err_msg)}\n\n"
            "Please copy and paste a valid Bot Token from @BotFather:</blockquote>",
            reply_markup=get_cancel_keyboard()
        )
        return TPL_TOKEN

    clean_tname = re.sub(r'^[^\w\s]+', '', tinfo.get('name', 'Template')).strip()
    bot_name = f"@{bot_uname} ({clean_tname})"
    bot_id = str(uuid.uuid4())[:8]
    bot_dir = os.path.join(DATA_DIR, "bots", f"{user_id}_{bot_id}")
    os.makedirs(bot_dir, exist_ok=True)
    script_path = os.path.join(bot_dir, "main.py")

    with open(script_path, "w", encoding="utf-8") as f:
        f.write(tinfo['code'])

    database.create_hosted_bot(bot_id, user_id, bot_name, token, script_path)
    await send_clean_screen(update, context, "⚙️ <i>Provisioning Gravix dedicated cloud instance and launching template...</i>")

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
        f"<blockquote>• <b>𝗕𝗼𝘁 𝗡𝗮𝗺𝗲:</b> <b>{safe_bot_name}</b>\n"
        f"• <b>𝗕𝗼𝘁 𝗜𝗗:</b> <code>#{html.escape(bot_id)}</code>\n"
        f"• <b>𝗦𝘁𝗮𝘁𝘂𝘀:</b> {status_badge}\n"
        f"• <b>Diagnostics:</b> {safe_msg}</blockquote>\n\n"
        "<blockquote>💡 <i>Your bot is now live and running 24/7 on <b>Gravix-Host</b>.</i></blockquote>"
    )
    await send_clean_screen(update, context, resp_text, reply_markup=get_bot_detail_reply_keyboard(bot_id, bot_status))
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
    await send_clean_screen(update, context, text, reply_markup=get_main_reply_keyboard(user_id))
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
        await send_clean_screen(update, context, msg)
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
        await send_clean_screen(update, context, msg, reply_markup=get_main_reply_keyboard(user_id))
        return ConversationHandler.END

    user_bots = database.get_user_bots(user_id)
    max_slots = db_user.get('max_slots', 3)
    if len(user_bots) >= max_slots:
        msg = (
            f"{make_header_card('QUOTA LIMIT REACHED', 'Resource Capacity Exceeded')}\n\n"
            f"<blockquote>⚠️ You have reached your slot limit of <code>{max_slots}</code> bots "
            f"(<code>{len(user_bots)}/{max_slots}</code>).\n\n"
            "Please delete an existing bot from <b>⇋ 𝗠𝘆 𝗛𝗼𝘀𝘁𝗲𝗱 𝗕𝗼𝘁𝘀 ⇋</b> or contact Admin for more slots.</blockquote>"
        )
        if update.callback_query:
            await update.callback_query.answer("⚠️ Slot Limit Reached", show_alert=True)
        await send_clean_screen(update, context, msg, reply_markup=get_main_reply_keyboard(user_id))
        return ConversationHandler.END

    if update.callback_query:
        await update.callback_query.answer()

    context.user_data['active_flow'] = 'host'
    header = make_header_card("CUSTOM BOT HOSTING", "Step 1 of 3: Instance Identification")
    text = (
        f"{header}\n\n"
        "<blockquote>Please enter a friendly <b>Display Name</b> for your bot.\n"
        "<i>Example:</i> <code>My Store Bot</code> or <code>Crypto Price Alert</code></blockquote>\n\n"
        "👇 <i>Type the name in chat or tap <b>⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋</b> below:</i>"
    )
    cancel_kb = get_cancel_keyboard()
    await send_clean_screen(update, context, text, reply_markup=cancel_kb)
    return NAME

async def host_bot_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message or not update.message.text:
        await send_clean_screen(
            update,
            context,
            "<blockquote>⚠️ Please enter a text name for your bot or tap <b>⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋</b>.</blockquote>",
            reply_markup=get_cancel_keyboard()
        )
        return NAME

    text = update.message.text.strip()
    norm_t = normalize_user_input(text).replace("⇋", "").strip().lower()
    if is_cancellation_text(text) or norm_t in ["cancel", "back to main menu", "main menu"]:
        context.user_data.pop('active_flow', None)
        context.user_data.pop('bot_name', None)
        context.user_data.pop('bot_token', None)
        context.user_data.pop('bot_id', None)
        context.user_data.pop('new_bot_name', None)
        context.user_data.pop('new_bot_token', None)
        context.user_data.pop('bot_uname', None)
        await send_clean_screen(update, context, "❌ Hosting wizard cancelled.", reply_markup=get_main_reply_keyboard(user_id))
        return ConversationHandler.END
    elif is_menu_navigation_text(text):
        context.user_data.pop('active_flow', None)
        context.user_data.pop('bot_name', None)
        context.user_data.pop('bot_token', None)
        context.user_data.pop('bot_id', None)
        context.user_data.pop('new_bot_name', None)
        context.user_data.pop('new_bot_token', None)
        context.user_data.pop('bot_uname', None)
        await user_text_router(update, context)
        return ConversationHandler.END

    if context.user_data.get('active_flow') != 'host':
        await send_clean_screen(
            update,
            context,
            "<blockquote>⚠️ <b>Session Interrupted:</b> Please use /start to begin again.</blockquote>",
            reply_markup=get_main_reply_keyboard(user_id)
        )
        return ConversationHandler.END

    bot_name = text
    if len(bot_name) < 2 or len(bot_name) > 30:
        await send_clean_screen(
            update,
            context,
            "<blockquote>⚠️ <b>Invalid Name:</b> Name must be between 2 and 30 characters. Please enter a valid name:</blockquote>",
            reply_markup=get_cancel_keyboard()
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
        "💡 <i>If your token is hardcoded in your Python script, tap <b>⇋ 𝗦𝗸𝗶𝗽 (𝗔𝘂𝘁𝗼-𝗗𝗲𝘁𝗲𝗰𝘁 𝗧𝗼𝗸𝗲𝗻) ⇋</b>.</i></blockquote>\n\n"
        "👇 <i>Send your token as text or choose an option below:</i>"
    )
    await send_clean_screen(update, context, text_resp, reply_markup=get_token_input_keyboard())
    return TOKEN

async def host_bot_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message or not update.message.text:
        await send_clean_screen(
            update,
            context,
            "<blockquote>⚠️ Please send your bot API token as text or tap <b>⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋</b>.</blockquote>",
            reply_markup=get_token_input_keyboard()
        )
        return TOKEN

    text = update.message.text.strip()
    norm_t = normalize_user_input(text).replace("⇋", "").strip().lower()
    if is_cancellation_text(text) or norm_t in ["cancel", "back to main menu", "main menu"]:
        context.user_data.pop('active_flow', None)
        context.user_data.pop('bot_name', None)
        context.user_data.pop('bot_token', None)
        context.user_data.pop('bot_id', None)
        context.user_data.pop('new_bot_name', None)
        context.user_data.pop('new_bot_token', None)
        context.user_data.pop('bot_uname', None)
        await send_clean_screen(update, context, "❌ Hosting wizard cancelled.", reply_markup=get_main_reply_keyboard(user_id))
        return ConversationHandler.END
    elif is_menu_navigation_text(text) and "skip" not in norm_t:
        context.user_data.pop('active_flow', None)
        context.user_data.pop('bot_name', None)
        context.user_data.pop('bot_token', None)
        context.user_data.pop('bot_id', None)
        context.user_data.pop('new_bot_name', None)
        context.user_data.pop('new_bot_token', None)
        context.user_data.pop('bot_uname', None)
        await user_text_router(update, context)
        return ConversationHandler.END

    if context.user_data.get('active_flow') != 'host':
        await send_clean_screen(
            update,
            context,
            "<blockquote>⚠️ <b>Session Interrupted:</b> Please resend your bot token to continue.</blockquote>",
            reply_markup=get_main_reply_keyboard(user_id)
        )
        return ConversationHandler.END

    # Check for Skip (Auto-Detect Token)
    if "skip" in norm_t or text == "⏩ Skip (Auto-Detect Token)" or text.lower() in ("skip", "/skip"):
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
            "<b>Option 2:</b> Upload a multi-file bot package as a <code>.zip</code> archive.\n"
            "<b>Option 3:</b> Paste your Python code directly in chat.\n\n"
            "🔍 <i>Our engine will automatically extract and validate your bot token from the script.</i></blockquote>\n\n"
            "👇 <i>Send the script file or text, or tap <b>⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋</b> to abort:</i>"
        )
        await send_clean_screen(update, context, resp_text, reply_markup=get_cancel_keyboard())
        return CODE

    token = sanitize_token(text)

    if token == BOT_TOKEN:
        await send_clean_screen(
            update,
            context,
            "<blockquote>⚠️ <b>Invalid Token:</b> You cannot host a bot using this platform's own bot token. "
            "Create a new bot with @BotFather and send its token:</blockquote>",
            reply_markup=get_token_input_keyboard()
        )
        return TOKEN

    is_valid, bot_uname, err_msg = await verify_telegram_token(token)
    if not is_valid:
        await send_clean_screen(
            update,
            context,
            f"<blockquote>⚠️ <b>Token Validation Failed:</b>\n{html.escape(err_msg)}\n\n"
            "Please copy and paste a valid Bot Token from @BotFather:</blockquote>",
            reply_markup=get_token_input_keyboard()
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
        "<b>Option 2:</b> Upload a multi-file bot package as a <code>.zip</code> archive.\n"
        "<b>Option 3:</b> Paste your Python code directly in chat.</blockquote>\n\n"
        "👇 <i>Send the script file or text, or tap <b>⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋</b> to abort:</i>"
    )
    await send_clean_screen(update, context, resp_text, reply_markup=get_cancel_keyboard())
    return CODE

async def host_bot_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message or (not update.message.text and not update.message.document):
        await send_clean_screen(
            update,
            context,
            "<blockquote>⚠️ <b>Invalid Input:</b> Please upload a <code>.py</code> script, a <code>.zip</code> project archive, or paste Python code.</blockquote>",
            reply_markup=get_cancel_keyboard()
        )
        return CODE

    if update.message.text:
        text = update.message.text.strip()
        norm_t = normalize_user_input(text).replace("⇋", "").strip().lower()
        if is_cancellation_text(text) or norm_t in ["cancel", "back to main menu", "main menu"]:
            context.user_data.pop('active_flow', None)
            context.user_data.pop('bot_name', None)
            context.user_data.pop('bot_token', None)
            context.user_data.pop('bot_id', None)
            context.user_data.pop('new_bot_name', None)
            context.user_data.pop('new_bot_token', None)
            context.user_data.pop('bot_uname', None)
            await send_clean_screen(update, context, "❌ Hosting wizard cancelled.", reply_markup=get_main_reply_keyboard(user_id))
            return ConversationHandler.END
        elif is_menu_navigation_text(text):
            context.user_data.pop('active_flow', None)
            context.user_data.pop('bot_name', None)
            context.user_data.pop('bot_token', None)
            context.user_data.pop('bot_id', None)
            context.user_data.pop('new_bot_name', None)
            context.user_data.pop('new_bot_token', None)
            context.user_data.pop('bot_uname', None)
            await user_text_router(update, context)
            return ConversationHandler.END

    if context.user_data.get('active_flow') != 'host':
        await send_clean_screen(
            update,
            context,
            "<blockquote>⚠️ <b>Session Interrupted:</b> Please use /start and try again.</blockquote>",
            reply_markup=get_main_reply_keyboard(user_id)
        )
        return ConversationHandler.END

    bot_name = context.user_data.get('new_bot_name') or context.user_data.get('bot_name', 'My Bot')
    token = context.user_data.get('bot_token') or context.user_data.get('new_bot_token', '')

    bot_id = str(uuid.uuid4())[:8]
    bot_dir = os.path.join(DATA_DIR, "bots", f"{user_id}_{bot_id}")
    os.makedirs(bot_dir, exist_ok=True)
    script_path = os.path.join(bot_dir, "main.py")

    if update.message.document:
        doc = update.message.document
        fname = (doc.file_name or "").lower()
        is_zip = fname.endswith(".zip")
        is_py = fname.endswith(".py")

        if not (is_zip or is_py):
            shutil.rmtree(bot_dir, ignore_errors=True)
            await send_clean_screen(
                update,
                context,
                "<blockquote>⚠️ <b>Invalid File:</b> Please upload either a Python script ending in <code>.py</code> or a project archive ending in <code>.zip</code>.</blockquote>",
                reply_markup=get_cancel_keyboard()
            )
            return CODE

        if is_zip:
            try:
                file = await doc.get_file()
                file_bytes = await file.download_as_bytearray()
            except Exception as e:
                shutil.rmtree(bot_dir, ignore_errors=True)
                logger.error(f"Error downloading ZIP archive: {e}")
                await send_clean_screen(
                    update,
                    context,
                    f"<blockquote>⚠️ <b>File Download Error:</b> Could not read uploaded ZIP: {html.escape(str(e))}</blockquote>",
                    reply_markup=get_cancel_keyboard()
                )
                return CODE

            is_valid, err_msg, extracted_token, imported_modules = extract_and_validate_zip(bytes(file_bytes), bot_dir)
            if not is_valid:
                shutil.rmtree(bot_dir, ignore_errors=True)
                header = make_header_card("ZIP VALIDATION FAILED", "Project Archive Error")
                safe_err = html.escape(err_msg or "Invalid ZIP project structure.")
                err_card = (
                    f"{header}\n\n"
                    f"<blockquote>❌ <b>ZIP Archive Validation Failed:</b>\n<code>{safe_err}</code></blockquote>\n\n"
                    "<blockquote>💡 <i>Make sure your ZIP archive contains a <code>main.py</code> entry point and valid Python code.</i></blockquote>\n\n"
                    "👇 <i>Please upload a valid <code>.zip</code> or <code>.py</code> file, or tap <b>⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋</b>:</i>"
                )
                await send_clean_screen(update, context, err_card, reply_markup=get_cancel_keyboard())
                return CODE

            # If token was AUTO_DETECT, resolve it
            if token == 'AUTO_DETECT':
                if not extracted_token:
                    header = make_header_card("NO TOKEN DETECTED", "Token Required")
                    prompt_text = (
                        f"{header}\n\n"
                        "<blockquote>⚠️ <b>Auto-Detection Failed:</b> We could not detect any Telegram bot token in your ZIP archive's <code>main.py</code>.</blockquote>\n\n"
                        "<blockquote>Please send your bot API token obtained from @BotFather manually:</blockquote>\n\n"
                        "👇 <i>Send your token as text or tap <b>⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋</b>:</i>"
                    )
                    shutil.rmtree(bot_dir, ignore_errors=True)
                    await send_clean_screen(update, context, prompt_text, reply_markup=get_cancel_keyboard())
                    return TOKEN

                if extracted_token == BOT_TOKEN:
                    shutil.rmtree(bot_dir, ignore_errors=True)
                    await send_clean_screen(
                        update,
                        context,
                        "<blockquote>⚠️ <b>Invalid Token Detected:</b> The token found in your archive matches this platform's own bot token. "
                        "Please use a distinct bot token from @BotFather:</blockquote>",
                        reply_markup=get_cancel_keyboard()
                    )
                    return CODE

                is_valid, bot_uname, v_err = await verify_telegram_token(extracted_token)
                if not is_valid:
                    shutil.rmtree(bot_dir, ignore_errors=True)
                    header = make_header_card("TOKEN VALIDATION FAILED", "Auto-Detected Token Error")
                    safe_verr = html.escape(v_err or "Telegram rejected token.")
                    token_preview = html.escape(extracted_token[:10] + "..." if len(extracted_token) > 10 else extracted_token)
                    err_card = (
                        f"{header}\n\n"
                        f"<blockquote>⚠️ A token was detected in your archive (<code>{token_preview}</code>), "
                        f"but Telegram validation failed:\n<code>{safe_verr}</code></blockquote>\n\n"
                        "👇 <i>Please update your ZIP with a valid token or send token manually:</i>"
                    )
                    await send_clean_screen(update, context, err_card, reply_markup=get_cancel_keyboard())
                    return CODE

                token = extracted_token
                context.user_data['bot_token'] = token
                context.user_data['new_bot_token'] = token
                context.user_data['bot_uname'] = bot_uname

        else:
            # is_py file
            try:
                file = await doc.get_file()
                file_bytes = await file.download_as_bytearray()
                code_content = file_bytes.decode("utf-8", errors="replace")
            except Exception as e:
                shutil.rmtree(bot_dir, ignore_errors=True)
                logger.error(f"Error downloading script document: {e}")
                await send_clean_screen(
                    update,
                    context,
                    f"<blockquote>⚠️ <b>File Download Error:</b> Could not read uploaded file: {html.escape(str(e))}</blockquote>",
                    reply_markup=get_cancel_keyboard()
                )
                return CODE

            valid, err_msg, lineno, line_text = validate_python_syntax(code_content)
            if not valid:
                shutil.rmtree(bot_dir, ignore_errors=True)
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
                    "👇 <i>Please fix the syntax error and re-upload your file or paste corrected code below:</i>"
                )
                await send_clean_screen(update, context, err_card, reply_markup=get_cancel_keyboard())
                return CODE

            if token == 'AUTO_DETECT':
                detected_token = extract_token_from_code(code_content)
                if not detected_token:
                    shutil.rmtree(bot_dir, ignore_errors=True)
                    header = make_header_card("NO TOKEN DETECTED", "Token Required")
                    prompt_text = (
                        f"{header}\n\n"
                        "<blockquote>⚠️ <b>Auto-Detection Failed:</b> We could not detect any Telegram bot token in your script.</blockquote>\n\n"
                        "<blockquote>Please send your bot API token obtained from @BotFather manually:</blockquote>\n\n"
                        "👇 <i>Send your token as text or tap <b>⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋</b>:</i>"
                    )
                    await send_clean_screen(update, context, prompt_text, reply_markup=get_cancel_keyboard())
                    return TOKEN

                if detected_token == BOT_TOKEN:
                    shutil.rmtree(bot_dir, ignore_errors=True)
                    await send_clean_screen(
                        update,
                        context,
                        "<blockquote>⚠️ <b>Invalid Token Detected:</b> The token found in your script matches this platform's own bot token. "
                        "Please use a distinct bot token from @BotFather:</blockquote>",
                        reply_markup=get_cancel_keyboard()
                    )
                    return CODE

                is_valid, bot_uname, v_err = await verify_telegram_token(detected_token)
                if not is_valid:
                    shutil.rmtree(bot_dir, ignore_errors=True)
                    header = make_header_card("TOKEN VALIDATION FAILED", "Auto-Detected Token Error")
                    safe_verr = html.escape(v_err or "Telegram rejected token.")
                    token_preview = html.escape(detected_token[:10] + "..." if len(detected_token) > 10 else detected_token)
                    err_card = (
                        f"{header}\n\n"
                        f"<blockquote>⚠️ A token was detected in your code (<code>{token_preview}</code>), "
                        f"but Telegram validation failed:\n<code>{safe_verr}</code></blockquote>\n\n"
                        "👇 <i>Please update your script with a valid token or send the token manually:</i>"
                    )
                    await send_clean_screen(update, context, err_card, reply_markup=get_cancel_keyboard())
                    return CODE

                token = detected_token
                context.user_data['bot_token'] = token
                context.user_data['new_bot_token'] = token
                context.user_data['bot_uname'] = bot_uname

            with open(script_path, "w", encoding="utf-8") as f:
                f.write(code_content)

    elif update.message.text:
        code_content = update.message.text
        valid, err_msg, lineno, line_text = validate_python_syntax(code_content)
        if not valid:
            shutil.rmtree(bot_dir, ignore_errors=True)
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
                "👇 <i>Please fix the syntax error and re-upload your file or paste corrected code below:</i>"
            )
            await send_clean_screen(update, context, err_card, reply_markup=get_cancel_keyboard())
            return CODE

        if token == 'AUTO_DETECT':
            detected_token = extract_token_from_code(code_content)
            if not detected_token:
                shutil.rmtree(bot_dir, ignore_errors=True)
                header = make_header_card("NO TOKEN DETECTED", "Token Required")
                prompt_text = (
                    f"{header}\n\n"
                    "<blockquote>⚠️ <b>Auto-Detection Failed:</b> We could not detect any Telegram bot token in your script.</blockquote>\n\n"
                    "<blockquote>Please send your bot API token obtained from @BotFather manually:</blockquote>\n\n"
                    "👇 <i>Send your token as text or tap <b>⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋</b>:</i>"
                )
                await send_clean_screen(update, context, prompt_text, reply_markup=get_cancel_keyboard())
                return TOKEN

            if detected_token == BOT_TOKEN:
                shutil.rmtree(bot_dir, ignore_errors=True)
                await send_clean_screen(
                    update,
                    context,
                    "<blockquote>⚠️ <b>Invalid Token Detected:</b> The token found in your script matches this platform's own bot token. "
                    "Please use a distinct bot token from @BotFather:</blockquote>",
                    reply_markup=get_cancel_keyboard()
                )
                return CODE

            is_valid, bot_uname, v_err = await verify_telegram_token(detected_token)
            if not is_valid:
                shutil.rmtree(bot_dir, ignore_errors=True)
                header = make_header_card("TOKEN VALIDATION FAILED", "Auto-Detected Token Error")
                safe_verr = html.escape(v_err or "Telegram rejected token.")
                token_preview = html.escape(detected_token[:10] + "..." if len(detected_token) > 10 else detected_token)
                err_card = (
                    f"{header}\n\n"
                    f"<blockquote>⚠️ A token was detected in your code (<code>{token_preview}</code>), "
                    f"but Telegram validation failed:\n<code>{safe_verr}</code></blockquote>\n\n"
                    "👇 <i>Please update your script with a valid token or send the token manually:</i>"
                )
                await send_clean_screen(update, context, err_card, reply_markup=get_cancel_keyboard())
                return CODE

            token = detected_token
            context.user_data['bot_token'] = token
            context.user_data['new_bot_token'] = token
            context.user_data['bot_uname'] = bot_uname

        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code_content)

    database.create_hosted_bot(bot_id, user_id, bot_name, token, script_path)

    await send_clean_screen(update, context, "⚙️ <i>Provisioning Gravix dedicated cloud environment and starting bot...</i>")
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
            "<blockquote>🎉 <b>Success!</b> Your custom bot has been provisioned and started on <b>Gravix Dedicated High-Speed Cloud</b>.</blockquote>\n\n"
            "<b>🤖 Instance Overview:</b>\n"
            f"<blockquote>• <b>Name:</b> <b>{safe_bot_name}</b>\n"
            f"• <b>𝗕𝗼𝘁 𝗜𝗗:</b> <code>#{html.escape(bot_id)}</code>\n"
            "• <b>𝗦𝘁𝗮𝘁𝘂𝘀:</b> 🟢 <code>RUNNING</code>\n"
            f"• <b>PID:</b> <code>{html.escape(pid_str)}</code>\n"
            "• <b>𝗨𝗽𝘁𝗶𝗺𝗲:</b> <code>Just started</code></blockquote>\n\n"
            "<b>⚙️ Configuration & Metadata:</b>\n"
            f"<blockquote>• <b>API Token:</b> <code>{html.escape(token_masked)}</code>\n"
            "• <b>𝗔𝘂𝘁𝗼-𝗥𝗲𝘀𝘁𝗮𝗿𝘁:</b> <code>Enabled (Watchdog Active)</code>\n"
            f"• <b>Created:</b> <code>{html.escape(created_str)}</code></blockquote>\n\n"
            "<blockquote>💡 <i>You can monitor live logs, restart, or manage this bot from the menu below.</i></blockquote>"
        )
        await send_clean_screen(update, context, resp_text, reply_markup=get_bot_detail_reply_keyboard(bot_id, "RUNNING"))
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
            "• <b>𝗦𝘁𝗮𝘁𝘂𝘀:</b> 🔴 <code>FAILED</code></blockquote>\n\n"
            "<b>📜 Console Traceback / Error Logs:</b>\n"
            f"<pre><code class=\"language-log\">{safe_logs}</code></pre>\n\n"
            "<blockquote>💡 <i>Inspect the error traceback above. You can fix the code and deploy again, or manage this bot below:</i></blockquote>"
        )
        await send_clean_screen(update, context, resp_text, reply_markup=get_bot_detail_reply_keyboard(bot_id, "FAILED"))

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
    await send_clean_screen(update, context, text, reply_markup=get_main_reply_keyboard(user_id))
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
    elif data in ["user_support", "user_helpdesk"]:
        await show_support_desk(update, context)
    elif data.startswith("user_my_bots_"):
        page = int(data.split("_")[3])
        await show_my_bots(update, context, page=page)
    elif data.startswith("ubot_export_"):
        bot_id = data.split("_")[2]
        await export_bot_data_handler(update, context, bot_id=bot_id)
    elif data.startswith("ubot_env_"):
        bot_id = data.split("_")[2]
        await user_env_start(update, context, bot_id=bot_id)
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
    elif data in ["user_referral", "user_referrals", "user_ref"]:
        await show_referral_hub(update, context)

async def user_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or not update.message.text:
        return False
    raw_text = update.message.text.strip()
    norm_text = normalize_user_input(raw_text)
    clean_text = norm_text.replace("⇋", "").strip()
    clean_lower = clean_text.lower()
    user_id = update.effective_user.id

    db_user = database.get_or_create_user(user_id)
    if db_user['is_banned']:
        msg = (
            f"{make_header_card('ACCOUNT SUSPENDED', 'Access Denied')}\n\n"
            "<blockquote>🚫 <b>Access Restricted:</b> Your account has been suspended.</blockquote>"
        )
        await send_clean_screen(update, context, msg)
        return True

    # Back / Home / Refresh navigation
    if (
        clean_lower in ["main menu", "back to main menu", "refresh", "/start", "/menu"]
        or "back to main menu" in clean_lower
        or "main menu" in clean_lower
        or clean_lower == "refresh"
    ):
        await start_command(update, context)
        return True

    # My Bots & Back to My Bots
    if (
        clean_lower in ["my hosted bots", "back to my bots", "/mybots", "/bots"]
        or "my hosted bots" in clean_lower
        or "back to my bots" in clean_lower
    ):
        await show_my_bots(update, context, page=0)
        return True

    # Host New Bot / Host Another Bot
    if (
        clean_lower in ["host new bot", "host custom bot", "host another bot"]
        or "host new bot" in clean_lower
        or "host another bot" in clean_lower
        or "host custom bot" in clean_lower
    ):
        await host_bot_start(update, context)
        return True

    # Pagination
    if clean_lower in ["prev bots", "previous bots"] or "prev bots" in clean_lower:
        page = max(0, context.user_data.get('bots_page', 0) - 1)
        await show_my_bots(update, context, page=page)
        return True
    if clean_lower in ["next bots"] or "next bots" in clean_lower:
        page = context.user_data.get('bots_page', 0) + 1
        await show_my_bots(update, context, page=page)
        return True

    # Quick Templates
    if (
        clean_lower in ["quick templates", "quick template deploy", "quick template", "/templates"]
        or "quick template" in clean_lower
        or "quick templates" in clean_lower
    ):
        await show_templates_menu(update, context)
        return True

    # Account & Slots
    if (
        clean_lower in ["my account & slots", "my account", "account & slots", "/account", "/slots"]
        or "my account" in clean_lower
        or "account & slots" in clean_lower
    ):
        await show_account_info(update, context)
        return True

    # Referral Hub & Slot Rewards
    if (
        clean_lower in ["refer & earn slots", "refer & earn free slots", "refer & earn", "referral rewards", "/referral", "/ref"]
        or "refer & earn" in clean_lower
        or "referral" in clean_lower
    ):
        await show_referral_hub(update, context)
        return True

    # Channel Promotion & Advertising
    if (
        clean_lower in ["channel promotion", "promote your channel", "promote channel", "channel promo", "promo", "/promote", "/promo", "/promotion"]
        or "channel promotion" in clean_lower
        or "promote" in clean_lower
        or "promo" in clean_lower
    ):
        await show_channel_promotion(update, context)
        return True

    # Help & Guidelines
    if (
        clean_lower in ["help & guidelines", "help", "guidelines", "/help"]
        or "help & guidelines" in clean_lower
    ):
        await show_help(update, context)
        return True

    # Customer Support Desk
    if (
        clean_lower in ["customer support", "support", "helpdesk", "/support", "/helpdesk"]
        or "customer support" in clean_lower
    ):
        await show_support_desk(update, context)
        return True

    # Export Backup (Global / Standalone)
    if (
        clean_lower in ["export backup", "export data backup", "/backup", "/export"]
        or "export backup" in clean_lower
    ):
        await export_bot_data_handler(update, context)
        return True

    # Check for template clicks from templates menu
    for k, v in TEMPLATES.items():
        t_clean = normalize_user_input(v['name']).replace("⇋", "").strip().lower()
        t_raw_clean = re.sub(r'^[^\w\s]+', '', v['name']).strip().lower()
        if clean_lower in (t_clean, t_raw_clean) or clean_lower.startswith(t_clean) or clean_lower.startswith(t_raw_clean) or t_clean in clean_lower or t_raw_clean in clean_lower:
            context.user_data['deploy_template_key'] = k
            await template_select_start(update, context)
            return True

    # Bot Item Selection: e.g. "⇋ My Bot [#a1b2c3d4] ⇋"
    bot_select_match = re.search(r"\[#([a-zA-Z0-9_-]+)\]", clean_text) or re.search(r"\[#([a-zA-Z0-9_-]+)\]", raw_text)
    action_keywords = ["start", "stop", "restart", "logs", "delete", "env vars", "export backup", "backup", "add variable", "delete variable", "confirm delete", "cancel delete"]
    if bot_select_match and not any(k in clean_lower for k in action_keywords):
        bot_id = bot_select_match.group(1)
        await show_bot_details(update, context, bot_id)
        return True

    # Bot Actions from keyboard buttons
    if bot_select_match:
        bot_id = bot_select_match.group(1)
        if "start bot" in clean_lower or ("start" in clean_lower and "bot" in clean_lower):
            await handle_bot_action(update, context, "start", bot_id)
            return True
        elif "stop bot" in clean_lower or ("stop" in clean_lower and "bot" in clean_lower):
            await handle_bot_action(update, context, "stop", bot_id)
            return True
        elif "restart bot" in clean_lower or ("restart" in clean_lower and "bot" in clean_lower):
            await handle_bot_action(update, context, "restart", bot_id)
            return True
        elif "view logs" in clean_lower or "logs" in clean_lower:
            await handle_bot_action(update, context, "logs", bot_id)
            return True
        elif "manage env vars" in clean_lower or "env vars" in clean_lower:
            await user_env_start(update, context, bot_id=bot_id)
            return True
        elif "export backup" in clean_lower or "backup" in clean_lower:
            await export_bot_data_handler(update, context, bot_id=bot_id)
            return True
        elif "confirm delete" in clean_lower:
            await handle_bot_action(update, context, "delete_execute", bot_id)
            return True
        elif "cancel delete" in clean_lower:
            await handle_bot_action(update, context, "cancel_delete", bot_id)
            return True
        elif "delete bot" in clean_lower:
            await handle_bot_action(update, context, "delete_confirm", bot_id)
            return True

    return False

# =========================================================
# Project Data Backup Exporter (.zip)
# =========================================================

async def export_bot_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id: str = None):
    """Exports a hosted bot's complete data directory as a downloadable .zip archive."""
    user = update.effective_user
    user_id = user.id

    if bot_id is None and update.message and update.message.text:
        m = re.search(r"\[#([a-zA-Z0-9_-]+)\]", update.message.text)
        if m:
            bot_id = m.group(1)

    if not bot_id:
        bot_id = context.user_data.get('env_bot_id') or context.user_data.get('bot_id')

    if not bot_id:
        user_bots = database.get_user_bots(user_id)
        if len(user_bots) == 1:
            bot_id = user_bots[0]['bot_id']
        else:
            await send_clean_screen(
                update,
                context,
                "<blockquote>⚠️ <b>Bot ID not specified:</b> Please select a bot from <b>⇋ 𝗠𝘆 𝗛𝗼𝘀𝘁𝗲𝗱 𝗕𝗼𝘁𝘀 ⇋</b> first.</blockquote>",
                reply_markup=get_my_bots_reply_keyboard(user_bots)
            )
            return

    bot_data = database.get_bot(bot_id)
    if not bot_data or (bot_data['user_id'] != user_id and user_id != ADMIN_ID):
        await send_clean_screen(
            update,
            context,
            "<blockquote>⚠️ Bot not found or unauthorized access.</blockquote>",
            reply_markup=get_back_to_main_keyboard()
        )
        return

    await send_clean_screen(update, context, "📦 <i>Generating complete project backup .zip archive...</i>")

    zip_path = bot_manager.create_bot_backup_zip(bot_id, user_id)
    if not zip_path or not os.path.exists(zip_path):
        await send_clean_screen(update, context, "<blockquote>❌ <b>Backup Failed:</b> Could not package bot workspace directory.</blockquote>")
        return

    chat_id = update.effective_chat.id if update.effective_chat else user_id
    try:
        bot_name = bot_data.get('bot_name', 'bot')
        clean_name = re.sub(r'[^a-zA-Z0-9_-]', '_', bot_name)
        safe_filename = f"backup_{clean_name}_{bot_id}.zip"
        caption = (
            f"<b>💾 PROJECT BACKUP ARCHIVE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<blockquote>🤖 <b>Bot:</b> {html.escape(bot_name)} (<code>#{bot_id}</code>)\n"
            f"📦 <b>Archive:</b> <code>{safe_filename}</code>\n"
            "Includes all script source files, configs, and local databases.</blockquote>"
        )
        with open(zip_path, "rb") as doc_file:
            sent_doc = await context.bot.send_document(
                chat_id=chat_id,
                document=doc_file,
                filename=safe_filename,
                caption=caption,
                parse_mode="HTML"
            )
        if sent_doc:
            database.record_chat_message(chat_id, sent_doc.message_id)
            old_mids = database.get_old_chat_messages(chat_id, keep_count=2)
            for mid in old_mids:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=mid)
                except Exception:
                    pass
            if old_mids:
                database.delete_chat_message_records(chat_id, old_mids)
    except Exception as e:
        logger.error(f"Error sending backup document: {e}")
        await send_clean_screen(update, context, f"<blockquote>❌ <b>Failed to send backup:</b> {html.escape(str(e))}</blockquote>")
    finally:
        try:
            if os.path.exists(zip_path):
                os.remove(zip_path)
        except Exception:
            pass

# =========================================================
# Custom Environment Variables (.env) Conversation Handler
# =========================================================

async def user_env_start(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id: str = None) -> int:
    user = update.effective_user
    user_id = user.id

    if bot_id is None and update.message and update.message.text:
        m = re.search(r"\[#([a-zA-Z0-9_-]+)\]", update.message.text)
        if m:
            bot_id = m.group(1)

    if bot_id is None and update.callback_query and update.callback_query.data:
        data = update.callback_query.data
        if data.startswith("ubot_env_"):
            bot_id = data.split("_")[2]

    if not bot_id:
        bot_id = context.user_data.get('env_bot_id') or context.user_data.get('bot_id')

    if not bot_id:
        user_bots = database.get_user_bots(user_id)
        if len(user_bots) == 1:
            bot_id = user_bots[0]['bot_id']
        else:
            await send_clean_screen(
                update,
                context,
                "<blockquote>⚠️ Please select a bot from <b>⇋ 𝗠𝘆 𝗛𝗼𝘀𝘁𝗲𝗱 𝗕𝗼𝘁𝘀 ⇋</b> first to manage environment variables.</blockquote>",
                reply_markup=get_my_bots_reply_keyboard(user_bots)
            )
            return ConversationHandler.END

    bot_data = database.get_bot(bot_id)
    if not bot_data or (bot_data['user_id'] != user_id and user_id != ADMIN_ID):
        await send_clean_screen(
            update,
            context,
            "<blockquote>⚠️ Bot not found or unauthorized access.</blockquote>",
            reply_markup=get_back_to_main_keyboard()
        )
        return ConversationHandler.END

    context.user_data['env_bot_id'] = bot_id
    context.user_data['active_flow'] = 'user_env'

    env_vars = database.get_bot_env_vars(bot_id) if hasattr(database, "get_bot_env_vars") else {}
    has_vars = bool(env_vars)

    var_lines = []
    if env_vars:
        for k, v in env_vars.items():
            masked_v = f"{v[:3]}...{v[-3:]}" if len(v) > 8 else ("••••••••" if len(v) > 0 else "<i>empty</i>")
            var_lines.append(f"• <code>{html.escape(k)}</code> = <code>{html.escape(masked_v)}</code>")
        vars_display = "\n".join(var_lines)
    else:
        vars_display = "<i>No custom environment variables configured yet.</i>"

    header = make_header_card("ENV VARS MANAGER", "Runtime Environment (.env)")
    safe_name = html.escape(bot_data.get('bot_name', 'Bot'))

    text = (
        f"{header}\n\n"
        f"🤖 <b>Target Bot:</b> <b>{safe_name}</b> (<code>#{html.escape(bot_id)}</code>)\n\n"
        "<b>📦 Configured Variables:</b>\n"
        f"<blockquote>{vars_display}</blockquote>\n\n"
        "<b>⚙️ Available Actions:</b>\n"
        "<blockquote>• <b>⇋ 𝗔𝗱𝗱 𝗩𝗮𝗿𝗶𝗮𝗯𝗹𝗲 ⇋:</b> Save a new KEY=VALUE pair\n"
        "• <b>⇋ 𝗗𝗲𝗹𝗲𝘁𝗲 𝗩𝗮𝗿𝗶𝗮𝗯𝗹𝗲 ⇋:</b> Remove a variable key\n"
        "• <b>⇋ 𝗕𝗮𝗰𝗸 𝘁𝗼 𝗕𝗼𝘁 ⇋:</b> Return to bot details</blockquote>\n\n"
        "💡 <i>Variables are automatically injected on next process start/restart.</i>"
    )

    reply_kb = get_env_menu_keyboard(has_vars=has_vars)
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass
    await send_clean_screen(update, context, text, reply_markup=reply_kb)
    return U_ENV_CHOICE

async def user_env_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return U_ENV_CHOICE
    raw_text = update.message.text.strip()
    clean_text = normalize_user_input(raw_text).replace("⇋", "").strip()
    clean_lower = clean_text.lower()
    bot_id = context.user_data.get('env_bot_id')

    if is_cancellation_text(raw_text) or "back to bot" in clean_lower or "back to bot inspector" in clean_lower or "back to bot details" in clean_lower or "back to my bots" in clean_lower or "main menu" in clean_lower or clean_lower == "cancel":
        return await cancel_user_env(update, context)

    if "add variable" in clean_lower or "set variable" in clean_lower:
        await send_clean_screen(
            update,
            context,
            "<b>➕ ADD ENVIRONMENT VARIABLE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "<blockquote>Please send the variable <b>KEY name</b> (e.g. <code>OPENAI_API_KEY</code>, <code>DATABASE_URL</code>, <code>ADMIN_ID</code>):</blockquote>\n\n"
            "👇 <i>Send the key name or tap <b>⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋</b>:</i>",
            reply_markup=get_cancel_keyboard()
        )
        return U_ENV_ADD_KEY

    elif "delete variable" in clean_lower or "remove variable" in clean_lower:
        await send_clean_screen(
            update,
            context,
            "<b>🗑️ DELETE ENVIRONMENT VARIABLE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "<blockquote>Please send the exact <b>KEY name</b> of the variable you want to delete:</blockquote>\n\n"
            "👇 <i>Send the key name or tap <b>⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋</b>:</i>",
            reply_markup=get_cancel_keyboard()
        )
        return U_ENV_DEL_KEY

    else:
        return await user_env_start(update, context, bot_id=bot_id)

async def user_env_add_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return U_ENV_ADD_KEY
    text = update.message.text.strip()
    norm_t = normalize_user_input(text).replace("⇋", "").strip().lower()
    bot_id = context.user_data.get('env_bot_id')

    if is_cancellation_text(text) or norm_t in ["cancel", "back", "back to bot"]:
        return await user_env_start(update, context, bot_id=bot_id)

    # Check if user sent KEY=VALUE directly in one message
    if "=" in text:
        parts = text.split("=", 1)
        key_name = parts[0].strip()
        val_str = parts[1].strip()
        if not re.match(r"^[A-Za-z0-9_]{1,64}$", key_name):
            await send_clean_screen(
                update,
                context,
                "<blockquote>⚠️ <b>Invalid Key Name:</b> Variable name can only contain letters, numbers, and underscores (max 64 chars).</blockquote>",
                reply_markup=get_cancel_keyboard()
            )
            return U_ENV_ADD_KEY
        if hasattr(database, "set_bot_env_var"):
            database.set_bot_env_var(bot_id, key_name, val_str)
        await send_clean_screen(
            update,
            context,
            f"<blockquote>✅ Variable <code>{html.escape(key_name)}</code> saved successfully!</blockquote>"
        )
        return await user_env_start(update, context, bot_id=bot_id)

    key_name = text.strip()
    if not re.match(r"^[A-Za-z0-9_]{1,64}$", key_name):
        await send_clean_screen(
            update,
            context,
            "<blockquote>⚠️ <b>Invalid Key Name:</b> Key can only contain letters, numbers, and underscores (max 64 chars).\n"
            "Example: <code>OPENAI_API_KEY</code></blockquote>",
            reply_markup=get_cancel_keyboard()
        )
        return U_ENV_ADD_KEY

    context.user_data['env_temp_key'] = key_name
    await send_clean_screen(
        update,
        context,
        f"<b>🔑 VARIABLE VALUE FOR <code>{html.escape(key_name)}</code></b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<blockquote>Please send the <b>VALUE</b> for <code>{html.escape(key_name)}</code>:</blockquote>\n\n"
        "👇 <i>Send the value or tap <b>⇋ 𝗖𝗮𝗻𝗰𝗲𝗹 ⇋</b>:</i>",
        reply_markup=get_cancel_keyboard()
    )
    return U_ENV_ADD_VAL

async def user_env_add_val(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return U_ENV_ADD_VAL
    val_str = update.message.text.strip()
    norm_t = normalize_user_input(val_str).replace("⇋", "").strip().lower()
    bot_id = context.user_data.get('env_bot_id')
    key_name = context.user_data.pop('env_temp_key', None)

    if is_cancellation_text(val_str) or norm_t in ["cancel", "back", "back to bot"]:
        return await user_env_start(update, context, bot_id=bot_id)

    if not key_name:
        return await user_env_start(update, context, bot_id=bot_id)

    if hasattr(database, "set_bot_env_var"):
        database.set_bot_env_var(bot_id, key_name, val_str)

    await send_clean_screen(
        update,
        context,
        f"<blockquote>✅ Variable <code>{html.escape(key_name)}</code> saved successfully!</blockquote>"
    )
    return await user_env_start(update, context, bot_id=bot_id)

async def user_env_del_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return U_ENV_DEL_KEY
    text = update.message.text.strip()
    norm_t = normalize_user_input(text).replace("⇋", "").strip().lower()
    bot_id = context.user_data.get('env_bot_id')

    if is_cancellation_text(text) or norm_t in ["cancel", "back", "back to bot"]:
        return await user_env_start(update, context, bot_id=bot_id)

    key_name = text.strip()
    deleted = False
    if hasattr(database, "delete_bot_env_var"):
        deleted = database.delete_bot_env_var(bot_id, key_name)

    if deleted:
        await send_clean_screen(
            update,
            context,
            f"<blockquote>🗑️ Variable <code>{html.escape(key_name)}</code> deleted successfully!</blockquote>"
        )
    else:
        await send_clean_screen(
            update,
            context,
            f"<blockquote>⚠️ Variable <code>{html.escape(key_name)}</code> not found.</blockquote>"
        )
    return await user_env_start(update, context, bot_id=bot_id)

async def cancel_user_env(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    bot_id = context.user_data.pop('env_bot_id', None)
    context.user_data.pop('active_flow', None)
    context.user_data.pop('env_temp_key', None)
    if bot_id:
        await show_bot_details(update, context, bot_id=bot_id)
    else:
        await show_my_bots(update, context, page=0)
    return ConversationHandler.END

user_env_conv = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex(r"(?i)^(?:.*Manage Env Vars|.*Env Vars|.*𝗠𝗮𝗻𝗮𝗴𝗲 𝗘𝗻𝘃 𝗩𝗮𝗿𝘀).*"), user_env_start),
        CallbackQueryHandler(user_env_start, pattern=r"^ubot_env_"),
        CommandHandler("env", user_env_start)
    ],
    states={
        U_ENV_CHOICE: [
            MessageHandler(filters.Regex(r"(?i)^(?:.*Add Variable|.*Set Variable|.*𝗔𝗱𝗱 𝗩𝗮𝗿𝗶𝗮𝗯𝗹𝗲).*"), user_env_choice),
            MessageHandler(filters.Regex(r"(?i)^(?:.*Delete Variable|.*Remove Variable|.*𝗗𝗲𝗹𝗲𝘁𝗲 𝗩𝗮𝗿𝗶𝗮𝗯𝗹𝗲).*"), user_env_choice),
            MessageHandler(filters.Regex(r"(?i)^(?:.*Back to Bot|.*Back to Bot Inspector|.*Back to Bot Details|.*𝗕𝗮𝗰𝗸 𝘁𝗼 𝗕𝗼𝘁).*"), cancel_user_env),
            MessageHandler(filters.TEXT & ~filters.COMMAND, user_env_choice)
        ],
        U_ENV_ADD_KEY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, user_env_add_key)
        ],
        U_ENV_ADD_VAL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, user_env_add_val)
        ],
        U_ENV_DEL_KEY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, user_env_del_key)
        ]
    },
    fallbacks=[
        CommandHandler("cancel", cancel_user_env),
        MessageHandler(filters.Regex(r"(?i)^(?:.*Cancel|.*𝗖𝗮𝗻𝗰𝗲𝗹|/cancel|cancel|.*Back to Bot|.*Back to My Bots|.*Back to Main Menu|.*Main Menu).*"), cancel_user_env),
        CallbackQueryHandler(cancel_user_env, pattern="^(cancel_env|user_menu)$")
    ],
    conversation_timeout=600,
    per_message=False
)

# =========================================================
# Direct Document Upload Handler (.py / .zip)
# =========================================================

async def handle_direct_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles direct upload of .py or .zip files outside active conversations."""
    if not update.message or not update.message.document:
        return
    doc = update.message.document
    fname = doc.file_name or "file"
    user_id = update.effective_user.id
    if fname.endswith(".py") or fname.endswith(".zip"):
        text = (
            "<b>📦 PROJECT FILE / ARCHIVE RECEIVED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<blockquote>File: <code>{html.escape(fname)}</code>\n\n"
            "To deploy this Python project as a 24/7 cloud bot instance, tap <b>⇋ 𝗛𝗼𝘀𝘁 𝗡𝗲𝘄 𝗕𝗼𝘁 ⇋</b> to launch the deployment wizard!</blockquote>"
        )
        await send_clean_screen(
            update,
            context,
            text,
            reply_markup=get_main_reply_keyboard(user_id)
        )
