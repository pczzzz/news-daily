#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日资讯日报生成器
==================
读取 config/sources.yml，并发抓取全部 RSS，按关键词打分、跨日去重，
输出 Markdown 日报 + 单页 HTML。

设计原则：
- 任何单个源失败都不影响整体（记录到 failures，继续跑）
- 不依赖任何 LLM，零 API 成本；需要摘要时另加
- 幂等：同一天重复运行会覆盖当天日报，不会产生重复文件
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import feedparser
    import requests
    import yaml
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(
        f"缺少依赖：{exc}\n请先执行 pip install -r requirements.txt\n"
    )
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "sources.yml"
DAILY_DIR = ROOT / "docs" / "daily"
HISTORY_PATH = ROOT / "docs" / "history.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

# URL 里需要剔除的追踪参数
TRACKING_PARAMS = re.compile(
    r"([?&])(utm_[a-z]+|fbclid|gclid|ref|source|spm|from)=[^&]*&?", re.I
)


# ----------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------
def normalize_url(url: str) -> str:
    """去掉追踪参数和末尾斜杠，用于跨源去重。"""
    if not url:
        return ""
    url = TRACKING_PARAMS.sub(r"\1", url)
    url = re.sub(r"[?&]+$", "", url)
    return url.rstrip("/").lower()


def normalize_title(title: str) -> str:
    """标题归一化：去空白、标点、大小写，用于判断同一条新闻。"""
    if not title:
        return ""
    t = re.sub(r"[\s\u3000]+", "", title.lower())
    t = re.sub(r"[^\w\u4e00-\u9fff]", "", t)
    return t


def url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def strip_html(text: str, limit: int = 300) -> str:
    """RSS 摘要常带 HTML，清成纯文本并截断。"""
    if not text:
        return ""
    # 先解码 HTML 实体（&#160; &#8217; &amp; 等），再清标签，
    # 否则 RSS 里的数字实体（如 &#8217;）会原样出现在日报里。
    text = html.unescape(text)
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def parse_time(entry: Any) -> datetime | None:
    """从 feedparser 条目里尽力解析发布时间。"""
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime.fromtimestamp(time.mktime(value), tz=timezone.utc)
            except (ValueError, OverflowError):
                continue
    return None


# ----------------------------------------------------------------------
# 抓取
# ----------------------------------------------------------------------
def fetch_one(source: dict, settings: dict) -> dict:
    """抓取单个源，返回 {source, items, error}。永不抛异常。"""
    name = source.get("name", source.get("url", "?"))
    result: dict = {"source": source, "items": [], "error": None}
    try:
        resp = requests.get(
            source["url"],
            timeout=settings.get("request_timeout", 20),
            headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"},
        )
        resp.raise_for_status()
        # 强制走 feedparser 的字节解析，避免编码猜错
        feed = feedparser.parse(resp.content)
        if feed.bozo and not feed.entries:
            raise ValueError(f"解析失败：{getattr(feed, 'bozo_exception', '未知')}")

        limit = settings.get("max_per_source", 6)
        for entry in feed.entries[: limit * 2]:
            title = strip_html(entry.get("title", ""), 200)
            link = entry.get("link", "")
            if not title or not link:
                continue
            result["items"].append(
                {
                    "title": title,
                    "link": link,
                    "summary": strip_html(entry.get("summary") or entry.get("description", "")),
                    "published": parse_time(entry),
                    "source_name": name,
                    "category": source.get("category", "其他"),
                    "weight": source.get("weight", 5),
                    "lang": source.get("lang", "en"),
                }
            )
            if len(result["items"]) >= limit:
                break
    except Exception as exc:  # noqa: BLE001 - 单源失败不应中断
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def fetch_all(sources: list[dict], settings: dict) -> tuple[list[dict], dict[str, str]]:
    items: list[dict] = []
    failures: dict[str, str] = {}
    workers = max(1, int(settings.get("concurrency", 8)))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_one, s, settings): s for s in sources}
        for future in as_completed(futures):
            res = future.result()
            name = res["source"].get("name", "?")
            if res["error"]:
                failures[name] = res["error"]
            items.extend(res["items"])
    return items, failures


