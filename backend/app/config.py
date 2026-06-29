import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
DATA_DIR = Path(os.environ.get("AZS_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.environ.get("AZS_DB_PATH", DATA_DIR / "azs.db"))
PHOTO_DIR = Path(os.environ.get("AZS_PHOTO_DIR", DATA_DIR / "photos"))
PHOTO_DIR.mkdir(parents=True, exist_ok=True)

FRONTEND_DIR = Path(os.environ.get("AZS_FRONTEND_DIR", BASE_DIR.parent / "frontend"))

# Data freshness windows (hours)
FRESH_HOURS = float(os.environ.get("AZS_FRESH_HOURS", 6))      # status considered current
STALE_HOURS = float(os.environ.get("AZS_STALE_HOURS", 24))     # after this, status dropped

# Report rate limit per device (seconds between reports for the same station)
REPORT_COOLDOWN_SEC = int(os.environ.get("AZS_REPORT_COOLDOWN", 30))

# Fuel types tracked
FUEL_TYPES = ["ai92", "ai95", "ai98", "dt", "gas"]
FUEL_LABELS = {
    "ai92": "АИ-92",
    "ai95": "АИ-95",
    "ai98": "АИ-98",
    "dt": "ДТ",
    "gas": "Газ",
}

# Station statuses
STATUSES = ["have", "low", "queue", "none", "closed"]
STATUS_LABELS = {
    "have": "Есть топливо",
    "low": "Заканчивается",
    "queue": "Большая очередь",
    "none": "Нет топлива",
    "closed": "Закрыта",
}
