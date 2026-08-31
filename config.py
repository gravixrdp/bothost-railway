import os

# Read secrets from the environment only. A hardcoded fallback here once let
# stale services keep polling Telegram with the real token even after their
# BOT_TOKEN was set to DISABLED, which caused permanent 409 getUpdates
# conflicts and broke every multi-step menu flow.
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
DATA_DIR = os.getenv("DATA_DIR", "/data")
DEFAULT_MAX_BOTS_PER_USER = int(os.getenv("DEFAULT_MAX_BOTS_PER_USER", "3"))
MAX_LOG_LINES = int(os.getenv("MAX_LOG_LINES", "100"))

# Ensure base directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "bots"), exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "logs"), exist_ok=True)
