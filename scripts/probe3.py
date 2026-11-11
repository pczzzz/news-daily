import os, requests, json
tok = os.environ.get("GITHUB_TOKEN","")
url = "https://models.github.ai/inference/chat/completions"
for model in ["gpt-4o-mini", "openai/gpt-4o-mini", "gpt-4.1-mini"]:
    r = requests.post(url, headers={"Authorization": f"Bearer {tok}", "Content-Type":"application/json", "Accept":"application/json"},
        json={"model": model, "messages":[{"role":"user","content":"Translate to Chinese: Hello world"}], "temperature":0.1}, timeout=90)
    print(f"=== {model} -> {r.status_code} ct={r.headers.get('content-type')}")
    print("BODY:", r.text[:900].replace("\n","\\n"))
    print()
