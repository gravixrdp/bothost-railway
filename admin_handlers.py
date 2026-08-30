import os
import shutil
import psutil
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID, DATA_DIR
import database
from bot_manager import bot_manager

logger = logging.getLogger("GravixHost.Admin")

# States for admin conversation handlers if needed
A_WAIT_BROADCAST, A_WAIT_SLOTS_UID, A_WAIT_SLOTS_NUM = range(10, 13)

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ Access Denied: You are not authorized to view the Admin Panel.")
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

    keyboard = [
        [
            InlineKeyboardButton("📊 System Stats", callback_data="admin_stats"),
            InlineKeyboardButton("👥 User Manager", callback_data="admin_users_0")
        ],
        [
            InlineKeyboardButton("🤖 All Hosted Bots", callback_data="admin_bots_0"),
            InlineKeyboardButton("📢 Broadcast Message", callback_data="admin_broadcast_prompt")
        ],
        [
            InlineKeyboardButton(f"⚙️ Toggle Maintenance ({maint_status})", callback_data="admin_toggle_maint")
        ],
        [
            InlineKeyboardButton("🔄 Refresh Panel", callback_data="admin_refresh"),
            InlineKeyboardButton("🏠 Exit Admin", callback_data="user_menu")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if not is_admin(user_id):
        await query.answer("⛔ Access Denied", show_alert=True)
        return

    await query.answer()

    if data == "admin_refresh" or data == "admin_panel":
        await admin_panel(update, context)
        return

    elif data == "admin_stats":
        users = database.get_all_users()
        bots = database.get_all_hosted_bots()
        
        running_bots = sum(1 for b in bots if b['status'] == 'RUNNING')
        stopped_bots = sum(1 for b in bots if b['status'] == 'STOPPED')
        failed_bots = sum(1 for b in bots if b['status'] in ['FAILED', 'CRASHED'])

        cpu_percent = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(DATA_DIR)

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
        keyboard = [[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("admin_users_"):
        page = int(data.split("_")[2])
        users = database.get_all_users()
        per_page = 5
        total_pages = max(1, (len(users) + per_page - 1) // per_page)
        curr_users = users[page * per_page : (page + 1) * per_page]

        text = f"👥 **User Directory** (Page {page + 1}/{total_pages})\n━━━━━━━━━━━━━━━━━━━━━━\n"
        keyboard = []
        for u in curr_users:
            banned_tag = " [BANNED]" if u['is_banned'] else ""
            uname = f"@{u['username']}" if u['username'] else u['first_name'] or "No-Name"
            btn_text = f"{uname} (ID: {u['user_id']}){banned_tag}"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"admin_uinfo_{u['user_id']}")])

        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"admin_users_{page - 1}"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"admin_users_{page + 1}"))
        if nav_row:
            keyboard.append(nav_row)

        keyboard.append([InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("admin_uinfo_"):
        target_uid = int(data.split("_")[2])
        target_user = database.get_or_create_user(target_uid)
        user_bots = database.get_user_bots(target_uid)

        banned_str = "🔴 Yes (Banned)" if target_user['is_banned'] else "🟢 No (Active)"
        text = (
            f"👤 **User Detail: {target_user.get('first_name', '')}**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 **User ID:** `{target_user['user_id']}`\n"
            f"🏷️ **Username:** @{target_user.get('username') or 'N/A'}\n"
            f"🚫 **Banned:** {banned_str}\n"
            f"📦 **Slot Limit:** `{target_user.get('max_slots', 3)}` bots\n"
            f"🤖 **Hosted Bots:** `{len(user_bots)}`\n"
            f"📅 **Joined At:** `{target_user.get('joined_at', 'N/A')}`\n"
        )
        ban_btn = InlineKeyboardButton("🔓 Unban User" if target_user['is_banned'] else "🚫 Ban User", callback_data=f"admin_toggle_ban_{target_uid}")
        slot_btn = InlineKeyboardButton("➕ Add +2 Slots", callback_data=f"admin_inc_slot_{target_uid}")
        back_btn = InlineKeyboardButton("🔙 Back to Users", callback_data="admin_users_0")

        keyboard = [[ban_btn, slot_btn], [back_btn]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("admin_toggle_ban_"):
        target_uid = int(data.split("_")[3])
        target_user = database.get_or_create_user(target_uid)
        new_ban = not target_user['is_banned']
        database.set_user_ban(target_uid, new_ban)
        if new_ban:
            # stop all bots for banned user
            for b in database.get_user_bots(target_uid):
                await bot_manager.stop_bot(b['bot_id'])
        await query.answer(f"User {'banned' if new_ban else 'unbanned'} successfully!", show_alert=True)
        # return to user detail
        query.data = f"admin_uinfo_{target_uid}"
        await handle_admin_callback(update, context)

    elif data.startswith("admin_inc_slot_"):
        target_uid = int(data.split("_")[3])
        target_user = database.get_or_create_user(target_uid)
        new_slots = target_user.get('max_slots', 3) + 2
        database.set_user_slots(target_uid, new_slots)
        await query.answer(f"Slots increased to {new_slots}!", show_alert=True)
        query.data = f"admin_uinfo_{target_uid}"
        await handle_admin_callback(update, context)

    elif data.startswith("admin_bots_"):
        page = int(data.split("_")[2])
        all_bots = database.get_all_hosted_bots()
        per_page = 5
        total_pages = max(1, (len(all_bots) + per_page - 1) // per_page)
        curr_bots = all_bots[page * per_page : (page + 1) * per_page]

        text = f"🤖 **All Platform Bots** (Page {page + 1}/{total_pages})\n━━━━━━━━━━━━━━━━━━━━━━\n"
        keyboard = []
        for b in curr_bots:
            status_emoji = "🟢" if b['status'] == "RUNNING" else ("🔴" if b['status'] in ["FAILED", "CRASHED"] else "⚪")
            btn_text = f"{status_emoji} {b['bot_name']} (Owner: {b['user_id']})"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"admin_binfo_{b['bot_id']}")])

        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"admin_bots_{page - 1}"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"admin_bots_{page + 1}"))
        if nav_row:
            keyboard.append(nav_row)

        keyboard.append([InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("admin_binfo_"):
        bot_id = data.split("_")[2]
        bot_data = database.get_bot(bot_id)
        if not bot_data:
            await query.answer("Bot not found!", show_alert=True)
            return

        status_emoji = "🟢" if bot_data['status'] == "RUNNING" else ("🔴" if bot_data['status'] in ["FAILED", "CRASHED"] else "⚪")
        text = (
            f"🤖 **Bot Manager: {bot_data['bot_name']}**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 **Bot ID:** `{bot_data['bot_id']}`\n"
            f"👤 **Owner ID:** `{bot_data['user_id']}`\n"
            f"📊 **Status:** {status_emoji} `{bot_data['status']}`\n"
            f"🔑 **Token (masked):** `{bot_data['bot_token'][:10]}...{bot_data['bot_token'][-5:]}`\n"
            f"🕒 **Created:** `{bot_data['created_at']}`\n"
        )

        row1 = []
        if bot_data['status'] == 'RUNNING':
            row1.append(InlineKeyboardButton("⏹️ Stop", callback_data=f"admin_baction_stop_{bot_id}"))
            row1.append(InlineKeyboardButton("🔄 Restart", callback_data=f"admin_baction_restart_{bot_id}"))
        else:
            row1.append(InlineKeyboardButton("▶️ Force Start", callback_data=f"admin_baction_start_{bot_id}"))

        row2 = [
            InlineKeyboardButton("📜 View Logs", callback_data=f"admin_blogs_{bot_id}"),
            InlineKeyboardButton("🗑️ Force Delete", callback_data=f"admin_baction_del_{bot_id}")
        ]
        row3 = [InlineKeyboardButton("🔙 Back to All Bots", callback_data="admin_bots_0")]

        keyboard = [row1, row2, row3]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("admin_baction_"):
        parts = data.split("_")
        action = parts[2]
        bot_id = parts[3]

        if action == "start":
            success, msg = await bot_manager.start_bot(bot_id)
            await query.answer(msg, show_alert=True)
        elif action == "stop":
            success, msg = await bot_manager.stop_bot(bot_id)
            await query.answer(msg, show_alert=True)
        elif action == "restart":
            success, msg = await bot_manager.restart_bot(bot_id)
            await query.answer(msg, show_alert=True)
        elif action == "del":
            await bot_manager.stop_bot(bot_id)
            bot_data = database.get_bot(bot_id)
            if bot_data:
                script_dir = os.path.dirname(bot_data['script_path'])
                if os.path.exists(script_dir):
                    shutil.rmtree(script_dir, ignore_errors=True)
            database.delete_bot_record(bot_id)
            await query.answer("Bot forcibly deleted!", show_alert=True)
            query.data = "admin_bots_0"
            await handle_admin_callback(update, context)
            return

        query.data = f"admin_binfo_{bot_id}"
        await handle_admin_callback(update, context)

    elif data.startswith("admin_blogs_"):
        bot_id = data.split("_")[2]
        logs = bot_manager.get_logs(bot_id, lines=30)
        text = f"📜 **Logs for Bot `{bot_id}`:**\n\n```\n{logs[-3500:]}\n```"
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh Logs", callback_data=f"admin_blogs_{bot_id}")],
            [InlineKeyboardButton("🔙 Back to Bot", callback_data=f"admin_binfo_{bot_id}")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "admin_toggle_maint":
        current = database.get_setting("maintenance_mode", "0") == "1"
        new_val = "0" if current else "1"
        database.set_setting("maintenance_mode", new_val)
        await query.answer(f"Maintenance mode set to {'ON' if new_val == '1' else 'OFF'}", show_alert=True)
        await admin_panel(update, context)

    elif data == "admin_broadcast_prompt":
        text = (
            "📢 **Send Global Broadcast Announcement**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "To send a broadcast to all registered users, send a message using the command:\n\n"
            "`/broadcast Your announcement message here...`\n\n"
            "Markdown formatting is supported."
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

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
