import sqlite3
import os
from datetime import datetime
from config import DATA_DIR, DEFAULT_MAX_BOTS_PER_USER

DB_PATH = os.path.join(DATA_DIR, "gravix_host.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
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
    
    # Set default maintenance mode if not exists
    cursor.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES ('maintenance_mode', '0')")
    
    conn.commit()
    conn.close()

# User Operations
def get_or_create_user(user_id: int, username: str = "", first_name: str = ""):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        joined_at = datetime.utcnow().isoformat()
        cursor.execute("""
        INSERT INTO users (user_id, username, first_name, is_banned, max_slots, joined_at)
        VALUES (?, ?, ?, 0, ?, ?)
        """, (user_id, username, first_name, DEFAULT_MAX_BOTS_PER_USER, joined_at))
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
    else:
        if user['username'] != username or user['first_name'] != first_name:
            cursor.execute("UPDATE users SET username = ?, first_name = ? WHERE user_id = ?", (username, first_name, user_id))
            conn.commit()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            user = cursor.fetchone()
            
    conn.close()
    return dict(user)

def get_all_users():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY joined_at DESC")
    users = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return users

def set_user_ban(user_id: int, is_banned: bool):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (1 if is_banned else 0, user_id))
    conn.commit()
    conn.close()

def set_user_slots(user_id: int, slots: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET max_slots = ? WHERE user_id = ?", (slots, user_id))
    conn.commit()
    conn.close()

# Bot Operations
def create_hosted_bot(bot_id: str, user_id: int, bot_name: str, bot_token: str, script_path: str):
    conn = get_connection()
    cursor = conn.cursor()
    created_at = datetime.utcnow().isoformat()
    cursor.execute("""
    INSERT INTO hosted_bots (bot_id, user_id, bot_name, bot_token, script_path, status, auto_restart, created_at, last_started)
    VALUES (?, ?, ?, ?, ?, 'STOPPED', 1, ?, NULL)
    """, (bot_id, user_id, bot_name, bot_token, script_path, created_at))
    conn.commit()
    conn.close()

def get_bot(bot_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM hosted_bots WHERE bot_id = ?", (bot_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_bots(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM hosted_bots WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def get_all_hosted_bots():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM hosted_bots ORDER BY created_at DESC")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def update_bot_status(bot_id: str, status: str):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat() if status == 'RUNNING' else None
    if now:
        cursor.execute("UPDATE hosted_bots SET status = ?, last_started = ? WHERE bot_id = ?", (status, now, bot_id))
    else:
        cursor.execute("UPDATE hosted_bots SET status = ? WHERE bot_id = ?", (status, bot_id))
    conn.commit()
    conn.close()

def delete_bot_record(bot_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM hosted_bots WHERE bot_id = ?", (bot_id,))
    conn.commit()
    conn.close()

# System Settings
def get_setting(key: str, default: str = "") -> str:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row['value'] if row else default

def set_setting(key: str, value: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()
