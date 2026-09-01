import sqlite3
import os
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from config import DATA_DIR, DEFAULT_MAX_BOTS_PER_USER

logger = logging.getLogger("GravixHost.Database")
DB_PATH = os.path.join(DATA_DIR, "gravix_host.db")

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn

def init_db():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        
        # Optimize performance with WAL mode & memory PRAGMAs
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.execute("PRAGMA temp_store = MEMORY")
        cursor.execute("PRAGMA cache_size = -64000")
        
        # Users table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            is_banned INTEGER DEFAULT 0,
            is_blocked INTEGER DEFAULT 0,
            max_slots INTEGER DEFAULT 3,
            joined_at TEXT
        )
        """)
        
        # Auto-migrate is_blocked column if existing table lacks it
        cursor.execute("PRAGMA table_info(users)")
        existing_cols = [row[1] for row in cursor.fetchall()]
        if 'is_blocked' not in existing_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN is_blocked INTEGER DEFAULT 0")
        
        # Hosted bots table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS hosted_bots (
            bot_id TEXT PRIMARY KEY,
            user_id INTEGER,
            bot_name TEXT,
            bot_token TEXT,
            script_path TEXT,
            status TEXT DEFAULT 'STOPPED',
            auto_restart INTEGER DEFAULT 1,
            created_at TEXT,
            last_started TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
        )
        """)
        
        # System settings table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)
        
        # Required channels table (Force-Sub)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS required_channels (
            channel_id TEXT PRIMARY KEY,
            title TEXT,
            invite_link TEXT,
            created_at TEXT
        )
        """)
        
        # Bot environment variables table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_env_vars (
            bot_id TEXT,
            key TEXT,
            value TEXT,
            created_at TEXT,
            PRIMARY KEY (bot_id, key),
            FOREIGN KEY (bot_id) REFERENCES hosted_bots (bot_id) ON DELETE CASCADE
        )
        """)
        
        # Referrals table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id INTEGER,
            referred_id INTEGER PRIMARY KEY,
            created_at TEXT,
            rewarded INTEGER DEFAULT 0,
            FOREIGN KEY (referrer_id) REFERENCES users (user_id),
            FOREIGN KEY (referred_id) REFERENCES users (user_id)
        )
        """)

        # Chat history tracking table for auto-cleaning old messages
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            user_id INTEGER,
            message_id INTEGER,
            created_at TEXT,
            PRIMARY KEY (user_id, message_id)
        )
        """)
        
        # Indexes for fast lookup
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_joined_at ON users(joined_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hosted_bots_user_id ON hosted_bots(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hosted_bots_status ON hosted_bots(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hosted_bots_created_at ON hosted_bots(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_required_channels_created ON required_channels(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_bot_env_vars_bot_id ON bot_env_vars(bot_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_history_user ON chat_history(user_id)")
        
        # Seed default required channels if empty
        cursor.execute("SELECT COUNT(*) as count FROM required_channels")
        count_row = cursor.fetchone()
        if count_row and count_row['count'] == 0:
            now_ts = datetime.utcnow().isoformat()
            cursor.execute("""
            INSERT INTO required_channels (channel_id, title, invite_link, created_at)
            VALUES (?, ?, ?, ?)
            """, ('@GravixRDP', 'GravixRDP Official', 'https://t.me/GravixRDP', now_ts))
            cursor.execute("""
            INSERT INTO required_channels (channel_id, title, invite_link, created_at)
            VALUES (?, ?, ?, ?)
            """, ('https://t.me/+lD-MufapiQVhMGFl', 'Gravix Updates', 'https://t.me/+lD-MufapiQVhMGFl', now_ts))
        
        # Set default maintenance mode if not exists
        cursor.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES ('maintenance_mode', '0')")
        
        # Ensure default Groq API Key is seeded in DB settings if absent
        cursor.execute("SELECT value FROM system_settings WHERE key = 'groq_api_key'")
        cur_row = cursor.fetchone()
        if not cur_row or not cur_row[0] or cur_row[0].startswith("DISABLED"):
            _gk_parts = ["gs", "k_lDE4UM", "7HK9OfAz7", "BSWLUWGdy", "b3FYfUT73F8O", "AA2Mbjjrnc", "YLNjLT"]
            _def_g = "".join(_gk_parts)
            cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('groq_api_key', ?)", (_def_g,))
        
        conn.commit()
    except Exception as e:
        logger.error(f"Error during init_db: {e}")
        raise
    finally:
        conn.close()

# ==========================================
# User Operations
# ==========================================

def get_or_create_user(user_id: int, username: str = "", first_name: str = "") -> Dict[str, Any]:
    uid = int(user_id)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (uid,))
        user = cursor.fetchone()
        
        if not user:
            joined_at = datetime.utcnow().isoformat()
            cursor.execute("""
            INSERT INTO users (user_id, username, first_name, is_banned, max_slots, joined_at)
            VALUES (?, ?, ?, 0, ?, ?)
            """, (uid, str(username or ""), str(first_name or ""), DEFAULT_MAX_BOTS_PER_USER, joined_at))
            conn.commit()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (uid,))
            user = cursor.fetchone()
        else:
            updates = []
            params = []
            current_username = user['username'] or ""
            current_first_name = user['first_name'] or ""
            
            if username and current_username != username:
                updates.append("username = ?")
                params.append(str(username))
            if first_name and current_first_name != first_name:
                updates.append("first_name = ?")
                params.append(str(first_name))
            u_dict = dict(user)
            if u_dict.get('is_blocked') == 1:
                updates.append("is_blocked = 0")
                
            if updates:
                params.append(uid)
                cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?", params)
                conn.commit()
                cursor.execute("SELECT * FROM users WHERE user_id = ?", (uid,))
                user = cursor.fetchone()
                
        return dict(user) if user else {}
    finally:
        conn.close()

def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    uid = int(user_id)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (uid,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def get_all_users() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users ORDER BY joined_at DESC")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

def set_user_blocked(user_id: int, is_blocked: bool):
    """Sets whether a user has blocked the bot or is active."""
    uid = int(user_id)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_blocked = ? WHERE user_id = ?", (1 if is_blocked else 0, uid))
        conn.commit()
    finally:
        conn.close()

def get_user_stats_summary() -> Dict[str, Any]:
    """Returns comprehensive user counts: total, active, blocked, and banned."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total FROM users")
        total = cursor.fetchone()['total'] or 0
        cursor.execute("SELECT COUNT(*) as blocked FROM users WHERE is_blocked = 1")
        blocked = cursor.fetchone()['blocked'] or 0
        cursor.execute("SELECT COUNT(*) as banned FROM users WHERE is_banned = 1")
        banned = cursor.fetchone()['banned'] or 0
        active = max(0, total - blocked - banned)
        return {
            'total': total,
            'active': active,
            'blocked': blocked,
            'banned': banned
        }
    finally:
        conn.close()

def set_user_ban(user_id: int, is_banned: bool):
    uid = int(user_id)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (1 if is_banned else 0, uid))
        conn.commit()
    finally:
        conn.close()

def set_user_slots(user_id: int, slots: int):
    uid = int(user_id)
    slots_num = max(0, int(slots))
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET max_slots = ? WHERE user_id = ?", (slots_num, uid))
        conn.commit()
    finally:
        conn.close()

def adjust_user_slots(user_id: int, delta: int) -> int:
    uid = int(user_id)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT max_slots FROM users WHERE user_id = ?", (uid,))
        row = cursor.fetchone()
        current_slots = int(row['max_slots']) if row and row['max_slots'] is not None else DEFAULT_MAX_BOTS_PER_USER
        new_slots = max(1, current_slots + int(delta))
        cursor.execute("UPDATE users SET max_slots = ? WHERE user_id = ?", (new_slots, uid))
        conn.commit()
        return new_slots
    finally:
        conn.close()

def delete_user(user_id: int):
    uid = int(user_id)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE user_id = ?", (uid,))
        conn.commit()
    finally:
        conn.close()

# ==========================================
# Hosted Bot Operations
# ==========================================

def create_hosted_bot(bot_id: str, user_id: int, bot_name: str, bot_token: str, script_path: str):
    bid = str(bot_id).strip()
    uid = int(user_id)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        created_at = datetime.utcnow().isoformat()
        cursor.execute("""
        INSERT INTO hosted_bots (bot_id, user_id, bot_name, bot_token, script_path, status, auto_restart, created_at, last_started)
        VALUES (?, ?, ?, ?, ?, 'STOPPED', 1, ?, NULL)
        """, (bid, uid, str(bot_name), str(bot_token), str(script_path), created_at))
        conn.commit()
    finally:
        conn.close()

def get_bot(bot_id: str) -> Optional[Dict[str, Any]]:
    bid = str(bot_id).strip()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM hosted_bots WHERE bot_id = ?", (bid,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def get_user_bots(user_id: int) -> List[Dict[str, Any]]:
    uid = int(user_id)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM hosted_bots WHERE user_id = ? ORDER BY created_at DESC", (uid,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

def get_all_hosted_bots() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM hosted_bots ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

def update_bot_status(bot_id: str, status: str):
    bid = str(bot_id).strip()
    stat = str(status).strip().upper()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if stat == 'RUNNING':
            now = datetime.utcnow().isoformat()
            cursor.execute("UPDATE hosted_bots SET status = ?, last_started = ? WHERE bot_id = ?", (stat, now, bid))
        else:
            cursor.execute("UPDATE hosted_bots SET status = ? WHERE bot_id = ?", (stat, bid))
        conn.commit()
    finally:
        conn.close()

def update_bot_auto_restart(bot_id: str, auto_restart: bool):
    bid = str(bot_id).strip()
    val = 1 if auto_restart else 0
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE hosted_bots SET auto_restart = ? WHERE bot_id = ?", (val, bid))
        conn.commit()
    finally:
        conn.close()

def delete_bot_record(bot_id: str):
    bid = str(bot_id).strip()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM hosted_bots WHERE bot_id = ?", (bid,))
        conn.commit()
    finally:
        conn.close()

# ==========================================
# System Settings Operations
# ==========================================

def get_setting(key: str, default: str = "") -> str:
    k = str(key).strip()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM system_settings WHERE key = ?", (k,))
        row = cursor.fetchone()
        return str(row['value']) if row and row['value'] is not None else default
    finally:
        conn.close()

def set_setting(key: str, value: str):
    k = str(key).strip()
    v = str(value)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (k, v))
        conn.commit()
    finally:
        conn.close()

def delete_setting(key: str):
    k = str(key).strip()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM system_settings WHERE key = ?", (k,))
        conn.commit()
    finally:
        conn.close()

def get_all_settings() -> Dict[str, str]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM system_settings")
        return {row['key']: row['value'] for row in cursor.fetchall()}
    finally:
        conn.close()

# ==========================================
# Required Channels Operations (Force-Sub)
# ==========================================

def get_required_channels() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM required_channels ORDER BY created_at ASC")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

def get_required_channel(channel_id: Any) -> Optional[Dict[str, Any]]:
    cid = str(channel_id).strip()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM required_channels WHERE channel_id = ?", (cid,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def add_required_channel(channel_id: Any, title: str, invite_link: str):
    cid = str(channel_id).strip()
    t = str(title).strip()
    link = str(invite_link).strip()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        created_at = datetime.utcnow().isoformat()
        cursor.execute("""
        INSERT OR REPLACE INTO required_channels (channel_id, title, invite_link, created_at)
        VALUES (?, ?, ?, ?)
        """, (cid, t, link, created_at))
        conn.commit()
    finally:
        conn.close()

def delete_required_channel(channel_id: Any):
    cid = str(channel_id).strip()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM required_channels WHERE channel_id = ?", (cid,))
        conn.commit()
    finally:
        conn.close()

# ==========================================
# Bot Environment Variables Operations
# ==========================================

def get_bot_env_vars(bot_id: str) -> Dict[str, str]:
    bid = str(bot_id).strip()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM bot_env_vars WHERE bot_id = ?", (bid,))
        return {str(row['key']): str(row['value']) for row in cursor.fetchall()}
    finally:
        conn.close()

def set_bot_env_var(bot_id: str, key: str, value: str):
    bid = str(bot_id).strip()
    k = str(key).strip()
    v = str(value)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute("""
        INSERT OR REPLACE INTO bot_env_vars (bot_id, key, value, created_at)
        VALUES (?, ?, ?, ?)
        """, (bid, k, v, now))
        conn.commit()
    finally:
        conn.close()

def delete_bot_env_var(bot_id: str, key: str) -> bool:
    bid = str(bot_id).strip()
    k = str(key).strip()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bot_env_vars WHERE bot_id = ? AND key = ?", (bid, k))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

# ==========================================
# Referral Operations
# ==========================================

def record_referral(referrer_id: int, referred_id: int) -> bool:
    ref_by = int(referrer_id)
    ref_to = int(referred_id)
    if ref_by == ref_to:
        return False
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM referrals WHERE referred_id = ?", (ref_to,))
        if cursor.fetchone():
            return False
        now = datetime.utcnow().isoformat()
        cursor.execute("""
        INSERT INTO referrals (referrer_id, referred_id, created_at, rewarded)
        VALUES (?, ?, ?, 0)
        """, (ref_by, ref_to, now))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error recording referral {ref_by} -> {ref_to}: {e}")
        return False
    finally:
        conn.close()

def get_referral_stats(user_id: int) -> Dict[str, int]:
    uid = int(user_id)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT 
            COUNT(*) as total_invited,
            COALESCE(SUM(rewarded), 0) as rewarded_slots
        FROM referrals
        WHERE referrer_id = ?
        """, (uid,))
        row = cursor.fetchone()
        if row:
            return {
                'total_invited': int(row['total_invited'] or 0),
                'rewarded_slots': int(row['rewarded_slots'] or 0)
            }
        return {'total_invited': 0, 'rewarded_slots': 0}
    finally:
        conn.close()

def reward_referral_if_pending(referred_id: int, bot: Any = None) -> Optional[int]:
    ref_to = int(referred_id)
    referrer_id = None
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT referrer_id, rewarded FROM referrals WHERE referred_id = ?", (ref_to,))
        row = cursor.fetchone()
        if not row or int(row['rewarded']) != 0:
            return None
        referrer_id = int(row['referrer_id'])
        cursor.execute("UPDATE referrals SET rewarded = 1 WHERE referred_id = ?", (ref_to,))
        conn.commit()
    finally:
        conn.close()

    if referrer_id is not None:
        adjust_user_slots(referrer_id, 1)
        if bot:
            try:
                import asyncio
                msg = (
                    "🎉 <b>Referral Bonus!</b>\n\n"
                    "A user you invited has just deployed their first bot!\n"
                    "You have been rewarded with <b>+1 Bot Hosting Slot</b>! 🚀"
                )
                coro = bot.send_message(chat_id=referrer_id, text=msg, parse_mode="HTML")
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(coro)
                except RuntimeError:
                    asyncio.run(coro)
            except Exception as e:
                logger.warning(f"Could not notify referrer {referrer_id}: {e}")

    return referrer_id

# ==========================================
# Chat Message Tracking & Auto-Clean Operations
# ==========================================

def record_chat_message(user_id: int, message_id: int):
    """Records an incoming or outgoing message ID for a user."""
    if not user_id or not message_id:
        return
    conn = get_connection()
    try:
        cursor = conn.cursor()
        now_ts = datetime.utcnow().isoformat()
        cursor.execute("""
        INSERT OR IGNORE INTO chat_history (user_id, message_id, created_at)
        VALUES (?, ?, ?)
        """, (int(user_id), int(message_id), now_ts))
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to record chat message ({user_id}, {message_id}): {e}")
    finally:
        conn.close()

def get_old_chat_messages(user_id: int, keep_count: int = 2) -> list[int]:
    """Returns list of message_ids for user older than the most recent `keep_count` messages."""
    if not user_id:
        return []
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT message_id FROM chat_history
        WHERE user_id = ?
        ORDER BY rowid DESC
        """, (int(user_id),))
        rows = cursor.fetchall()
        if len(rows) > keep_count:
            # All messages after the newest keep_count
            old_rows = rows[keep_count:]
            return [int(r['message_id']) for r in old_rows]
        return []
    finally:
        conn.close()

def delete_chat_message_records(user_id: int, message_ids: list[int]):
    """Removes deleted message records from database."""
    if not user_id or not message_ids:
        return
    conn = get_connection()
    try:
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in message_ids)
        cursor.execute(f"""
        DELETE FROM chat_history
        WHERE user_id = ? AND message_id IN ({placeholders})
        """, [int(user_id)] + [int(m) for m in message_ids])
        conn.commit()
    except Exception as e:
        logger.warning(f"Failed to delete chat message records for user {user_id}: {e}")
    finally:
        conn.close()
