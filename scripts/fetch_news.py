#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日资讯日报生成器
==================
读取 config/sources.yml，并发抓取全部 RSS，按关键词打分、跨日去重，
再为入选条目抓取**原文正文**并逐段翻译成中文，输出 Markdown 日报 + 单页 HTML。

设计原则：
- 任何单个源/单篇文章失败都不影响整体（记录到 failures，继续跑）
- 翻译采用逐段直译，不改写、不总结、不删减，保证信息完整
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
    from bs4 import BeautifulSoup
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

# Google 翻译的词典扩展接口（无需 Key，支持一次提交多段，返回等长数组）
# 注意：/translate_a/single 在 GitHub 服务器 IP 上会被 429 限流，这个端点不会。
TRANSLATE_URL = "https://translate.googleapis.com/translate_a/t"

# 正文提取时要剔除的噪音标签
NOISE_TAGS = (
    "script", "style", "nav", "footer", "header", "aside", "form",
    "iframe", "noscript", "svg", "button", "figure", "figcaption",
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


def looks_chinese(text: str) -> bool:
    """判断文本是否已经是中文（无需翻译）。"""
    if not text:
        return True
    zh = len(re.findall(r"[\u4e00-\u9fff]", text))
    return zh > len(text) * 0.2


def escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


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
# 原文正文提取
# ----------------------------------------------------------------------
def extract_article_text(page_html: str, max_paragraphs: int = 10) -> list[str]:
    """从文章页 HTML 里提取正文段落。

    策略：优先 <article>/<main> 容器，退化为全页；只保留有实质内容的段落，
    按出现顺序截取前 max_paragraphs 段，保证不混入导航、评论、推荐位。
    """
    soup = BeautifulSoup(page_html, "html.parser")
    for tag in soup(list(NOISE_TAGS)):
        tag.decompose()

    container = soup.find("article") or soup.find("main") or soup.body or soup

    paragraphs: list[str] = []
    seen: set[str] = set()
    for node in container.find_all(["p", "h2", "h3"]):
        text = node.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        # 太短的多半是按钮、版权、图片说明
        if len(text) < 45:
            continue
        # 去掉常见的站点尾巴
        if re.search(r"(cookie|subscribe|newsletter|sign up|all rights reserved)", text, re.I):
            continue
        key = text[:60].lower()
        if key in seen:
            continue
        seen.add(key)
        paragraphs.append(text)
        if len(paragraphs) >= max_paragraphs:
            break
    return paragraphs


def fetch_article(item: dict, settings: dict) -> dict:
    """抓取单篇原文正文，失败时留空并记录原因。"""
    if not settings.get("enrich_article", True):
        return item
    try:
        resp = requests.get(
            item["link"],
            timeout=settings.get("request_timeout", 20),
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
            },
        )
        resp.raise_for_status()
        item["article_en"] = extract_article_text(
            resp.text, int(settings.get("article_paragraphs", 10))
        )
        item["article_error"] = None
    except Exception as exc:  # noqa: BLE001
        item["article_en"] = []
        item["article_error"] = f"{type(exc).__name__}"
    return item


# ----------------------------------------------------------------------
# 翻译（逐段直译，不改写、不总结）
# ----------------------------------------------------------------------
def translate_batch(texts: list[str], timeout: int = 45) -> list[str]:
    """一次请求翻译多段，返回与输入等长的列表。

    刻意不做任何改写/扩写：输入什么就翻什么，逐段对应，保证是一手信息的精确保真。
    接口返回形如 [["译文","源语言"], ...]，顺序与 q 参数一致。
    """
    cleaned = [(t or "").strip() for t in texts]
    if not cleaned:
        return []
    # 已经是中文的段落不用再翻，直接回填，避免占额度
    todo = [i for i, t in enumerate(cleaned) if t and not looks_chinese(t)]
    if not todo:
        return cleaned

    params = [("client", "dict-chrome-ex"), ("sl", "auto"), ("tl", "zh-CN")]
    for i in todo:
        params.append(("q", cleaned[i][:4000]))

    for attempt in range(4):
        try:
            resp = requests.get(
                TRANSLATE_URL, params=params, headers={"User-Agent": UA}, timeout=timeout
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                raise ValueError("unexpected payload")
            out = []
            for seg in data:
                if isinstance(seg, list) and seg:
                    out.append(str(seg[0]).strip())
                else:
                    out.append(str(seg).strip())
            if len(out) == len(todo):
                for idx, zh in zip(todo, out):
                    cleaned[idx] = zh or cleaned[idx]
                return cleaned
            raise ValueError(f"length mismatch {len(out)} != {len(todo)}")
        except Exception:  # noqa: BLE001 - 重试
            time.sleep(1.5 * (attempt + 1))
    # 全部重试失败：保留英文原文，由渲染层标注，不静默丢信息
    return cleaned


def chunk_indices(texts: list[str], max_chars: int = 2200) -> list[list[int]]:
    """把段落按字符数切批，避免 GET 请求 URL 过长。"""
    batches: list[list[int]] = []
    cur: list[int] = []
    size = 0
    for i, t in enumerate(texts):
        length = len(t)
        if cur and size + length > max_chars:
            batches.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += length
    if cur:
        batches.append(cur)
    return batches


def translate_paragraphs(paragraphs: list[str], workers: int = 4) -> list[str]:
    """分批并发翻译草稿，保持段落一一对应。"""
    if not paragraphs:
        return []
    results: list[str] = [""] * len(paragraphs)
    batches = chunk_indices(paragraphs)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(translate_batch, [paragraphs[i] for i in batch]): batch
            for batch in batches
        }
        for future in as_completed(futures):
            batch = futures[future]
            try:
                out = future.result()
            except Exception:  # noqa: BLE001
                out = []
            for idx, zh in zip(batch, out):
                results[idx] = zh
    return results


