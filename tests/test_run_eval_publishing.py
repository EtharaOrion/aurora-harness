"""Focused no-network regression tests for run_eval.sh publishing removal.

Requirements tested:
- Removed options (--no-push, --data-repo, --git-branch, --env-file) are unknown
- --data-dir must pre-exist as a writable, searchable directory (fail before uv/ECR/Docker)
- An ordinary non-git directory is valid for --data-dir (no .git/origin checks)
- No publishing git operations (clone/fetch/pull/add/commit/push) or GitHub API
  usage while still allowing SDK read-only git rev-parse
- No mkdir -p of DATA_PUBLISH_DIR or PUBLISH_BASE
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def run_eval_src() -> str:
    return (REPO_ROOT / "run_eval.sh").read_text(encoding="utf-8")


# ── Unknown removed options ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "option",
    ["--no-push", "--data-repo", "--git-branch", "--env-file"],
)
def test_removed_options_are_unknown(option: str):
    """Removed publishing options must trigger 'Unknown option' and non-zero exit."""
    cmd = [
        "bash",
        str(REPO_ROOT / "run_eval.sh"),
        option,
    ]
    if option in ("--data-repo", "--git-branch", "--env-file"):
        cmd.append("dummy_value")  # these took an argument
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert proc.returncode != 0, f"{option} should cause non-zero exit"
    assert "Unknown option" in proc.stdout or "Unknown option" in proc.stderr, (
        f"{option} should produce 'Unknown option' message"
    )


def test_removed_options_absent_from_source(run_eval_src: str):
    """Removed publishing options must not appear anywhere in run_eval.sh."""
    for option in ("--no-push", "--data-repo", "--git-branch", "--env-file"):
        assert option not in run_eval_src


# ── No mkdir -p of DATA_PUBLISH_DIR or PUBLISH_BASE ──────────────────────────


def test_no_mkdir_of_data_publish_dir(run_eval_src: str):
    """run_eval.sh must never create the staging root automatically."""
    for variable in ("DATA_PUBLISH_DIR", "PUBLISH_BASE", "_DATA_DIR_ORIG"):
        forbidden = (
            f'mkdir -p "${variable}"',
            f'mkdir -p "${{{variable}}}"',
            f"mkdir -p ${variable}",
            f"mkdir -p ${{{variable}}}",
        )
        for command in forbidden:
            assert command not in run_eval_src


def test_no_auto_clone_or_mkdir(run_eval_src: str):
    """run_eval.sh must NOT automatically clone or mkdir the staging root."""
    data_dir_default = run_eval_src.index(
        'DATA_PUBLISH_DIR="${SCRIPT_DIR}/../milo-bench-dataset"'
    )
    post_default = run_eval_src[data_dir_default:]
    assert "git clone" not in post_default, "run_eval.sh must not clone a publish repo"


# ── Data-dir validation ordering ─────────────────────────────────────────────


def test_data_dir_validates_all_four_conditions(run_eval_src: str):
    """Validation must check -e, -d, -w, and -x separately."""
    assert '! -e "$_DATA_DIR_ORIG"' in run_eval_src
    assert '! -d "$_DATA_DIR_ORIG"' in run_eval_src
    assert '! -w "$_DATA_DIR_ORIG"' in run_eval_src
    assert '! -x "$_DATA_DIR_ORIG"' in run_eval_src


def test_original_path_preserved_for_messages(run_eval_src: str):
    """The original user-supplied path is preserved and used in error messages."""
    assert '_DATA_DIR_ORIG="$DATA_PUBLISH_DIR"' in run_eval_src
    # Validation uses _DATA_DIR_ORIG, not the resolved path
    idx_orig = run_eval_src.index('_DATA_DIR_ORIG="$DATA_PUBLISH_DIR"')
    idx_validate = run_eval_src.index('! -e "$_DATA_DIR_ORIG"')
    assert idx_orig < idx_validate


def test_cd_pwd_guarded(run_eval_src: str):
    """The cd && pwd canonicalization is guarded with an if-!."""
    assert 'if ! DATA_PUBLISH_DIR="$(cd "$_DATA_DIR_ORIG" && pwd)"' in run_eval_src
    assert "could not be resolved to an absolute path" in run_eval_src


# ── No .git/origin/remote checks on data-dir ────────────────────────────────


def test_no_git_remote_checks_on_data_dir(run_eval_src: str):
    """run_eval.sh must not verify .git, origin remote, or remote URL of data-dir."""
    data_dir_default = run_eval_src.index(
        'DATA_PUBLISH_DIR="${SCRIPT_DIR}/../milo-bench-dataset"'
    )
    post_default = run_eval_src[data_dir_default:]
    assert 'git -C "$DATA_PUBLISH_DIR"' not in post_default
    assert "remote get-url origin" not in post_default
    assert "_normalize_git_url" not in post_default


# ── Absence of publishing git/GitHub behavior ────────────────────────────────


def test_no_github_api_calls(run_eval_src: str):
    """run_eval.sh must not call the GitHub API (api.github.com)."""
    assert "api.github.com" not in run_eval_src


def test_no_github_token_verification(run_eval_src: str):
    """run_eval.sh must not verify GitHub tokens."""
    assert "verify_github_token_and_identity" not in run_eval_src


def test_no_git_clone_fetch_pull_add_commit_push(run_eval_src: str):
    """run_eval.sh must not perform publishing git operations.

    Note: SDK git rev-parse (for reading the SDK SHA) is still allowed.
    Comments mentioning git operations (e.g. explaining .git stripping) are fine.
    """
    non_comment_lines = [
        line for line in run_eval_src.splitlines() if not line.lstrip().startswith("#")
    ]
    non_comment_src = "\n".join(non_comment_lines)

    for op in (
        "git clone",
        "git fetch",
        "git pull",
        "git add",
        "git commit",
        "git push",
    ):
        assert op not in non_comment_src, (
            f"'{op}' found in run_eval.sh (non-comment code)"
        )


def test_sdk_git_rev_parse_still_allowed(run_eval_src: str):
    """The SDK read-only git rev-parse must still be present."""
    assert "git rev-parse" in run_eval_src


def test_no_push_lock(run_eval_src: str):
    """No push lock mechanism should remain."""
    assert "PUSH_LOCK" not in run_eval_src
    assert "run_eval_push.lock" not in run_eval_src


def test_no_push_enabled_variable(run_eval_src: str):
    """PUSH_ENABLED variable should not exist."""
    assert "PUSH_ENABLED" not in run_eval_src


def test_no_git_token_handling(run_eval_src: str):
    """No GIT_TOKEN, GIT_TOKEN_SRC, GIT_NAME, GIT_EMAIL for publishing."""
    assert "GIT_TOKEN" not in run_eval_src
    assert "GIT_TOKEN_SRC" not in run_eval_src
    assert "GIT_NAME" not in run_eval_src
    assert "GIT_EMAIL" not in run_eval_src


def test_no_env_file_reading(run_eval_src: str):
    """No .env file reading for tokens."""
    assert "read_env_var" not in run_eval_src
    assert "ENV_FILE_RESOLVED" not in run_eval_src


# ── UUID child dirs still created ────────────────────────────────────────────


def test_uuid_child_dirs_still_created(run_eval_src: str):
    """stage_dataset must still create UUID-keyed child directories."""
    assert 'd_bundle="$PUBLISH_BASE/$uuid"' in run_eval_src


@pytest.fixture(scope="module")
def readme_src() -> str:
    return (REPO_ROOT / "README.md").read_text(encoding="utf-8")


# ── README must not document removed publishing behavior ─────────────────────
# The README twice drifted back to documenting --no-push and a GITHUB_TOKEN
# publish preflight after both were removed from run_eval.sh, so the documented
# canonical invocation failed with "Unknown option". These tests keep the
# onboarding docs in step with the parser.


def test_readme_has_no_removed_publishing_flags(readme_src: str):
    """README must not document flags the parser now rejects."""
    for option in ("--no-push", "--data-repo", "--git-branch", "--env-file"):
        assert option not in readme_src, (
            f"README documents {option}, which run_eval.sh rejects as unknown"
        )


def test_readme_pipeline_section_has_no_token_preflight(readme_src: str):
    """The run_eval pipeline section must not require a GitHub token.

    Scoped to that section so unrelated GitHub docs (e.g. the cloud-eval
    dispatch workflow) stay free to mention their own secrets.
    """
    section = readme_src[
        readme_src.index(
            "## Running the Multi-SWE-bench milo pipeline"
        ) : readme_src.index("## Rich Logging")
    ]
    assert "GITHUB_TOKEN" not in section
    assert "GH_TOKEN" not in section


def test_readme_documented_flags_exist_in_parser(readme_src: str, run_eval_src: str):
    """Every long flag documented in the run section must exist in the parser."""
    section = readme_src[
        readme_src.index("### The run") : readme_src.index("### Which model does what")
    ]
    documented = sorted(set(re.findall(r"--[A-Za-z][A-Za-z0-9-]*", section)))
    assert documented, "no flags found in the README run section"

    parser_start = run_eval_src.index("while [[ $# -gt 0 ]]; do")
    parser_block = run_eval_src[
        parser_start : run_eval_src.index("\ndone", parser_start)
    ]
    for flag in documented:
        assert f"{flag})" in parser_block, (
            f"README documents {flag}, absent from the run_eval.sh parser"
        )


# ── Syntax validation ────────────────────────────────────────────────────────


def test_bash_syntax_valid():
    """run_eval.sh must pass bash -n syntax check."""
    proc = subprocess.run(
        ["bash", "-n", str(REPO_ROOT / "run_eval.sh")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"bash -n failed:\n{proc.stderr}"


# ── Behavioral tests: data-dir validation via actual script invocation ───────
# These tests invoke run_eval.sh with a fake `uv` on PATH that records calls
# and exits nonzero for lock/sync/sync --frozen, causing the script to
# hard-fail at the dependency fallback. This prevents reaching ECR/Docker/eval.


@pytest.fixture()
def fake_uv_dir(tmp_path: Path) -> Path:
    """Create a directory with a fake uv that logs calls and fails on lock/sync."""
    uv_bin = tmp_path / "fake_bin" / "uv"
    uv_bin.parent.mkdir()
    uv_bin.write_text(
        textwrap.dedent("""\
        #!/usr/bin/env bash
        echo "FAKE_UV_CALL: $*" >> "${FAKE_UV_LOG}"
        # Fail on lock and sync (both with and without --frozen)
        case "$1" in
            lock|sync) exit 1 ;;
        esac
        exit 0
        """)
    )
    uv_bin.chmod(0o755)
    return uv_bin.parent


def _run_eval_with_data_dir(
    data_dir: str,
    fake_uv_dir: Path,
    tmp_path: Path,
) -> subprocess.CompletedProcess[str]:
    """Invoke run_eval.sh with a failing fake uv as a hard network sentinel."""
    output_dir = tmp_path / "eval_outputs"
    llm_cfg = tmp_path / "llm.json"
    llm_cfg.write_text(
        '{"model": "test/model", "base_url": "http://x", "api_key": "k"}'
    )
    dataset = tmp_path / "ds.jsonl"
    dataset.write_text(
        '{"org":"o","repo":"r","number":1,"uuid":"abc-123","instance_id":"o__r-1"}\n'
    )

    env = os.environ.copy()
    env["FAKE_UV_LOG"] = str(tmp_path / "uv_calls.log")
    env["PATH"] = str(fake_uv_dir) + ":" + env.get("PATH", "")

    cmd = [
        "bash",
        str(REPO_ROOT / "run_eval.sh"),
        "--llm-config",
        str(llm_cfg),
        "--dataset",
        str(dataset),
        "--ecr-prefix",
        "000.dkr.ecr.us-east-1.amazonaws.com/test",
        "--output-dir",
        str(output_dir),
        "--data-dir",
        data_dir,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)


def _assert_stopped_before_expensive_work(tmp_path: Path) -> None:
    """Invalid data-dir cases must stop before uv and output setup."""
    assert not (tmp_path / "uv_calls.log").exists()
    assert not (tmp_path / "eval_outputs").exists()


def test_data_dir_missing_path(tmp_path: Path, fake_uv_dir: Path):
    """A nonexistent --data-dir fails with its path and never reaches uv."""
    bogus = str(tmp_path / "does_not_exist")
    proc = _run_eval_with_data_dir(bogus, fake_uv_dir, tmp_path)
    assert proc.returncode != 0
    assert "does not exist" in proc.stderr
    assert bogus in proc.stderr
    assert "mkdir -p" in proc.stderr
    _assert_stopped_before_expensive_work(tmp_path)


def test_data_dir_is_file(tmp_path: Path, fake_uv_dir: Path):
    """A file path fails as not-a-directory before uv or output setup."""
    file_path = tmp_path / "a_file"
    file_path.write_text("not a dir")
    proc = _run_eval_with_data_dir(str(file_path), fake_uv_dir, tmp_path)
    assert proc.returncode != 0
    assert "not a directory" in proc.stderr
    assert str(file_path) in proc.stderr
    _assert_stopped_before_expensive_work(tmp_path)


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permission checks")
def test_data_dir_not_writable(tmp_path: Path, fake_uv_dir: Path):
    """A searchable but non-writable directory gets the specific diagnostic."""
    ro_dir = tmp_path / "readonly"
    ro_dir.mkdir()
    ro_dir.chmod(0o555)
    try:
        proc = _run_eval_with_data_dir(str(ro_dir), fake_uv_dir, tmp_path)
        assert proc.returncode != 0
        assert "not writable" in proc.stderr
        assert str(ro_dir) in proc.stderr
        _assert_stopped_before_expensive_work(tmp_path)
    finally:
        ro_dir.chmod(0o755)


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permission checks")
def test_data_dir_not_searchable(tmp_path: Path, fake_uv_dir: Path):
    """A writable but non-searchable directory preserves its path in the error."""
    nox_dir = tmp_path / "nox"
    nox_dir.mkdir()
    nox_dir.chmod(stat.S_IRUSR | stat.S_IWUSR)
    try:
        proc = _run_eval_with_data_dir(str(nox_dir), fake_uv_dir, tmp_path)
        assert proc.returncode != 0
        assert "not searchable" in proc.stderr
        assert str(nox_dir) in proc.stderr
        assert 'mkdir -p ""' not in proc.stderr
        _assert_stopped_before_expensive_work(tmp_path)
    finally:
        nox_dir.chmod(0o755)


def test_data_dir_valid_non_git_reaches_only_fake_uv(tmp_path: Path, fake_uv_dir: Path):
    """A plain directory passes preflight, then the failing uv sentinel halts work."""
    good_dir = tmp_path / "staging"
    good_dir.mkdir()
    proc = _run_eval_with_data_dir(str(good_dir), fake_uv_dir, tmp_path)
    combined = proc.stdout + proc.stderr

    assert "Staging base:" in combined
    assert "not a git repository" not in combined.lower()
    origin_mentions = [
        line
        for line in combined.lower().splitlines()
        if "origin" in line and "ecr" not in line
    ]
    assert not origin_mentions, f"Unexpected origin mentions: {origin_mentions}"

    uv_log = tmp_path / "uv_calls.log"
    assert uv_log.exists(), "fake uv was never invoked"
    uv_calls = uv_log.read_text().splitlines()
    assert any("FAKE_UV_CALL: lock " in call for call in uv_calls)
    assert any("FAKE_UV_CALL: sync --frozen" in call for call in uv_calls)
    assert proc.returncode != 0
    assert "FATAL: environment is in an inconsistent state" in combined
    assert "ECR login:" not in combined
    assert "docker pull" not in combined.lower()
    assert not (tmp_path / "eval_outputs").exists()
