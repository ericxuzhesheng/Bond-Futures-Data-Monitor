"""China Treasury bond futures quote collector."""

from __future__ import annotations

import logging
import math
from datetime import date as Date
from typing import Any

from bond_futures_monitor.retry import retry_call


logger = logging.getLogger(__name__)

CONTRACTS = ("TS", "TF", "T", "TL")


def collect_futures_quotes(run_date: str, use_live_data: bool = True) -> list[dict[str, object]]:
    """Collect CFFEX Treasury futures quotes from real market-data sources."""

    if not use_live_data:
        raise RuntimeError("Sample data is disabled; futures quotes must come from a live source.")

    quotes = {str(row["contract"]): row for row in _collect_cffex_daily(run_date)}
    missing = tuple(contract for contract in CONTRACTS if contract not in quotes)
    if missing:
        logger.warning("CFFEX coverage is missing %s for %s; falling back to Sina.", list(missing), run_date)
        for row in _collect_sina_main(run_date, missing):
            quotes.setdefault(str(row["contract"]), row)

    still_missing = [contract for contract in CONTRACTS if contract not in quotes]
    if still_missing:
        raise RuntimeError(
            "Live futures quote coverage is incomplete: "
            f"expected {list(CONTRACTS)}, missing {still_missing} for {run_date}."
        )
    return [quotes[contract] for contract in CONTRACTS]


def _collect_cffex_daily(run_date: str) -> list[dict[str, object]]:
    try:
        import akshare as ak  # type: ignore
    except Exception as exc:
        raise RuntimeError("AKShare is required for CFFEX futures quotes.") from exc

    trade_date = Date.fromisoformat(run_date).strftime("%Y%m%d")
    try:
        daily = retry_call(
            lambda: ak.get_cffex_daily(date=trade_date),
            description=f"CFFEX daily query for {trade_date}",
        )
    except Exception:
        logger.warning("CFFEX daily query failed for %s.", trade_date, exc_info=True)
        return []

    if daily is None or daily.empty or "variety" not in daily.columns:
        return []

    rows: list[dict[str, object]] = []
    for contract in CONTRACTS:
        subset = daily[daily["variety"].astype(str).str.upper() == contract].copy()
        if subset.empty:
            continue
        subset["volume"] = subset["volume"].astype(float)
        main = subset.sort_values("volume", ascending=False).iloc[0]
        try:
            rows.append(_cffex_row(run_date, contract, main, trade_date))
        except RuntimeError:
            logger.warning("Skipping invalid CFFEX row for %s on %s.", contract, run_date, exc_info=True)
    return rows


def _cffex_row(run_date: str, contract: str, row: Any, trade_date: str) -> dict[str, object]:
    pre_settle = _require_float(row.get("pre_settle"), "pre_settle", contract)
    close_price = _require_float(row.get("close"), "close", contract)
    if pre_settle <= 0 or close_price <= 0:
        raise RuntimeError(
            f"Non-positive price for {contract}: close={close_price}, pre_settle={pre_settle}."
        )
    return {
        "date": run_date,
        "contract": contract,
        "close_price": close_price,
        "daily_return": close_price / pre_settle - 1,
        "volume": _require_float(row.get("volume"), "volume", contract),
        "open_interest": _require_float(row.get("open_interest"), "open_interest", contract),
        "data_source": f"akshare_cffex_daily:{trade_date}",
    }


def _collect_sina_main(run_date: str, contracts: tuple[str, ...]) -> list[dict[str, object]]:
    try:
        import akshare as ak  # type: ignore
    except Exception as exc:
        raise RuntimeError("AKShare is required for Sina continuous futures quotes.") from exc

    rows: list[dict[str, object]] = []
    symbol_map = {"TS": "TS0", "TF": "TF0", "T": "T0", "TL": "TL0"}
    for contract in contracts:
        symbol = symbol_map[contract]
        try:
            history = retry_call(
                lambda symbol=symbol: ak.futures_zh_daily_sina(symbol=symbol),
                description=f"Sina daily query for {symbol}",
            )
        except Exception:
            logger.warning("Sina daily query failed for %s (%s).", contract, symbol, exc_info=True)
            continue
        if history is None or history.empty or "date" not in history.columns:
            continue
        history = history.reset_index(drop=True)
        matched_index = history.index[history["date"].astype(str) == run_date]
        if len(matched_index) == 0:
            continue
        try:
            rows.append(_sina_row(run_date, contract, symbol, history, int(matched_index[-1])))
        except RuntimeError:
            logger.warning("Skipping invalid Sina row for %s on %s.", contract, run_date, exc_info=True)
    return rows


def _sina_row(run_date: str, contract: str, symbol: str, history: Any, idx: int) -> dict[str, object]:
    row = history.iloc[idx]
    close_price = _require_float(row.get("close"), "close", contract)
    if close_price <= 0:
        raise RuntimeError(f"Non-positive close price for {contract}: {close_price}.")
    baseline = _previous_settle(history, idx, contract)
    return {
        "date": run_date,
        "contract": contract,
        "close_price": close_price,
        "daily_return": close_price / baseline - 1,
        "volume": _require_float(row.get("volume"), "volume", contract),
        "open_interest": _require_float(row.get("hold"), "hold", contract),
        "data_source": f"akshare_sina_main_daily:{symbol}",
    }


def _previous_settle(history: Any, idx: int, contract: str) -> float:
    """Previous trading day's settle (falling back to close), matching the CFFEX pre-settle basis."""

    if idx <= 0:
        raise RuntimeError(f"No previous trading day available to compute daily return for {contract}.")
    previous = history.iloc[idx - 1]
    for field in ("settle", "close"):
        value = previous.get(field)
        if value is None or value == "":
            continue
        number = float(value)
        if not math.isnan(number) and number > 0:
            return number
    raise RuntimeError(f"No usable previous settle/close for {contract}.")


def _require_float(value: object, field: str, contract: str) -> float:
    """Convert a required market-data field, failing loudly instead of silently zeroing."""

    if value is None or value == "":
        raise RuntimeError(f"Missing required field '{field}' for contract {contract}.")
    number = float(value)  # type: ignore[arg-type]
    if math.isnan(number):
        raise RuntimeError(f"Field '{field}' is NaN for contract {contract}.")
    return number
