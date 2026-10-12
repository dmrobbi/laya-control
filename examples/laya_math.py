"""laya_math.py — the tiny Laya client the tutorials share.

Talks only to the documented HTTP surface (see docs/LAYA-SETUP.md in this
repo): GET /health and POST /v1/systemone {state, questions, model?} ->
{model, answers, usage, routing}. Stdlib urllib, no dependencies.

Defaults to the loopback endpoint a laya-serve install exposes; point
LAYA_URL anywhere else to use a remote decision server (remember: an
unbindable-from-loopback deploy MUST set LAYA_API_KEY).

The answer shapes this returns:
  answers[qid]["choice"]        label string           (choice)
  answers[qid]["noul"]          P(true), 0.0..1.0      (noul)
  answers[qid]["score"]         ordinal rubric value   (score)
  answers[qid]["confidence"]    calibrated decision confidence
  answers[qid]["probabilities"] full distribution
  routing["model"] / routing["reason"]
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_URL = os.environ.get("LAYA_URL", "http://127.0.0.1:8099")


class LayaError(RuntimeError):
    pass


class DM:
    """A minimal client for laya-serve's two routes."""

    def __init__(self, url: str | None = None, api_key: str | None = None, timeout: float = 60.0):
        self.url = (url or DEFAULT_URL).rstrip("/")
        self.api_key = api_key or os.environ.get("LAYA_API_KEY")
        self.timeout = timeout
        self.last_latency_ms = 0.0

    def health(self) -> dict:
        try:
            with urllib.request.urlopen(self.url + "/health", timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, OSError) as exc:
            raise LayaError(f"laya-serve at {self.url} is unreachable: {exc}") from exc

    def decide(self, state, questions: dict, model: str | None = None) -> dict:
        """One POST /v1/systemone call. Returns the parsed JSON response."""
        body: dict = {"state": state, "questions": questions}
        if model:
            body["model"] = model
        data = json.dumps(body).encode()
        request = urllib.request.Request(
            self.url + "/v1/systemone",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if self.api_key:
            request.add_header("Authorization", "Bearer " + self.api_key)
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:400]
            raise LayaError(f"HTTP {exc.code} from laya-serve: {detail}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise LayaError(f"laya-serve at {self.url} is unreachable: {exc}") from exc
        self.last_latency_ms = (time.perf_counter() - started) * 1000.0
        if "answers" not in payload:
            raise LayaError(f"malformed response from laya-serve: {payload!r}")
        return payload

    @property
    def latency_ms(self) -> float:
        return self.last_latency_ms


# ---- answer readers (what every tutorial uses) ---------------------------

def choice(result: dict, qid: str) -> str:
    return result["answers"][qid]["choice"]


def probabilities(result: dict, qid: str) -> dict:
    return result["answers"][qid].get("probabilities", {})


def noul(result: dict, qid: str) -> float:
    return float(result["answers"][qid]["noul"])


def score(result: dict, qid: str) -> float:
    return float(result["answers"][qid]["score"])


def confidence(result: dict, qid: str) -> float:
    return float(result["answers"][qid].get("confidence", result["answers"][qid].get("answer_confidence", 0.0)))


def routed_model(result: dict) -> str:
    return result.get("routing", {}).get("model", "?")


def tau_gate(noul_value: float, tau: float = 0.20) -> str:
    """The house gate idiom (tau_kp / tau_resp in the SOC docs).

    noul is P(true). The gate escalates to the authoritative compute path
    (here: the deterministic engine; in the SOC: the gemma fallback) when the
    model is not at least tau committed in either direction:
      |p - 0.5| < tau  -> undecided -> escalate
      p >= 0.5 + tau   -> "yes"
      p <= 0.5 - tau   -> "no"
    """
    if abs(noul_value - 0.5) < tau:
        return "escalate"
    return "yes" if noul_value >= 0.5 else "no"


def banner(title: str) -> None:
    """Consistent step banner so recordings read cleanly."""
    line = "-" * max(4, min(72, len(title) + 8))
    print(line)
    print(f"== {title}")
    print(line)