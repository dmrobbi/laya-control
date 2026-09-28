#!/usr/bin/env python3
"""SOC state builders for Laya (Phase 1.2) + rich-state severity eval (Phase 1).

State budget: english checkpoint reads 512 tokens; target states <= ~150 tokens.
Rule-level -> severity mapping is the SOC contract from
soc-agents/soc-triage/IDENTITY.md (0-2 informational, 3-7 low, 8-11 medium,
12-13 high, 14+ critical) — that mapping is also the OBJECTIVE ground truth
for the severity eval (no LLM-judge needed).

Run:  python3 rich_state_eval.py [--models english,typed-decisions]
"""
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --- SOC contract (IDENTITY.md) — single source of truth for objective labels ---
LEVEL_TO_SEVERITY = [(14, "critical"), (12, "high"), (8, "medium"), (3, "low"), (0, "informational")]

def severity_from_level(level: int) -> str:
    for floor, sev in LEVEL_TO_SEVERITY:
        if level >= floor:
            return sev
    return "informational"

# --- question sets (mirror laya_questions.yaml) ---
SEVERITY_Q = {
    "type": "choice",
    "instructions": ("Severity class for this Wazuh alert per the SOC contract: "
                     "informational (rule level 0-2), low (3-7), medium (8-11), "
                     "high (12-13), critical (14+). Judge from the alert content."),
    "criteria": {
        "informational": "rule level 0-2; no action; record only",
        "low": "rule level 3-7; minor; batch review",
        "medium": "rule level 8-11; noteworthy; routine analyst review",
        "high": "rule level 12-13; serious; needs prompt attention",
        "critical": "rule level 14+; immediate response",
    },
}
KNOWN_PATTERN_Q = {"type": "noul",
                   "instructions": "Is this a known, recurring event pattern (seen before, expected in this environment)?"}
RESPONSE_Q = {
    "type": "choice",
    "instructions": "Which immediate response does this alert warrant?",
    "criteria": {
        "note_only": "log a note only",
        "digest_only": "include in the periodic digest",
        "email": "email the analyst now",
        "page": "notify the analyst immediately (call/pager)",
        "auto_remediate": "apply the known-safe automated remediation",
    },
}

def _first(d, *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default

def build_alert_state(a: dict) -> str:
    """Compact, deterministic state text from a wazuh alert. <= ~150 tokens."""
    rule = a.get("rule") or {}
    level = rule.get("level")
    rule_id = rule.get("id")
    desc = str(_first(rule, "description", default="") or "")[:220]
    agent = (_first(a.get("agent") or {}, "name") or "unknown-agent")
    data = a.get("data") or {}
    srcip = _first(data, "srcip", "src_ip", "source_ip")
    decoder = _first(a, "decoder") or {}
    decoder = decoder.get("name") if isinstance(decoder, dict) else decoder
    location = a.get("location")
    parts = [f"Wazuh alert rule {rule_id} severity level {level} on agent {agent}."]
    if desc:
        parts.append(f"Rule: {desc}.")
    if decoder:
        parts.append(f"Decoder: {decoder}.")
    if srcip:
        parts.append(f"Source IP: {srcip}.")
    if location:
        parts.append(f"Location: {location}.")
    return " ".join(parts)

def load_sample():
    p = Path(__file__).resolve().parent / "data" / "wazuh-sample.json"
    return json.load(open(p))

def eval_checkpoint(router, model, rows):
    res, lat = defaultdict(lambda: {"ok": 0, "n": 0, "conf": []}), []
    confusions = defaultdict(lambda: defaultdict(int))
    for st, expected, questions in rows:
        t0 = time.perf_counter()
        out = router.predict(st, questions, model=model)
        lat.append((time.perf_counter() - t0) * 1000)
        for qid, exp in expected.items():
            a = out["answers"][qid]
            d = res[qid]
            if questions[qid]["type"] == "choice":
                d["n"] += 1
                d["ok"] += int(a["choice"] == exp)
                confusions[qid][f"{exp}->{a['choice']}"] += 1
            else:
                d["n"] += 1
                d["ok"] += int((a["noul"] >= 0.5) == exp)
            d["conf"].append(a.get("answer_confidence"))
    return res, lat, confusions

def main():
    sample = load_sample()
    rows = []
    for a in sample:
        st = build_alert_state(a)
        lvl = int(a.get("rule", {}).get("level", 0))
        sev = severity_from_level(lvl)
        rows.append((st, {"severity": sev},
                     {"severity": dict(SEVERITY_Q),
                      "known_pattern": dict(KNOWN_PATTERN_Q),
                      "response": dict(RESPONSE_Q)}))
    print(f"rich-state severity eval: {len(rows)} alerts (objective rule-level labels)")
    models = sys.argv[1].split(",") if len(sys.argv) > 1 else ["typed-decisions", "english"]
    from laya import Router
    reports = {}
    for model in models:
        router = Router(preload=False)
        t0 = time.time()
        res, lat, confusions = eval_checkpoint(router, model, rows)
        rep = {"model": model, "n": len(rows), "latency_ms": {"p50": sorted(lat)[len(lat)//2],
               "mean": sum(lat)/len(lat)}, "questions": {}}
        for qid, d in res.items():
            rep["questions"][qid] = {"acc": round(d["ok"]/max(d["n"], 1), 3), "n": d["n"]}
        rep["confusions"] = {q: dict(sorted(cm.items(), key=lambda x: -x[1])[:8]) for q, cm in confusions.items()}
        reports[model] = rep
        print(f"== {model} == {time.time()-t0:.0f}s")
        for qid, m in rep["questions"].items():
            print(f"  {qid:14s} acc {m['acc']:.3f} (n={m['n']})")
        for q, cm in rep["confusions"].items():
            print(f"  {q} top: {cm}")
        out = Path(__file__).resolve().parent / "results" / f"rich-state-{model}.json"
        out.write_text(json.dumps(rep, indent=2))
        print("  wrote", out)

if __name__ == "__main__":
    main()