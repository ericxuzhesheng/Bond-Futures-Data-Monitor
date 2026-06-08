"""Application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    database_path: Path = Path(os.getenv("DATABASE_PATH", "data/bond_futures_monitor.db"))
    reports_output_dir: Path = Path(os.getenv("REPORTS_OUTPUT_DIR", "reports_output"))
    use_live_data: bool = os.getenv("USE_LIVE_DATA", "0").strip().lower() in {"1", "true", "yes"}


def get_settings() -> Settings:
    """Return current application settings."""

    return Settings()
