import sqlite3
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from config import DATA_DIR, DEFAULT_MAX_BOTS_PER_USER

DB_PATH = os.path.join(DATA_DIR, "gravix_host.db")

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        
        # Optimize performance with WAL mode
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        
        # Users table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            is_banned INTEGER DEFAULT 0,
            max_slots INTEGER DEFAULT 3,
            joined_at TEXT
        )
        """)
        
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
            FOREIGN KEY (user_id) REFERENCES users (user_id)
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
        
        # Indexes for fast lookup
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_joined_at ON users(joined_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hosted_bots_user_id ON hosted_bots(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_hosted_bots_status ON hosted_bots(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_required_channels_created ON required_channels(created_at)")
        
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
            """, ('@GravixRDP_Backup', 'Backup Community', 'https://t.me/+lD-MufapiQVhMGFl', now_ts))
        
        # Set default maintenance mode if not exists
        cursor.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES ('maintenance_mode', '0')")
        
        conn.commit()
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
            if username and user['username'] != username:
                updates.append("username = ?")
                params.append(str(username))
            if first_name and user['first_name'] != first_name:
                updates.append("first_name = ?")
                params.append(str(first_name))
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
    slots_num = int(slots)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET max_slots = ? WHERE user_id = ?", (slots_num, uid))
        conn.commit()
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
    bid = str(bot_id)
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
    bid = str(bot_id)
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
    bid = str(bot_id)
    stat = str(status)
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
    bid = str(bot_id)
    val = 1 if auto_restart else 0
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE hosted_bots SET auto_restart = ? WHERE bot_id = ?", (val, bid))
        conn.commit()
    finally:
        conn.close()

def delete_bot_record(bot_id: str):
    bid = str(bot_id)
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
    k = str(key)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM system_settings WHERE key = ?", (k,))
        row = cursor.fetchone()
        return str(row['value']) if row and row['value'] is not None else default
    finally:
        conn.close()

def set_setting(key: str, value: str):
    k = str(key)
    v = str(value)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (k, v))
        conn.commit()
    finally:
        conn.close()

def delete_setting(key: str):
    k = str(key)
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
