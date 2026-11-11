import requests, feedparser
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36"
cands=[
 ("HN官方","https://news.ycombinator.com/rss"),
 ("HN-best","https://hnrss.org/best"),
 ("Nikkei-na","https://asia.nikkei.com/rss/feed/na"),
 ("JapanTimes","https://www.japantimes.co.jp/feed/"),
 ("Zaobao-cn","https://www.zaobao.com.sg/rss/china"),
 ("Zaobao-world","https://www.zaobao.com.sg/rss/world"),
 ("CNA","https://www.cna.com.tw/rss/aall.aspx"),
 ("THE-news","https://www.timeshighereducation.com/news/rss.xml"),
 ("Reuters-CN","https://www.reuters.com/rssFeed/worldNews"),
 ("AlJazeera-cn","https://www.aljazeera.com/xml/rss/all.xml"),
]
for n,u in cands:
    try:
        r=requests.get(u,timeout=20,headers={"User-Agent":UA})
        f=feedparser.parse(r.content)
        print(f"{n:14} {r.status_code:3} entries={len(f.entries):2} title={f.feed.get('title','')[:40]}")
    except Exception as e:
        print(f"{n:14} ERR {type(e).__name__}: {str(e)[:70]}")
