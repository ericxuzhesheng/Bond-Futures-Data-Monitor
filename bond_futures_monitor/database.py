"""SQLite database helpers for the bond futures monitor."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS futures_quotes (
    date TEXT NOT NULL,
    contract TEXT NOT NULL,
    close_price REAL NOT NULL,
    daily_return REAL NOT NULL,
    volume REAL NOT NULL,
    open_interest REAL NOT NULL,
    data_source TEXT NOT NULL,
    PRIMARY KEY (date, contract)
);

CREATE TABLE IF NOT EXISTS bond_yields (
    date TEXT NOT NULL,
    tenor TEXT NOT NULL,
    yield_value REAL NOT NULL,
    data_source TEXT NOT NULL,
    PRIMARY KEY (date, tenor)
);

CREATE TABLE IF NOT EXISTS funding_rates (
    date TEXT NOT NULL,
    rate_name TEXT NOT NULL,
    rate_value REAL NOT NULL,
    data_source TEXT NOT NULL,
    PRIMARY KEY (date, rate_name)
);

CREATE TABLE IF NOT EXISTS policy_news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    content TEXT NOT NULL,
    url TEXT,
    data_source TEXT NOT NULL,
    UNIQUE (date, title, source)
);

CREATE TABLE IF NOT EXISTS ai_text_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    event_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    bond_impact TEXT NOT NULL,
    affected_maturity TEXT NOT NULL,
    related_contracts TEXT NOT NULL,
    confidence INTEGER NOT NULL,
    reasoning TEXT NOT NULL,
    model_name TEXT NOT NULL,
    UNIQUE (news_id, model_name),
    FOREIGN KEY (news_id) REFERENCES policy_news(id)
);

CREATE TABLE IF NOT EXISTS daily_features (
    date TEXT PRIMARY KEY,
    yield_10y_change REAL,
    yield_30y_change REAL,
    spread_10y_2y REAL,
    spread_30y_10y REAL,
    dr007_change REAL,
    avg_futures_return REAL,
    avg_volume_change REAL,
    avg_ai_sentiment_score REAL,
    details_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_market_signals (
    date TEXT PRIMARY KEY,
    total_score REAL NOT NULL,
    market_view TEXT NOT NULL,
    key_drivers TEXT NOT NULL,
    risk_notes TEXT NOT NULL,
    details_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_time TEXT NOT NULL,
    run_date TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL
);
"""


def connect(database_path: Path | str) -> sqlite3.Connection:
    """Create a SQLite connection and ensure the parent directory exists."""

    path = Path(database_path)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Initialize all database tables."""

    conn.executescript(SCHEMA)
    conn.commit()


def insert_futures_quotes(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    return _insert_many(
        conn,
        """
        INSERT INTO futures_quotes
        (date, contract, close_price, daily_return, volume, open_interest, data_source)
        VALUES (:date, :contract, :close_price, :daily_return, :volume, :open_interest, :data_source)
        ON CONFLICT(date, contract) DO UPDATE SET
            close_price=excluded.close_price,
            daily_return=excluded.daily_return,
            volume=excluded.volume,
            open_interest=excluded.open_interest,
            data_source=excluded.data_source
        WHERE futures_quotes.close_price IS NOT excluded.close_price
           OR futures_quotes.daily_return IS NOT excluded.daily_return
           OR futures_quotes.volume IS NOT excluded.volume
           OR futures_quotes.open_interest IS NOT excluded.open_interest
           OR futures_quotes.data_source IS NOT excluded.data_source
        """,
        rows,
    )


def insert_bond_yields(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    return _insert_many(
        conn,
        """
        INSERT INTO bond_yields
        (date, tenor, yield_value, data_source)
        VALUES (:date, :tenor, :yield_value, :data_source)
        ON CONFLICT(date, tenor) DO UPDATE SET
            yield_value=excluded.yield_value,
            data_source=excluded.data_source
        WHERE bond_yields.yield_value IS NOT excluded.yield_value
           OR bond_yields.data_source IS NOT excluded.data_source
        """,
        rows,
    )


def insert_funding_rates(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    return _insert_many(
        conn,
        """
        INSERT INTO funding_rates
        (date, rate_name, rate_value, data_source)
        VALUES (:date, :rate_name, :rate_value, :data_source)
        ON CONFLICT(date, rate_name) DO UPDATE SET
            rate_value=excluded.rate_value,
            data_source=excluded.data_source
        WHERE funding_rates.rate_value IS NOT excluded.rate_value
           OR funding_rates.data_source IS NOT excluded.data_source
        """,
        rows,
    )


def insert_policy_news(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    return _insert_many(
        conn,
        """
        INSERT OR IGNORE INTO policy_news
        (date, title, source, content, url, data_source)
        VALUES (:date, :title, :source, :content, :url, :data_source)
        """,
        rows,
    )


def insert_ai_text_signal(conn: sqlite3.Connection, signal: dict[str, Any]) -> int:
    payload = dict(signal)
    payload["related_contracts"] = json.dumps(payload["related_contracts"], ensure_ascii=False)
    return _insert_many(
        conn,
        """
        INSERT INTO ai_text_signals
        (news_id, date, event_type, summary, bond_impact, affected_maturity,
         related_contracts, confidence, reasoning, model_name)
        VALUES (:news_id, :date, :event_type, :summary, :bond_impact, :affected_maturity,
                :related_contracts, :confidence, :reasoning, :model_name)
        ON CONFLICT(news_id, model_name) DO UPDATE SET
            date=excluded.date,
            event_type=excluded.event_type,
            summary=excluded.summary,
            bond_impact=excluded.bond_impact,
            affected_maturity=excluded.affected_maturity,
            related_contracts=excluded.related_contracts,
            confidence=excluded.confidence,
            reasoning=excluded.reasoning
        """,
        [payload],
    )


def upsert_daily_features(conn: sqlite3.Connection, features: dict[str, Any]) -> None:
    payload = dict(features)
    payload["details_json"] = json.dumps(payload.pop("details"), ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO daily_features
        (date, yield_10y_change, yield_30y_change, spread_10y_2y, spread_30y_10y,
         dr007_change, avg_futures_return, avg_volume_change, avg_ai_sentiment_score, details_json)
        VALUES (:date, :yield_10y_change, :yield_30y_change, :spread_10y_2y, :spread_30y_10y,
                :dr007_change, :avg_futures_return, :avg_volume_change, :avg_ai_sentiment_score, :details_json)
        ON CONFLICT(date) DO UPDATE SET
            yield_10y_change=excluded.yield_10y_change,
            yield_30y_change=excluded.yield_30y_change,
            spread_10y_2y=excluded.spread_10y_2y,
            spread_30y_10y=excluded.spread_30y_10y,
            dr007_change=excluded.dr007_change,
            avg_futures_return=excluded.avg_futures_return,
            avg_volume_change=excluded.avg_volume_change,
            avg_ai_sentiment_score=excluded.avg_ai_sentiment_score,
            details_json=excluded.details_json
        """,
        payload,
    )
    conn.commit()


