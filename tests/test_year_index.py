from bond_futures_monitor.reports.year_index import generate_year_index


def test_index_refresh_includes_daily_reports_without_rewriting_history(tmp_path):
    records = ("backfill_2026_manifest.json", "2026_warmup_validation.json", "2026_omo_scope_repair.json")
    for name in records:
        (tmp_path / name).write_text('{"end": "2026-09-01"}', encoding="utf-8")
    original = {name: (tmp_path / name).read_bytes() for name in records}
    for day in ("2026-09-01", "2025-12-31", "2026-01-05", "2027-01-04"):
        (tmp_path / f"{day}_daily_report.md").write_text("report", encoding="utf-8")
    generate_year_index(tmp_path, 2026)
    (tmp_path / "2026-10-29_daily_report.md").write_text("report", encoding="utf-8")
    path = generate_year_index(tmp_path, 2026)
    content = path.read_text(encoding="utf-8")
    assert "截至 2026-10-29，已生成 3 期日报。" in content
    assert content.index("## 2026-01") < content.index("## 2026-09") < content.index("## 2026-10")
    assert "[2026-10-29](2026-10-29_daily_report.md)" in content
    assert "2025-12-31" not in content and "2027-01-04" not in content
    assert "不代表交易日覆盖完整" in content
    for name in records:
        assert f"]({name})" in content
        assert (tmp_path / name).read_bytes() == original[name]
    generate_year_index(tmp_path, 2026)
    assert path.read_text(encoding="utf-8") == content


def test_new_year_index_does_not_require_backfill_records(tmp_path):
    (tmp_path / "2027-01-04_daily_report.md").write_text("report", encoding="utf-8")
    content = generate_year_index(tmp_path, 2027).read_text(encoding="utf-8")
    assert "截至 2027-01-04，已生成 1 期日报。" in content
    assert "[2027-01-04](2027-01-04_daily_report.md)" in content
    assert ".json" not in content
