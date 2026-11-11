import requests, json
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
text = "The United States and China are expected to meet on the sidelines of the APEC summit next week."
def lib(url):
    r = requests.post(url, json={"q":text,"source":"en","target":"zh","format":"text"}, headers={"User-Agent":UA,"Content-Type":"application/json"}, timeout=20)
    return f"{r.status_code} {r.text[:200]}"
def g5():
    r=requests.get("https://clients5.google.com/translate_a/t",
        params={"client":"dict-chrome-ex","sl":"en","tl":"zh-CN","q":text}, headers={"User-Agent":UA}, timeout=15)
    return f"{r.status_code} {r.text[:200]}"
def g6():
    r=requests.get("https://translate.googleapis.com/translate_a/t",
        params={"client":"dict-chrome-ex","sl":"en","tl":"zh-CN","q":text}, headers={"User-Agent":UA}, timeout=15)
    return f"{r.status_code} {r.text[:200]}"
def mymem2():
    r=requests.get("https://api.mymemory.translated.net/get",
        params={"q":text,"langpair":"en|zh-CN","de":"news-daily@example.com"}, headers={"User-Agent":UA}, timeout=15)
    d=r.json()
    return f"{r.status_code} {json.dumps(d.get('responseData'),ensure_ascii=False)[:150]} quota={d.get('quotaFinished')}"

tests = [("clients5.google",g5),("googleapis_t",g6),("mymemory_de",mymem2)]
for u in ["https://translate.argosopentech.com","https://trans.zillyhuhn.com","https://libretranslate.pussthecat.org","https://translate.terraprint.co","https://translate.fedilab.app","https://libretranslate.eownerdead.dedyn.io"]:
    tests.append((u.split("//")[1], lambda u=u: lib(u+"/translate")))
for name, fn in tests:
    try: print(f"[{name}] {fn()}")
    except Exception as e: print(f"[{name}] ERR {type(e).__name__}: {str(e)[:100]}")