def upsert_daily_market_signal(conn: sqlite3.Connection, signal: dict[str, Any]) -> None:
    payload = dict(signal)
    payload["key_drivers"] = json.dumps(payload["key_drivers"], ensure_ascii=False)
    payload["risk_notes"] = json.dumps(payload["risk_notes"], ensure_ascii=False)
    payload["details_json"] = json.dumps(payload.pop("details"), ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO daily_market_signals
        (date, total_score, market_view, key_drivers, risk_notes, details_json)
        VALUES (:date, :total_score, :market_view, :key_drivers, :risk_notes, :details_json)
        ON CONFLICT(date) DO UPDATE SET
            total_score=excluded.total_score,
            market_view=excluded.market_view,
            key_drivers=excluded.key_drivers,
            risk_notes=excluded.risk_notes,
            details_json=excluded.details_json
        """,
        payload,
    )
    conn.commit()


def log_run(conn: sqlite3.Connection, run_date: str, status: str, message: str) -> None:
    conn.execute(
        "INSERT INTO run_log (run_time, run_date, status, message) VALUES (?, ?, ?, ?)",
        (datetime.utcnow().isoformat(timespec="seconds"), run_date, status, message),
    )
    conn.commit()


def purge_sample_fallback_for_date(conn: sqlite3.Connection, run_date: str) -> None:
    """Remove sample fallback rows for a date before a live-data refresh."""

    conn.execute(
        """
        DELETE FROM ai_text_signals
        WHERE news_id IN (
            SELECT id FROM policy_news WHERE date = ? AND data_source = 'sample_fallback'
        )
        """,
        (run_date,),
    )
    conn.execute("DELETE FROM policy_news WHERE date = ? AND data_source = 'sample_fallback'", (run_date,))
    conn.execute("DELETE FROM futures_quotes WHERE date = ? AND data_source = 'sample_fallback'", (run_date,))
    conn.execute("DELETE FROM bond_yields WHERE date = ? AND data_source = 'sample_fallback'", (run_date,))
    conn.execute("DELETE FROM funding_rates WHERE date = ? AND data_source = 'sample_fallback'", (run_date,))
    conn.commit()


def fetch_policy_news(conn: sqlite3.Connection, date: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM policy_news WHERE date = ? ORDER BY id", (date,)).fetchall()


def fetch_table_for_date(conn: sqlite3.Connection, table: str, date: str) -> list[sqlite3.Row]:
    if table not in {
        "futures_quotes",
        "bond_yields",
        "funding_rates",
        "ai_text_signals",
        "daily_features",
        "daily_market_signals",
    }:
        raise ValueError(f"Unsupported table: {table}")
    return conn.execute(f"SELECT * FROM {table} WHERE date = ?", (date,)).fetchall()


def _insert_many(conn: sqlite3.Connection, sql: str, rows: Iterable[dict[str, Any]]) -> int:
    before = conn.total_changes
    conn.executemany(sql, list(rows))
    conn.commit()
    return conn.total_changes - before
