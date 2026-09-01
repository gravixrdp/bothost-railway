import asyncio
import logging
import os
import re
import sys
from typing import Pattern, Union, Optional

from telegram import Update, Message
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    TypeHandler,
    filters,
    ContextTypes
)
from config import BOT_TOKEN, ADMIN_ID
import database
from bot_manager import bot_manager
from code_analyzer import normalize_user_input, from_bold_sans
from admin_handlers import (
    admin_panel,
    admin_stats_handler,
    admin_users_list_handler,
    admin_user_detail_handler,
    admin_user_action_handler,
    admin_bots_list_handler,
    admin_bot_detail_handler,
    admin_bot_action_handler,
    admin_fsub_list_handler,
    admin_fsub_del_handler,
    admin_toggle_maint_handler,
    admin_broadcast_prompt_handler,
    admin_exit_handler,
    handle_admin_callback,
    handle_admin_text,
    broadcast_command,
    admin_fsub_conv,
    admin_fsub_add_start,
    admin_fsub_get_id,
    admin_fsub_get_title,
    admin_fsub_get_link,
    admin_fsub_cancel,
    A_FSUB_ID,
    A_FSUB_TITLE,
    A_FSUB_LINK,
    admin_slots_conv
)
from user_handlers import (
    send_clean_screen,
    start_command,
    show_my_bots,
    show_account_info,
    show_referral_hub,
    show_channel_promotion,
    show_help,
    show_support_desk,
    show_templates_menu,
    show_bot_details,
    handle_bot_action,
    user_callback_handler,
    user_text_router,
    export_bot_data_handler,
    user_env_conv,
    handle_direct_document_upload,
    host_bot_start,
    host_bot_name,
    host_bot_token,
    host_bot_code,
    cancel_host,
    template_select_start,
    template_token_received,
    cancel_tpl,
    NAME,
    TOKEN,
    CODE,
    TPL_TOKEN,
    get_main_reply_keyboard
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("GravixHost.Main")

# An abandoned flow keeps its in-memory state forever, and because host_conv is
# checked before tpl_conv it would swallow the next plain-text message a user
# sends - including the bot token meant for a template deploy. Expire stale
# conversations so they cannot hijack later input.
CONV_TIMEOUT = 600


# Regex pattern for stripping arrow symbols (⇋, ⇆, ⇌, ⇄, etc.)
ARROW_CHARS_REGEX = re.compile(r"[⇋⇆⇌⇄↔⇔◀▶◄►⇦⇨⇠⇢⇤⇥⇚⇛]")


def strip_arrows(text: str) -> str:
    """
    Strips decorative arrow symbols (⇋, ⇆, ⇌, ⇄, etc.) and collapses redundant whitespace.
    """
    if not isinstance(text, str) or not text:
        return ""
    cleaned = ARROW_CHARS_REGEX.sub("", text)
    return " ".join(cleaned.split())


class NormalizedRegex(filters.MessageFilter):
    """
    Message filter that normalizes message text (converting Unicode Bold Sans-Serif,
    Serif Bold, Monospace, etc. to standard ASCII text, and stripping decorative arrow symbols
    ⇋, ⇆, ⇌, ⇄) before evaluating regex patterns.
    Seamlessly matches styled '⇋ 𝗧𝗘𝗫𝗧 ⇋' arrow buttons, emoji buttons, and raw text.
    """
    __slots__ = ("pattern",)

    def __init__(self, pattern: Union[str, Pattern[str]]):
        if isinstance(pattern, str):
            pattern = re.compile(pattern)
        self.pattern: Pattern[str] = pattern
        super().__init__(name=f"NormalizedRegex({self.pattern})", data_filter=True)

    def filter(self, message: Message) -> dict[str, list[re.Match[str]]]:
        if message and message.text:
            raw = message.text
            clean = normalize_user_input(raw)
            clean_stripped = strip_arrows(clean)
            raw_stripped = strip_arrows(raw)

            # Test candidates in prioritized order:
            # 1. Cleaned ASCII with arrows stripped (e.g. "Host New Bot")
            # 2. Cleaned ASCII with arrows preserved (e.g. "⇋ Host New Bot ⇋")
            # 3. Raw text with arrows stripped (e.g. "𝗛𝗼𝘀𝘁 𝗡𝗲𝘄 𝗕𝗼𝘁")
            # 4. Raw text intact (e.g. "⇋ 𝗛𝗼𝘀𝘁 𝗡𝗲𝘄 𝗕𝗼𝘁 ⇋")
            for candidate in (clean_stripped, clean, raw_stripped, raw):
                if candidate and (match := self.pattern.search(candidate)):
                    return {"matches": [match]}
        return {}


async def purge_old_messages(bot, user_id: int, keep_count: int = 2):
    """Deletes all messages from chat history except the last `keep_count` messages."""
    if not user_id:
        return
    old_msg_ids = database.get_old_chat_messages(user_id, keep_count=keep_count)
    if not old_msg_ids:
        return
    for mid in old_msg_ids:
        try:
            await bot.delete_message(chat_id=user_id, message_id=mid)
        except Exception:
            pass
    database.delete_chat_message_records(user_id, old_msg_ids)


async def pre_update_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tracks incoming user message and deletes old messages before handler dispatch."""
    if update.effective_user and update.effective_message:
        uid = update.effective_user.id
        mid = update.effective_message.message_id
        database.record_chat_message(uid, mid)
        await purge_old_messages(context.bot, uid, keep_count=2)


async def post_init(application):
    logger.info("Initializing Gravix-Host Database & Storage...")
    database.init_db()

    # Pass Telegram bot instance to BotProcessManager and launch watchdog loop
    bot_manager.set_telegram_bot_instance(application.bot)
    bot_manager.start_watchdog(application.bot)

    all_bots = database.get_all_hosted_bots()
    resumed = 0
    for b in all_bots:
        if b.get('auto_restart') and b.get('status') == 'RUNNING':
            logger.info(f"Auto-resuming hosted bot {b['bot_id']} ({b['bot_name']})...")
            success, _ = await bot_manager.start_bot(b['bot_id'])
            if success:
                resumed += 1
    logger.info(f"Gravix-Host initialized. Auto-resumed {resumed} bot(s).")


async def general_message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text
    clean_text = normalize_user_input(text)
    clean_stripped = strip_arrows(clean_text)
    clean_lower = clean_stripped.lower()
    user_id = update.effective_user.id

    if update.message and update.effective_user:
        history = context.user_data.setdefault("chat_msg_history", [])
        if update.message.message_id not in history:
            history.append(update.message.message_id)
        while len(history) > 2:
            old_id = history.pop(0)
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=old_id)
            except Exception:
                pass

    if user_id == ADMIN_ID:
        handled = await handle_admin_text(update, context)
        if handled:
            return
    handled = await user_text_router(update, context)
    if handled:
        return

    # Fallback checking on normalized text if raw handlers didn't match
    if user_id == ADMIN_ID:
        if (
            clean_stripped in ["Open Admin Panel", "Refresh Admin", "Back to Admin", "Admin Panel", "Admin"]
            or clean_text in ["👑 Open Admin Panel", "🔄 Refresh Admin", "🔙 Back to Admin", "🏠 Back to Admin"]
        ):
            await admin_panel(update, context)
            return
        elif clean_stripped in ["Exit Admin", "Exit", "Quit"] or clean_text == "🏠 Exit Admin":
            await admin_exit_handler(update, context)
            return
        elif clean_stripped in ["System Stats", "Stats"] or clean_text == "📊 System Stats":
            await admin_stats_handler(update, context)
            return
        elif clean_stripped.startswith("Toggle Maintenance") or clean_text.startswith("⚙️ Toggle Maintenance"):
            await admin_toggle_maint_handler(update, context)
            return
        elif (
            clean_stripped in ["Broadcast Announcement", "Broadcast Message", "Broadcast"]
            or clean_text in ["📢 Broadcast Announcement", "📢 Broadcast Message"]
        ):
            await admin_broadcast_prompt_handler(update, context)
            return
        elif clean_stripped in ["User Manager", "Back to Users", "Users"] or clean_text in ["👥 User Manager", "🔙 Back to Users"]:
            page = context.user_data.get('admin_users_page', 0) if "Back to Users" in clean_stripped or clean_text == "🔙 Back to Users" else 0
            await admin_users_list_handler(update, context, page)
            return
        elif clean_stripped in ["All Hosted Bots", "Back to All Bots", "All Bots"] or clean_text in ["🤖 All Hosted Bots", "🔙 Back to All Bots"]:
            page = context.user_data.get('admin_bots_page', 0) if "Back to All Bots" in clean_stripped or clean_text == "🔙 Back to All Bots" else 0
            await admin_bots_list_handler(update, context, page)
            return
        elif clean_stripped in ["Force-Sub Channels", "Back to Force-Sub", "Force-Sub"] or clean_text in ["📢 Force-Sub Channels", "🔙 Back to Force-Sub"]:
            page = context.user_data.get('admin_fsub_page', 0) if "Back to Force-Sub" in clean_stripped or clean_text == "🔙 Back to Force-Sub" else 0
            await admin_fsub_list_handler(update, context, page)
            return

    if (
        clean_stripped in ["Main Menu", "Back to Main Menu", "Refresh", "Start", "Menu"]
        or clean_text in ["🏠 Main Menu", "🔙 Back to Main Menu", "🔄 Refresh", "/start", "/menu"]
        or clean_lower in ["/start", "/menu", "start", "menu"]
    ):
        await start_command(update, context)
        return
    elif (
        clean_stripped in ["My Hosted Bots", "Back to My Bots", "My Bots"]
        or clean_text in ["🤖 My Hosted Bots", "🔙 Back to My Bots", "/mybots", "/bots"]
        or clean_lower in ["/mybots", "/bots"]
    ):
        await show_my_bots(update, context, page=0)
        return
    elif (
        clean_stripped in ["Host New Bot", "Host Custom Bot", "Host Another Bot", "Host Bot"]
        or clean_text in ["➕ Host New Bot", "➕ Host Custom Bot", "➕ Host Another Bot"]
    ):
        await host_bot_start(update, context)
        return
    elif (
        clean_stripped in ["Quick Template Deploy", "Quick Templates", "Templates"]
        or clean_text in ["⚡ Quick Template Deploy", "⚡ Quick Templates", "/templates"]
        or clean_lower in ["/templates"]
    ):
        await show_templates_menu(update, context)
        return
    elif (
        clean_stripped in ["My Account & Slots", "My Account", "Account & Slots", "Account", "Slots"]
        or clean_text in ["📊 My Account & Slots", "/account", "/slots"]
        or clean_lower in ["/account", "/slots"]
    ):
        await show_account_info(update, context)
        return
    elif (
        clean_stripped in ["Refer & Earn Free Slots", "Refer & Earn Slots", "Refer & Earn", "Referral Rewards", "Referrals"]
        or clean_text in ["🎁 Refer & Earn Free Slots", "🎁 Refer & Earn", "🎁 Referral Rewards", "/referral", "/ref"]
        or clean_lower in ["/referral", "/ref"]
    ):
        await show_referral_hub(update, context)
        return
    elif (
        clean_stripped in ["Channel Promotion", "Promote Your Channel", "Promote Channel", "Channel Promo", "Promo"]
        or clean_text in ["📢 Channel Promotion", "/promote", "/promo", "/promotion"]
        or clean_lower in ["/promote", "/promo", "/promotion", "channel promotion"]
    ):
        await show_channel_promotion(update, context)
        return
    elif (
        clean_stripped in ["Help & Guidelines", "Help", "Guidelines"]
        or clean_text in ["❓ Help & Guidelines", "/help"]
        or clean_lower in ["/help"]
    ):
        await show_help(update, context)
        return
    elif (
        clean_stripped in ["Customer Support", "Support", "Helpdesk"]
        or clean_text in ["💬 Customer Support", "/support", "/helpdesk"]
        or clean_lower in ["/support", "/helpdesk"]
    ):
        await show_support_desk(update, context)
        return
    elif (
        clean_stripped in ["Export Backup", "Export Data Backup", "Export Data", "Backup"]
        or clean_text in ["💾 Export Backup", "💾 Export Data Backup", "/backup", "/export"]
        or clean_lower in ["/backup", "/export"]
    ):
        await export_bot_data_handler(update, context)
        return

    nav_card = (
        "<b>💡 GRAVIX-HOST NAVIGATION</b>\n"
        "<blockquote>Please use the interactive buttons on your keyboard below or send <code>/start</code> to access the main dashboard.</blockquote>"
    )
    await send_clean_screen(
        update,
        context,
        nav_card,
        reply_markup=get_main_reply_keyboard(user_id),
        parse_mode="HTML"
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)


def main():
    if not BOT_TOKEN or BOT_TOKEN == "DISABLED":
        logger.error("BOT_TOKEN environment variable is not valid! Exiting.")
        sys.exit(1)

    if not ADMIN_ID:
        logger.warning("ADMIN_ID is not set - the admin panel will be unreachable.")

    # Logged so that two instances sharing one token are obvious at a glance:
    # concurrent pollers cause 409 getUpdates conflicts and lose menu state.
    logger.info(
        "Starting Gravix-Host Telegram Master Bot (Admin: %s, service: %s, replica: %s)...",
        ADMIN_ID,
        os.getenv("RAILWAY_SERVICE_NAME", "local"),
        os.getenv("RAILWAY_REPLICA_ID", "-")
    )
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Pre-Update Global Hook (Group -1: Auto-Delete Old Messages)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    application.add_handler(TypeHandler(Update, pre_update_tracker), group=-1)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Conversation Handlers
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    cancel_filter = NormalizedRegex(
        r"(?i)^(?:[❌🔙🏠⇋⇆⇌⇄]\s*)?(?:Cancel|Back to Main Menu|Main Menu|Back to Admin|Exit Admin|Back to Users|Back to All Bots|Back to My Bots|Back to Force-Sub|Back|Exit|Quit|Abort|Stop|𝗖𝗮𝗻𝗰𝗲𝗹|𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂|𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂|𝗕𝗮𝗰𝗸 𝘁𝗼 𝗔𝗱𝗺𝗶𝗻|𝗘𝘅𝗶𝘁 𝗔𝗱𝗺𝗶𝗻)(?:\s*[❌🔙🏠⇋⇆⇌⇄])?$|"
        r"^/(?:cancel|exit|quit|abort|stop|back|menu|start)$"
    )

    host_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(host_bot_start, pattern="^user_host_start$"),
            MessageHandler(
                NormalizedRegex(r"^(?:[➕⇋⇆⇌⇄]\s*)?(?:Host New Bot|Host Custom Bot|Host Another Bot|Host Bot|𝗛𝗼𝘀𝘁 𝗡𝗲𝘄 𝗕𝗼𝘁|𝗛𝗼𝘀𝘁 𝗖𝘂𝘀𝘁𝗼𝗺 𝗕𝗼𝘁|𝗛𝗼𝘀𝘁 𝗔𝗻𝗼𝘁𝗵𝗲𝗿 𝗕𝗼𝘁)(?:\s*[⇋⇆⇌⇄])?$"),
                host_bot_start
            )
        ],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~cancel_filter, host_bot_name)],
            TOKEN: [
                MessageHandler(NormalizedRegex(r"^(?:[⏩⇋⇆⇌⇄]\s*)?(?:Skip \(Auto-Detect Token\)|Skip Auto-Detect Token|Skip|𝗦𝗸𝗶𝗽 \(𝗔𝘂𝘁𝗼-𝗗𝗲𝘁𝗲𝗰𝘁 𝗧𝗼𝗸𝗲𝗻\)|𝗦𝗸𝗶𝗽)(?:\s*[⇋⇆⇌⇄])?$"), host_bot_token),
                MessageHandler(filters.TEXT & ~filters.COMMAND & ~cancel_filter, host_bot_token)
            ],
            CODE: [
                MessageHandler(filters.Document.ALL, host_bot_code),
                MessageHandler(filters.TEXT & ~filters.COMMAND & ~cancel_filter, host_bot_code)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_host),
            MessageHandler(
                NormalizedRegex(r"(?i)^(?:[❌🔙🏠⇋⇆⇌⇄]\s*)?(?:Cancel|Back to Main Menu|Main Menu|Back to Admin|Exit Admin|Back to My Bots|Back|Exit|Quit|Abort|Stop|𝗖𝗮𝗻𝗰𝗲𝗹|𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂|𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂)(?:\s*[❌🔙🏠⇋⇆⇌⇄])?$|^(?:/cancel|/exit|/quit|/abort|/stop|/back|/menu|/start)$"),
                cancel_host
            ),
            CallbackQueryHandler(cancel_host, pattern="^(cancel_host|user_menu)$")
        ],
        conversation_timeout=CONV_TIMEOUT,
        per_message=False
    )

    tpl_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(template_select_start, pattern="^deploy_tpl_"),
            MessageHandler(
                NormalizedRegex(r"^(?:[📢🛡️📣🤖📦⚡⇋⇆⇌⇄]\s*)?(?:Simple Echo & Info Bot|Group Welcome Bot|Broadcast Bot.*|AI ChatGPT.*|Telegram File Store.*|Anti-Spam.*)(?:\s*[⇋⇆⇌⇄])?$"),
                template_select_start
            )
        ],
        states={
            TPL_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~cancel_filter, template_token_received)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_tpl),
            MessageHandler(
                NormalizedRegex(r"(?i)^(?:[❌🔙🏠⇋⇆⇌⇄]\s*)?(?:Cancel|Back to Main Menu|Main Menu|Back to Admin|Exit Admin|Back to My Bots|Back|Exit|Quit|Abort|Stop|𝗖𝗮𝗻𝗰𝗲𝗹|𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂|𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂)(?:\s*[❌🔙🏠⇋⇆⇌⇄])?$|^(?:/cancel|/exit|/quit|/abort|/stop|/back|/menu|/start)$"),
                cancel_tpl
            ),
            CallbackQueryHandler(cancel_tpl, pattern="^(cancel_tpl|user_menu)$")
        ],
        conversation_timeout=CONV_TIMEOUT,
        per_message=False
    )

    admin_fsub_conv = ConversationHandler(
        entry_points=[
            MessageHandler(
                NormalizedRegex(r"^(?:[➕⇋⇆⇌⇄]\s*)?(?:Add Force-Sub Channel|Add Force-Sub|Add Channel|𝗔𝗱𝗱 𝗙𝗼𝗿𝗰𝗲-𝗦𝘂𝗯 𝗖𝗵𝗮𝗻𝗻𝗲𝗹)(?:\s*[⇋⇆⇌⇄])?$"),
                admin_fsub_add_start
            ),
            CallbackQueryHandler(admin_fsub_add_start, pattern="^admin_fsub_add_start$"),
            CommandHandler("addchannel", admin_fsub_add_start)
        ],
        states={
            A_FSUB_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~cancel_filter, admin_fsub_get_id)],
            A_FSUB_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~cancel_filter, admin_fsub_get_title)],
            A_FSUB_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~cancel_filter, admin_fsub_get_link)],
        },
        fallbacks=[
            CommandHandler("cancel", admin_fsub_cancel),
            MessageHandler(
                NormalizedRegex(r"(?i)^(?:[❌🔙🏠⇋⇆⇌⇄]\s*)?(?:Cancel|Back to Admin|Exit Admin|Back to Users|Back to All Bots|Back to Force-Sub|Back|Exit|Quit|Abort|Stop|𝗖𝗮𝗻𝗰𝗲𝗹|𝗕𝗮𝗰𝗸 𝘁𝗼 𝗔𝗱𝗺𝗶𝗻|𝗘𝘅𝗶𝘁 𝗔𝗱𝗺𝗶𝗻)(?:\s*[❌🔙🏠⇋⇆⇌⇄])?$|^(?:/cancel|/exit|/quit|/abort|/stop|/back|/menu|/start)$"),
                admin_fsub_cancel
            ),
            CallbackQueryHandler(admin_fsub_cancel, pattern="^(admin_fsub_cancel|admin_panel)$")
        ],
        conversation_timeout=CONV_TIMEOUT,
        per_message=False
    )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Application Handler Registration
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    # 1. Primary Slash Command Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("help", show_help))
    application.add_handler(CommandHandler("support", show_support_desk))
    application.add_handler(CommandHandler("helpdesk", show_support_desk))
    application.add_handler(CommandHandler("mybots", show_my_bots))
    application.add_handler(CommandHandler("referral", show_referral_hub))
    application.add_handler(CommandHandler("ref", show_referral_hub))
    application.add_handler(CommandHandler("backup", export_bot_data_handler))
    application.add_handler(CommandHandler("export", export_bot_data_handler))

    # 2. Multi-Step Conversation Handlers
    application.add_handler(host_conv)
    application.add_handler(tpl_conv)
    application.add_handler(user_env_conv)
    application.add_handler(admin_fsub_conv)
    application.add_handler(admin_slots_conv)

    # 3. User Navigation & Primary Menus
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[🔙🏠🔄⇋⇆⇌⇄]\s*)?(?:Back to Main Menu|Main Menu|Refresh|Start|Menu|𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂|𝗠𝗮𝗶𝗻 𝗠𝗲𝗻𝘂|𝗥𝗲𝗳𝗿𝗲𝘀𝗵)(?:\s*[⇋⇆⇌⇄])?$"),
        start_command
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[🤖⇋⇆⇌⇄]\s*)?(?:My Hosted Bots|My Bots|𝗠𝘆 𝗛𝗼𝘀𝘁𝗲𝗱 𝗕𝗼𝘁𝘀|𝗠𝘆 𝗕𝗼𝘁𝘀)(?:\s*[⇋⇆⇌⇄])?$"),
        show_my_bots
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[🔙⇋⇆⇌⇄]\s*)?(?:Back to My Bots|𝗕𝗮𝗰𝗸 𝘁𝗼 𝗠𝘆 𝗕𝗼𝘁𝘀)(?:\s*[⇋⇆⇌⇄])?$"),
        show_my_bots
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[⚡⇋⇆⇌⇄]\s*)?(?:Quick Template Deploy|Quick Templates|Templates|𝗤𝘂𝗶𝗰𝗸 𝗧𝗲𝗺𝗽𝗹𝗮𝘁𝗲 𝗗𝗲𝗽𝗹𝗼𝘆|𝗤𝘂𝗶𝗰𝗸 𝗧𝗲𝗺𝗽𝗹𝗮𝘁𝗲𝘀)(?:\s*[⇋⇆⇌⇄])?$"),
        show_templates_menu
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[📊⇋⇆⇌⇄]\s*)?(?:My Account & Slots|My Account|Account & Slots|Account|Slots|𝗠𝘆 𝗔𝗰𝗰𝗼𝘂𝗻𝘁 & 𝗦𝗹𝗼𝘁𝘀|𝗠𝘆 𝗔𝗰𝗰𝗼𝘂𝗻𝘁)(?:\s*[⇋⇆⇌⇄])?$|^/(?:account|slots)$"),
        show_account_info
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[🎁⇋⇆⇌⇄]\s*)?(?:Refer & Earn Free Slots|Refer & Earn Slots|Refer & Earn|Referral Rewards|Referrals|𝗥𝗲𝗳𝗲𝗿 & 𝗘𝗮𝗿𝗻 𝗙𝗿𝗲𝗲 𝗦𝗹𝗼𝘁𝘀|𝗥𝗲𝗳𝗲𝗿 & 𝗘𝗮𝗿𝗻 𝗦𝗹𝗼𝘁𝘀|𝗥𝗲𝗳𝗲𝗿 & 𝗘𝗮𝗿𝗻|𝗥𝗲𝗳𝗲𝗿𝗿𝗮𝗹 𝗥𝗲𝘄𝗮𝗿𝗱𝘀)(?:\s*[⇋⇆⇌⇄])?$|^/(?:referral|ref)$"),
        show_referral_hub
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[❓⇋⇆⇌⇄]\s*)?(?:Help & Guidelines|Help|Guidelines|𝗛𝗲𝗹𝗽 & 𝗚𝘂𝗶𝗱𝗲𝗹𝗶𝗻𝗲𝘀)(?:\s*[⇋⇆⇌⇄])?$"),
        show_help
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[💬⇋⇆⇌⇄]\s*)?(?:Customer Support|Support|Helpdesk|𝗖𝘂𝘀𝘁𝗼𝗺𝗲𝗿 𝗦𝘂𝗽𝗽𝗼𝗿𝘁)(?:\s*[⇋⇆⇌⇄])?$|^/(?:support|helpdesk)$"),
        show_support_desk
    ))

    # 4. User Bots Pagination, Details, & Actions
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[⬅️⇋⇆⇌⇄]\s*)?(?:Prev Bots|𝗣𝗿𝗲𝘃 𝗕𝗼𝘁𝘀)|(?:Next Bots|𝗡𝗲𝘅𝘁 𝗕𝗼𝘁𝘀)(?:\s*[➡️⇋⇆⇌⇄])?$"),
        user_text_router
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[🟢🔴⚪⇋⇆⇌⇄]\s*)*.+\[#([a-zA-Z0-9_-]+)\](?:\s*[⇋⇆⇌⇄])?$"),
        show_bot_details
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[▶️⏹️🔄📜🗑️🔑⇋⇆⇌⇄]\s*)?(?:Start Bot|Stop Bot|Restart Bot|View Logs|Delete Bot|Manage Env Vars|Env Vars|Start|Stop|Restart|Logs|Delete|𝗦𝘁𝗮𝗿𝘁 𝗕𝗼𝘁|𝗦𝘁𝗼𝗽 𝗕𝗼𝘁|𝗥𝗲𝘀𝘁𝗮𝗿𝘁 𝗕𝗼𝘁|𝗩𝗶𝗲𝘄 𝗟𝗼𝗴𝘀|𝗗𝗲𝗹𝗲𝘁𝗲 𝗕𝗼𝘁|𝗠𝗮𝗻𝗮𝗴𝗲 𝗘𝗻𝘃 𝗩𝗮𝗿𝘀|𝗘𝗻𝘃 𝗩𝗮𝗿𝘀)\s*(?:[⇋⇆⇌⇄]\s*)?\[#([a-zA-Z0-9_-]+)\](?:\s*[⇋⇆⇌⇄])?$"),
        handle_bot_action
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[⚠️❌⇋⇆⇌⇄]\s*)?(?:Confirm Delete|Cancel Delete|Confirm|Cancel|𝗖𝗼𝗻𝗳𝗶𝗿𝗺 𝗗𝗲𝗹𝗲𝘁𝗲|𝗖𝗮𝗻𝗰𝗲𝗹 𝗗𝗲𝗹𝗲𝘁𝗲)\s*(?:[⇋⇆⇌⇄]\s*)?\[#([a-zA-Z0-9_-]+)\](?:\s*[⇋⇆⇌⇄])?$"),
        handle_bot_action
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[💾⇋⇆⇌⇄]\s*)?(?:Export Backup|Export Data Backup|Export Data|Backup|𝗘𝘅𝗽𝗼𝗿𝘁 𝗕𝗮𝗰𝗸𝘂𝗽|𝗘𝘅𝗽𝗼𝗿𝘁 𝗗𝗮𝘁𝗮 𝗕𝗮𝗰𝗸𝘂𝗽)\s*(?:[⇋⇆⇌⇄]\s*)?(?:\[#([a-zA-Z0-9_-]+)\])?(?:\s*[⇋⇆⇌⇄])?$"),
        export_bot_data_handler
    ))

    # 5. Admin Panel Open / Navigation / Stats
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[👑🔄🔙🏠⇋⇆⇌⇄]\s*)?(?:Open Admin Panel|Refresh Admin|Back to Admin|Admin Panel|Admin|𝗢𝗽𝗲𝗻 𝗔𝗱𝗺𝗶𝗻 𝗣𝗮𝗻𝗲𝗹|𝗥𝗲𝗳𝗿𝗲𝘀𝗵 𝗔𝗱𝗺𝗶𝗻|𝗕𝗮𝗰𝗸 𝘁𝗼 𝗔𝗱𝗺𝗶𝗻)(?:\s*[👑⇋⇆⇌⇄])?$"),
        admin_panel
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[🏠⇋⇆⇌⇄]\s*)?(?:Exit Admin|Exit|Quit|𝗘𝘅𝗶𝘁 𝗔𝗱𝗺𝗶𝗻)(?:\s*[⇋⇆⇌⇄])?$"),
        admin_exit_handler
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[📊⇋⇆⇌⇄]\s*)?(?:System Stats|Stats|𝗦𝘆𝘀𝘁𝗲𝗺 𝗦𝘁𝗮𝘁𝘀)(?:\s*[⇋⇆⇌⇄])?$"),
        admin_stats_handler
    ))

    # 6. Admin Users Management
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[👥🔙⇋⇆⇌⇄]\s*)?(?:User Manager|Back to Users|Users|𝗨𝘀𝗲𝗿 𝗠𝗮𝗻𝗮𝗴𝗲𝗿|𝗕𝗮𝗰𝗸 𝘁𝗼 𝗨𝘀𝗲𝗿𝘀)(?:\s*[⇋⇆⇌⇄])?$"),
        admin_users_list_handler
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[⬅️⇋⇆⇌⇄]\s*)?(?:Prev Users|𝗣𝗿𝗲𝘃 𝗨𝘀𝗲𝗿𝘀)|(?:Next Users|𝗡𝗲𝘅𝘁 𝗨𝘀𝗲𝗿𝘀)(?:\s*[➡️⇋⇆⇌⇄])?$"),
        handle_admin_text
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[👤⇋⇆⇌⇄]\s*)?.+\s+\((?:UID|𝗨𝗜𝗗):\s*(\d+)\)(?:\s*[⇋⇆⇌⇄])?$"),
        admin_user_detail_handler
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[🔓🚫⇋⇆⇌⇄]\s*)?(?:Unban User|Ban User|Unban|Ban|𝗨𝗻𝗯𝗮𝗻 𝗨𝘀𝗲𝗿|𝗕𝗮𝗻 𝗨𝘀𝗲𝗿)\s*(?:[⇋⇆⇌⇄]\s*)?\[(?:UID|𝗨𝗜𝗗):\s*(\d+)\](?:\s*[⇋⇆⇌⇄])?$"),
        admin_user_action_handler
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[➕➖✏️⇋⇆⇌⇄]\s*)?(?:\+1|＋1|\+𝟭|＋𝟭|-1|－1|-𝟭|－𝟭|Add \+2|Add \+2 Slots|\+2 Slots|\+2|\+𝟮|Set Custom Slots|Custom Slots|𝗦𝗲𝘁 𝗖𝘂𝘀𝘁𝗼𝗺 𝗦𝗹𝗼𝘁𝘀)\s*(?:Slot|Slots|𝗦𝗹𝗼𝘁|𝗦𝗹𝗼𝘁𝘀)?\s*(?:[⇋⇆⇌⇄]\s*)?\[(?:UID|𝗨𝗜𝗗):\s*(\d+)\](?:\s*[⇋⇆⇌⇄])?$"),
        admin_user_action_handler
    ))

    # 7. Admin Bots Management
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[🤖🔙⇋⇆⇌⇄]\s*)?(?:All Hosted Bots|Back to All Bots|All Bots|𝗔𝗹𝗹 𝗛𝗼𝘀𝘁𝗲𝗱 𝗕𝗼𝘁𝘀|𝗕𝗮𝗰𝗸 𝘁𝗼 𝗔𝗹𝗹 𝗕𝗼𝘁𝘀)(?:\s*[⇋⇆⇌⇄])?$"),
        admin_bots_list_handler
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[⬅️⇋⇆⇌⇄]\s*)?(?:Prev All Bots|Prev Bots|𝗣𝗿𝗲𝘃 𝗔𝗹𝗹 𝗕𝗼𝘁𝘀)|(?:Next All Bots|Next Bots|𝗡𝗲𝘅𝘁 𝗔𝗹𝗹 𝗕𝗼𝘁𝘀)(?:\s*[➡️⇋⇆⇌⇄])?$"),
        handle_admin_text
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[▶️⏹️🔄📜🗑️⇋⇆⇌⇄]\s*)?(?:Force Start|Stop|Restart|View Logs|Force Delete|Start|Delete|Logs|𝗙𝗼𝗿𝗰𝗲 𝗦𝘁𝗮𝗿𝘁|𝗦𝘁𝗼𝗽|𝗥𝗲𝘀𝘁𝗮𝗿𝘁|𝗩𝗶𝗲𝘄 𝗟𝗼𝗴𝘀|𝗙𝗼𝗿𝗰𝗲 𝗗𝗲𝗹𝗲𝘁𝗲)\s*(?:[⇋⇆⇌⇄]\s*)?\[#([a-zA-Z0-9_-]+)\](?:\s*[⇋⇆⇌⇄])?$"),
        admin_bot_action_handler
    ))

    # 8. Admin Force-Sub Channel Management
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[📢🔙⇋⇆⇌⇄]\s*)?(?:Force-Sub Channels|Back to Force-Sub|Force-Sub|Channels|𝗙𝗼𝗿𝗰𝗲-𝗦𝘂𝗯 𝗖𝗵𝗮𝗻𝗻𝗲𝗹𝘀|𝗕𝗮𝗰𝗸 𝘁𝗼 𝗙𝗼𝗿𝗰𝗲-𝗦𝘂𝗯)(?:\s*[⇋⇆⇌⇄])?$"),
        admin_fsub_list_handler
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[⬅️⇋⇆⇌⇄]\s*)?(?:Prev FSub|Prev Channels|𝗣𝗿𝗲𝘃 𝗙𝗦𝘂𝗯)|(?:Next FSub|Next Channels|𝗡𝗲𝘅𝘁 𝗙𝗦𝘂𝗯)(?:\s*[➡️⇋⇆⇌⇄])?$"),
        handle_admin_text
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[🗑️⇋⇆⇌⇄]\s*)?(?:Remove|Delete|Remove Channel|𝗥𝗲𝗺𝗼𝘃𝗲)\s+.+\s+\[.+\](?:\s*[⇋⇆⇌⇄])?$"),
        admin_fsub_del_handler
    ))

    # 9. Admin Maintenance & Global Broadcast Announcement
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^⚙️\s*(?:Toggle Maintenance|Maintenance|𝗧𝗼𝗴𝗴𝗹𝗲 𝗠𝗮𝗶𝗻𝘁𝗲𝗻𝗮𝗻𝗰𝗲).*|^[⇋⇆⇌⇄]\s*(?:Toggle Maintenance|Maintenance|𝗧𝗼𝗴𝗴𝗹𝗲 𝗠𝗮𝗶𝗻𝘁𝗲𝗻𝗮𝗻𝗰𝗲).*"),
        admin_toggle_maint_handler
    ))
    application.add_handler(MessageHandler(
        NormalizedRegex(r"^(?:[📢⇋⇆⇌⇄]\s*)?(?:Broadcast Announcement|Broadcast Message|Broadcast|Announcement|𝗕𝗿𝗼𝗮𝗱𝗰𝗮𝘀𝘁 𝗔𝗻𝗻𝗼𝘂𝗻𝗰𝗲𝗺𝗲𝗻𝘁|𝗕𝗿𝗼𝗮𝗱𝗰𝗮𝘀𝘁 𝗠𝗲𝘀𝘀𝗮𝗴𝗲)(?:\s*[⇋⇆⇌⇄])?$"),
        admin_broadcast_prompt_handler
    ))

    # 10. Direct Document Uploads (.py & .zip) outside active conversation
    application.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, handle_direct_document_upload))

    # 11. Legacy Callback Query Handlers
    application.add_handler(CallbackQueryHandler(handle_admin_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(user_callback_handler))

    # 12. General Fallback Text Router
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, general_message_router))

    # 13. Global Error Handler
    application.add_error_handler(error_handler)

    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()

