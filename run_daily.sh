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

echo "[run_daily] date=$DATE push=$PUSH"

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

# 发布到 gh-pages + 提交数据（autopilot 场景恒推送；--push 手动推送）
if [[ "$PUSH" == "yes" || "${AI_DAILY_AUTOPILOT:-}" == "1" ]]; then
  echo "[run_daily] deploy site/ -> gh-pages"
  python3 - "$DATE" <<'PY'
import os, subprocess, sys, shutil
from pathlib import Path

date = sys.argv[1]
root = Path.cwd()
site = root / "site"
if not site.exists():
    sys.exit("site/ missing, nothing to deploy")

def run(args, check=True):
    r = subprocess.run(args, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"cmd failed ({' '.join(args)}): {r.stderr[:500]}")
    return r

# 1) 用独立 worktree 更新 gh-pages，避免与 main 工作树冲突
wt = root.parent / "ai-daily-report-ghpages"
run(["git", "fetch", "origin", "gh-pages", "--depth=1"], check=False)
if wt.exists():
    run(["git", "worktree", "remove", str(wt), "--force"], check=False)
run(["git", "worktree", "add", str(wt), "gh-pages"])
try:
    # 清空 worktree（保留 .git）
    for item in wt.iterdir():
        if item.name == ".git":
            continue
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item)
        else:
            item.unlink()
    # 拷贝 site 内容
    for item in site.iterdir():
        shutil.move(str(item), str(wt / item.name))
    run(["git", "-C", str(wt), "add", "-A"])
    changed = run(["git", "-C", str(wt), "status", "--porcelain"]).stdout.strip()
    if changed:
        run(["git", "-C", str(wt), "commit", "-m", f"site: publish AI daily report {date}"])
        run(["git", "-C", str(wt), "push", "origin", "gh-pages"])
        print("[run_daily] gh-pages pushed")
    else:
        print("[run_daily] gh-pages no changes")
finally:
    run(["git", "worktree", "remove", str(wt), "--force"], check=False)

# 2) 提交数据状态到 main
run(["git", "add", "data/state.json", "data/reports/"])
if run(["git", "diff", "--cached", "--quiet"]).returncode != 0:
    run(["git", "commit", "-m", f"chore(data): update report state for {date}"])
    run(["git", "push", "origin", "main"])
    print("[run_daily] main data pushed")
else:
    print("[run_daily] main no data changes")
PY
fi

echo "[run_daily] done ${DATE}"
