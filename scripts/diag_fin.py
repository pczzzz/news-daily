import sys
import yaml
import importlib.util

spec = importlib.util.spec_from_file_location("fn", "scripts/fetch_news.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

cfg = yaml.safe_load(open("config/sources.yml", encoding="utf-8"))
kw = cfg["keywords"]
pen = cfg.get("penalties", [])
targets = [s for s in cfg["sources"] if s["category"] == "财经宏观"]

print("=== 财经宏观源诊断 ===", flush=True)
for src in targets:
    print(f"\n--- {src['name']} ---", flush=True)
    try:
        items, failures = m.fetch_all([src], cfg.get("settings", {}))
        print(f"  条目数: {len(items)}", flush=True)
        if failures:
            print(f"  失败: {failures}", flush=True)
        for it in items[:15]:
            it["category"] = src["category"]
            it["weight"] = src.get("weight", 5)
            sc = m.score_item(it, kw, pen)
            mark = "PASS" if sc >= 35 else "drop"
            print(f"  [{sc:3}] {mark} {it['title'][:70]}", flush=True)
    except Exception as e:
        print("  ERR", type(e).__name__, e, flush=True)
