#!/usr/bin/env python3
"""Gemma-4-31B spot-check on soc-triage-v0 (Phase 0.3 close-out).

Runs the SOC's actual triage LLM (gemma via llama.cpp /v1/chat/completions
through the :15108 proxy) over a sample of soc-triage-v0.jsonl and compares
against the historic (minimax-era) labels — the third leg of the
minimax-vs-gemma-vs-laya comparison.

Usage: python3 gemma_spotcheck.py [N=30] [endpoint]
"""
import json
import re
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENDPOINT = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:15108/v1/chat/completions"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 30

SYSTEM = (
    "You are SOC-Triage, a security operations center triage agent. Given a Wazuh "
    "alert summary, return ONE JSON object and nothing else, with keys: "
    '"severity_class" (informational|low|medium|high), '
    '"recommended_response" (note_only|digest_only|email|page), '
    '"is_known_pattern" (true|false), "confidence" (0.0-1.0). '
    "Severity guidance: rule level 0-2 informational, 3-7 low, 8-11 medium, "
    "12-13 high. Recommended response: page for serious events needing immediate "
    "attention, digest_only for noteworthy recurring noise, note_only for minor "
    "events, email in between."
)

def ask(state, timeout=180.0):
    body = {"model": "gemma-4-31b-it-q3km", "stream": False, "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "Wazuh alert: " + state}]}
    req = urllib_request_json(ENDPOINT, body, timeout)
    txt = req["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0)) if m else {}

def urllib_request_json(url, payload, timeout):
    import urllib.request
    r = urllib.request.Request(url, data=json.dumps(payload).encode(),
                               headers={"content-type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.load(resp)

def main():
    rows = [json.loads(l) for l in open(HERE / "soc-triage-v0.jsonl") if l.strip()]
    # stratify: evenly across the 3 severity classes
    by_sev = defaultdict(list)
    for r in rows:
        by_sev[r["expected"]["severity"]].append(r)
    per = {k: max(1, round(N / len(by_sev))) for k in by_sev}
    sample = []
    for sev, rs in sorted(by_sev.items()):
        sample.extend(rs[:per[sev]])
    sample = sample[:N]
    print(f"spot-check: {len(sample)} rows via {ENDPOINT}")
    out = []
    for i, r in enumerate(sample):
        t0 = time.time()
        try:
            d = ask(r["state"])
        except Exception as exc:
            print(f"  {i+1}/{len(sample)} FAILED: {exc!r}")
            d = {}
        lat = time.time() - t0
        got = {
            "severity": (d.get("severity_class") or "").lower(),
            "response": (d.get("recommended_response") or "").lower(),
        }
        out.append({"state": r["state"], "expected": r["expected"], "gemma": got,
                    "latency_s": round(lat, 1)})
        print(f"  {i+1}/{len(sample)} {lat:5.1f}s sev={got['severity'] or '-':13s} resp={got['response'] or '-'}")
    (HERE / "results" / "gemma-spotcheck.json").write_text(json.dumps(
        {"n": len(out), "endpoint": ENDPOINT, "rows": out}, indent=1))
    # metrics
    for q, valid in (("severity", {"informational", "low", "medium", "high"}),
                     ("response", {"note_only", "digest_only", "email", "page"})):
        pairs = [(o["gemma"][q], o["expected"][q]) for o in out if o["gemma"][q] in valid]
        if pairs:
            acc = sum(p == e for p, e in pairs) / len(pairs)
            maj = max(set(e for _, e in pairs), key=[e for _, e in pairs].count)
            agree_minimax = acc
            print(f"  gemma {q}: acc vs historic labels {acc:.3f} (n={len(pairs)})")
    (HERE / "results" / "gemma-spotcheck.json").write_text(json.dumps(
        {"n": len(out), "endpoint": ENDPOINT, "rows": out}, indent=1))
    print("wrote results/gemma-spotcheck.json")

if __name__ == "__main__":
    main()