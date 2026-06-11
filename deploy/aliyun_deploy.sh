#!/usr/bin/env bash
# One-click deployment for an Aliyun ECS instance (Ubuntu / Alibaba Cloud Linux).
#
# Usage (on a fresh ECS as root or a sudo-capable user):
#   export TUSHARE_TOKEN=your_token
#   export REPO_URL=https://<user>:<PAT>@github.com/<user>/Bond-Futures-Data-Monitor.git
#   bash deploy/aliyun_deploy.sh
#
# What it does:
#   1. Installs docker and git when missing (Aliyun mirror for docker).
#   2. Clones/updates the repo under /opt/bond-futures-monitor.
#   3. Writes .env from TUSHARE_TOKEN.
#   4. Builds the runner image with the Aliyun PyPI mirror.
#   5. Installs a weekday-19:05-Beijing cron entry running deploy/run_daily.sh.
#
# NOTE: keep only ONE scheduler active. If this cron is enabled, disable the
# GitHub Actions schedule (or vice versa) to avoid two pushes racing on main.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/bond-futures-monitor}"
REPO_URL="${REPO_URL:?REPO_URL is required, e.g. https://user:PAT@github.com/user/Bond-Futures-Data-Monitor.git}"
TUSHARE_TOKEN="${TUSHARE_TOKEN:?TUSHARE_TOKEN is required}"
CRON_SCHEDULE="${CRON_SCHEDULE:-5 19 * * 1-5}"  # ECS runs in CST already (TZ below).

echo "==> [1/5] Installing prerequisites (docker, git, cron)"
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | bash -s -- --mirror Aliyun
    systemctl enable --now docker
fi
if ! command -v git >/dev/null 2>&1; then
    (apt-get update -y && apt-get install -y git cron) 2>/dev/null || yum install -y git cronie
fi

echo "==> [2/5] Cloning/updating repository at ${APP_DIR}"
if [ -d "${APP_DIR}/.git" ]; then
    git -C "${APP_DIR}" pull --ff-only
else
    git clone "${REPO_URL}" "${APP_DIR}"
fi

echo "==> [3/5] Writing .env"
cat > "${APP_DIR}/.env" <<EOF
DATABASE_PATH=data/bond_futures_monitor.db
REPORTS_OUTPUT_DIR=reports_output
USE_LIVE_DATA=1
TUSHARE_TOKEN=${TUSHARE_TOKEN}
EOF
chmod 600 "${APP_DIR}/.env"

echo "==> [4/5] Building docker image (Aliyun PyPI mirror)"
docker build -t bond-futures-monitor \
    --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple \
    "${APP_DIR}"

echo "==> [5/5] Installing cron entry (${CRON_SCHEDULE}, Asia/Shanghai)"
chmod +x "${APP_DIR}/deploy/run_daily.sh"
CRON_LINE="TZ=Asia/Shanghai
${CRON_SCHEDULE} ${APP_DIR}/deploy/run_daily.sh >> /var/log/bond-futures-monitor.log 2>&1"
( crontab -l 2>/dev/null | grep -v run_daily.sh | grep -v '^TZ=Asia/Shanghai$' ; echo "${CRON_LINE}" ) | crontab -

echo ""
echo "Deployed. Verify with a manual run:"
echo "  ${APP_DIR}/deploy/run_daily.sh"
echo "Logs: tail -f /var/log/bond-futures-monitor.log"
echo ""
echo "IMPORTANT: this cron pushes results to git. Disable the GitHub Actions"
echo "schedule (comment out the cron block in .github/workflows/daily-report.yml)"
echo "so only one scheduler is active."
