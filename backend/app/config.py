from __future__ import annotations
import os
from pathlib import Path

PROJECT_NAME = "幕窗钟"
DB_PATH = Path(
    os.environ.get("CURTAINCLOCK_DB")
    or (Path(__file__).resolve().parents[2] / "data" / "curtainclock.db")
)
