import requests, json, urllib.parse
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
text = "The United States and China are expected to meet on the sidelines of the APEC summit next week."
results = {}

def probe(name, fn):
    try:
        results[name] = fn()
    except Exception as e:
        results[name] = f"ERR {type(e).__name__}: {str(e)[:120]}"

def g1():
    r = requests.get("https://translate.googleapis.com/translate_a/single",
        params={"client":"gtx","sl":"auto","tl":"zh-CN","dt":"t","q":text}, headers={"User-Agent":UA}, timeout=15)
    return f"{r.status_code} {r.text[:160]}"
def g2():
    r = requests.get("https://translate.google.com/translate_a/single",
        params={"client":"gtx","sl":"auto","tl":"zh-CN","dt":"t","q":text}, headers={"User-Agent":UA}, timeout=15)
    return f"{r.status_code} {r.text[:160]}"
def mymem():
    r = requests.get("https://api.mymemory.translated.net/get",
        params={"q":text[:400],"langpair":"en|zh-CN"}, headers={"User-Agent":UA}, timeout=15)
    return f"{r.status_code} {r.text[:200]}"
def libre():
    r = requests.post("https://translate.disroot.org/translate",
        json={"q":text,"source":"en","target":"zh","format":"text"}, headers={"User-Agent":UA}, timeout=15)
    return f"{r.status_code} {r.text[:200]}"
def libre2():
    r = requests.post("https://libretranslate.de/translate",
        json={"q":text,"source":"en","target":"zh","format":"text"}, headers={"User-Agent":UA}, timeout=15)
    return f"{r.status_code} {r.text[:200]}"
def bing():
    r = requests.get("https://www.bing.com/ttranslatev3",
        params={"fromLang":"en","to":"zh-Hans","text":text}, headers={"User-Agent":UA}, timeout=15)
    return f"{r.status_code} {r.text[:200]}"
def gtx_cn():
    r = requests.get("https://translate.google.cn/translate_a/single",
        params={"client":"gtx","sl":"auto","tl":"zh-CN","dt":"t","q":text}, headers={"User-Agent":UA}, timeout=15)
    return f"{r.status_code} {r.text[:160]}"
def deepl_free():
    r = requests.post("https://api-free.deepl.com/v2/translate",
        data={"text":text,"target_lang":"ZH"}, timeout=15)
    return f"{r.status_code} {r.text[:160]}"

for n,f in [("googleapis",g1),("google.com",g2),("mymemory",mymem),("disroot",libre),("libretranslate.de",libre2),("bing",bing),("google.cn",gtx_cn),("deepl-free",deepl_free)]:
    probe(n,f)
print("="*60)
for k,v in results.items():
    print(f"[{k}]\n  {v}\n")
