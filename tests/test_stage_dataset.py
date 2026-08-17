"""Behavioral tests for the stage_dataset function extracted from run_eval.sh.

These tests build a network-free Bash harness that:
1. Extracts the actual stage_dataset function from run_eval.sh source
2. Asserts extraction integrity (one start marker, expected boundary, closing brace)
3. Supplies stubs for log, PUBLISH_BASE, RUBRIC_BUNDLE_DEST
4. Covers: flat Milo branch, legacy task+trajectory branch, missing UUID (status 1)
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_EVAL_SH = REPO_ROOT / "run_eval.sh"


@pytest.fixture(scope="module")
def run_eval_src() -> str:
    return RUN_EVAL_SH.read_text(encoding="utf-8")


# ── Extraction integrity assertions ─────────────────────────────────────────


def test_stage_dataset_has_exactly_one_start_marker(run_eval_src: str):
    """There must be exactly one 'stage_dataset() {' declaration."""
    assert run_eval_src.count("stage_dataset() {") == 1


def test_stage_dataset_precedes_process_dataset(run_eval_src: str):
    """stage_dataset function must be defined before process_dataset."""
    stage_idx = run_eval_src.index("stage_dataset() {")
    process_idx = run_eval_src.index("process_dataset() {")
    assert stage_idx < process_idx


def test_stage_dataset_ends_with_closing_brace(run_eval_src: str):
    """The extracted stage_dataset block must end at a closing brace line."""
    start = run_eval_src.index("stage_dataset() {")
    # Find process_dataset boundary
    process_start = run_eval_src.index("process_dataset() {", start)
    block = run_eval_src[start:process_start].rstrip()
    # Find the last '}' line — that's the function's closing brace
    lines = block.splitlines()
    brace_lines = [i for i, line in enumerate(lines) if line.strip() == "}"]
    assert brace_lines, "No closing brace found in stage_dataset"
    # The last brace must be at column 0 (unindented = top-level function close)
    last_brace_line = lines[brace_lines[-1]]
    assert last_brace_line.strip() == "}"
    assert last_brace_line == "}"  # unindented


def test_stage_dataset_ends_with_return_0(run_eval_src: str):
    """stage_dataset must have an explicit return 0 before the closing brace."""
    start = run_eval_src.index("stage_dataset() {")
    process_start = run_eval_src.index("process_dataset() {", start)
    block = run_eval_src[start:process_start].rstrip()
    lines = block.splitlines()
    # Find the last unindented '}' (function close)
    brace_lines = [i for i, line in enumerate(lines) if line == "}"]
    assert brace_lines, "No closing brace found"
    brace_idx = brace_lines[-1]
    # The line immediately before the closing brace (skipping blank lines)
    preceding = [line for line in lines[:brace_idx] if line.strip()]
    assert preceding[-1].strip() == "return 0"


# ── Harness builder ──────────────────────────────────────────────────────────


def _extract_stage_dataset(src: str) -> str:
    """Extract the stage_dataset function body from run_eval.sh source."""
    start = src.index("stage_dataset() {")
    # Find the next top-level function (process_dataset) as the upper bound
    upper = src.index("\nprocess_dataset()", start)
    block = src[start:upper]
    # Trim to the last unindented '}' (the function's closing brace)
    lines = block.splitlines()
    brace_lines = [i for i, line in enumerate(lines) if line == "}"]
    assert brace_lines, "No closing brace found in stage_dataset"
    return "\n".join(lines[: brace_lines[-1] + 1])


def _build_harness(
    publish_base: str,
    bundle_dest: str,
    extra_setup: str = "",
) -> str:
    """Build a self-contained bash script that sources stage_dataset and runs it."""
    stage_fn = _extract_stage_dataset(RUN_EVAL_SH.read_text(encoding="utf-8"))
    return textwrap.dedent(f"""\
        #!/usr/bin/env bash
        set -uo pipefail

        # Stubs
        log() {{ echo "LOG: $*"; }}
        PUBLISH_BASE="{publish_base}"
        RUBRIC_BUNDLE_DEST="{bundle_dest}"
        SCRIPT_DIR="{REPO_ROOT}"

        {extra_setup}

        # Extracted function
        {stage_fn}

        # Invoke
        stage_dataset "$@"
    """)


# ── Flat Milo bundle branch ─────────────────────────────────────────────────


def test_flat_milo_bundle_copied_and_git_stripped(tmp_path: Path):
    """When a milo bundle exists, it is copied to PUBLISH_BASE/<uuid>,
    nested .git dirs are stripped, and sibling verdicts are NOT copied.
    Status 0."""
    uuid = "test-uuid-flat"
    # Set up bundle source
    bundle_dest = tmp_path / "milo_bundles"
    bundle_src = bundle_dest / uuid
    bundle_src.mkdir(parents=True)
    (bundle_src / "trajectory.json").write_text('{"key":"val"}')
    (bundle_src / "nested" / ".git").mkdir(parents=True)
    (bundle_src / "nested" / ".git" / "HEAD").write_text("ref: refs/heads/main")
    # Sibling verdicts dir (should not be copied)
    verdicts = bundle_dest / "verdicts"
    verdicts.mkdir()
    (verdicts / "scratch.json").write_text("{}")

    publish_base = tmp_path / "publish"
    publish_base.mkdir()

    harness = _build_harness(str(publish_base), str(bundle_dest))
    script = tmp_path / "harness.sh"
    script.write_text(harness)
    script.chmod(0o755)

    proc = subprocess.run(
        ["bash", str(script), "tag", "iid", "ds", "rb", "harbor", "model", uuid],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"

    dest = publish_base / uuid
    assert dest.is_dir()
    assert (dest / "trajectory.json").exists()
    # Nested .git stripped
    assert not (dest / "nested" / ".git").exists()
    # Verdicts NOT present in publish
    assert not (publish_base / "verdicts").exists() or not any(
        (publish_base / "verdicts").iterdir()
    )


def test_flat_milo_sibling_verdicts_not_copied(tmp_path: Path):
    """Sibling verdicts/ directory from the bundle store must never appear
    in the publish destination."""
    uuid = "test-uuid-no-verdicts"
    bundle_dest = tmp_path / "milo_bundles"
    bundle_src = bundle_dest / uuid
    bundle_src.mkdir(parents=True)
    (bundle_src / "data.json").write_text("{}")

    # verdicts as a sibling
    (bundle_dest / "verdicts" / "judge1.json").mkdir(parents=True)

    publish_base = tmp_path / "publish"
    publish_base.mkdir()

    harness = _build_harness(str(publish_base), str(bundle_dest))
    script = tmp_path / "harness.sh"
    script.write_text(harness)
    script.chmod(0o755)

    proc = subprocess.run(
        ["bash", str(script), "tag", "iid", "ds", "rb", "harbor", "model", uuid],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0

    # Only the uuid dir should exist under publish, NOT verdicts
    published_dirs = [d.name for d in publish_base.iterdir() if d.is_dir()]
    assert uuid in published_dirs
    assert "verdicts" not in published_dirs


# ── Legacy task+trajectory branch ────────────────────────────────────────────


def test_legacy_task_trajectory_copied(tmp_path: Path):
    """When no milo bundle exists, the legacy harbor task + trajectory
    directories are copied. Status 0."""
    uuid = "test-uuid-legacy"
    bundle_dest = tmp_path / "milo_bundles"
    bundle_dest.mkdir()
    # No bundle for this uuid (bundle_dest/<uuid> does NOT exist)

    # Set up harbor output
    harbor_out = tmp_path / "harbor"
    (harbor_out / "task").mkdir(parents=True)
    (harbor_out / "task" / "instance.json").write_text('{"id":"x"}')
    (harbor_out / "trajectory" / "model1").mkdir(parents=True)
    (harbor_out / "trajectory" / "model1" / "traj.json").write_text('{"steps":[]}')

    publish_base = tmp_path / "publish"
    publish_base.mkdir()

    harness = _build_harness(str(publish_base), str(bundle_dest))
    script = tmp_path / "harness.sh"
    script.write_text(harness)
    script.chmod(0o755)

    proc = subprocess.run(
        [
            "bash",
            str(script),
            "tag",
            "iid",
            "ds",
            "rb",
            str(harbor_out),
            "model",
            uuid,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"

    # Check dataset/<uuid> and trajectory/<uuid> exist
    assert (publish_base / "dataset" / uuid / "instance.json").exists()
    assert (publish_base / "trajectory" / uuid / "model1" / "traj.json").exists()


# ── Missing UUID → status 1 ─────────────────────────────────────────────────


def test_missing_uuid_returns_1(tmp_path: Path):
    """Calling stage_dataset with an empty uuid must return 1."""
    bundle_dest = tmp_path / "milo_bundles"
    bundle_dest.mkdir()
    publish_base = tmp_path / "publish"
    publish_base.mkdir()

    harness = _build_harness(str(publish_base), str(bundle_dest))
    script = tmp_path / "harness.sh"
    script.write_text(harness)
    script.chmod(0o755)

    # Pass empty string as dataset_uuid (7th positional arg)
    proc = subprocess.run(
        ["bash", str(script), "tag", "iid", "ds", "rb", "harbor", "model", ""],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 1
    assert "FATAL" in proc.stdout or "FATAL" in proc.stderr
