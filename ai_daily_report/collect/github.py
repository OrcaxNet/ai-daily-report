"""GitHub Releases 采集器（A 级一手，官方仓库发版）。"""

from __future__ import annotations

import base64
import json
import os
from datetime import timedelta
from typing import List

from ..util import parse_dt, http_get, now_shanghai, fmt_iso
from ..models import Candidate
from .base import Collector, CollectorError


def _gh_token() -> str:
    t = os.environ.get("GH_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
    if t:
        return t
    # 从 gh CLI hosts.yml 读取（运行时读取，不入库）
    try:
        p = os.path.expanduser("~/.config/gh/hosts.yml")
        if os.path.exists(p):
            import yaml
            with open(p, "r", encoding="utf-8") as f:
                hosts = yaml.safe_load(f) or {}
            for _, v in hosts.get("github.com", {}).items():
                if isinstance(v, dict) and v.get("oauth_token"):
                    return v["oauth_token"]
    except Exception:
        pass
    return ""


class GithubReleasesCollector(Collector):
    name = "github_releases"

    def collect(self) -> List[Candidate]:
        repos = self.cfg.get("repos", [])
        per = int(self.cfg.get("per_repo", 3))
        days = int(self.cfg.get("days", 3))
        cutoff = now_shanghai() - timedelta(days=days)
        token = _gh_token()
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        out: List[Candidate] = []
        for repo in repos:
            try:
                url = f"https://api.github.com/repos/{repo}/releases?per_page={per}"
                data = http_get(url, timeout=self.timeout, headers=headers).json()
                for r in data:
                    if r.get("draft") or r.get("prerelease"):
                        continue
                    published = parse_dt(r.get("published_at") or r.get("created_at") or "")
                    if published is None:
                        continue
                    if published.astimezone(now_shanghai().tzinfo) < cutoff:
                        continue
                    tag = r.get("tag_name", "")
                    title = f"{repo.split('/')[-1]} 发布 {tag}" if tag else f"{repo.split('/')[-1]} 发布新版本"
                    body = (r.get("body") or "").strip()
                    out.append(self._candidate(
                        title=title,
                        url=r.get("html_url") or url,
                        published_at=published.isoformat(timespec="seconds"),
                        summary=body[:800],
                        category_hint="AI 应用",
                        dedup_hint=f"release:{repo}:{tag}",
                        raw={"feed": "github_releases", "repo": repo, "tag": tag},
                    ))
            except Exception as e:  # noqa: BLE001
                # 单仓库失败降级，不阻塞
                continue
        return out