# ----------------------------------------------------------------------
# 打分与去重
# ----------------------------------------------------------------------
def score_item(item: dict, keywords: dict, penalties: list[str]) -> int:
    """关键词加权打分，0-100。"""
    text = f"{item['title']} {item['summary']}"
    text_lower = text.lower()

    score = 0
    for word in keywords.get("critical", []):
        if word.lower() in text_lower:
            score += 40
            break
    for word in keywords.get("major", []):
        if word.lower() in text_lower:
            score += 20
            break
    for word in keywords.get("useful", []):
        if word.lower() in text_lower:
            score += 8
            break

    # 科技新闻专属加权（+20）：只对科技新闻板块生效，
    # 否则同一条 AI/芯片新闻会把国际新闻板块的分数推虚。
    if item.get("category") == "科技新闻":
        for word in keywords.get("tech", []):
            if word.lower() in text_lower:
                score += 20
                break

    # 源权重（1-10 → 最多 15 分）
    score += int(item.get("weight", 5) * 1.5)

    for word in penalties:
        if word.lower() in text_lower:
            score -= 25

    # 时效性加分：24 小时内 +10，48 小时内 +5
    published = item.get("published")
    if published:
        age_hours = (datetime.now(timezone.utc) - published).total_seconds() / 3600
        if age_hours <= 24:
            score += 10
        elif age_hours <= 48:
            score += 5
    else:
        score += 5  # 无时间信息的给中性分

    return max(0, min(100, score))


def load_history(settings: dict) -> dict:
    """加载跨日去重历史。

    注意：**当天**写入的记录会被排除，保证同一天重复运行是幂等的（结果一致），
    只有跨天的条目才会被去重。
    """
    keep_days = settings.get("history_days", 10)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=keep_days)
    today = now.date()
    if not HISTORY_PATH.exists():
        return {}
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    fresh: dict[str, str] = {}
    for h, ts in data.items():
        try:
            dt = datetime.fromisoformat(ts)
        except (TypeError, ValueError):
            continue
        if dt < cutoff or dt.date() >= today:
            continue
        fresh[h] = ts
    return fresh


# ----------------------------------------------------------------------
# 渲染
# ----------------------------------------------------------------------
def render_markdown(date_str: str, groups: dict[str, list[dict]], failures: dict[str, str], stats: dict) -> str:
    lines = [
        f"# 每日资讯日报 · {date_str}",
        "",
        f"> 生成时间：{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M')}　"
        f"共 {stats['total']} 条 · 来自 {stats['ok_sources']}/{stats['all_sources']} 个源",
        "",
    ]

    order = ["国际硬新闻", "深度政论", "科技新闻", "中文视角", "军事防务", "其他"]
    for category in order:
        items = groups.get(category)
        if not items:
            continue
        lines.append(f"## {category}")
        lines.append("")
        for idx, item in enumerate(items, 1):
            published = item.get("published")
            when = published.astimezone().strftime("%m-%d %H:%M") if published else "—"
            lines.append(f"**{idx}. [{item['title']}]({item['link']})**")
            meta = f"　　`{item['source_name']}` · {when} · 评分 {item['score']}"
            lines.append(meta)
            if item.get("summary"):
                lines.append(f"　　{item['summary']}")
            lines.append("")

    if failures:
        lines.append("---")
        lines.append("")
        lines.append("<details><summary>本次抓取失败的源（点开看原因）</summary>")
        lines.append("")
        for name, err in sorted(failures.items()):
            lines.append(f"- **{name}**：{err}")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    return "\n".join(lines)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>每日资讯日报 · {date_str}</title>
