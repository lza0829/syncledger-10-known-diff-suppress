import os
from pathlib import Path

APP_NAME = "Syncledger"
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DB_FILENAME = "app.db"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
RUNTIME_FIXTURES_DIR = DATA_DIR / "fixtures"
