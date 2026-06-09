import pytest

from bond_futures_monitor.database import connect, init_db
from bond_futures_monitor.validation import validate_real_data_coverage
from tests.test_report import RUN_DATE, seed_real_source_rows


def test_validate_real_data_coverage_passes_for_complete_live_sources(tmp_path):
    with connect(tmp_path / "monitor.db") as conn:
        init_db(conn)
        seed_real_source_rows(conn)
        validate_real_data_coverage(conn, RUN_DATE)


def test_validate_real_data_coverage_rejects_sample_sources(tmp_path):
    with connect(tmp_path / "monitor.db") as conn:
        init_db(conn)
        seed_real_source_rows(conn)
        conn.execute(
            "UPDATE futures_quotes SET data_source = 'sample_fallback' WHERE date = ? AND contract = 'TS'",
            (RUN_DATE,),
        )
        conn.commit()
        with pytest.raises(RuntimeError, match="Sample/mock data"):
            validate_real_data_coverage(conn, RUN_DATE)


def test_validate_real_data_coverage_rejects_missing_required_rows(tmp_path):
    with connect(tmp_path / "monitor.db") as conn:
        init_db(conn)
        seed_real_source_rows(conn)
        conn.execute("DELETE FROM funding_rates WHERE date = ? AND rate_name = 'DR007'", (RUN_DATE,))
        conn.commit()
        with pytest.raises(RuntimeError, match="funding_rates"):
            validate_real_data_coverage(conn, RUN_DATE)
