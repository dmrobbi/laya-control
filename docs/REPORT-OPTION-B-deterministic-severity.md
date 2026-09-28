# Report — Option B: Deterministic Contract Severity (2026-09-26)

*Status: DEPLOYED to edge host + verified. Commit: soc-openclaw `66bc322` (A+B together).*
*Backups: `realtime_ingest.py.bak-optionB-20260926`, `lite_soc_agent.py.bak-optionB-20260926`.*

## 1. The problem

The ingest's severity **fallback** (used whenever the triage LLM is unavailable)
mapped rule levels to severity classes that contradict the SOC's own documented
contract (`soc-agents/soc-triage/IDENTITY.md`):

| Rule level | IDENTITY contract (what the LLM is told) | Old fallback (realtime_ingest + lib) |
|---|---|---|
| 0–2 | informational | *low* |
| 3–7 | low | low ✓ |
| 8–11 | medium | medium (embedded, from ≥7) / same (lib) |
| 10–11 | **medium** | *high* (both impls) |
| 12–13 | high | *critical* (both impls) |
| 14+ | critical | critical ✓ (embedded ≥12; lib ≥12) |

Three boundary drifts. Combined with the flat-only parsing bug (Option A's
report), the practical result was worse: **nested-format alerts (the format
real traffic uses) parsed level 0**, so whenever the LLM was unavailable the
severity collapsed to "low" for ANY level — observed on 3 organic alerts during
the 2026-09-26 power-off window (`triage_ok=False`, sev low). A real L12
bruteforce alert during an LLM outage produced "low", no incident, no page.

## 2. The change

The fallback mapping now matches the contract exactly, in **both** live
implementations (the embedded `LiteTriageAgent` in `realtime_ingest.py` — the
active backend, and `lite_soc_agent.SecurityOperationsAgent`):

```
level >= 14  → critical      (unchanged)
level >= 12  → high          (was critical)
level >= 8   → medium        (was ≥10 high / ≥7 medium)
level >= 3   → low           (was ≥7 medium boundary)
else         → informational (was low)
```

Precedence unchanged: LLM triage-text patterns still adjust severity when they
match (see §4), and the `\bescalate\b` keyword still escalates to critical.

## 3. Semantics after the fix

| Trigger | Before | After |
|---|---|---|
| Nested alert, LLM **down** | level 0 → "low" always | contract mapping (L12 → high) |
| Nested alert, LLM **up** | "low" always (override regex never matched — see Option B report §4) | contract mapping (deterministic) |
| Flat alert, any LLM state | old drifted mapping | contract mapping |
| L10–11 under fallback | **high → incident auto-opens** | medium → no incident (LLM "escalate" keyword can still open one) |
| L12–13 | critical → incident | high → incident (still opens) |
| L0–2 | low | informational (display-only change; no escalation either way) |

**Incident-volume impact:** the only escalation-relevant change is **L10–11
alerts no longer auto-open incidents** under the deterministic path. That is the
contract's intent (medium = routine analyst review); the nightly/daily reports
and human escalation paths are unaffected. If you want L10–11 to keep opening
incidents, that is a one-line revert (`>= 10: high`) — flagged here explicitly.

## 4. Interaction with the (broken) LLM override — important finding

While writing the change I discovered the "LLM regex override"
(`severity['": =]+(critical|high|...)`) **never matched** the actual triage
output format `"severity_class": "..."` — underscore is not in its character
class. So in practice, severity in the realtime-ingest path was **always
deterministic**, just with the drifted mapping. I deliberately did NOT fix that
regex: making it match would re-activate gemma's severity bias (spot-check:
0.565 accuracy vs historic labels, 87% "page" rate) — worse than the
deterministic mapping, which by the evals is the correct decision-maker for
severity (rich-state eval: level-mapping 1.00 vs Laya 0.269 vs gemma ~0.565).
The regex remains for its `escalate` keyword behavior; a code comment now
documents this so nobody "fixes" it by accident.

## 5. Tests (all pass)

Unit (`/tmp/test_option_ab.py` on edge host, fake LLM, no gemma turns consumed):
- Contract mapping matrix: L15→critical, L13→high, L11→medium, L9→medium,
  L7→low, L5→low, L1→informational, L0→informational ✓
- Flat alerts parse as before (L10 → medium, fields intact) ✓
- LLM-up path: `triage_ok=True`, severity still deterministic (quirk documented) ✓
- Incidents: nested L12 opens an incident under fallback; L11 does not ✓
- lib implementation: same nested parse + mapping ✓

## 6. Rollback

```bash
cp /opt/soc-openclaw/services/realtime-ingest/realtime_ingest.py.bak-optionB-20260926 \
   /opt/soc-openclaw/services/realtime-ingest/realtime_ingest.py
cp /opt/soc-openclaw/lib/lite_soc_agent.py.bak-optionB-20260926 /opt/soc-openclaw/lib/lite_soc_agent.py
# restart realtime-soc-server (Option A shares the same files — roll both back together)
```

## 7. Follow-ups

- Phase 2 gating: severity is now contract-deterministic everywhere — the
  `severity` Laya question can be dropped from the shadow set (keep
  known_pattern/response/escalate, which have no deterministic answer).
- Consider removing the dead severity-regex block in Phase 2 (or converting it
  to an explicit "LLM may escalate via keyword only" comment — effectively
  already true).