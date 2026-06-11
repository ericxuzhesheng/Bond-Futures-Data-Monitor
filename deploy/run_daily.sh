#!/usr/bin/env bash
# Daily pipeline payload for the ECS cron installed by aliyun_deploy.sh.
# Mirrors .github/workflows/daily-report.yml: pull latest, run the pipeline in
# docker, commit the report + CSV + database, rebase, push.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${APP_DIR}"

RUN_DATE=$(TZ=Asia/Shanghai date +%F)
echo "=== bond-futures-monitor run ${RUN_DATE} ($(date -u +%FT%TZ)) ==="

# Start from the latest main so the DB snapshot includes prior days.
git pull --rebase origin main

docker run --rm \
    --env-file .env \
    -v "${APP_DIR}/data:/app/data" \
    -v "${APP_DIR}/reports_output:/app/reports_output" \
    bond-futures-monitor run --date "${RUN_DATE}"

git config user.name "aliyun-runner"
git config user.email "aliyun-runner@noreply.local"
git add -f "reports_output/${RUN_DATE}_daily_report.md" reports_output/daily_features.csv
git add data/bond_futures_monitor.db
if git diff --cached --quiet; then
    echo "No changes to commit."
else
    git commit -m "report: update daily bond futures report ${RUN_DATE}"
    git pull --rebase origin main && git push \
        || (git pull --rebase origin main && git push)
fi
echo "=== done ==="
