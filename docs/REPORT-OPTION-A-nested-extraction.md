# Report — Option A: Nested-Aware Field Extraction (2026-09-26)

*Status: DEPLOYED to edge host + verified end-to-end. Commit: soc-openclaw `66bc322`
(ships together with Option B; the two share files and roll back together).*
*Backups: `realtime_ingest.py.bak-optionB-20260926`, `lite_soc_agent.py.bak-optionB-20260926`
(same as Option B's — the two options were applied to the same files).*

## 1. The problem

Real Wazuh traffic arrives in the **nested** indexer format:

```json
{"rule": {"level": 12, "id": "5710", "description": "..."},
 "agent": {"name": "web-01", "id": "003"},
 "data":  {"srcip": "1.2.3.4"}, "decoder": {"name": "sshd"}}
```

… but every field-extraction path in the ingest pipeline reads **flat,
top-level keys only**:

- `realtime_ingest.py` embedded `LiteTriageAgent._field` — case-insensitive
  exact + fuzzy (`n in k`) match over `a`'s top-level keys
- `lib/lite_soc_agent.py` `ingest_wazuh_alert` — direct `low.get(...)` on
  lower-cased top-level keys

Consequences observed in production data:

| Field | What the code got for nested alerts |
|---|---|
| `level` | **0** (`"level"` fuzzy-matches nothing; `rule.level` invisible) |
| `rule_id` | "" (invisible) |
| `rule_description` | "" (invisible) |
| `agent_name` | `str({'name': 'web-01', 'id': '003'})` — the **dict repr**, via fuzzy match on name "agent" → top-level `agent` key → dict stringified |
| `src_ip` | "" (invisible) |
| `severity` | "low" always under LLM downtime (level 0 → fallback floor) |

Evidence: the 3 organic alerts ingested during the 2026-09-26 power-off window
(`triage_ok=False`) recorded level 0 / sev low; and the pre-fix E2E test POST
recorded `agent={'name': 'laya-fixtest-01', ...}` (dict string) in
`realtime_soc.jsonl`.

Consequences beyond severity: the incident title (`[L{level}] {host}`) showed
"L0 {dict-repr}"; the ticket/evidence trails keyed on these fields were
empty/garbage for nested alerts; and the Laya shadow's `context.level` (used by
the nightly agreement job for objective-label comparison) inherited the broken
parse.

## 2. The change

Both implementations now check, in order: **top-level (case-insensitive, fuzzy
as before) → `rule` → `agent` → `data` → `decoder` sub-objects**, and collapse
any matched dict to a scalar via a `_scalar()` helper (prefers `name`, then
`id`, then `value`) so `agent_name` no longer resolves to a dict string:

```python
@staticmethod
def _scalar(v):
    if isinstance(v, dict):
        for k in ("name", "id", "value"):
            if v.get(k) is not None:
                return v[k]
        return ""
    return v

def _field(self, a, *names, default=""):
    sources = [a] + [a[s] for s in ("rule", "agent", "data", "decoder")
                     if isinstance(a.get(s), dict)]
    ...
```

(lib version: identical logic as inner helpers `_scalar`/`_nf` inside
`ingest_wazuh_alert`.) Flat-format alerts are unaffected — top-level keys are
still checked first, so the flat path behaves identically to before.

Deliberately **not** changed: field priority order, fuzzy matching semantics
("n in k" still allowed — preserved for backwards compatibility with whatever
flat shapes the pipeline has historically posted), and the LLM call itself.

## 3. Semantics after the fix

| Input | Field | Before | After |
|---|---|---|---|
| Nested L12 | level | 0 | **12** |
| Nested | rule_id | "" | "5710" |
| Nested | agent_name | `{'name': 'web-01'...}` | "web-01" |
| Nested | src_ip | "" | "1.2.3.4" |
| Nested L12 + LLM down | severity | low | high (with Option B) |
| Flat (legacy) | all | unchanged | unchanged |

## 4. Tests (all pass)

Same suite as Option B's report (they share the test file):
- Nested L12 → `level=12 rule_id=5710 agent=web-01 src=1.2.3.4` ✓ (was
  `0/""/{dict}/""`)
- 8-level mapping matrix on nested input ✓
- Flat regression: identical to pre-fix behavior ✓
- lib implementation: identical nested parse ✓

**End-to-end (live stack, one real gemma turn):** POST nested L12 to
`/ingest` → `realtime_soc.jsonl` record: `level=12 sev=high rule=5710
agent=laya-fixtest-02 src=192.0.2.124`; incident opened (INC-20260926-000001
in the post-restart window); **shadow row `context.level=12`** with Laya's
independent severity verdict alongside (`high`, conf 0.40). Also consumed by
the ingest chain without errors (`/healthz` ok, 7,636+ alerts logged).

Note: the first E2E POST appeared to fail — because the service had not been
restarted yet after patching (unit tests import the file fresh, the running
server kept the old code). Restart fixed it; recorded here so the failure mode
(patch → compile → **restart** → verify) isn't skipped next time.

## 5. Blast radius

- Downstream consumers of `realtime_soc.jsonl` / `agent.alerts`: records now
  carry **correct** level/rule_id/agent_name/src_ip for nested alerts. Anything
  that (incorrectly) depended on level=0 (e.g., the dashboard "low" wall during
  LLM outages) will see real levels — that is the fix, not a regression.
- The laya shadow context now carries true levels → the nightly agreement job's
  objective comparison (`severity_vs_objective`) is correct going forward.
- No change to email routing, ticket creation, or the LLM triage prompt.

## 6. Rollback

Same files as Option B (roll both together):

```bash
cp /opt/soc-openclaw/services/realtime-ingest/realtime_ingest.py.bak-optionB-20260926 \
   /opt/soc-openclaw/services/realtime-ingest/realtime_ingest.py
cp /opt/soc-openclaw/lib/lite_soc_agent.py.bak-optionB-20260926 \
   /opt/soc-openclaw/lib/lite_soc_agent.py
sudo systemctl restart realtime-soc-server.service
```

## 7. Follow-ups

- Sweep other SOC services for the same flat-only assumption
  (`soc_audit.py` record paths, `soc_score.py` aggregations on edge host) —
  they may have the same blind spot on nested alerts.
- The laya `build_alert_state` already handled nested format (written
  nested-first), which is why the shadow's *state text* was never affected —
  only its `context.level` was; now both are correct.