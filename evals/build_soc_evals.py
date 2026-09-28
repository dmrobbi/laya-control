#!/usr/bin/env python3
"""Build Laya eval datasets from the SOC audit log (Phase 0.3).

Extracts soc-triage's historic structured decisions from
~/.openclaw-soc/audit_log.jsonl as ground truth and writes JSONL datasets in
Laya's eval format ({state, questions, expected, tags}) — compatible with the
upstream `laya-evals` harness (GitHub main); PyPI 0.3.20 has no laya.evals
module, so run_baseline.py scores these directly via Router.predict.

Ground-truth caveat: labels are the SOC LLM's own historic decisions
(minimax-m3:cloud era), NOT human labels. See docs/laya-baseline.md.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

AUDIT_LOG = Path.home() / ".openclaw-soc" / "audit_log.jsonl"
OUT_DIR = Path(__file__).resolve().parent

SEVERITY_Q = {
    "type": "choice",
    "instructions": "What severity class does this security event warrant?",
    "criteria": {
        "high": "needs immediate attention; potential compromise or critical impact",
        "medium": "noteworthy; routine analyst review",
        "low": "minor; batch review is fine",
        "informational": "no action; record only",
    },
}
RESPONSE_Q = {
    "type": "choice",
    "instructions": "Which immediate response does this event warrant?",
    "criteria": {
        "page": "notify the analyst immediately",
        "email": "email the analyst now",
        "digest_only": "include in the periodic digest",
        "note_only": "log a note only",
    },
}
KNOWN_PATTERN_Q = {
    "type": "noul",
    "instructions": "Is this a known, recurring event pattern (seen before, expected)?",
}
ESCALATE_Q = {
    "type": "noul",
    "instructions": "Should this decision be escalated for more careful review instead of being trusted as-is?",
}

def rows():
    with open(AUDIT_LOG) as f:
        for line in f:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue

def main():
    seen, out, skipped_dup, skipped_malformed = set(), [], 0, 0
    sev, resp, lowconf = Counter(), Counter(), Counter()
    for r in rows():
        if r.get("agent_id") != "soc-triage" or r.get("outcome") != "ok":
            continue
        mo = r.get("model_output")
        if not isinstance(mo, str):
            continue
        try:
            d = json.loads(mo)
        except json.JSONDecodeError:
            continue  # free-text outputs: unparseable for v0
        if "severity_class" not in d or "recommended_response" not in d:
            continue
        h = r.get("input_hash", "")
        if h in seen:
            skipped_dup += 1
            continue
        seen.add(h)
        state = (r.get("input_summary") or "").strip()
        if not state:
            skipped_malformed += 1
            continue
        sev[d["severity_class"]] += 1
        resp[d["recommended_response"]] += 1
        questions = {
            "severity": dict(SEVERITY_Q),
            "response": dict(RESPONSE_Q),
            "known_pattern": dict(KNOWN_PATTERN_Q),
        }
        expected = {
            "severity": str(d["severity_class"]),
            "response": str(d["recommended_response"]),
            "known_pattern": bool(d.get("is_known_pattern")),
        }
        if "low_confidence" in d:
            questions["escalate"] = dict(ESCALATE_Q)
            expected["escalate"] = bool(d["low_confidence"])
            lowconf[bool(d["low_confidence"])] += 1
        row = {
            "state": state,
            "questions": questions,
            "expected": expected,
            "tags": [f"model={r.get('model')}", f"tenant={r.get('tenant_id')}"],
        }
        out.append(json.dumps(row))
    path = OUT_DIR / "soc-triage-v0.jsonl"
    path.write_text("\n".join(out) + "\n")
    print(f"wrote {len(out)} rows -> {path}")
    print(f"skipped: {skipped_dup} dupes, {skipped_malformed} empty-state")
    print(f"severity: {dict(sev)}")
    print(f"response: {dict(resp)}")
    print(f"low_confidence(escalate expected): {dict(lowconf)}")
    # sanity: all expected labels within question criteria
    bad = [json.loads(l) for l in open(path)
           if json.loads(l)["expected"]["severity"] not in SEVERITY_Q["criteria"]
           or json.loads(l)["expected"]["response"] not in RESPONSE_Q["criteria"]]
    print(f"label sanity: {len(bad)} rows with out-of-criteria expected labels")
    return 0 if not bad else 1

if __name__ == "__main__":
    sys.exit(main())