def enrich_items(items: list[dict], settings: dict) -> None:
    """为入选条目补全原文正文并翻译（原地修改）。"""
    if not settings.get("enrich_article", True):
        return
    workers = max(1, int(settings.get("concurrency", 8)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda it: fetch_article(it, settings), items))

    if not settings.get("translate", True):
        return

    trans_workers = max(1, int(settings.get("translate_concurrency", 4)))

    def process(item: dict) -> None:
        # 标题 + 摘要一次请求搞定
        head = translate_batch([item["title"], item.get("summary", "")])
        item["title_zh"] = (head[0] if head else "") or item["title"]
        item["summary_zh"] = (head[1] if len(head) > 1 else "") or item.get("summary", "")
        # 正文按段落分批翻译，保持一一对应
        src_paras = item.get("article_en") or []
        zh_paras = translate_paragraphs(src_paras, trans_workers)
        item["article_zh"] = [
            zh if zh else f"（本段翻译失败，保留原文）{en}"
            for zh, en in zip(zh_paras, src_paras)
        ]

    with ThreadPoolExecutor(max_workers=max(1, int(settings.get("article_concurrency", 4)))) as pool:
        list(pool.map(process, items))


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
CATEGORY_ORDER = ["国际硬新闻", "深度政论", "科技新闻", "中文视角", "军事防务", "其他"]


