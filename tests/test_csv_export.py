import csv

from bond_futures_monitor.database import (
    connect,
    init_db,
    upsert_daily_features,
    upsert_daily_market_signal,
)
from bond_futures_monitor.features.daily_features import build_daily_features
from bond_futures_monitor.reports.csv_export import export_features_csv
from bond_futures_monitor.signals.rule_based import generate_market_signal
from tests.test_report import RUN_DATE, seed_real_source_rows


def _read_csv(path):
    with path.open(encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def test_export_features_csv_writes_one_row_per_date(tmp_path):
    with connect(tmp_path / "monitor.db") as conn:
        init_db(conn)
        seed_real_source_rows(conn)
        features = build_daily_features(conn, RUN_DATE)
        upsert_daily_features(conn, features)
        upsert_daily_market_signal(conn, generate_market_signal(features))

        path = export_features_csv(conn, tmp_path)

        rows = _read_csv(path)
        assert len(rows) == 1
        row = rows[0]
        assert row["date"] == RUN_DATE
        assert row["market_view"] in {"bullish", "bearish", "neutral"}
        assert row["total_score"] != ""
        # Spreads derive from same-day yields seeded by the fixture.
        assert float(row["spread_10y_2y"]) != 0.0
        # Every per-dimension score column is present and populated.
        for column in (
            "score_rate_direction",
            "score_curve_shape",
            "score_funding",
            "score_omo",
            "score_futures_volume_price",
            "score_text_signal",
            "score_macro",
        ):
            assert row[column] != "", f"missing score column {column}"


def test_export_features_csv_is_idempotent_and_cumulative(tmp_path):
    with connect(tmp_path / "monitor.db") as conn:
        init_db(conn)
        second_date = "2026-06-09"
        for run_date in (RUN_DATE, second_date):
            seed_real_source_rows(conn, run_date)
            features = build_daily_features(conn, run_date)
            upsert_daily_features(conn, features)
            upsert_daily_market_signal(conn, generate_market_signal(features))

        first = _read_csv(export_features_csv(conn, tmp_path))
        second = _read_csv(export_features_csv(conn, tmp_path))

        assert first == second
        assert [row["date"] for row in first] == [RUN_DATE, second_date]
