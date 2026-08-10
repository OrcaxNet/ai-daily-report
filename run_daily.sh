#!/usr/bin/env bash
# AI 日报每日任务入口（由 Multica autopilot agent 在每日 08:00 Asia/Shanghai 调用）。
# 用法: ./run_daily.sh [--date YYYY-MM-DD] [--push]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

DATE=""
PUSH="no"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --date) DATE="$2"; shift 2 ;;
    --push) PUSH="yes"; shift ;;
    *) shift ;;
  esac
done
if [[ -z "$DATE" ]]; then
  DATE="$(TZ=Asia/Shanghai date +%F)"
fi

# 环境准备
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt

# 自动重试一次（PRD §5.3：间隔 5 分钟）
if ! .venv/bin/python -m ai_daily_report run --date "$DATE"; then
  echo "[run_daily] 首次失败，5 分钟后重试一次（PRD §5.3）"
  sleep 300
  .venv/bin/python -m ai_daily_report run --date "$DATE"
fi

# 发布到 gh-pages（由调用方决定是否 --push；autopilot 场景恒推送）
if [[ "$PUSH" == "yes" || "${AI_DAILY_AUTOPILOT:-}" == "1" ]]; then
  echo "[run_daily] push site/ -> gh-pages"
  python3 - <<'PY'
import os, subprocess, sys
from pathlib import Path
root = Path.cwd()
site = root / "site"
if not site.exists():
    sys.exit(0)
# 轻量发布：把 site 内容同步到 gh-pages 分支工作树
subprocess.run(["git", "fetch", "origin", "gh-pages", "--depth=1"], check=False)
branches = subprocess.run(["git", "branch", "--list", "gh-pages"], capture_output=True, text=True).stdout.strip()
if branches:
    subprocess.run(["git", "checkout", "gh-pages"], check=True)
else:
    subprocess.run(["git", "checkout", "--orphan", "gh-pages"], check=True)
    subprocess.run(["git", "rm", "-rf", "--ignore-unmatch", "."], check=False)
# 拷贝 site 内容到工作树
import shutil
for item in site.iterdir():
    dst = root / item.name
    if dst.exists():
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    shutil.move(str(item), str(dst))
subprocess.run(["git", "add", "-A"], check=True)
changed = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
if changed:
    subprocess.run(["git", "commit", "-m", f"chore(site): publish AI daily report {DATE}"], check=True)
    subprocess.run(["git", "push", "origin", "gh-pages"], check=True)
    print("[run_daily] gh-pages pushed")
else:
    print("[run_daily] no site changes")
PY
  # 回 main 分支，提交 data 状态
  git checkout main 2>/dev/null || true
  git add data/state.json data/reports/ 2>/dev/null || true
  if git diff --cached --quiet; then
    echo "[run_daily] no data changes"
  else
    git commit -m "chore(data): update report state for ${DATE}" || true
    git push origin main || true
  fi
fi

echo "[run_daily] done ${DATE}"
