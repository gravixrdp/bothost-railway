import asyncio
import logging
import os
import sys
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes
)
from config import BOT_TOKEN, ADMIN_ID
import database
from bot_manager import bot_manager
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
    admin_fsub_conv
)
from user_handlers import (
    start_command,
    show_my_bots,
    show_account_info,
    show_help,
    show_templates_menu,
    show_bot_details,
    handle_bot_action,
    user_callback_handler,
    user_text_router,
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

async def post_init(application):
    logger.info("Initializing Gravix-Host Database & Storage...")
    database.init_db()

    asyncio.create_task(bot_manager.watchdog_loop())

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
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        handled = await handle_admin_text(update, context)
        if handled:
            return
    handled = await user_text_router(update, context)
    if handled:
        return

    nav_card = (
        "╭━━━━━━━━━━━━━━━━━━━━━━━━━━━━╮\n"
        "│  💡 <b>ɢʀᴀᴠɪx-ʜᴏsᴛ ɴᴀᴠɪɢᴀᴛɪᴏɴ</b>\n"
        "╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯\n"
        "<blockquote>Please use the interactive buttons on your keyboard below or send <code>/start</code> to access the main dashboard.</blockquote>"
    )
    await update.message.reply_text(
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
    # Conversation Handlers
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    host_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(host_bot_start, pattern="^user_host_start$"),
            MessageHandler(filters.Regex("^(➕ Host New Bot|➕ Host Custom Bot|➕ Host Another Bot)$"), host_bot_start)
        ],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, host_bot_name)],
            TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, host_bot_token)],
            CODE: [
                MessageHandler(filters.Document.ALL, host_bot_code),
                MessageHandler(filters.TEXT & ~filters.COMMAND, host_bot_code)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_host),
            MessageHandler(filters.Regex("^(❌ Cancel|/cancel|cancel|🔙 Back to Main Menu)$"), cancel_host),
            CallbackQueryHandler(cancel_host, pattern="^(cancel_host|user_menu)$")
        ],
        conversation_timeout=CONV_TIMEOUT,
        per_message=False
    )

    tpl_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(template_select_start, pattern="^deploy_tpl_"),
            MessageHandler(filters.Regex("^(📢 Simple Echo & Info Bot|🛡️ Group Welcome Bot|📣 Broadcast Bot.*)$"), template_select_start)
        ],
        states={
            TPL_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, template_token_received)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_tpl),
            MessageHandler(filters.Regex("^(❌ Cancel|/cancel|cancel|🔙 Back to Main Menu)$"), cancel_tpl),
            CallbackQueryHandler(cancel_tpl, pattern="^(cancel_tpl|user_menu)$")
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
    application.add_handler(CommandHandler("mybots", show_my_bots))

    # 2. Multi-Step Conversation Handlers
    application.add_handler(host_conv)
    application.add_handler(tpl_conv)
    application.add_handler(admin_fsub_conv)

    # 3. User Navigation & Primary Menus
    application.add_handler(MessageHandler(filters.Regex("^(🔙 Back to Main Menu|🏠 Main Menu|🔄 Refresh)$"), start_command))
    application.add_handler(MessageHandler(filters.Regex("^🤖 My Hosted Bots$"), show_my_bots))
    application.add_handler(MessageHandler(filters.Regex("^🔙 Back to My Bots$"), show_my_bots))
    application.add_handler(MessageHandler(filters.Regex("^⚡ Quick Template Deploy$"), show_templates_menu))
    application.add_handler(MessageHandler(filters.Regex("^📊 My Account & Slots$"), show_account_info))
    application.add_handler(MessageHandler(filters.Regex("^❓ Help & Guidelines$"), show_help))

    # 4. User Bots Pagination, Details, & Actions
    application.add_handler(MessageHandler(filters.Regex("^(⬅️ Prev Bots|Next Bots ➡️)$"), user_text_router))
    application.add_handler(MessageHandler(filters.Regex(r"^(?:🟢|🔴|⚪)\s+.*\[#([a-zA-Z0-9_-]+)\]$"), show_bot_details))
    application.add_handler(MessageHandler(filters.Regex(r"^(?:▶️ Start Bot|⏹️ Stop Bot|🔄 Restart Bot|📜 View Logs|🗑️ Delete Bot)\s+\[#([a-zA-Z0-9_-]+)\]$"), handle_bot_action))
    application.add_handler(MessageHandler(filters.Regex(r"^(?:⚠️ Confirm Delete|❌ Cancel Delete)\s+\[#([a-zA-Z0-9_-]+)\]$"), handle_bot_action))

    # 5. Admin Panel Open / Navigation / Stats
    application.add_handler(MessageHandler(filters.Regex("^(👑 Open Admin Panel|🔄 Refresh Admin|🔙 Back to Admin|🏠 Back to Admin)$"), admin_panel))
    application.add_handler(MessageHandler(filters.Regex("^🏠 Exit Admin$"), admin_exit_handler))
    application.add_handler(MessageHandler(filters.Regex("^📊 System Stats$"), admin_stats_handler))

    # 6. Admin Users Management
    application.add_handler(MessageHandler(filters.Regex("^(👥 User Manager|🔙 Back to Users)$"), admin_users_list_handler))
    application.add_handler(MessageHandler(filters.Regex("^(⬅️ Prev Users|Next Users ➡️)$"), handle_admin_text))
    application.add_handler(MessageHandler(filters.Regex(r"^👤\s+.+\s+\(UID:\s*\d+\)$"), admin_user_detail_handler))
    application.add_handler(MessageHandler(filters.Regex(r"^(?:🔓 Unban User|🚫 Ban User)\s+\[UID:\s*\d+\]$"), admin_user_action_handler))
    application.add_handler(MessageHandler(filters.Regex(r"^➕ Add \+2 Slots\s+\[UID:\s*\d+\]$"), admin_user_action_handler))

    # 7. Admin Bots Management
    application.add_handler(MessageHandler(filters.Regex("^(🤖 All Hosted Bots|🔙 Back to All Bots)$"), admin_bots_list_handler))
    application.add_handler(MessageHandler(filters.Regex("^(⬅️ Prev All Bots|Next All Bots ➡️)$"), handle_admin_text))
    application.add_handler(MessageHandler(filters.Regex(r"^(?:▶️ Force Start|⏹️ Stop|🔄 Restart|📜 View Logs|🗑️ Force Delete)\s+\[#[a-zA-Z0-9_-]+\]$"), admin_bot_action_handler))

    # 8. Admin Force-Sub Channel Management
    application.add_handler(MessageHandler(filters.Regex("^(📢 Force-Sub Channels|🔙 Back to Force-Sub)$"), admin_fsub_list_handler))
    application.add_handler(MessageHandler(filters.Regex("^(⬅️ Prev FSub|Next FSub ➡️)$"), handle_admin_text))
    application.add_handler(MessageHandler(filters.Regex(r"^🗑️ Remove\s+.+\s+\[.+\]$"), admin_fsub_del_handler))

    # 9. Admin Maintenance & Global Broadcast Announcement
    application.add_handler(MessageHandler(filters.Regex(r"^⚙️ Toggle Maintenance.*"), admin_toggle_maint_handler))
    application.add_handler(MessageHandler(filters.Regex("^(📢 Broadcast Announcement|📢 Broadcast Message)$"), admin_broadcast_prompt_handler))

    # 10. Legacy Callback Query Handlers
    application.add_handler(CallbackQueryHandler(handle_admin_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(user_callback_handler))

    # 11. General Fallback Text Router
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, general_message_router))

    # 12. Global Error Handler
    application.add_error_handler(error_handler)

    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