<style>
  :root {{ --fg:#1a1a1a; --muted:#6b7280; --bg:#fafafa; --card:#fff; --line:#e5e7eb; --accent:#1d4ed8; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --fg:#e5e7eb; --muted:#9ca3af; --bg:#111827; --card:#1f2937; --line:#374151; --accent:#60a5fa; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
         font:16px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif; }}
  .wrap {{ max-width:820px; margin:0 auto; }}
  h1 {{ font-size:26px; margin:0 0 4px; }}
  .meta {{ color:var(--muted); font-size:14px; margin-bottom:28px; }}
  h2 {{ font-size:18px; margin:32px 0 14px; padding-left:10px; border-left:4px solid var(--accent); }}
  .item {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
           padding:14px 16px; margin-bottom:12px; transition:.15s; }}
  .item:hover {{ border-color:var(--accent); transform:translateY(-1px); }}
  .item a {{ color:var(--fg); text-decoration:none; font-weight:600; }}
  .item a:hover {{ color:var(--accent); }}
  .sub {{ color:var(--muted); font-size:13px; margin:6px 0; }}
  .sum {{ font-size:14px; color:#4b5563; }}
  @media (prefers-color-scheme: dark) {{ .sum {{ color:#9ca3af; }} }}
  .score {{ display:inline-block; padding:0 6px; border-radius:4px; background:var(--line); font-size:12px; }}
  details {{ margin-top:36px; font-size:13px; color:var(--muted); }}
</style>
</head>
<body>
<div class="wrap">
<h1>每日资讯日报 · {date_str}</h1>
<div class="meta">{generated}　共 {total} 条 · {ok}/{all} 个源正常</div>
{body}
</div>
</body>
</html>
"""


def render_html(date_str: str, groups: dict[str, list[dict]], stats: dict) -> str:
    blocks = []
    order = ["国际硬新闻", "深度政论", "科技新闻", "中文视角", "军事防务", "其他"]
    for category in order:
        items = groups.get(category)
        if not items:
            continue
        blocks.append(f"<h2>{category}</h2>")
        for item in items:
            published = item.get("published")
            when = published.astimezone().strftime("%m-%d %H:%M") if published else "—"
            summary = f'<div class="sum">{item["summary"]}</div>' if item.get("summary") else ""
            blocks.append(
                f'<div class="item"><a href="{item["link"]}" target="_blank" rel="noopener">{item["title"]}</a>'
                f'<div class="sub">{item["source_name"]} · {when} · '
                f'<span class="score">{item["score"]}</span></div>{summary}</div>'
            )
    return HTML_TEMPLATE.format(
        date_str=date_str,
        generated=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
        total=stats["total"],
        ok=stats["ok_sources"],
        all=stats["all_sources"],
        body="\n".join(blocks),
    )


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def main() -> int:
    if not CONFIG_PATH.exists():
        sys.stderr.write(f"找不到配置文件：{CONFIG_PATH}\n")
        return 1

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    settings = config.get("settings", {}) or {}
    sources = config.get("sources", []) or []
    keywords = config.get("keywords", {}) or {}
    penalties = config.get("penalties", []) or []

    if not sources:
        sys.stderr.write("配置里没有任何订阅源，退出。\n")
        return 1

    tz_name = settings.get("timezone", "Asia/Shanghai")
    try:
        from zoneinfo import ZoneInfo

        now_local = datetime.now(ZoneInfo(tz_name))
    except Exception:  # noqa: BLE001
        now_local = datetime.now()
    date_str = now_local.strftime("%Y-%m-%d")

    print(f"[1/4] 开始抓取 {len(sources)} 个源…")
    items, failures = fetch_all(sources, settings)
    print(f"      抓到 {len(items)} 条原始条目，{len(failures)} 个源失败")

    print("[2/4] 打分 + 去重…")
    history = load_history(settings)
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    kept: list[dict] = []
    min_score = settings.get("min_score", 35)
    max_age_days = settings.get("max_age_days", 7)
    now_utc = datetime.now(timezone.utc)
    expired = 0

    for item in sorted(items, key=lambda x: x.get("published") or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        # 旧闻过滤：RSS 里常混入几个月前的陈年条目
        published = item.get("published")
        if published and (now_utc - published) > timedelta(days=max_age_days):
            expired += 1
            continue

        u = normalize_url(item["link"])
        t = normalize_title(item["title"])
        if not u or u in seen_urls or (t and t in seen_titles):
            continue
        if url_hash(u) in history:
            continue
        seen_urls.add(u)
        if t:
            seen_titles.add(t)

        item["score"] = score_item(item, keywords, penalties)
        if item["score"] >= min_score:
            kept.append(item)

    # 先按分数全局排序，再按板块配额截断，
    # 避免科技/快讯类源数量多就把其他板块挤没。
    kept.sort(key=lambda x: x["score"], reverse=True)
    max_per_category = int(settings.get("max_per_category", 0) or 0)
    if max_per_category > 0:
        quota: dict[str, int] = {}
        limited: list[dict] = []
        for item in kept:
            cat = item["category"]
            if quota.get(cat, 0) >= max_per_category:
                continue
            quota[cat] = quota.get(cat, 0) + 1
            limited.append(item)
        kept = limited

    max_items = settings.get("max_items", 40)
    kept = kept[:max_items]
    print(
        f"      保留 {len(kept)} 条（阈值 {min_score} 分，上限 {max_items} 条，"
        f"丢弃旧闻 {expired} 条）"
    )

    groups: dict[str, list[dict]] = {}
    for item in kept:
        groups.setdefault(item["category"], []).append(item)
    for category in groups:
        groups[category].sort(key=lambda x: x["score"], reverse=True)

    stats = {
        "total": len(kept),
        "ok_sources": len(sources) - len(failures),
        "all_sources": len(sources),
    }

    print("[3/4] 写入文件…")
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    md = render_markdown(date_str, groups, failures, stats)
    (DAILY_DIR / f"{date_str}.md").write_text(md, encoding="utf-8")

    html = render_html(date_str, groups, stats)
    (ROOT / "docs" / "index.html").write_text(html, encoding="utf-8")

    # 更新历史索引
    for item in kept:
        history[url_hash(normalize_url(item["link"]))] = datetime.now(timezone.utc).isoformat()
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 归档索引（供首页列出历史）
    archive = sorted([p.stem for p in DAILY_DIR.glob("*.md")], reverse=True)
    (ROOT / "docs" / "archive.json").write_text(
        json.dumps(archive, ensure_ascii=False), encoding="utf-8"
    )

    print(f"[4/4] 完成：{DAILY_DIR / (date_str + '.md')}")
    if failures:
        print("\n失败的源：")
        for name, err in sorted(failures.items()):
            print(f"  - {name}: {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
