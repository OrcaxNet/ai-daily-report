# AI 日报（AI Daily Report）

每天 08:00（Asia/Shanghai）自动生成并发布一份中文 AI 日报，以静态 HTML 站点形式通过域名直接访问。

## 站点

- 首页：<https://orcaxnet.github.io/ai-daily-report/>
- 当日页：`/daily/YYYY-MM-DD.html`
- 归档：`/archive.html`
- 更正记录：`/corrections.html`
- 结构化数据：`/data/report-YYYY-MM-DD.json`

## 架构（七步流水线）

采集 → 筛选评分 → 生成（LLM 中文改写）→ 组装（HTML+JSON）→ 校验 → 发布（原子切换）→ 通知与归档

技术栈：Python 3 数据流水线 + Jinja2 静态 HTML 生成；调度走 Multica autopilot（每日 08:00 Asia/Shanghai cron）；托管走 GitHub Pages（默认 URL）；通知走 Multica issue 评论留痕。

## 本地运行

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run_daily.sh --date 2026-08-10          # 生成并发布指定日
.venv/bin/python -m ai_daily_report run --date 2026-08-10
.venv/bin/python -m ai_daily_report --help
```

## 目录

```
ai_daily_report/      流水线源码（collect/score/generate/assemble/validate/publish/notify）
config/sources.yaml   来源白名单（PRD §3.2，A/B/C 分级配置化）
config/llm.yaml       LLM 生成配置（密钥从本机 ~/.arkcli 解析，不入库）
site/                生成产物（gh-pages 分支内容，gitignored）
data/                运行状态/日志/元数据
tests/               单元测试
run_daily.sh         每日任务入口（autopilot agent 调用）
```

## 质量与容错

- 100 分制打分（影响 30 / 新颖 20 / 可验证 20 / 行动价值 20 / 中文相关 10），≥60 入选。
- 同事件跨源合并（dedup_key），保留一手源为主链接。
- 幂等键 report_date：重跑当日不产生重复页。
- 任一环节失败：保留错误日志、通知负责人、不切换 live 指针（上一期保持可访问）；自动重试 1 次（间隔 5 分钟）。
- 成本：LLM 走 Coding Plan 订阅（无额外按量成本）；记录 token 用量供计量。
