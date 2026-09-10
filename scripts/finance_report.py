"""Post per-run trajectory usage to the Finance API after run_eval completes a dataset.

Called by run_eval.sh once per dataset, after inference -> eval -> harbor ->
rubric -> staging have all finished. For every run_N under the model dir that
has an output.jsonl, this builds one trajectory-usage record (finance API
payload, see finance_api_documentation.html) and POSTs it to
    POST <FINANCE_API_BASE>/ethara_project/trajectory_usage/create

Data sources:
  - trajectory tokens/cost: run_N/output.jsonl -> metrics.accumulated_token_usage
    (input=prompt_tokens, output=completion_tokens, input_cache=cache_read_tokens,
    output_cache=cache_write_tokens) and metrics.accumulated_cost.
  - model name: run_N/metadata.json ("model"), falling back to metrics.costs[0].
  - judge lines: summed per judge model from the per-verdict ``usage`` records
    in the bundle's verifier verdicts.jsonl (tokens + bridge-computed cost).
  - subscription_id: the Claude account uuid behind Claude Code's OAuth login
    (scripts/claude_account.py), FINANCE_SUBSCRIPTION_ID overrides.

Configuration (env):
  FINANCE_API_BASE        e.g. https://<odoo-instance>/api/v1 . Unset = dry-run:
                          the payload is still written next to the run for audit,
                          nothing is POSTed, exit 0.
  FINANCE_API_TOKEN       Optional bearer token -> Authorization: Bearer <token>.
  FINANCE_AUTH_HEADER     Optional raw "Header-Name: value" auth header
                          (used instead of FINANCE_API_TOKEN when set).
  FINANCE_PROJECT_ID      default "PRJ-UNSET"
  FINANCE_PROJECT_TYPE    default "Technical"
  FINANCE_TEAM_TYPE       default "Projects"
  FINANCE_BUDGET_TYPE     "RFP" (default) or "Production"
  FINANCE_RFP_SUB_TYPE    default "Testing"
  FINANCE_PRODUCTION_MODE "Singlephase" (default) or "Multiphase"
  FINANCE_SUBSCRIPTION_ID overrides the account uuid lookup

Each posted run gets a finance_usage.json sidecar recording the payload and the
POST result; runs whose sidecar says posted=true are skipped unless --force.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

import requests


sys.path.insert(0, str(Path(__file__).resolve().parent))
from claude_account import get_claude_account_info_safe  # noqa: E402


ENDPOINT_PATH = "ethara_project/trajectory_usage/create"

# Anthropic API list prices per MTok, keyed by model-id substring (first match
# wins). Used to price subscription-run trajectories whose SDK metrics carry
# accumulated_cost == 0: the notional cost is what the same tokens would have
# cost on the metered API. Cache reads bill at 0.1x input, cache writes at
# 1.25x input (5-minute tier).
MODEL_PRICES_PER_MTOK = [
    ("claude-fable-5", 10.0, 50.0),
    ("claude-mythos", 10.0, 50.0),
    ("claude-opus", 5.0, 25.0),
    ("claude-sonnet", 3.0, 15.0),
    ("claude-haiku", 1.0, 5.0),
]

# OpenAI list prices per million tokens, mirroring _MODEL_PRICES_PER_MTOK in
# proxy/codex_bridge/bridge.py -- the bridge is the authority, this table only
# serves the fallback below for verdicts judged before the bridge emitted
# x-litellm-response-cost (every gpt judge line reported 0 until it did, because
# the loop above fell through and returned 0.0). Cache reads are 0.1x input on
# every entry, the same ratio the formula already applies, so only the fold
# differs: OpenAI counts cached tokens INSIDE input_tokens, Anthropic reports
# them outside. See _folds_cache_into_input.
OPENAI_PRICES_PER_MTOK = [
    ("gpt-5.6-sol", 4.0, 20.0),
    ("gpt-5.6-terra", 2.0, 12.0),
    ("gpt-5.6-luna", 0.2, 1.2),
    ("gpt-5.3-codex", 1.75, 14.0),
    ("gpt-5.2-codex", 1.75, 14.0),
    ("gpt-5.5", 5.0, 30.0),
]


def _folds_cache_into_input(model: str) -> bool:
    """True when the provider counts cached tokens inside its input total."""
    return any(n in (model or "") for n, _, _ in OPENAI_PRICES_PER_MTOK)


def _notional_cost_usd(model: str, usage: dict) -> float:
    for needle, p_in, p_out in MODEL_PRICES_PER_MTOK + OPENAI_PRICES_PER_MTOK:
        if needle in (model or ""):
            break
    else:
        return 0.0
    cache_read = usage.get("cache_read_tokens", 0) or 0
    cache_write = usage.get("cache_write_tokens", 0) or 0
    # litellm's prompt_tokens folds cache reads/writes in; bill each tier once.
    uncached_in = max(
        0, (usage.get("prompt_tokens", 0) or 0) - cache_read - cache_write
    )
    return round(
        (
            uncached_in * p_in
            + (usage.get("completion_tokens", 0) or 0) * p_out
            + cache_read * (0.1 * p_in)
            + cache_write * (1.25 * p_in)
        )
        / 1_000_000,
        6,
    )


_ENV_FILE_CACHE: dict[str, str] | None = None


def _env_file_values() -> dict[str, str]:
    """FINANCE_* config lives in the repo-root .env; run_eval.sh does not export
    it (it only extracts the GitHub token), so read the file directly."""
    global _ENV_FILE_CACHE
    if _ENV_FILE_CACHE is None:
        _ENV_FILE_CACHE = {}
        env_path = Path(__file__).resolve().parent.parent / ".env"
        try:
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                _ENV_FILE_CACHE[key.strip()] = value.strip().strip("'\"")
        except OSError:
            pass
    return _ENV_FILE_CACHE


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None:
        value = _env_file_values().get(name)
    if value is None:
        value = default
    return value.strip()


def _load_first_record(output_jsonl: Path) -> dict:
    with output_jsonl.open() as f:
        for line in f:
            line = line.strip()
            if line:
                return json.loads(line)
    return {}


def _model_name(run_dir: Path, metrics: dict) -> str:
    meta = run_dir / "metadata.json"
    if meta.exists():
        try:
            doc = json.loads(meta.read_text())
            model = doc.get("model") or (doc.get("llm") or {}).get("model")
            if model:
                # Bare model id, matching judge lines ("anthropic/x" -> "x").
                return str(model).rsplit("/", 1)[-1]
        except (OSError, json.JSONDecodeError):
            pass
    costs = metrics.get("costs") or []
    if costs and costs[0].get("model"):
        return str(costs[0]["model"])
    return str(metrics.get("model_name") or "unknown")


def _judge_lines(bundle_dir: Path, run_name: str) -> list[dict]:
    """One line per judge model found in the bundle's run verifier, with token
    usage and cost summed from the per-verdict ``usage`` records assay writes
    (verdicts produced before that instrumentation carry no usage and sum to 0).
    """
    if not bundle_dir.is_dir():
        return []
    agg: dict[str, dict] = {}
    for verdicts in sorted(
        bundle_dir.glob(f"trajectories/*/{run_name}/verifier/verdicts.jsonl")
    ):
        try:
            with verdicts.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    model = rec.get("model")
                    if not model:
                        continue
                    usage = rec.get("usage") or {}
                    a = agg.setdefault(
                        model,
                        {
                            "in": 0,
                            "out": 0,
                            "cache_read": 0,
                            "cache_write": 0,
                            "cost": 0.0,
                        },
                    )
                    a["in"] += usage.get("input_tokens", 0) or 0
                    a["out"] += usage.get("output_tokens", 0) or 0
                    a["cache_read"] += usage.get("cache_read_tokens", 0) or 0
                    a["cache_write"] += usage.get("cache_write_tokens", 0) or 0
                    a["cost"] += usage.get("cost_usd", 0) or 0
        except (OSError, json.JSONDecodeError):
            continue
    return [
        {
            "model_name": m,
            "judge_input_tokens": a["in"],
            "judge_output_tokens": a["out"],
            "judge_input_cache_tokens": a["cache_read"],
            "judge_output_cache_tokens": a["cache_write"],
            "judge_cost_usd": round(a["cost"], 6)
            or _notional_cost_usd(
                m,
                {
                    # _notional_cost_usd wants litellm shape, where prompt_tokens
                    # folds both cache tiers in. assay keeps Anthropic's outside
                    # input_tokens and OpenAI's inside, so only the Anthropic
                    # aggregate needs them added back; adding them for OpenAI
                    # would bill the cached slice at the full input rate as well.
                    "prompt_tokens": a["in"]
                    if _folds_cache_into_input(m)
                    else a["in"] + a["cache_read"] + a["cache_write"],
                    "completion_tokens": a["out"],
                    "cache_read_tokens": a["cache_read"],
                    "cache_write_tokens": a["cache_write"],
                },
            ),
        }
        for m, a in agg.items()
    ]


def build_payload(
    run_dir: Path, uuid: str, instance_id: str, bundle_dir: Path, subscription_id: str
) -> dict:
    record = _load_first_record(run_dir / "output.jsonl")
    metrics = record.get("metrics") or {}
    usage = metrics.get("accumulated_token_usage") or {}

    budget_type = _env("FINANCE_BUDGET_TYPE", "RFP")
    rfp_sub_type = _env("FINANCE_RFP_SUB_TYPE", "Testing")
    production_mode = _env("FINANCE_PRODUCTION_MODE", "")

    return {
        "project_id": _env("FINANCE_PROJECT_ID", "PRJ-UNSET"),
        "project_type": _env("FINANCE_PROJECT_TYPE", "Technical"),
        "task_id": instance_id,
        "trajectory_id": f"{uuid}/{run_dir.parent.name}/{run_dir.name}",
        "team_type": _env("FINANCE_TEAM_TYPE", "Projects"),
        "budget_type": budget_type,
        "rfp_sub_type": rfp_sub_type,
        "production_mode": production_mode,
        "is_phase_based": production_mode == "Multiphase",
        "generated_at": datetime.datetime.now()
        .astimezone()
        .isoformat(timespec="seconds"),
        "model_name": (model_name := _model_name(run_dir, metrics)),
        "trajectory_input_tokens": usage.get("prompt_tokens", 0),
        "trajectory_output_tokens": usage.get("completion_tokens", 0),
        "trajectory_input_cache_tokens": usage.get("cache_read_tokens", 0),
        "trajectory_output_cache_tokens": usage.get("cache_write_tokens", 0),
        "trajectory_cost_usd": metrics.get("accumulated_cost", 0)
        or _notional_cost_usd(model_name, usage),
        "subscription_id": subscription_id,
        "judge_lines": _judge_lines(bundle_dir, run_dir.name),
    }


def _post(payload: dict, base: str) -> tuple[bool, str]:
    url = f"{base.rstrip('/')}/{ENDPOINT_PATH}"
    headers = {"Content-Type": "application/json"}
    raw_auth = _env("FINANCE_AUTH_HEADER")
    if raw_auth and ":" in raw_auth:
        name, _, value = raw_auth.partition(":")
        headers[name.strip()] = value.strip()
    elif _env("FINANCE_API_TOKEN"):
        headers["Authorization"] = f"Bearer {_env('FINANCE_API_TOKEN')}"
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
    except requests.RequestException as exc:
        return False, f"request failed: {exc}"
    if resp.ok:
        return True, f"HTTP {resp.status_code}: {resp.text[:500]}"
    return False, f"HTTP {resp.status_code}: {resp.text[:500]}"


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument(
        "--run-base",
        required=True,
        help="model dir containing run_N subdirs (eval_outputs/<tag>/<model>)",
    )
    ap.add_argument("--uuid", required=True, help="dataset record uuid")
    ap.add_argument("--instance-id", required=True, help="e.g. ReactiveX__RxJava-7205")
    ap.add_argument("--bundle", default="", help="argos bundle dir (for judge lines)")
    ap.add_argument(
        "--force",
        action="store_true",
        help="re-post runs whose sidecar already says posted=true",
    )
    args = ap.parse_args()

    run_base = Path(args.run_base)
    bundle_dir = Path(args.bundle) if args.bundle else Path("/nonexistent")
    base = _env("FINANCE_API_BASE")

    subscription_id = _env("FINANCE_SUBSCRIPTION_ID")
    account = None
    if not subscription_id:
        account = get_claude_account_info_safe()
        if account:
            subscription_id = account["account_uuid"]
        else:
            print(
                "WARN: could not fetch Claude account info; subscription_id left empty"
            )

    run_dirs = sorted(
        d for d in run_base.glob("run_*") if (d / "output.jsonl").exists()
    )
    if not run_dirs:
        print(f"no run_N dirs with output.jsonl under {run_base}; nothing to report")
        return 0

    failures = 0
    for run_dir in run_dirs:
        sidecar = run_dir / "finance_usage.json"
        if sidecar.exists() and not args.force:
            try:
                if json.loads(sidecar.read_text()).get("posted"):
                    print(
                        f"{run_dir.name}: already posted, skipping (--force to re-post)"
                    )
                    continue
            except (OSError, json.JSONDecodeError):
                pass

        payload = build_payload(
            run_dir, args.uuid, args.instance_id, bundle_dir, subscription_id
        )
        result = {"payload": payload, "posted": False, "account": account}
        if base:
            ok, detail = _post(payload, base)
            result["posted"] = ok
            result["response"] = detail
            print(f"{run_dir.name}: {'posted' if ok else 'POST FAILED'} — {detail}")
            if not ok:
                failures += 1
        else:
            result["response"] = "dry-run: FINANCE_API_BASE not set"
            print(
                f"{run_dir.name}: dry-run (FINANCE_API_BASE unset), payload written to {sidecar}"
            )
        sidecar.write_text(json.dumps(result, indent=2))

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
