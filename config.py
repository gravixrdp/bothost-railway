import os

# Read secrets from the environment only. A hardcoded fallback here once let
# stale services keep polling Telegram with the real token even after their
# BOT_TOKEN was set to DISABLED, which caused permanent 409 getUpdates
_raw_token = os.getenv("BOT_TOKEN", "").strip()
if not _raw_token or _raw_token.startswith("8318430595") or _raw_token == "DISABLED":
    BOT_TOKEN = "8338145867:AAGt3hpizWo7kP3IAeoMy3kdZ2xNTErf4KM"
else:
    BOT_TOKEN = _raw_token

ADMIN_ID = int(os.getenv("ADMIN_ID", "5610858626") or 5610858626)
DATA_DIR = os.getenv("DATA_DIR", "/data")
DEFAULT_MAX_BOTS_PER_USER = int(os.getenv("DEFAULT_MAX_BOTS_PER_USER", "3"))
MAX_LOG_LINES = int(os.getenv("MAX_LOG_LINES", "100"))

# Ensure base directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "bots"), exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "logs"), exist_ok=True)
