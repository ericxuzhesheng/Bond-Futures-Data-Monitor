"""China Treasury bond futures quote collector."""

from __future__ import annotations

from datetime import date as Date


CONTRACTS = ("TS", "TF", "T", "TL")


def collect_futures_quotes(run_date: str, use_live_data: bool = False) -> list[dict[str, object]]:
    """Collect futures quotes, falling back to deterministic sample data."""

    if use_live_data:
        live_rows = _try_collect_akshare(run_date)
        if live_rows:
            return live_rows
    return sample_futures_quotes(run_date)


def sample_futures_quotes(run_date: str) -> list[dict[str, object]]:
    base = {
        "TS": (101.245, 0.0007, 18230, 52210),
        "TF": (102.870, 0.0011, 36120, 80420),
        "T": (104.355, 0.0016, 72880, 153400),
        "TL": (108.640, 0.0022, 45890, 96710),
    }
    return [
        {
            "date": run_date,
            "contract": contract,
            "close_price": close,
            "daily_return": daily_return,
            "volume": volume,
            "open_interest": open_interest,
            "data_source": "sample_fallback",
        }
        for contract, (close, daily_return, volume, open_interest) in base.items()
    ]


def _try_collect_akshare(run_date: str) -> list[dict[str, object]]:
    """Collect CFFEX Treasury futures from AKShare."""

    try:
        import akshare as ak  # type: ignore
    except Exception:
        return []

    trade_date = Date.fromisoformat(run_date).strftime("%Y%m%d")
    try:
        daily = ak.get_cffex_daily(date=trade_date)
    except Exception:
        return []

    if daily.empty or "variety" not in daily.columns:
        return []

    rows: list[dict[str, object]] = []
    for contract in CONTRACTS:
        subset = daily[daily["variety"].astype(str).str.upper() == contract].copy()
        if subset.empty:
            continue
        subset["volume"] = subset["volume"].astype(float)
        main = subset.sort_values("volume", ascending=False).iloc[0]
        pre_settle = float(main.get("pre_settle") or 0)
        close_price = float(main["close"])
        daily_return = close_price / pre_settle - 1 if pre_settle else 0.0
        rows.append(
            {
                "date": run_date,
                "contract": contract,
                "close_price": close_price,
                "daily_return": daily_return,
                "volume": float(main["volume"]),
                "open_interest": float(main["open_interest"]),
                "data_source": "akshare_cffex_daily",
            }
        )
    return rows
