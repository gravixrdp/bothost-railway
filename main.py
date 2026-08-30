import asyncio
import logging
import signal
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
    broadcast_command
)
from user_handlers import (
    start_command,
    user_callback_handler,
    host_bot_start,
    host_bot_name,
    host_bot_token,
    host_bot_code,
    cancel_host,
    handle_template_token_input,
    NAME,
    TOKEN,
    CODE
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("GravixHost.Main")

async def post_init(application):
    logger.info("Initializing Gravix-Host Database & Storage...")
    database.init_db()

    # Start background watchdog
    asyncio.create_task(bot_manager.watchdog_loop())

    # Auto-resume previously running bots
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
    # Check if user is in template token submission flow
    handled = await handle_template_token_input(update, context)
    if not handled:
        # Default response if non-command text received
        await update.message.reply_text("💡 Please use the interactive menu buttons or /start to interact with Gravix-Host.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update: {context.error}")

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is not set! Exiting.")
        sys.exit(1)

    logger.info(f"Starting Gravix-Host Telegram Master Bot (Admin: {ADMIN_ID})...")
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Conversation handler for hosting a new custom bot
    host_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(host_bot_start, pattern="^user_host_start$")],
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
            CallbackQueryHandler(cancel_host, pattern="^cancel_host$")
        ],
        per_message=False
    )

    # Register handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(host_conv)

    # Callback query routing
    application.add_handler(CallbackQueryHandler(handle_admin_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(user_callback_handler))

    # General text messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, general_message_router))

    application.add_error_handler(error_handler)

    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
