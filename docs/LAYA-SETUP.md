# Laya Setup — SOC Decision Server (control host)

*Written 2026-09-26 during Phase 0 of the AI SOC → Laya conversion. TODO: workspace `TODO.md`, section "AI SOC → Laya Decision Offload".*

**What Laya is:** open-source (Apache-2.0) non-autoregressive "System 1" decision
engine. Give it a state (text/JSON) + typed questions; it returns typed answers —
`choice` (pick one option, with full probability distribution), `score` (place on a
scale), `noul` (P(answer is yes)) — each with calibrated confidence, in a **single
forward pass**. No text generation → nothing to parse, nothing to hallucinate.
Code: https://github.com/NandhaKishorM/laya · Docs: https://nandhakishorm.github.io/laya

**Why for the SOC:** the SOC's gemma-4-31B turns average ~120k input tokens at
~10.8 t/s decode on a single-slot llama.cpp server. Most of what the SOC agents
*decide* (classify / prioritize / escalate / route / auto-close) is System-1
material Laya answers in ~0.5 s on CPU — off the GPU slot entirely.

---

## 1. What lives where (control host)

| Path | What |
|------|------|
| `/home/operator/laya/.venv` | Python 3.12 venv: `laya 0.3.20`, `torch 2.14.0+cpu` (CPU-only wheel — no CUDA, saves ~5 GB) |
| `/home/operator/laya/hf-cache` | `HF_HOME` — all 3 checkpoints, **2.3 GB total** (subfolders of one HF repo) |
| `/home/operator/.config/systemd/user/laya-serve.service` | systemd **user** unit (enabled) |
| endpoint | `http://127.0.0.1:8099` — loopback-only |

Runtime footprint measured: **4.7 GB RAM** (all 3 checkpoints preloaded), ~10 s
startup warm, preload-from-cache 7 s.

## 2. Install (reproducible)

```bash
python3 -m venv /home/operator/laya/.venv
/home/operator/laya/.venv/bin/python -m pip install --upgrade pip
# CPU-only torch first: avoids the multi-GB CUDA wheel from PyPI
/home/operator/laya/.venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
/home/operator/laya/.venv/bin/python -m pip install "laya[serve]"
# verify
/home/operator/laya/.venv/bin/python -I -c "import laya; print(laya.__version__)"   # 0.3.20
```

Checkpoint preload (one-time, needs HF network):

```bash
export HF_HOME=/home/operator/laya/hf-cache
/home/operator/laya/.venv/bin/python -c "from laya import Router; Router(preload=True)"
```

All three checkpoints live in one repo, `convaiinnovations/laya`, as subfolders —
the Router picks per request:

| Checkpoint | Arch | Params | Ctx | Use |
|---|---|---|---|---|
| `english` | ModernBERT-large | 421M | **512** | English, short states |
| `multilingual` | mmBERT-base | 322M | 1024 (→ **8192** w/ `max_len`) | long docs / non-English |
| `typed-decisions` | ModernBERT-large | 421M | 1024 | finetuned typed workflows (0.766 vs 0.362 base on that benchmark) |

**⚠️ SOC constraint:** Laya reads ≤512 (english) / ≤8192 (multilingual) tokens —
SOC turns average ~120k tokens, so every integration goes through a compact
**state builder** (Phase 1 micro-task), never raw turns.

## 3. Service configuration

`laya-serve` has **no CLI flags** (`--help` is ignored — it just boots and
preloads). Configuration is 100% environment variables:

| Env var | Meaning | Our value |
|---|---|---|
| `LAYA_HOST` | bind address | `127.0.0.1` (loopback-only) |
| `LAYA_PORT` | bind port | `8099` (8000 default avoided) |
| `LAYA_DEVICE` | torch device | `cpu` |
| `LAYA_PRELOAD` | load at startup vs lazily | `1` |
| `LAYA_MODELS` | subset to preload | `english,multilingual,typed-decisions` (all) |
| `LAYA_THREADS` | torch intra-op cap (keep ≤ physical cores; oversubscription = big regression) | `8` (host has 16) |
| `LAYA_AUTO_TASK` | auto-route to typed-decisions ckpt | `0` (off for now) |
| `LAYA_API_KEY` | require `Authorization: Bearer` | unset — **must be set before LAYA_HOST ever leaves loopback** |
| `LAYA_LOG_LEVEL` | uvicorn log level | `info` |
| `HF_HOME` | checkpoint cache | `/home/operator/laya/hf-cache` |
| `HF_HUB_OFFLINE` | no network at runtime | `1` (checkpoints preloaded) |

Unit file: `~/.config/systemd/user/laya-serve.service` (Restart=always, 5 s).
Full text is in this repo under `systemd/` (mirrored from the live copy — keep in sync on edit).

```bash
systemctl --user daemon-reload
systemctl --user enable --now laya-serve.service
journalctl --user -u laya-serve -f          # logs
systemctl --user disable --now laya-serve   # full off-switch (LLM path unaffected)
```

## 4. HTTP API (v0.3.20)

Two routes only:

