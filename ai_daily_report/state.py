"""运行状态与幂等：data/state.json、run 日志、可追溯性。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class StateStore:
    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root)
        self.data_dir = self.repo_root / "data"
        self.reports_dir = self.data_dir / "reports"
        self.runs_dir = self.data_dir / "runs"
        self.state_path = self.data_dir / "state.json"
        for d in (self.data_dir, self.reports_dir, self.runs_dir):
            d.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"published_dates": [], "last_published_date": "", "corrections": []}

    def save(self, state: dict):
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def get_published_dates(self) -> list:
        return self.load().get("published_dates", [])

    def save_report_json(self, report: dict):
        path = self.reports_dir / f"report-{report['report_date']}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return path

    def read_report_json(self, date: str) -> Optional[dict]:
        p = self.reports_dir / f"report-{date}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return None

    def write_run_log(self, date: str, entry: dict):
        path = self.runs_dir / f"{date}.json"
        logs = []
        if path.exists():
            try:
                logs = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                logs = []
        logs.append(entry)
        path.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")

    def read_run_logs(self, date: str) -> list:
        path = self.runs_dir / f"{date}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []
