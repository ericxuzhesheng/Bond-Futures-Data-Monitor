"""Production data-quality checks."""

from __future__ import annotations

import sqlite3


REQUIRED_CONTRACTS = {"TS", "TF", "T", "TL"}
REQUIRED_TENORS = {"1Y", "2Y", "5Y", "10Y", "30Y"}
SHIBOR_RATE_NAMES = {"SHIBOR_ON", "SHIBOR_7D"}
WEIGHTED_REPO_RATE_NAMES = {"DR001", "DR007", "R007"}
FIXING_REPO_RATE_NAMES = {"FDR001", "FDR007", "FR007"}
REQUIRED_MACRO_INDICATORS = {"LPR_1Y", "LPR_5Y", "CPI_YOY", "PPI_YOY", "PMI_MFG"}


def validate_real_data_coverage(conn: sqlite3.Connection, run_date: str) -> None:
    """Fail fast when the daily run does not satisfy real-data coverage requirements."""

    _assert_no_sample_sources(conn, run_date)
    checks = [
        _coverage_check(conn, "futures_quotes", "contract", run_date, REQUIRED_CONTRACTS),
        _coverage_check(conn, "bond_yields", "tenor", run_date, REQUIRED_TENORS),
        _funding_coverage_check(conn, run_date),
        _coverage_check(conn, "macro_indicators", "indicator", run_date, REQUIRED_MACRO_INDICATORS),
    ]
    # PBC pages or their historical maturity notice can occasionally be
    # unreachable. A missing OMO row is tolerated and scored neutral rather
    # than failing otherwise complete market data.

    # Policy/news is an optional text signal. Public feeds may carry no relevant
    # item for a day; the rule engine then scores this dimension as neutral.

    total_rows = sum(
        conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE date = ?", (run_date,)).fetchone()["n"]
        for table in (
            "futures_quotes",
            "bond_yields",
            "funding_rates",
            "open_market_operations",
            "policy_news",
            "macro_indicators",
        )
    )
    if total_rows < 5:
        checks.append(f"daily data rows: expected at least 5 real rows, got {total_rows}")

    failures = [item for item in checks if item]
    if failures:
        raise RuntimeError("Real-data coverage check failed: " + "; ".join(failures))


def _coverage_check(
    conn: sqlite3.Connection,
    table: str,
    field: str,
    run_date: str,
    required: set[str],
) -> str:
    rows = conn.execute(f"SELECT DISTINCT {field} FROM {table} WHERE date = ?", (run_date,)).fetchall()
    available = {str(row[field]) for row in rows}
    missing = sorted(required - available)
    if missing:
        return f"{table}.{field}: missing {missing}; available {sorted(available) or 'none'}"
    return ""


def _funding_coverage_check(conn: sqlite3.Connection, run_date: str) -> str:
    rows = conn.execute(
        "SELECT DISTINCT rate_name FROM funding_rates WHERE date = ?",
        (run_date,),
    ).fetchall()
    available = {str(row["rate_name"]) for row in rows}
    missing_shibor = SHIBOR_RATE_NAMES - available
    has_repo_set = WEIGHTED_REPO_RATE_NAMES.issubset(available) or FIXING_REPO_RATE_NAMES.issubset(available)
    if not missing_shibor and has_repo_set:
        return ""
    return (
        "funding_rates.rate_name: expected "
        f"{sorted(SHIBOR_RATE_NAMES)} plus either {sorted(WEIGHTED_REPO_RATE_NAMES)} "
        f"or {sorted(FIXING_REPO_RATE_NAMES)}; available {sorted(available) or 'none'}"
    )


def _assert_no_sample_sources(conn: sqlite3.Connection, run_date: str) -> None:
    tables = (
        "futures_quotes",
        "bond_yields",
        "funding_rates",
        "open_market_operations",
        "policy_news",
        "macro_indicators",
    )
    sample_hits = []
    for table in tables:
        rows = conn.execute(
            f"SELECT DISTINCT data_source FROM {table} WHERE date = ? AND lower(data_source) LIKE '%sample%'",
            (run_date,),
        ).fetchall()
        sample_hits.extend(f"{table}:{row['data_source']}" for row in rows)
    if sample_hits:
        raise RuntimeError("Sample/mock data is not allowed in production output: " + ", ".join(sample_hits))
