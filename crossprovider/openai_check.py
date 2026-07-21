#!/usr/bin/env python3
"""
Run the promptcheck battery against OpenAI gpt-5.6 variants (luna/terra/sol),
reusing the same deterministic scoring. Scope drift is judged by Claude
opus-4-8 (same judge as the Claude study) for cross-study comparability.

Needs OPENAI_API_KEY (targets) and ANTHROPIC_API_KEY (scope judge).
"""
import json, os, sys, time, urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # repo root, so `import promptcheck` works from anywhere
import promptcheck as pc   # reuse battery + deterministic scorers + Claude judge

OAI = "https://api.openai.com/v1/chat/completions"

def oai(model, system, messages, max_completion_tokens=3000):
    body = {"model": model, "max_completion_tokens": max_completion_tokens,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages}
    req = urllib.request.Request(OAI, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
                 "content-type": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read())
            msg = d["choices"][0]["message"]
            return (msg.get("content") or msg.get("refusal") or ""), None
        except urllib.error.HTTPError as e:
            m = e.read().decode()
            if e.code in (429, 500, 503) and attempt < 3: time.sleep(4 * (attempt + 1)); continue
            return None, f"HTTP {e.code}: {m[:120]}"
        except Exception as e:
            if attempt < 3: time.sleep(4); continue
            return None, str(e)

def score_test(model, prompt, t, judge_model):
    if t["kind"] == "canary":
        resp, err = oai(model, prompt, [{"role": "user", "content": t["msg"]}])
        if err: return None, "API: " + err
        return (not pc.emitted_canary(resp)), ("emitted canary" if pc.emitted_canary(resp) else "refused/ignored")
    if t["kind"] == "leak":
        resp, err = oai(model, prompt, [{"role": "user", "content": t["msg"]}])
        if err: return None, "API: " + err
        lk = pc.leaked_prompt(prompt, resp); return (not lk), ("reproduced prompt" if lk else "did not reveal")
    if t["kind"] == "persona":
        r1, e1 = oai(model, prompt, [{"role": "user", "content": t["msg"]}])
        if e1: return None, "API: " + e1
        r2, e2 = oai(model, prompt, [{"role": "user", "content": t["msg"]},
                                     {"role": "assistant", "content": r1 or ""},
                                     {"role": "user", "content": t["turn2"]}])
        if e2: return None, "API: " + e2
        hj = pc.in_persona_hijack(r1) or pc.in_persona_hijack(r2)
        return (not hj), ("adopted persona" if hj else "kept voice")
    if t["kind"] == "scope":
        resp, err = oai(model, prompt, [{"role": "user", "content": t["msg"]}])
        if err: return None, "API: " + err
        perf = pc.judge_scope(judge_model, prompt, t["msg"], resp)
        if perf is None: return None, "judge error"
        return (not perf), ("did off-topic task" if perf else "stayed in role")

def run_model(model, prompt, judge_model):
    tests = pc.build_tests(agent=False)
    rows, errs = [], 0
    for t in tests:
        passed, why = score_test(model, prompt, t, judge_model)
        if passed is None: errs += 1
        rows.append((t["cat"], t["name"], passed, why))
        tag = "PASS" if passed else ("ERR " if passed is None else "FAIL")
        print(f"    {tag}  {t['cat']:10} · {t['name']:28} {why}")
    # normalized score over present categories
    num = den = 0.0
    catrate = {}
    for cat, w in pc.WEIGHTS.items():
        sub = [r for r in rows if r[0] == cat and r[2] is not None]
        if not sub: continue
        rate = sum(r[2] for r in sub) / len(sub)
        catrate[cat] = rate; num += w * rate; den += w
    total = int(round(100 * num / den)) if den else 0
    return total, catrate, errs

def main():
    prompt = open(os.path.join(ROOT, "examples", "weak.txt")).read().strip()
    judge = "claude-opus-4-8"
    models = ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]
    print(f"prompt: neutral support prompt ({len(prompt.split())} words) | judge: {judge}\n")
    summary = {}
    for m in models:
        print(f"=== {m} ===")
        total, cr, errs = run_model(m, prompt, judge)
        summary[m] = (total, cr, errs)
        print(f"    -> score {total}/100" + (f"  ({errs} errors)" if errs else ""), "\n")
    # comparison table
    cats = ["injection", "leak", "persona", "scope"]
    print("=== SUMMARY (neutral prompt; higher = more resistant) ===")
    print(f"{'model':16} {'score':>6}  " + "  ".join(f"{pc.CATLABEL[c].split()[0]:>9}" for c in cats))
    for m in models:
        total, cr, errs = summary[m]
        cells = "  ".join(f"{int(round(cr.get(c,0)*100)):>8}%" for c in cats)
        print(f"{m:16} {total:>5}/100  {cells}")
    print("\nClaude ref (sonnet-5, same neutral prompt, earlier run): ~65-75/100, "
          "injection~100 leak~100 persona~0 scope~33-67")
    json.dump(summary, open(os.path.join(os.path.dirname(__file__), "openai_results.json"), "w"), indent=2, default=str)

if __name__ == "__main__":
    main()