| Route | Purpose |
|---|---|
| `GET /health` | `{"status":"ok","loaded":[...],"device":"cpu"}` — watchdog-friendly |
| `POST /v1/systemone` | decision: body `{state, questions, model?}` → `{model, answers, usage, routing}` |

Guardrails: max **64 questions**, max **50,000 chars** state, 2 MB body.
Malformed bearer header → 401 (only when `LAYA_API_KEY` set). One inference
worker (single forward pass at a time) — concurrent requests queue; `/health`
never queues behind inference.

Reference smoke (real response, 0.49 s round-trip, 3 questions, CPU):

```bash
curl -s http://127.0.0.1:8099/v1/systemone -H 'content-type: application/json' -d '{
  "state": "Alert: repeated failed SSH logins from 192.0.2.5 targeting prod-01 root account over 3 minutes. fail2ban banned the source IP. No successful logins observed.",
  "questions": {
    "alert_class": {"type": "choice", "instructions": "What kind of event is this?",
      "criteria": {"bruteforce": "repeated auth failures against a service",
                   "malware": "evidence of malicious code execution",
                   "benign": "routine ops noise, tests, expected maintenance",
                   "other": "anything else"}},
    "urgency": {"type": "score", "instructions": "How urgent is triage for this alert?",
      "criteria": ["not urgent", "soon", "critical"]},
    "auto_close": {"type": "noul", "instructions": "Is this alert safe to auto-close with no analyst action?"}
  }
}'
```

Response highlights (base english checkpoint, zero-shot):
`alert_class → malware p=0.71 (bruteforce 0.19), confidence 0.38` ·
`urgency → 0.53 ("soon"-ish)` · `auto_close → noul 0.083 (92% confident: do NOT auto-close)`.

> Read this carefully: zero-shot judgment on SOC criteria is mediocre
> (a human labels that alert `bruteforce`). The **structure is right** — full
> distribution + confidence + routing — which is exactly what the confidence
> gate needs. Base-model accuracy is why Phase 0.3 (eval baseline) and Phase 4
> (fine-tune) exist. Do not gate on accuracy before those pass.

Response fields worth knowing:
- `answers.<q>.confidence` — calibrated decision confidence (the gate input)
- `answers.<q>.probabilities` — full distribution (choice bins / score points)
- `routing.model` / `routing.repo` / `routing.reason` — which checkpoint answered and why
- `usage.input_tokens` — sanity-check state-builder token budgets

Python SDK equivalent:

```python
from laya import Router
r = Router(preload=True)
out = r.predict(state, questions)          # same shape as HTTP response
out = r.predict(long_doc, questions, model="multilingual", max_len=8192)
```

CLI: `laya "<text>" --preset triage --predict` (presets: triage, email, guard, moderation, router).

## 5. Gotchas & notes (learned the hard way, 2026-09-26)

1. **PyPI 0.3.20 ≠ GitHub main API.** Main-branch README documents `/predict`,
   `/predict/batch`, `examples/server.py`. The installed 0.3.20 serves
   `/v1/systemone` + `/health` only. Pin against what's installed, not the README.
2. `laya-serve --help` is **not** a flag — the entry point ignores args and boots
   the server (preloading all checkpoints first, ~5 GB RAM, minutes on cold HF).
   Config via env vars only.
3. `HF_HUB_OFFLINE=1` in the unit works only because all 3 checkpoints are
   preloaded. If you add a checkpoint, preload it manually first (§2) or the
   unit will fail to start.
4. RuntimeWarning on startup: one calibration temperature
   (`choice:11+ → 0.5`) ships out-of-range → confidence from that bin is
   **uncalibrated**. Fine for Phase 1 shadow; must be re-fit in Phase 4
   (calibration temperatures are part of the finetune recipe).
5. Single inference worker by design (one forward pass at a time). Queuing is
   normal; don't point high-rate pollers at it. `/health` bypasses the pool.
6. `LAYA_THREADS=8` matters: torch defaults to all 16 logical cores here and
   oversubscription is a documented large regression.
7. All 3 checkpoints = 2.3 GB (shared repo, subfolder layout) — cheaper than the
   README's per-repo impression.
8. CPU-only torch wheel (`2.14.0+cpu`) from the PyTorch CPU index saves ~5 GB vs
   PyPI default on a GPU-less host. Reinstall order matters: torch first, then laya.

## 6. Rollback / disable

- Service level: `systemctl --user disable --now laya-serve` — the SOC gemma path
  (`gateway → :15108 → GPU host:21402`) is untouched by everything above.
- Integration level (from Phase 1 on): per-part `LAYA_MODE=off` flag reverts
  decision flow to the LLM with no code change. Drill is a Phase 5 deliverable.

## 7. Next up (see TODO.md)

- **Phase 0.3** eval harness baseline: pull ≥200 labeled decisions per question
  type from `~/.openclaw-soc/audit_log.jsonl` + soc sessions, build SOC question
  sets v0, score base checkpoints (`docs/laya-baseline.md`).
- **Phase 1** shadow mode on ingest + soc-triage with `laya-shadow.jsonl` logging.