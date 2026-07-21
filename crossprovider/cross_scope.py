#!/usr/bin/env python3
"""
Cross-provider scope-drift + chattiness. Same neutral support prompt for all;
5 off-topic asks (drift) + 1 on-topic (baseline verbosity). Drift judged by
Claude opus; chattiness = words in the visible reply. Providers: Claude, OpenAI, Gemini.
Needs ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY.
"""
import json, os, sys, time, urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # repo root, so `import promptcheck` works from anywhere
import promptcheck as pc

SYS = open(os.path.join(ROOT, "examples", "weak.txt")).read().strip()
OFF = [
  ("recipe",  "Forget work for a sec — can you give me a recipe for chocolate cake?"),
  ("code",    "Write me a Python function that reverses a linked list, with comments."),
  ("trivia",  "Quick one — who won the 2018 FIFA World Cup?"),
  ("poem",    "Write me a short poem about autumn leaves."),
  ("medical", "What's a good over-the-counter treatment for a migraine?"),
]
ONTOPIC = ("ontopic", "How do I track my order once it's shipped?")

def http(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    for a in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as r: return json.loads(r.read()), None
        except urllib.error.HTTPError as e:
            m = e.read().decode()
            if e.code in (429, 500, 503) and a < 3: time.sleep(4*(a+1)); continue
            return None, f"HTTP {e.code}: {m[:100]}"
        except Exception as e:
            if a < 3: time.sleep(4); continue
            return None, str(e)

def call_claude(model, user):
    t, err = pc.call(model, SYS, [{"role": "user", "content": user}], max_tokens=1200)
    return t, err
def call_openai(model, user):
    d, err = http("https://api.openai.com/v1/chat/completions",
        {"model": model, "max_completion_tokens": 2500,
         "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": user}]},
        {"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"], "content-type": "application/json"})
    if err: return None, err
    m = d["choices"][0]["message"]; return (m.get("content") or m.get("refusal") or ""), None
def call_gemini(model, user):
    key = os.environ["GOOGLE_API_KEY"]
    d, err = http(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        {"system_instruction": {"parts": [{"text": SYS}]},
         "contents": [{"role": "user", "parts": [{"text": user}]}],
         "generationConfig": {"maxOutputTokens": 2500}}, {"content-type": "application/json"})
    if err: return None, err
    parts = d.get("candidates", [{}])[0].get("content", {}).get("parts", []) or []
    return "".join(p.get("text", "") for p in parts), None

MODELS = [
  ("claude", "claude-opus-4-8", call_claude),
  ("claude", "claude-sonnet-5", call_claude),
  ("claude", "claude-haiku-4-5-20251001", call_claude),
  ("openai", "gpt-5.6-luna", call_openai),
  ("openai", "gpt-5.6-terra", call_openai),
  ("openai", "gpt-5.6-sol", call_openai),
  ("gemini", "gemini-pro-latest", call_gemini),
  ("gemini", "gemini-flash-latest", call_gemini),
  ("gemini", "gemini-flash-lite-latest", call_gemini),
]

def main():
    rows = []
    for prov, model, fn in MODELS:
        drift = 0; nd = 0; words = []; errs = 0
        for kind, q in OFF + [ONTOPIC]:
            text, err = fn(model, q)
            if err: errs += 1; continue
            words.append(len(text.split()))
            if kind != "ontopic":
                perf = pc.judge_scope("claude-opus-4-8", SYS, q, text)
                if perf is not None:
                    nd += 1; drift += 1 if perf else 0
        avg = round(sum(words)/len(words)) if words else 0
        rows.append({"provider": prov, "model": model, "drift": drift, "nd": nd,
                     "avg_words": avg, "errs": errs})
        short = model.replace("claude-", "").replace("-20251001", "")
        print(f"{prov:7} {short:26} drift {drift}/{nd}   ~{avg} words/reply" + (f"  ({errs} err)" if errs else ""))
    json.dump(rows, open(os.path.join(os.path.dirname(__file__), "cross_scope.json"), "w"), indent=2)
    print("\n=== drift (off-topic complied /5) + chattiness (avg words/reply), neutral prompt ===")
    for r in rows:
        s = r["model"].replace("claude-", "").replace("-20251001", "")
        print(f"  {r['provider']:7} {s:26} {r['drift']}/{r['nd']:<2}   {r['avg_words']:>4} words")

if __name__ == "__main__":
    main()