def render_markdown(date_str: str, groups: dict[str, list[dict]], failures: dict[str, str], stats: dict) -> str:
    lines = [
        f"# 每日资讯日报 · {date_str}",
        "",
        f"> 生成时间：{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M')}　"
        f"共 {stats['total']} 条 · 来自 {stats['ok_sources']}/{stats['all_sources']} 个源",
        "",
    ]

    for category in CATEGORY_ORDER:
        items = groups.get(category)
        if not items:
            continue
        lines.append(f"## {category}")
        lines.append("")
        for idx, item in enumerate(items, 1):
            published = item.get("published")
            when = published.astimezone().strftime("%m-%d %H:%M") if published else "—"
            title_zh = item.get("title_zh") or item["title"]
            lines.append(f"**{idx}. {title_zh}**")
            lines.append(f"　　`{item['source_name']}` · {when} · 评分 {item['score']} · [原文]({item['link']})")
            lines.append(f"　　<sub>{item['title']}</sub>")
            if item.get("summary_zh"):
                lines.append(f"　　{item['summary_zh']}")
            zh_paras = item.get("article_zh") or []
            if zh_paras:
                lines.append("")
                lines.append("<details><summary>展开全文</summary>")
                lines.append("")
                for para in zh_paras:
                    lines.append(para)
                    lines.append("")
                lines.append("</details>")
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
  :root {{ --fg:#1a1a1a; --muted:#6b7280; --bg:#fafafa; --card:#fff; --line:#e5e7eb; --accent:#1d4ed8; --soft:#f3f4f6; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --fg:#e5e7eb; --muted:#9ca3af; --bg:#111827; --card:#1f2937; --line:#374151; --accent:#60a5fa; --soft:#111827; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
         font:16px/1.75 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif; }}
  .wrap {{ max-width:840px; margin:0 auto; }}
  h1 {{ font-size:26px; margin:0 0 4px; }}
  .meta {{ color:var(--muted); font-size:14px; margin-bottom:28px; }}
  h2 {{ font-size:18px; margin:32px 0 14px; padding-left:10px; border-left:4px solid var(--accent); }}
  .item {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
           padding:16px 18px; margin-bottom:14px; transition:.15s; }}
  .item:hover {{ border-color:var(--accent); }}
  .item .title {{ color:var(--fg); text-decoration:none; font-weight:700; font-size:17px; display:block; }}
  .item .title:hover {{ color:var(--accent); }}
  .orig {{ color:var(--muted); font-size:13px; margin-top:4px; line-height:1.5; }}
  .sub {{ color:var(--muted); font-size:13px; margin:8px 0; }}
  .score {{ display:inline-block; padding:0 6px; border-radius:4px; background:var(--soft); font-size:12px; }}
  .sum {{ font-size:15px; color:#374151; margin-top:6px; }}
  @media (prefers-color-scheme: dark) {{ .sum {{ color:#cbd5e1; }} }}
  details {{ margin-top:10px; }}
  details > summary {{ cursor:pointer; font-size:14px; color:var(--accent); list-style:none; user-select:none; }}
  details > summary::-webkit-details-marker {{ display:none; }}
  details > summary::before {{ content:"▸ "; }}
  details[open] > summary::before {{ content:"▾ "; }}
  .zh p {{ margin:10px 0; font-size:15px; line-height:1.85; }}
  .en {{ margin-top:12px; padding-top:12px; border-top:1px dashed var(--line); }}
  .en p {{ margin:8px 0; font-size:14px; line-height:1.7; color:var(--muted); font-family:Georgia,"Times New Roman",serif; }}
  .src {{ display:inline-block; margin-top:10px; font-size:13px; color:var(--accent); text-decoration:none; }}
  .src:hover {{ text-decoration:underline; }}
  .fail {{ margin-top:36px; font-size:13px; color:var(--muted); }}
</style>
</head>
<body>
<div class="wrap">
<h1>每日资讯日报 · {date_str}</h1>
<div class="meta">{generated}　共 {total} 条 · {ok}/{all} 个源正常 · 中文为逐段直译</div>
{body}
</div>
</body>
</html>
"""


def render_item_html(item: dict) -> str:
    published = item.get("published")
    when = published.astimezone().strftime("%m-%d %H:%M") if published else "—"
    title_zh = escape(item.get("title_zh") or item["title"])
    summary_zh = escape(item.get("summary_zh") or "")

    parts = [
        f'<div class="item">',
        f'<a class="title" href="{escape(item["link"])}" target="_blank" rel="noopener">{title_zh}</a>',
        f'<div class="orig">{escape(item["title"])}</div>',
        f'<div class="sub">{escape(item["source_name"])} · {when} · '
        f'<span class="score">{item["score"]}</span></div>',
    ]
    if summary_zh:
        parts.append(f'<div class="sum">{summary_zh}</div>')

    zh_paras = item.get("article_zh") or []
    en_paras = item.get("article_en") or []
    if zh_paras:
        body_zh = "".join(f"<p>{escape(p)}</p>" for p in zh_paras)
        parts.append(f'<details><summary>展开全文（中文翻译）</summary><div class="zh">{body_zh}')
        if en_paras:
            body_en = "".join(f"<p>{escape(p)}</p>" for p in en_paras)
            parts.append(f'<details class="en"><summary>English original</summary>{body_en}</details>')
        parts.append("</div></details>")
    elif item.get("article_error"):
        parts.append(
            f'<div class="sub">（原文抓取失败：{escape(item["article_error"])}，'
            f'<a class="src" href="{escape(item["link"])}" target="_blank">手动打开原文</a>）</div>'
        )

    parts.append(
        f'<a class="src" href="{escape(item["link"])}" target="_blank" rel="noopener">阅读原文 →</a>'
    )
    parts.append("</div>")
    return "".join(parts)


def render_html(date_str: str, groups: dict[str, list[dict]], stats: dict) -> str:
    blocks = []
    for category in CATEGORY_ORDER:
        items = groups.get(category)
        if not items:
            continue
        blocks.append(f"<h2>{category}</h2>")
        for item in items:
            blocks.append(render_item_html(item))
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

    print(f"[1/5] 开始抓取 {len(sources)} 个源…")
    items, failures = fetch_all(sources, settings)
    print(f"      抓到 {len(items)} 条原始条目，{len(failures)} 个源失败")

    print("[2/5] 打分 + 去重…")
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

    print(f"[3/5] 抓取原文正文 + 翻译（{len(kept)} 篇）…")
    enrich_items(kept, settings)
    ok_article = sum(1 for i in kept if i.get("article_en"))
    ok_trans = sum(1 for i in kept if i.get("article_zh"))
    print(f"      正文抓取成功 {ok_article} 篇，翻译完成 {ok_trans} 篇")

    stats = {
        "total": len(kept),
        "ok_sources": len(sources) - len(failures),
        "all_sources": len(sources),
    }

    print("[4/5] 写入文件…")
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    md = render_markdown(date_str, groups, failures, stats)
    (DAILY_DIR / f"{date_str}.md").write_text(md, encoding="utf-8")

    html_out = render_html(date_str, groups, stats)
    (ROOT / "docs" / "index.html").write_text(html_out, encoding="utf-8")

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

    print(f"[5/5] 完成：{DAILY_DIR / (date_str + '.md')}")
    if failures:
        print("\n失败的源：")
        for name, err in sorted(failures.items()):
            print(f"  - {name}: {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
