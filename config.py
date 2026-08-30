import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "8318430595:AAH-lok5Gk1rZfuh_lPA_W7ak4-Yr8dOzFI")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5610858626"))
DATA_DIR = os.getenv("DATA_DIR", "/data")
DEFAULT_MAX_BOTS_PER_USER = int(os.getenv("DEFAULT_MAX_BOTS_PER_USER", "3"))
MAX_LOG_LINES = int(os.getenv("MAX_LOG_LINES", "100"))

# Ensure base directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "bots"), exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "logs"), exist_ok=True)
