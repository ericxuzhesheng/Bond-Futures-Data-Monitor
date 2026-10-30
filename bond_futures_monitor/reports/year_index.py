"""Yearly navigation for reports already present on disk."""

from pathlib import Path


def generate_year_index(output_dir: Path, year: int) -> Path:
    reports = sorted(output_dir.glob(f"{year}-??-??_daily_report.md"))
    dates = [path.name[:10] for path in reports if path.is_file()]
    summary = f"截至 {dates[-1]}，已生成 {len(dates)} 期日报。" if dates else "尚无已生成日报。"
    lines = [f"# {year} 年国债期货日报", "", summary, "",
             "本索引随日报生成更新，按现有日报文件列出，不代表交易日覆盖完整。", ""]
    records = [
        (f"backfill_{year}_manifest.json", "历史回补清单"),
        (f"{year}_warmup_validation.json", "历史预热验收结果"),
        (f"{year}_omo_scope_repair.json", "历史 OMO 修复记录"),
    ]
    links = [f"[{label}]({name})" for name, label in records if (output_dir / name).is_file()]
    if links:
        lines.extend([
            "历史回补、验收与修复记录保留各自执行时的范围和结果，不随每日更新改写："
            + "、".join(links) + "。", "",
            "历史重建版采用重建时的排版与评分规则，不是当日实际发布的版本；"
            "月度宏观按官方发布日期截断，预热日不计入本年度日报数量。", "",
            "未缓存的历史新闻及部分补充数据仍缺失，详见每期附录与历史回补清单。"
            "部分历史曲线使用中债备用源，2年期为1年与3年线性插值，不能视为直接发布值。", "",
        ])
    month = None
    for day in dates:
        if day[:7] != month:
            if month is not None:
                lines.append("")
            month = day[:7]
            lines.extend([f"## {month}", ""])
        lines.append(f"- [{day}]({day}_daily_report.md)")
    lines.append("")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{year}_index.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
