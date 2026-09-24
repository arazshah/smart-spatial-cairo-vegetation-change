"""Helpers for the LLM-driven notebook (no analysis logic lives here).

Every analysis is produced by s3geo itself from a natural-language question:

* mode="live"   - calls the official entry point ``s3geo.query(question, layers=...)``.
                  The LLM (OpenAI-compatible endpoint: LLM_API_KEY / LLM_BASE_URL /
                  LLM_MODEL) writes the plan; s3geo validates, plans and executes it.
                  The accepted plan and every attempt are saved to plans/<qid>.json.
* mode="replay" - re-executes a plan saved by an earlier *live* run, through the same
                  public pipeline s3geo.query() wires up (LLMQuerySpecGenerator with
                  StaticLLMClient -> DeterministicPlanner -> DagExecutor). No API key is
                  needed and the numbers are reproducible, but the plan is still the LLM's.

Nothing here edits, patches or wraps s3geo internals: only names exported by ``s3geo``
are used.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import s3geo

HERE = Path(__file__).resolve().parent
PLANS = Path(os.getenv("S3GEO_PLANS_DIR") or HERE / "plans")
RESULTS = Path(os.getenv("S3GEO_RESULTS_DIR") or HERE / "results")
PLANS.mkdir(parents=True, exist_ok=True)
RESULTS.mkdir(parents=True, exist_ok=True)


@dataclass
class Run:
    qid: str
    question: str
    mode: str
    ok: bool
    seconds: float
    goal: str | None = None
    operations: list[str] = field(default_factory=list)
    plan: dict | None = None
    query_spec: dict | None = None
    attempts: int = 0
    repaired: bool = False
    output: Any = None
    error: str | None = None
    model: str | None = None

    def summary(self) -> dict:
        return {
            "qid": self.qid, "mode": self.mode, "ok": self.ok, "seconds": round(self.seconds, 1),
            "goal": self.goal, "operations": " → ".join(self.operations),
            "llm_attempts": self.attempts, "repaired": self.repaired, "model": self.model,
            "error": (self.error or "")[:300],
        }


def llm_config() -> dict:
    """What the live mode will use (key is never printed)."""
    key = os.getenv("LLM_API_KEY") or os.getenv("AVALAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    return {
        "api_key_set": bool(key),
        "base_url": os.getenv("LLM_BASE_URL") or "https://api.avalai.ir/v1 (s3geo default)",
        "model": os.getenv("LLM_MODEL") or "gpt-4o-mini (s3geo default)",
    }


def _attempts_to_json(attempts) -> list[dict]:
    out = []
    for a in attempts or ():
        out.append({"number": getattr(a, "number", None), "plan": getattr(a, "plan", None),
                    "error": getattr(a, "error", None)})
    return out


def _save_plan(qid: str, question: str, plan: dict | None, attempts, spec: dict | None, ok: bool,
               error: str | None) -> None:
    rec = {
        "qid": qid, "question": question, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "s3geo_version": _version(), "llm": {k: v for k, v in llm_config().items() if k != "api_key_set"},
        "ok": ok, "error": error, "plan": plan, "query_spec": spec, "attempts": _attempts_to_json(attempts),
    }
    (PLANS / f"{qid}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str),
                                       encoding="utf-8")


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("smart-spatial-system")
    except Exception:  # pragma: no cover
        return "unknown"


def _replay(question: str, plan: dict, layers: dict) -> tuple[Any, Any, Any]:
    """Same wiring as s3geo.query(), with the saved plan served by StaticLLMClient."""
    initial = {k: (json.loads(v.to_json(default=str)) if hasattr(v, "to_json") else v) for k, v in layers.items()}
    extent = s3geo.derive_input_data_extent(layers)
    gen = s3geo.LLMQuerySpecGenerator(s3geo.StaticLLMClient(json.dumps(plan)), max_repair_attempts=0)
    spec = gen.generate(question, context={}, system_hints="", input_data_extent=extent)
    dag = s3geo.DeterministicPlanner(s3geo.PlannerConfig(strict_params=True)).build(spec)
    res = s3geo.DagExecutor(s3geo.RegistryCapabilityResolver(s3geo.registry())).execute(dag, initial_inputs=initial)
    if not res.success:
        raise s3geo.S3GeoExecutionError(str(res.error), query_spec=s3geo.query_spec_to_dict(spec), plan=plan)
    return spec, res.outputs[spec.operations[-1].output], gen.last_attempts


def ask(qid: str, question: str, layers: dict, *, mode: str = "live", system_hints: str | None = None,
        max_repair_attempts: int = 2) -> Run:
    """Ask s3geo one question. live: LLM plans it. replay: re-run the saved LLM plan."""
    t0 = time.time()
    cfg = llm_config()
    if mode == "live":
        try:
            r = s3geo.query(question, layers=layers, system_hints=system_hints,
                            max_repair_attempts=max_repair_attempts)
            _save_plan(qid, question, r.plan, r.generation_attempts, r.query_spec, True, None)
            return Run(qid, question, mode, True, time.time() - t0, r.goal, r.operations, r.plan, r.query_spec,
                       r.attempt_count, r.repaired, r.output, None, cfg["model"])
        except Exception as e:  # keep the failure: it is a result of the evaluation
            plan = getattr(e, "plan", None)
            attempts = getattr(e, "generation_attempts", None) or getattr(e, "attempts", None) or ()
            _save_plan(qid, question, plan, attempts, getattr(e, "query_spec", None), False,
                       f"{type(e).__name__}: {e}")
            return Run(qid, question, mode, False, time.time() - t0, plan=plan, attempts=len(attempts),
                       error=f"{type(e).__name__}: {e}", model=cfg["model"])
    if mode == "replay":
        path = PLANS / f"{qid}.json"
        if not path.exists():
            return Run(qid, question, mode, False, 0.0, error=f"no saved plan {path.name}: run live first")
        rec = json.loads(path.read_text(encoding="utf-8"))
        if not rec.get("ok") or not rec.get("plan"):
            return Run(qid, question, mode, False, 0.0, plan=rec.get("plan"),
                       error=f"live run failed: {rec.get('error')}", model=rec["llm"].get("model"))
        try:
            spec, out, attempts = _replay(question, rec["plan"], layers)
            return Run(qid, question, mode, True, time.time() - t0, spec.goal, [o.op for o in spec.operations],
                       rec["plan"], s3geo.query_spec_to_dict(spec), len(rec.get("attempts") or []),
                       len(rec.get("attempts") or []) > 1, out, None, rec["llm"].get("model"))
        except Exception as e:
            return Run(qid, question, mode, False, time.time() - t0, plan=rec["plan"],
                       error=f"{type(e).__name__}: {e}", model=rec["llm"].get("model"))
    raise ValueError("mode must be 'live' or 'replay'")


# ---------- output helpers (read what s3geo returned; no analysis) ----------

def features_of(out: Any) -> list[dict]:
    if hasattr(out, "features"):
        return list(out.features)
    if isinstance(out, dict) and "features" in out:
        return list(out["features"])
    return []


def raster_of(out: Any):
    """RasterOut/dict -> (numpy array, metadata)."""
    import numpy as np
    data = getattr(out, "data", None)
    meta = getattr(out, "metadata", None)
    if data is None and isinstance(out, dict):
        data, meta = out.get("data"), out.get("metadata")
    arr = np.array([[np.nan if v is None else v for v in row] for row in data], dtype="float64")
    return arr, meta or {}


def find_prop(props: dict, *needles: str) -> str | None:
    """First property name containing all needles (LLM chooses stat prefixes)."""
    for k in props:
        if all(n in k for n in needles):
            return k
    return None
