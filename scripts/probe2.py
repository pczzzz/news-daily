import os, requests, json
tok = os.environ.get("GITHUB_TOKEN","")
print("token len", len(tok))
text = """1. The United States and China are expected to meet on the sidelines of the APEC summit next week.
2. Officials said the talks would focus on trade and regional security."""

def call(url, model, headers_extra=None):
    h = {"Authorization": f"Bearer {tok}", "Content-Type":"application/json", "Accept":"application/json"}
    if headers_extra: h.update(headers_extra)
    r = requests.post(url, headers=h, json={
        "model": model,
        "messages":[{"role":"system","content":"你是专业新闻翻译。把用户给的英文逐条翻译成简体中文，保持编号和条目数一致，不增删不改写，只输出译文。"},
                    {"role":"user","content":text}],
        "temperature":0.1,
    }, timeout=120)
    return r.status_code, (r.text or "")[:400]

for url, model in [
    ("https://models.github.ai/inference/chat/completions","gpt-4o-mini"),
    ("https://models.github.ai/inference/chat/completions","openai/gpt-4o-mini"),
    ("https://models.inference.ai.azure.com/chat/completions","gpt-4o-mini"),
]:
    try:
        code, body = call(url, model)
        print(f"[{url.split('//')[1].split('/')[0]} | {model}] {code}\n  {body[:300]}\n")
    except Exception as e:
        print(f"[{url}] ERR {type(e).__name__}: {str(e)[:150]}")
