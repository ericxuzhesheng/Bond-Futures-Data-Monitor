"""Funding-rate collector."""

from __future__ import annotations

import os
from datetime import date as Date


def collect_funding_rates(run_date: str, use_live_data: bool = False) -> list[dict[str, object]]:
    if use_live_data:
        live_rows = _try_collect_tushare(run_date)
        if live_rows:
            return live_rows
    return sample_funding_rates(run_date)


def sample_funding_rates(run_date: str) -> list[dict[str, object]]:
    values = {
        "DR001": 1.42,
        "DR007": 1.63,
        "R007": 1.78,
        "SHIBOR_ON": 1.45,
        "SHIBOR_7D": 1.67,
    }
    return [
        {"date": run_date, "rate_name": name, "rate_value": value, "data_source": "sample_fallback"}
        for name, value in values.items()
    ]


def _try_collect_tushare(run_date: str) -> list[dict[str, object]]:
    try:
        import tushare as ts  # type: ignore
    except Exception:
        return []

    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        return []

    trade_date = Date.fromisoformat(run_date).strftime("%Y%m%d")
    pro = ts.pro_api(token)
    rows: list[dict[str, object]] = []

    try:
        shibor = pro.shibor(date=trade_date)
        if not shibor.empty:
            first = shibor.iloc[0]
            rows.extend(
                [
                    {
                        "date": run_date,
                        "rate_name": "SHIBOR_ON",
                        "rate_value": float(first["on"]),
                        "data_source": "tushare_shibor",
                    },
                    {
                        "date": run_date,
                        "rate_name": "SHIBOR_7D",
                        "rate_value": float(first["1w"]),
                        "data_source": "tushare_shibor",
                    },
                ]
            )
    except Exception:
        pass

    try:
        repo = pro.repo_daily(trade_date=trade_date)
        if not repo.empty:
            repo_code_map = [
                ("DR001.IB", "DR001"),
                ("DR007.IB", "DR007"),
                ("R001.IB", "R001"),
                ("R007.IB", "R007"),
                ("206001.SH", "R001"),
                ("206007.SH", "R007"),
            ]
            seen_rate_names = {str(row["rate_name"]) for row in rows}
            for code, name in repo_code_map:
                if name in seen_rate_names:
                    continue
                matched = repo[repo["ts_code"].astype(str) == code]
                if not matched.empty:
                    rows.append(
                        {
                            "date": run_date,
                            "rate_name": name,
                            "rate_value": float(matched.iloc[0]["weight"]),
                            "data_source": "tushare_repo_daily",
                        }
                    )
                    seen_rate_names.add(name)
    except Exception:
        pass

    return rows
