"""AI 日报流水线 CLI。"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import timedelta
from pathlib import Path

from . import __version__
from .config import REPO_ROOT, load_llm, load_sources
from .state import StateStore
from .models import CATEGORIES, CORE_CATEGORIES, Report
from .util import now_shanghai, fmt_iso, window_for, parse_dt
from .collect import collect_all
from .scoring import score_candidate, dedup_merge, filter_by_window, SCORE_THRESHOLD
from .generate import generate_items
from .llm import LLMClient, LLMError, CostGuardExceeded
from .assemble import render_site
from .validate import validate_report, resolve_link
from .publish import publish_site
from .notify import record_run

log = logging.getLogger("ai_daily_report")

AI_DISCLOSURE = (
    "本日报由 AI 辅助自动整理生成：内容来自公开来源白名单，经自动采集、评分与 AI 中文改写。"
    "信息仅供参考，以原始来源为准。"
)


def _setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _select_items(candidates, max_items: int = 15, min_items: int = 8):
    """筛选评分 + 栏目覆盖选择。返回 (items_with_score, empty_categories, insufficient_note)。"""
    scored = []
    for c in candidates:
        s = score_candidate(c)
        if s >= SCORE_THRESHOLD:
            scored.append((c, s))
    scored.sort(key=lambda x: x[1], reverse=True)

    selected = []
    used = set()
    # 先保证四核心栏目至少 1 条（有合格内容时）
    for cat in CORE_CATEGORIES:
        best = None
        for c, s in scored:
            if c.category_hint == cat and c.dedup_key_hint not in used:
                best = (c, s)
                break
        if best:
            selected.append(best)
            used.add(best[0].dedup_key_hint)
    # 再按分数填充
    for c, s in scored:
        if len(selected) >= max_items:
            break
        if c.dedup_key_hint not in used:
            selected.append((c, s))
            used.add(c.dedup_key_hint)

    present_cats = {c.category_hint for c, _ in selected}
    empty_categories = [c for c in CORE_CATEGORIES if c not in present_cats]

    insufficient = None
    if len(selected) < min_items:
        insufficient = f"今日候选经筛选后仅有 {len(selected)} 条达标内容（目标 8–15 条），未用低质内容凑数。"
    return selected, empty_categories, insufficient


def _replace_unreachable(selected, candidates, min_items: int = 8,
                         resolver=resolve_link):
    """校验入选链接并从已评分池替换不可达候选，同栏目优先。"""
    scored_pool = []
    for candidate in candidates:
        score = score_candidate(candidate)
        if score >= SCORE_THRESHOLD:
            scored_pool.append((candidate, score))
    scored_pool.sort(key=lambda pair: pair[1], reverse=True)

    used = {candidate.dedup_key_hint for candidate, _ in selected}
    checked = {}

    def check(candidate):
        result = checked.get(candidate.source_url)
        if result is None:
            result = resolver(candidate.source_url)
            checked[candidate.source_url] = result
        if result.usable:
            candidate.source_url = result.canonical_url
        return result

    output = []
    removed_categories = set()
    for candidate, score in selected:
        result = check(candidate)
        if result.usable:
            output.append((candidate, score))
            continue

        removed_categories.add(candidate.category_hint)
        alternatives = [
            pair for pair in scored_pool
            if pair[0].dedup_key_hint not in used
        ]
        alternatives.sort(key=lambda pair: pair[0].category_hint != candidate.category_hint)
        replacement = None
        for alternate, alternate_score in alternatives:
            used.add(alternate.dedup_key_hint)
            if check(alternate).usable:
                replacement = (alternate, alternate_score)
                break
        if replacement:
            output.append(replacement)
            log.warning("外链不可达，已替换候选: %s -> %s", candidate.source_url,
                        replacement[0].source_url)
        else:
            log.warning("外链不可达且候选池耗尽，移除: %s (%s)", candidate.source_url,
                        result.reason)

    if removed_categories and len(output) < min_items:
        raise RuntimeError(f"外链替换耗尽后仅剩 {len(output)} 条，低于硬门槛 {min_items} 条")

    before_core = {candidate.category_hint for candidate, _ in selected} & set(CORE_CATEGORIES)
    after_core = {candidate.category_hint for candidate, _ in output} & set(CORE_CATEGORIES)
    lost_core = before_core - after_core
    if lost_core:
        raise RuntimeError("外链替换耗尽后核心栏目缺失: " + "、".join(sorted(lost_core)))
    return output


def _build_report(date: str, opts) -> Report:
    state_store = StateStore(REPO_ROOT)
    sources_cfg = load_sources()
    window_start, window_end = window_for(date)

    # 步骤1 采集
    candidates, stats = collect_all(sources_cfg)
    if not candidates:
        raise RuntimeError("采集到 0 条候选，无法生成日报")

    # 步骤2 筛选评分 + 去重（含内容窗口 + 低产回看 grace）
    candidates_all = dedup_merge(candidates)
    candidates = filter_by_window(candidates_all, window_start, window_end)
    grace_note = ""
    qualified = [c for c in candidates if score_candidate(c) >= SCORE_THRESHOLD]
    grace_days = int(sources_cfg.get("collection", {}).get("grace_days", 3))
    if len(qualified) < 8 and grace_days > 0:
        # 窗口内达标不足：向前回看至多 grace_days，透明披露
        start_dt = parse_dt(window_start) - timedelta(days=grace_days)
        grace_start = fmt_iso(start_dt)
        candidates = filter_by_window(candidates_all, grace_start, window_end)
        grace_note = (
            f"本日标准内容窗口（{window_start} → {window_end}）内达标内容不足，"
            f"已向前回看至 {grace_start} 补充近期动态。"
        )
    selected, empty_categories, insufficient = _select_items(candidates, max_items=15, min_items=8)
    selected = _replace_unreachable(selected, candidates, min_items=8)
    if len(selected) >= 8:
        insufficient = None
    if not selected:
        # 无合格条目：仍产出空栏目日报（不发布低质内容）
        selected = []

    # 步骤3 生成（LLM 中文改写）
    llm = LLMClient(load_llm())
    candidate_list = [c for c, _ in selected]
    if opts.skip_llm:
        # 直接以原文作为中文条目（测试/降级模式，标题/摘要用原文）
        items = _fallback_items(candidate_list, date)
    else:
        items = generate_items(candidate_list, date, llm)
    # 回填分数
    score_map = {c.dedup_key_hint: s for c, s in selected}
    for it in items:
        it.score = score_map.get(it.dedup_key, 0.0)

    # 生成后按实际栏目重算空栏目
    present_cats = {i.category for i in items}
    empty_categories = [c for c in CORE_CATEGORIES if c not in present_cats]

    item_count = len(items)
    category_counts = {}
    for c in CATEGORIES:
        category_counts[c] = sum(1 for i in items if i.category == c)

    report = Report(
        report_date=date,
        generated_at=fmt_iso(now_shanghai()),
        content_window_start=window_start,
        content_window_end=window_end,
        item_count=item_count,
        category_counts=category_counts,
        corrections=state_store.load().get("corrections", []),
        data_cutoff=window_end,
        ai_disclosure=AI_DISCLOSURE,
        items=items,
        empty_categories=empty_categories,
        insufficient_note=insufficient,
        grace_note=grace_note or None,
        generation={"llm_usage": llm.usage, "collection_stats": stats},
    )
    return report


def _fallback_items(candidates, date: str):
    """无 LLM 时的降级：以原文标题/摘要直接生成条目（供测试与断网降级）。"""
    from .models import Item
    from .util import make_item_id, make_dedup_key
    items = []
    for i, c in enumerate(candidates):
        items.append(Item(
            item_id=make_item_id(date, i, c.dedup_key_hint),
            title_cn=c.title_original,
            summary_cn=c.summary_original[:200] or "详见原始来源。",
            why_it_matters_cn="值得关注，建议查看原始来源了解详情。",
            tags=["AI"],
            category=c.category_hint or "模型进展",
            source_name=c.source_name,
            source_url=c.source_url,
            source_published_at=c.source_published_at,
            collected_at=c.collected_at,
            source_grade=c.source_grade,
            fact_type="发布方主张",
            score=0.0,
            dedup_key=c.dedup_key_hint,
            title_original=c.title_original,
        ))
    return items


def cmd_run(date: str, opts):
    state_store = StateStore(REPO_ROOT)
    t0 = time.time()
    steps = []

    def step(name):
        steps.append({"step": name, "ts": fmt_iso(now_shanghai())})
        log.info("=== 步骤 %d/%d: %s ===", len(steps), 7, name)

    try:
        step("1 采集 / 2 评分 / 3 生成")
        report = _build_report(date, opts)
        step("4 组装")
        staging = REPO_ROOT / "build" / "staging"
        render_site(report, state_store, staging)
        step("5 校验")
        daily_html = (staging / "daily" / f"{date}.html").read_text(encoding="utf-8")
        validate_report(report, check_links=not opts.no_links_check)
        step("6 发布")
        if opts.no_publish:
            log.info("--no-publish：仅生成到 staging=%s", staging)
            outcome = "staged"
        else:
            site_root = REPO_ROOT / "site"
            publish_site(staging, site_root, date, state_store)
            outcome = "success"
        step("7 通知与归档")
        record_run(state_store, date, outcome, "pipeline", f"运行完成（{outcome}）",
                   {"elapsed_s": round(time.time() - t0, 1), "items": report.item_count,
                    "categories": report.category_counts, **report.generation})
        print(json_dumps({
            "ok": True, "date": date, "outcome": outcome, "item_count": report.item_count,
            "category_counts": report.category_counts, "empty_categories": report.empty_categories,
            "insufficient_note": report.insufficient_note, "elapsed_s": round(time.time() - t0, 1),
            "llm_usage": report.generation.get("llm_usage", {}),
            "collection_stats": report.generation.get("collection_stats", {}),
        }))
        return 0
    except (LLMError, CostGuardExceeded, RuntimeError, Exception) as e:  # noqa: BLE001
        record_run(state_store, date, "failed", steps[-1]["step"] if steps else "start", str(e),
                   {"elapsed_s": round(time.time() - t0, 1)})
        print(json_dumps({"ok": False, "date": date, "step": steps[-1]["step"] if steps else "start", "error": str(e)}))
        return 1


def json_dumps(o) -> str:
    import json
    return json.dumps(o, ensure_ascii=False, indent=2)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ai_daily_report", description="AI 日报流水线")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="运行完整流水线")
    p_run.add_argument("--date", default=now_shanghai().strftime("%Y-%m-%d"))
    p_run.add_argument("--skip-llm", action="store_true", help="测试模式：不调用 LLM，直接以原文生成")
    p_run.add_argument("--no-publish", action="store_true", help="仅生成到 staging，不发布到 site/")
    p_run.add_argument("--no-links-check", action="store_true", help="跳过外链可达性校验")
    p_run.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))
    if args.cmd == "run":
        return cmd_run(args.date, args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
