import requests, json
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
URL="https://translate.googleapis.com/translate_a/t"
paras=[
 "The United States and China are expected to meet on the sidelines of the APEC summit next week.",
 "Officials said the talks would focus on trade, regional security and climate cooperation.",
 "A senior official briefed reporters on condition of anonymity.",
]
def batch(qs):
    params=[("client","dict-chrome-ex"),("sl","auto"),("tl","zh-CN")]+[("q",q) for q in qs]
    r=requests.get(URL,params=params,headers={"User-Agent":UA},timeout=40)
    return r.status_code, r.text[:600]

code, body = batch(paras)
print("BATCH", code, body)
print()
# 长文本单段
long_text = "The quick brown fox jumps over the lazy dog. " * 40
code2, body2 = batch([long_text[:1800]])
print("LONG", code2, len(body2), body2[:200])
print()
# 中文输入（应原样返回）
code3, body3 = batch(["这是中文测试"])
print("ZH", code3, body3)
