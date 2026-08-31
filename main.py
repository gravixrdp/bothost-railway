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
    handle_admin_callback,
    broadcast_command,
    admin_fsub_conv
)
from user_handlers import (
    start_command,
    show_my_bots,
    show_account_info,
    show_help,
    show_templates_menu,
    user_callback_handler,
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
    TPL_TOKEN
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
    await update.message.reply_text("\U0001F4A1 Please use the keyboard menu buttons below or /start to interact with Gravix-Host.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update: {context.error}")

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
            MessageHandler(filters.Regex("^(❌ Cancel|/cancel|cancel)$"), cancel_host),
            CallbackQueryHandler(cancel_host, pattern="^(cancel_host|user_menu)$")
        ],
        conversation_timeout=CONV_TIMEOUT,
        per_message=False
    )

    tpl_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(template_select_start, pattern="^deploy_tpl_")],
        states={
            TPL_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, template_token_received)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_tpl),
            MessageHandler(filters.Regex("^(❌ Cancel|/cancel|cancel)$"), cancel_tpl),
            CallbackQueryHandler(cancel_tpl, pattern="^(cancel_tpl|user_menu)$")
        ],
        conversation_timeout=CONV_TIMEOUT,
        per_message=False
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("broadcast", broadcast_command))

    application.add_handler(host_conv)
    application.add_handler(tpl_conv)
    application.add_handler(admin_fsub_conv)

    # Persistent reply keyboard button handlers
    application.add_handler(MessageHandler(filters.Regex("^👑 Open Admin Panel$"), admin_panel))
    application.add_handler(MessageHandler(filters.Regex("^🤖 My Hosted Bots$"), show_my_bots))
    application.add_handler(MessageHandler(filters.Regex("^⚡ Quick Template Deploy$"), show_templates_menu))
    application.add_handler(MessageHandler(filters.Regex("^📊 My Account & Slots$"), show_account_info))
    application.add_handler(MessageHandler(filters.Regex("^❓ Help & Guidelines$"), show_help))
    application.add_handler(MessageHandler(filters.Regex("^🔄 Refresh$"), start_command))

    application.add_handler(CallbackQueryHandler(handle_admin_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(user_callback_handler))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, general_message_router))

    application.add_error_handler(error_handler)

    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
