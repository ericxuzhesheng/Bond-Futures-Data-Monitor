"""China Treasury bond futures quote collector."""

from __future__ import annotations

from datetime import date as Date
from typing import Any


CONTRACTS = ("TS", "TF", "T", "TL")


def collect_futures_quotes(run_date: str, use_live_data: bool = True) -> list[dict[str, object]]:
    """Collect CFFEX Treasury futures quotes from real market-data sources."""

    if not use_live_data:
        raise RuntimeError("Sample data is disabled; futures quotes must come from a live source.")

    rows = _collect_cffex_daily(run_date)
    if len({row["contract"] for row in rows}) == len(CONTRACTS):
        return rows

    secondary_rows = _collect_sina_main(run_date)
    if len({row["contract"] for row in secondary_rows}) == len(CONTRACTS):
        return secondary_rows

    available = sorted({row["contract"] for row in rows + secondary_rows})
    raise RuntimeError(
        "Live futures quote coverage is incomplete: "
        f"expected {list(CONTRACTS)}, got {available or 'none'} for {run_date}."
    )


def _collect_cffex_daily(run_date: str) -> list[dict[str, object]]:
    try:
        import akshare as ak  # type: ignore
    except Exception as exc:
        raise RuntimeError("AKShare is required for CFFEX futures quotes.") from exc

    trade_date = Date.fromisoformat(run_date).strftime("%Y%m%d")
    try:
        daily = ak.get_cffex_daily(date=trade_date)
    except Exception:
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
        rows.append(_cffex_row(run_date, contract, main, trade_date))
    return rows


def _cffex_row(run_date: str, contract: str, row: Any, trade_date: str) -> dict[str, object]:
    pre_settle = _as_float(row.get("pre_settle"))
    close_price = _as_float(row["close"])
    daily_return = close_price / pre_settle - 1 if pre_settle else 0.0
    return {
        "date": run_date,
        "contract": contract,
        "close_price": close_price,
        "daily_return": daily_return,
        "volume": _as_float(row["volume"]),
        "open_interest": _as_float(row["open_interest"]),
        "data_source": f"akshare_cffex_daily:{trade_date}",
    }


def _collect_sina_main(run_date: str) -> list[dict[str, object]]:
    try:
        import akshare as ak  # type: ignore
    except Exception as exc:
        raise RuntimeError("AKShare is required for Sina continuous futures quotes.") from exc

    rows: list[dict[str, object]] = []
    symbol_map = {"TS": "TS0", "TF": "TF0", "T": "T0", "TL": "TL0"}
    for contract, symbol in symbol_map.items():
        try:
            history = ak.futures_zh_daily_sina(symbol=symbol)
        except Exception:
            continue
        if history is None or history.empty or "date" not in history.columns:
            continue
        matched = history[history["date"].astype(str) == run_date]
        if matched.empty:
            continue
        row = matched.iloc[-1]
        close_price = _as_float(row["close"])
        open_price = _as_float(row["open"])
        rows.append(
            {
                "date": run_date,
                "contract": contract,
                "close_price": close_price,
                "daily_return": close_price / open_price - 1 if open_price else 0.0,
                "volume": _as_float(row["volume"]),
                "open_interest": _as_float(row["hold"]),
                "data_source": f"akshare_sina_main_daily:{symbol}",
            }
        )
    return rows


def _as_float(value: object) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)
