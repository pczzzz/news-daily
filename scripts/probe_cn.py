import requests, feedparser

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

CANDS = [
    ("Guardian-China", "https://www.theguardian.com/world/china/rss"),
    ("NYT-China", "https://rss.nytimes.com/services/xml/rss/nyt/China.xml"),
    ("BBC-China", "https://feeds.bbci.co.uk/news/world/asia/china/rss.xml"),
    ("DW-Asia", "https://rss.dw.com/rdf/rss-en-asia"),
    ("SCMP-China", "https://www.scmp.com/rss/4/feed"),
    ("CDT", "https://chinadigitaltimes.net/chinese/feed/"),
    ("SixthTone", "https://www.sixthtone.com/rss"),
    ("Diplomat-China", "https://thediplomat.com/category/china/feed/"),
    ("CNN-China", "http://rss.cnn.com/rss/cnn_china.rss"),
    ("FP-China", "https://foreignpolicy.com/category/regions/china/feed/"),
    ("JT-China", "https://www.japantimes.co.jp/tag/china/feed/"),
    ("Economist-China", "https://www.economist.com/china/rss.xml"),
    ("AlJazeera-China", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Politico-China", "https://www.politico.com/rss/politicopicks.xml"),
]

for name, url in CANDS:
    try:
        r = requests.get(url, timeout=25, headers={"User-Agent": UA})
        f = feedparser.parse(r.content)
        t = f.feed.get("title", "")[:38]
        print(f"{name:16} {r.status_code:3} entries={len(f.entries):3} | {t}", flush=True)
        if f.entries:
            print(f"                 e.g. {f.entries[0].get('title','')[:70]}", flush=True)
    except Exception as e:
        print(f"{name:16} ERR {type(e).__name__}: {str(e)[:60]}", flush=True)
