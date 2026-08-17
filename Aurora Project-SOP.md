# Project Guide \- Aurora

> **Start here:** Sections 1–12 below are preserved historical LHT/EC2 design material. For the current repository, onboarding, and delivery workflow, use **[As-Built System Reference](#as-built-system-reference-verified-against-the-codebase-2026-08-17)**. When this document conflicts with executable code or tests, the checked-out source and passing tests are authoritative.

# Long-Horizon Tasks (LHT) Pipeline Guide

A step-by-step guide to the LHT pipeline.

---

## Table of Contents

1. [Overview](https://docs.google.com/document/d/1hyEzUdg4IRO19_aNp3e5AFbaHFBtIfEv0wburbF-UtE/edit#1-overview)  
2. [Data Scraping](https://docs.google.com/document/d/1hyEzUdg4IRO19_aNp3e5AFbaHFBtIfEv0wburbF-UtE/edit#2-data-scraping)  
3. [Dataset Format (LHT JSONL Schema)](https://docs.google.com/document/d/1hyEzUdg4IRO19_aNp3e5AFbaHFBtIfEv0wburbF-UtE/edit#3-dataset-format-lht-jsonl-schema)  
4. [Eval Harness Integration](https://docs.google.com/document/d/1hyEzUdg4IRO19_aNp3e5AFbaHFBtIfEv0wburbF-UtE/edit#4-eval-harness-integration)  
5. [Trajectory Generation](https://docs.google.com/document/d/1hyEzUdg4IRO19_aNp3e5AFbaHFBtIfEv0wburbF-UtE/edit#5-trajectory-generation)  
6. [Evaluation Details](https://docs.google.com/document/d/1hyEzUdg4IRO19_aNp3e5AFbaHFBtIfEv0wburbF-UtE/edit#6-evaluation-details)  
7. [Architecture](https://docs.google.com/document/d/1hyEzUdg4IRO19_aNp3e5AFbaHFBtIfEv0wburbF-UtE/edit#7-architecture)  
8. [Known Challenges](https://docs.google.com/document/d/1hyEzUdg4IRO19_aNp3e5AFbaHFBtIfEv0wburbF-UtE/edit#8-known-challenges)

---

## 1\. Overview

This section explains what LHT is and how the pipeline works from start to finish.

### 1.1 What is LHT?

Long-Horizon Tasks (LHT) is a benchmark framework for evaluating coding agents on multi-PR version intervals. Unlike traditional benchmarks, where one instance equals one pull request, LHT instances span version intervals containing multiple PRs.

**Key Difference:**

| Aspect | Multi-SWE-Bench | LHT |
| :---- | :---- | :---- |
| Instance scope | Single PR | Version interval (N PRs) |
| Instance ID | `{org}__{repo}-{number}` | `{org}__{repo}-{tag_start}..{tag_end}` |
| Patch source | One PR diff | Cumulative diff across interval |
| Task description | Single PR body | Aggregated from all PRs in interval |

### 1.2 Pipeline Flow

```

```

### 1.3 Core Concepts

This section defines the key terms you'll see throughout this guide.

**Version Interval:** A pair of consecutive tags in the same release line (e.g., v1.2.0 to v1.2.1). The interval contains all changes merged between these two points.

**Cumulative Diff:** The complete set of code changes across all PRs in the interval, split into:

- `fix_patch`: Non-test file changes (the actual fixes)  
- `test_patch`: Test file changes (validating the fixes)

**Attribution Method:** The technique used to identify which PRs belong to a version interval. Recorded per instance for traceability.

---

## 2\. Data Scraping

This section covers how we turn raw Git repositories into structured LHT instances through four stages, one after the other.

### 2.1 Stage 1: Version Tag Discovery and Classification

This section explains how we find and organize version tags.

**Objective:** Identify all version tags and pair consecutive releases.

#### Tag Fetching

```shell
git ls-remote --tags origin
```

Returns all annotated and lightweight tags from the remote repository.

#### Tag Classification

Tags are classified into version schemes using regex patterns:

| Scheme | Pattern | Examples |
| :---- | :---- | :---- |
| Semver | `^v?\d+\.\d+\.\d+` | v1.2.3, 2.0.0 |
| Calver | `^\d{4}\.\d{2}\.\d{2}` | 2024.01.15 |
| Pre-release | \`(alpha | beta |

#### Tag Pairing Logic

Consecutive tags are paired within the same release line:

```
Release line v1.2.x:  v1.2.0 → v1.2.1 → v1.2.2
Release line v1.3.x:  v1.3.0 → v1.3.1
```

**Edge Cases:**

| Case | Handling |
| :---- | :---- |
| Pre-release tags | Filtered out or flagged; not paired with stable releases |
| Mixed schemes | Group by detected scheme, warn on inconsistencies |
| Single tag in line | Skipped (no interval to measure) |
| Non-version tags | Ignored (documentation, build tags, etc.) |

### 2.2 Stage 2: PR Attribution per Tag Pair

This section explains how we find which PRs belong to each version interval.

**Objective:** Identify which PRs were merged between each tag pair.

#### 4-Tier Fallback Strategy

PR attribution tries methods in order, falling back only if the previous yields zero results:

**Tier 1: Merge Commit Log**

```shell
git log --merges --first-parent tag1..tag2 --oneline
```

Extracts merge commits and maps them to PR numbers via commit message patterns.

**Tier 2: GitHub Compare API**

```
GET /repos/{org}/{repo}/compare/{tag1}...{tag2}
```

Returns commits between tags. PR numbers extracted from commit messages.

**Tier 3: Git Cherry**

```shell
git cherry tag1 tag2
```

Identifies commits in tag2 but not in tag1. Filters to merge commits only.

**Tier 4: Date-Range Fallback**

```
GET /search/issues?q=repo:{org}/{repo}+type:pr+merged:{date1}..{date2}
```

Uses GitHub Search API to find PRs merged between tag dates. Least accurate but most reliable.

#### Attribution Recording

Each instance records which method succeeded:

```json
{
  "pr_attribution_method": "merge_log|compare_api|git_cherry|date_range"
}
```

#### Rate Limiting Strategy

| API | Limit | Strategy |
| :---- | :---- | :---- |
| GitHub REST | 5000 req/hr | Token rotation, conditional requests |
| GitHub Search | 10 req/min | Exponential backoff, request batching |
| Git operations | N/A | Local caching, shallow clones |

### 2.3 Stage 3: Cumulative Diff Generation

This section explains how we generate the code changes for each version interval.

**Objective:** Generate the complete code diff for each version interval.

#### Full Diff Generation

```shell
git diff tag1..tag2 > cumulative.diff
```

Produces a unified diff containing all changes between the two tags.

#### Patch Splitting

The cumulative diff is split into two patches using language-specific path heuristics:

**Test Path Patterns by Language:**

| Language | Test Path Patterns |
| :---- | :---- |
| JavaScript/TypeScript | `test/`, `__tests__/`, `*.test.js`, `*.spec.ts`, `*.test.ts` |
| Python | `tests/`, `test_*.py`, `*_test.py`, `*/testing/` |
| Java | `src/test/`, `*Test.java`, `*/test/java/` |
| Go | `*_test.go`, `testdata/` |
| Rust | `tests/`, `#[cfg(test)]`, `*test*.rs` |
| C/C++ | `test/`, `tests/`, `*_test.cpp`, `*_test.c` |
| Ruby | `spec/`, `test/`, `*_spec.rb`, `*_test.rb` |
| PHP | `tests/`, `*Test.php`, `phpunit.xml` |

**Split Logic:**

```
cumulative.diff
    ├── fix_patch:  Files NOT matching test patterns
    └── test_patch: Files matching test patterns
```

**Edge Cases:**

| Case | Handling |
| :---- | :---- |
| Test-only changes | Empty fix\_patch, populated test\_patch |
| Fix-only changes | Populated fix\_patch, empty test\_patch |
| Mixed changes | Both patches populated |
| Binary files | Excluded from patches (recorded separately) |

### 2.4 Stage 4: Metadata Aggregation

This section explains how we build the task description from PR and issue data.

**Objective:** Build the instance description from aggregated PR metadata.

#### Linked Issue Extraction

Scans PR bodies for issue references:

```
Fixes #123
Closes #456
Resolves #789
Related to #abc
```

Fetches issue bodies via GitHub API and aggregates into `resolved_issues`.

#### Body Aggregation

The instance `body` field combines:

1. **PR Titles:** List of all PR titles in the interval  
2. **PR Descriptions:** Concatenated PR bodies  
3. **Issue Bodies:** Content of linked issues

**Structure:**

```
## Version Interval: v1.2.0..v1.2.1

### Pull Requests (3)

#### PR #145: Fix memory leak in connection pool
[Full PR description...]

#### PR #146: Update documentation for auth
[Full PR description...]

#### PR #147: Add retry logic for timeouts
[Full PR description...]

### Linked Issues

#### Issue #144: Memory leak reported under load
[Issue body...]
```

---

## 3\. Dataset Format (LHT JSONL Schema)

This section describes the data format for LHT instances. Each LHT instance is one line in a JSONL (JSON Lines) file. The schema extends Multi-SWE-Bench with version-interval-specific fields.

### 3.1 Changed Fields vs Multi-SWE-Bench

| Field | Multi-SWE-Bench | LHT |
| :---- | :---- | :---- |
| `instance_id` | `{org}__{repo}-{number}` | `{org}__{repo}-{tag_start}..{tag_end}` |
| `number` | PR number (int) | **Removed** |
| `base.sha` | PR base commit | Commit of `tag_start` |
| `body` | Single PR description | Aggregated from all PRs |
| `fix_patch` | Single PR diff | Cumulative non-test diff |
| `test_patch` | Single PR test changes | Cumulative test diff |

### 3.2 New Fields

| Field | Type | Description |
| :---- | :---- | :---- |
| `tag_start` | string | Starting version tag (e.g., "v1.2.0") |
| `tag_end` | string | Ending version tag (e.g., "v1.2.1") |
| `pr_numbers` | array\[int\] | List of PR numbers in interval |
| `pr_attribution_method` | string | Method used: merge\_log, compare\_api, git\_cherry, date\_range |
| `version_scheme` | string | semver, calver, or mixed |
| `head.sha` | string | Commit SHA of `tag_end` |
| `head.ref` | string | Reference for `tag_end` |

### 3.3 Unchanged Fields

| Field | Description |
| :---- | :---- |
| `org` | GitHub organization |
| `repo` | Repository name |
| `lang` | Programming language |
| `run_result` | Pre-baked baseline test results |
| `test_patch_result` | Pre-baked test-patch results |
| `fix_patch_result` | Pre-baked fix-patch results |
| `f2p_tests` | Tests expected to go from fail to pass |

### 3.4 Complete Example JSONL Entry

```json
{
  "instance_id": "fastify__fastify-v4.28.0..v4.28.1",
  "org": "fastify",
  "repo": "fastify",
  "lang": "javascript",
  "tag_start": "v4.28.0",
  "tag_end": "v4.28.1",
  "version_scheme": "semver",
  "pr_numbers": [5421, 5423, 5425],
  "pr_attribution_method": "merge_log",
  "base": {
    "sha": "abc123def456...",
    "ref": "v4.28.0"
  },
  "head": {
    "sha": "def789abc012...",
    "ref": "v4.28.1"
  },
  "body": "## Version Interval: v4.28.0..v4.28.1\n\n### Pull Requests (3)\n\n#### PR #5421: Fix schema compilation error\n[Description...]\n\n#### PR #5423: Update dependencies\n[Description...]\n\n#### PR #5425: Add validation for nested objects\n[Description...]\n\n### Linked Issues\n\n#### Issue #5420: Schema compilation fails on circular refs\n[Issue body...]",
  "resolved_issues": ["#5420", "#5422"],
  "fix_patch": "diff --git a/lib/schema.js b/lib/schema.js\n...",
  "test_patch": "diff --git a/test/schema.test.js b/test/schema.test.js\n...",
  "run_result": {
    "passed_count": 245,
    "failed_count": 0,
    "skipped_count": 12,
    "passed_tests": ["test1", "test2", ...],
    "failed_tests": [],
    "skipped_tests": ["skip1", "skip2", ...]
  },
  "test_patch_result": {
    "passed_count": 248,
    "failed_count": 3,
    "skipped_count": 12,
    "passed_tests": ["test1", "test2", "new_test1", ...],
    "failed_tests": ["new_test2", "new_test3", "new_test4"],
    "skipped_tests": ["skip1", "skip2", ...]
  },
  "fix_patch_result": {
    "passed_count": 251,
    "failed_count": 0,
    "skipped_count": 12,
    "passed_tests": ["test1", "test2", "new_test1", "new_test2", "new_test3", "new_test4", ...],
    "failed_tests": [],
    "skipped_tests": ["skip1", "skip2", ...]
  },
  "f2p_tests": ["new_test2", "new_test3", "new_test4"]
}
```

---

## 4\. Eval Harness Integration

This section explains how the evaluation system works with LHT instances.

The existing Multi-SWE-Bench evaluation harness requires minimal changes to support LHT instances.

### 4.1 Compatibility Overview

The harness architecture is patch-source-agnostic. The 3-Docker-run pattern (baseline, test-patch-only, fix+test) works identically for LHT.

**Changes Required:**

| Component | Change | Lines |
| :---- | :---- | :---- |
| Instance/PullRequest layer | Support new `instance_id` format | \~20 |
| Checkout logic | Tag-based instead of PR-based | \~15 |
| Docker naming | Tag interval in image tag | \~10 |
| Parse log | No changes | 0 |
| Report generation | No changes | 0 |

### 4.2 Instance ID Handling

The harness parses `instance_id` to extract org, repo, and identifier:

```py
# Multi-SWE-Bench
"fastify__fastify-1455" → org=fastify, repo=fastify, id=1455

# LHT
"fastify__fastify-v4.28.0..v4.28.1" → org=fastify, repo=fastify, 
                                        tag_start=v4.28.0, tag_end=v4.28.1
```

### 4.3 Tag-Based Checkout

Instead of checking out a PR's base commit, LHT instances checkout the `tag_start` commit:

```shell
# Multi-SWE-Bench
git checkout {base_commit}

# LHT
git checkout {tag_start}
# or
git checkout {base.sha}
```

### 4.4 Docker Image Naming

| Benchmark | Image Tag Format |
| :---- | :---- |
| Multi-SWE-Bench | `mswebench/{org}_m_{repo}:pr-{number}` |
| LHT | `mswebench/{org}_m_{repo}:{tag_start}..{tag_end}` |

Example:

```
mswebench/fastify_m_fastify:v4.28.0..v4.28.1
```

### 4.5 Parse Log Function

The language-specific `parse_log()` methods require **no changes**. They operate on test output strings, which have the same format regardless of patch source.

```py
class Fastify(Instance):
    def parse_log(self, test_log: str) -> TestResult:
        # Identical for both Multi-SWE-Bench and LHT
        ...
```

---

## 5\. Trajectory Generation

This section covers how we run agents and evaluate their performance.

Trajectory generation follows the same 4-phase pattern as Multi-SWE-Bench, adapted for LHT's aggregated task descriptions.

### 5.1 Phase 0: Docker Image Setup

This section explains how we set up the environment for running agents.

**Base Image:**

- Repository checked out at `tag_start` commit  
- Dependencies installed per language requirements  
- Build environment configured

**Agent-Server Image:**

- Layers OpenHands agent runtime on base image  
- Multi-stage build with `source-minimal` target  
- Patches file permissions for `openhands` user (UID 10001\)

**Pre-Build Strategy:**

1. Build base image from first instance  
2. Pre-build agent-server images for all instances in parallel  
3. Pre-clone shared repos to `.shared_repos/`

### 5.2 Phase 1: Inference

This section explains how agents generate fixes.

**Task Input:**

The agent receives the aggregated `body` field containing:

- Version interval description  
- All PR titles and descriptions  
- Linked issue content

**Execution Model:**

For pass@k evaluation (typically k=8):

- Temperature \= 1.0 for diverse outputs  
- NUM\_WORKERS instances in parallel  
- Each instance spawns k independent runs

**Per-Run Command:**

```shell
uv run python -m benchmarks.multiswebench.run_infer \
  {llm_config} \
  --dataset {instance_jsonl} \
  --split train \
  --lang {language} \
  --workspace docker \
  --max-iterations 1000 \
  --num-workers 1 \
  --max-retries 3 \
  --max-attempts 1 \
  --output-dir {run_dir}
```

**Resume Logic:**

If `output.jsonl` exists and contains valid JSON, the run is skipped. Invalid files are deleted and re-run.

### 5.3 Phase 2: Evaluation

This section explains how we check if the agent's fix works.

**Patch Application:**

1. Checkout repo at `tag_start` commit  
2. Apply agent's generated patch  
3. Apply `test_patch` (cumulative test changes)  
4. Run test suite

**State Transitions:**

The evaluation tracks test state transitions across the 3 runs:

| State | Meaning |
| :---- | :---- |
| p2p | Pass to Pass (no regression) |
| f2p | Fail to Pass (fix worked) |
| s2p | Skip to Pass (fix enabled test) |
| n2p | None to Pass (new test passes) |

**Resolution Criteria:**

An instance is resolved if:

1. All `f2p_tests` pass in the fix\_patch\_run  
2. No previously-passing tests fail (no regression)  
3. Tests actually ran (not all skipped)

### 5.4 Phase 3: Summary

This section explains how we calculate the final scores.

**pass@k Calculation:**

```json
{
  "metric": "pass@8",
  "k": 8,
  "total_instances": 50,
  "instances_with_any_pass": 23,
  "pass_at_k": 0.46,
  "per_instance": {
    "fastify__fastify-v4.28.0..v4.28.1": {
      "run_1": "Pass",
      "run_2": "Fail",
      ...
    }
  }
}
```

An instance is resolved if ANY of the k runs produces a correct fix.

### 5.5 Command Reference

This section lists the commands for running the pipeline.

**Full Pipeline (inference \+ evaluation, pass@8):**

```shell
cd /home/ec2-user/traj/benchmarks

bash run_custom_eval.sh \
  --llm-config .llm_config/claude.json \
  --dataset datastes/fastify__fastify_lht.jsonl \
  --ecr-prefix 426628337772.dkr.ecr.ap-south-1.amazonaws.com/rfp-coding-q1-tag \
  --lang javascript \
  -k 8 \
  --num-workers 16
```

**Inference Only:**

```shell
bash run_custom_eval.sh \
  --llm-config .llm_config/claude.json \
  --dataset datastes/fastify__fastify_lht.jsonl \
  --ecr-prefix ... \
  --lang javascript \
  -k 8 --num-workers 7 \
  --skip-eval
```

**Evaluation Only:**

```shell
bash run_custom_eval.sh \
  --llm-config .llm_config/claude.json \
  --dataset datastes/fastify__fastify_lht.jsonl \
  --ecr-prefix ... \
  --lang javascript \
  -k 8 --num-workers 16 \
  --skip-infer
```

### 5.6 Output Directory Structure

This section shows where files are stored after a run.

```
eval_outputs/
├── .shared_repos/
│   └── {org}/{repo}/
│
├── {instance_id}/                          # fastify__fastify-v4.28.0..v4.28.1/
│   └── {model}/                            # claude/
│       ├── runner.log
│       ├── pass_at_8_summary.json
│       │
│       ├── run_1/
│       │   ├── infer.log
│       │   ├── output.jsonl
│       │   ├── output_converted.jsonl
│       │   ├── metadata.json
│       │   ├── config.json
│       │   ├── eval.log
│       │   ├── output.report.json
│       │   └── eval_files/
│       │       └── workdir/{org}/{repo}/
│       │           └── evals/{instance_id}/
│       │               ├── report.json
│       │               └── fix-patch-run.log
│       │
│       ├── run_2/ ... run_8/
```

### 5.7 LLM Configuration

This section shows how to set up the language model.

```json
{
  "model": "bedrock/converse/<inference-profile-arn>",
  "api_key": "<base64-encoded-key>",
  "model_canonical_name": "anthropic.claude-sonnet-4-6",
  "aws_region_name": "us-east-1",
  "temperature": 1.0,
  "top_p": null
}
```

---

## 6\. Evaluation Details

This section dives deeper into how we evaluate agent performance.

### 6.1 The Three Test Runs

Each LHT instance undergoes 3 Docker container executions:

```
Run 1: run()              → No patches applied
       Command: bash /scripts/run.sh
       Purpose: Baseline test behavior

Run 2: test_patch_run()   → Test patch only
       Command: bash /scripts/test-run.sh
       Purpose: Show tests that fail without fix

Run 3: fix_patch_run()    → Test patch + fix patch
       Command: bash /scripts/fix-run.sh
       Purpose: Verify fix resolves failures
```

### 6.2 TestResult Dataclass

```py
@dataclass
class TestResult:
    passed_count: int
    failed_count: int
    skipped_count: int
    passed_tests: set[str]
    failed_tests: set[str]
    skipped_tests: set[str]
    _tests: dict[str, TestStatus]
```

**Validation:**

- `len(passed_tests) == passed_count`  
- Pass/fail/skip sets are mutually exclusive

### 6.3 Report with State Transitions

The `Report` class tracks state transitions for each test:

```py
@dataclass
class Test:
    run: TestStatus      # Baseline
    test: TestStatus     # Test-patch-only
    fix: TestStatus      # Fix+test

class Report:
    tests: dict[str, Test]
    p2p: set[str]        # Pass → Pass
    f2p: set[str]        # Fail → Pass
    s2p: set[str]        # Skip → Pass
    n2p: set[str]        # None → Pass
```

**State Transition Table:**

| Test Patch | Fix Patch | State | Meaning |
| :---- | :---- | :---- | :---- |
| PASS | PASS | p2p | Already passing, still passes |
| FAIL | PASS | f2p | Fix resolved the failure |
| SKIP | PASS | s2p | Fix enabled a skipped test |
| NONE | PASS | n2p | New test introduced by fix |

### 6.4 Validity Checks (Report.check())

A report must pass these checks:

1. **Results Exist:** `fix_patch_result.all_count > 0` (tests actually ran)  
2. **No Regressions:** No p2p tests became FAIL  
3. **Fixes Something:** At least one f2p, s2p, or n2p transition  
4. **No Anomalies:** Unexpected state combinations flagged

### 6.5 FinalReport

Aggregates results across all instances:

```py
@dataclass
class FinalReport:
    resolved: list[str]      # Instance IDs with valid fixes
    unresolved: list[str]    # Instance IDs where fix didn't resolve
    error: list[str]         # Instance IDs with execution errors
    empty: list[str]        # Instance IDs with no test results
```

### 6.6 Language-Specific Log Parsing

This section shows how we read test output for different languages.

**JavaScript (mocha/spec):**

- Pass: `✓ test name`  
- Fail: Numbered failures at bottom of output

**JavaScript (node:test):**

- Pass: `✔ test name`  
- Fail: `✖ test name`  
- Summary: `ℹ` lines

**Python (pytest):**

- Pass: `PASSED` or `passed`  
- Fail: `FAILED` or `failed`  
- Skip: `SKIPPED` or `skipped`

**Go (go test):**

- Pass: `--- PASS: TestName`  
- Fail: `--- FAIL: TestName`

**Java (Maven/Surefire):**

- Parses Maven test output XML  
- Extracts from console summary

**Rust (cargo test):**

- Pass: `test result: ok`  
- Fail: `test result: FAILED`  
- Individual: `test test_name ... ok`

---

## 7\. Architecture

This section describes the code organization and data structures.

### 7.1 Recommended Module Structure

```
lht_pipeline/
├── __init__.py
├── main.py                    # CLI entry point
├── config.py                  # Configuration dataclasses
├── models.py                  # Core data models
├── output.py                  # Output serialization
│
├── tags/                      # Stage 1: Tag Discovery
│   ├── __init__.py
│   ├── fetcher.py            # git ls-remote wrapper
│   ├── classifier.py         # semver/calver detection
│   └── pairer.py             # Consecutive tag pairing
│
├── attribution/               # Stage 2: PR Attribution
│   ├── __init__.py
│   ├── merge_log.py          # Tier 1: git log --merges
│   ├── github_compare.py     # Tier 2: Compare API
│   ├── git_cherry.py         # Tier 3: git cherry
│   ├── date_range.py         # Tier 4: Search API
│   └── aggregator.py         # PR metadata aggregation
│
├── patches/                   # Stage 3: Diff Generation
│   ├── __init__.py
│   ├── differ.py             # git diff execution
│   └── splitter.py           # fix/test patch splitting
│
└── metadata/                  # Stage 4: Metadata
    ├── __init__.py
    ├── issues.py             # Linked issue extraction
    └── descriptions.py       # Body aggregation
```

### 7.2 Core Data Models

This section defines the main data structures used in the code.

```py
# models.py

@dataclass
class VersionTag:
    name: str
    commit: str
    scheme: str  # semver, calver, prerelease
    parsed: Union[semver.VersionInfo, datetime]

@dataclass
class TagPair:
    start: VersionTag
    end: VersionTag
    release_line: str

@dataclass
class PullRequest:
    number: int
    title: str
    body: str
    merge_commit: Optional[str]
    merged_at: datetime
    linked_issues: list[str]

@dataclass
class LHTInstance:
    instance_id: str
    org: str
    repo: str
    tag_start: str
    tag_end: str
    pr_numbers: list[int]
    pr_attribution_method: str
    version_scheme: str
    base_sha: str
    head_sha: str
    head_ref: str
    body: str
    resolved_issues: list[str]
    fix_patch: str
    test_patch: str
    run_result: TestResult
    test_patch_result: TestResult
    fix_patch_result: TestResult
    f2p_tests: list[str]
```

### 7.3 CLI Usage Examples

This section shows example commands for running different parts of the pipeline.

**Full Pipeline:**

```shell
python -m lht_pipeline.main \
  --repo fastify/fastify \
  --output datastes/fastify__fastify_lht.jsonl \
  --scheme semver \
  --skip-prerelease
```

**Tag Discovery Only:**

```shell
python -m lht_pipeline.tags \
  --repo fastify/fastify \
  --output tags.json \
  --scheme-filter semver
```

**PR Attribution Only:**

```shell
python -m lht_pipeline.attribution \
  --repo fastify/fastify \
  --tags tags.json \
  --output attribution.json \
  --method-priority merge_log,compare_api,git_cherry,date_range
```

**Generate Patches:**

```shell
python -m lht_pipeline.patches \
  --repo fastify/fastify \
  --attribution attribution.json \
  --output patches/
```

---

## 8\. Known Challenges

This section lists common problems and how we handle them.

### 8.1 PR Attribution Accuracy

**Challenge:** Determining which PRs belong to a version interval is the most complex and error-prone part of the pipeline.

**Impact:** \~40% of development effort

**Mitigations:**

- 4-tier fallback strategy  
- Record attribution method for each instance  
- Manual validation sampling  
- Cross-reference with release notes when available

### 8.2 GitHub API Rate Limiting

**Limits:**

- REST API: 5000 requests/hour  
- Search API: 10 requests/minute

**Mitigations:**

- Token rotation across multiple accounts  
- Conditional requests (If-None-Match)  
- Exponential backoff with jitter  
- Local caching of API responses  
- Request batching where possible

### 8.3 Tag Classification Edge Cases

**Challenges:**

- Mixed versioning schemes within one repo  
- Pre-release tags (alpha, beta, rc) mixed with stable  
- Non-version tags (docs, build, etc.)  
- Inconsistent tagging patterns

**Mitigations:**

- Configurable regex patterns per repo  
- Manual override lists  
- Pre-release filtering options  
- Scheme consistency validation

### 8.4 Test Path Heuristic False Positives

**Challenge:** Language-specific test path patterns may misclassify files.

**Examples:**

- `lib/test_utils.js` (utility, not test)  
- `src/testing/framework.go` (framework code, not test)  
- `docs/examples/test_sample.py` (example, not test)

**Mitigations:**

- Multi-pattern matching  
- Negative pattern lists  
- Manual review of edge cases  
- Per-repo configuration overrides

### 8.5 Large Intervals

**Challenge:** Version intervals containing 100+ PRs create:

- Very large patch files  
- Overwhelming task descriptions  
- Attribution ambiguity

**Mitigations:**

- Interval size limits (configurable)  
- Major version boundary detection  
- Sampling strategies for very active repos  
- Hierarchical aggregation (group related PRs)

### 8.6 Repositories with No/Irregular Tags

**Challenge:** Some repositories lack consistent version tagging.

**Mitigations:**

- Commit-date-based intervals as fallback  
- Manual tag curation for high-value repos  
- Skip lists for unsuitable repositories  
- Alternative interval definitions (weekly, monthly)

---

## Appendix: Quick Reference

### Instance ID Format

```
{org}__{repo}-{tag_start}..{tag_end}

Examples:
  fastify__fastify-v4.28.0..v4.28.1
  python__cpython-v3.12.0..v3.12.1
  rust-lang__rust-1.75.0..1.76.0
```

### Docker Image Naming

```
mswebench/{org}_m_{repo}:{tag_start}..{tag_end}

Examples:
  mswebench/fastify_m_fastify:v4.28.0..v4.28.1
  mswebench/python_m_cpython:v3.12.0..v3.12.1
```

### Attribution Method Priority

1. `merge_log` \- Most accurate, uses git history  
2. `compare_api` \- GitHub API comparison  
3. `git_cherry` \- Commit cherry-pick detection  
4. `date_range` \- Fallback using merge dates

### Test Path Patterns by Language

See Section 2.3 for complete list.

### State Transitions

| Code | From | To | Meaning |
| :---- | :---- | :---- | :---- |
| p2p | PASS | PASS | No regression |
| f2p | FAIL | PASS | Fix worked |
| s2p | SKIP | PASS | Fix enabled test |
| n2p | NONE | PASS | New test passes |

---

*End of LHT Pipeline Guide*

# Docker Image Build & Run Result Workflow

# Multi-SWE-Bench: Docker Image Build & Run Result Workflow

This document describes the end-to-end workflow \- from repository configuration to Docker image building to test execution and run result data generation.

---

## Table of Contents

1. [Overview](https://docs.google.com/document/d/1JUsXu6bZ_K7WwP7QpREjx0GZUsWdwAKd34BWnuJeEOI/edit#overview)  
2. [Repository Configuration](https://docs.google.com/document/d/1JUsXu6bZ_K7WwP7QpREjx0GZUsWdwAKd34BWnuJeEOI/edit#repository-configuration)  
3. [Instance Registry](https://docs.google.com/document/d/1JUsXu6bZ_K7WwP7QpREjx0GZUsWdwAKd34BWnuJeEOI/edit#instance-registry)  
4. [Docker Image Architecture](https://docs.google.com/document/d/1JUsXu6bZ_K7WwP7QpREjx0GZUsWdwAKd34BWnuJeEOI/edit#docker-image-architecture)  
5. [Docker Image Building](https://docs.google.com/document/d/1JUsXu6bZ_K7WwP7QpREjx0GZUsWdwAKd34BWnuJeEOI/edit#docker-image-building)  
6. [Test Execution (Run Results)](https://docs.google.com/document/d/1JUsXu6bZ_K7WwP7QpREjx0GZUsWdwAKd34BWnuJeEOI/edit#test-execution-run-results)  
7. [Report Generation & Test State Transitions](https://docs.google.com/document/d/1JUsXu6bZ_K7WwP7QpREjx0GZUsWdwAKd34BWnuJeEOI/edit#report-generation--test-state-transitions)  
8. [Evaluation Mode](https://docs.google.com/document/d/1JUsXu6bZ_K7WwP7QpREjx0GZUsWdwAKd34BWnuJeEOI/edit#evaluation-mode)  
9. [Key Data Models](https://docs.google.com/document/d/1JUsXu6bZ_K7WwP7QpREjx0GZUsWdwAKd34BWnuJeEOI/edit#key-data-models)

---

## Overview

```
┌────────────────────┐
│  Repo Config File  │  Per-repo Python file under repos/{lang}/{org}/{repo}.py
│  (Image + Instance)│
└────────┬───────────┘
         │
         ▼
┌────────────────────┐
│  Instance Registry  │  @Instance.register(org, repo) decorator
│  Instance.create()  │  Factory method looks up registry by "{org}/{repo}"
└────────┬───────────┘
         │
         ▼
┌────────────────────┐
│  Docker Image Build │  Dependency graph traversal: base image → PR image
│  (Dockerfile gen)   │  DockerfileEnhancer injects BuildKit, ARGs, labels
└────────┬───────────┘
         │
         ▼
┌────────────────────┐
│  Test Execution     │  3 Docker container runs per instance:
│  (3 runs per PR)    │  1. run (baseline)  2. test_patch_run  3. fix_patch_run
└────────┬───────────┘
         │
         ▼
┌────────────────────┐
│  Report Generation  │  parse_log() → TestResult → Report
│  (p2p/f2p/s2p/n2p) │  State transitions + validity checks
└────────────────────┘
```

---

## Repository Configuration

Each supported repository has a config file at:

```
multi_swe_bench/harness/repos/{language}/{org}/{repo}.py
```

Supported languages include: `c`, `cpp`, `java`, `javascript`, `typescript`, `golang`, `rust`, `python`, and more (15+ languages total).

### Each config file defines three components:

### 1\. Base Image Class (extends `Image`)

Defines the foundational Docker image \- OS, system dependencies, and repo clone.

```py
class AMReXImageBase(Image):
    def dependency(self):
        return "ubuntu:22.04"  # Returns a string = external base image

    def dockerfile(self):
        return """
        RUN apt-get update && apt-get install -y build-essential cmake ...
        RUN git clone https://github.com/{org}/{repo}.git /repo
        RUN cd /repo && git checkout {base_commit}
        """

    def files(self):
        return []  # Additional files to copy into build context
```

- `dependency()` returns a **string** (an external Docker image name like `ubuntu:22.04`).  
- Installs system-level packages, clones the repo, checks out the base commit.

### 2\. PR Image Class (extends `Image`)

Builds on the base image, adding PR-specific patches and test scripts.

```py
class AMReXImageDefault(Image):
    def dependency(self):
        return AMReXImageBase  # Returns an Image class = depends on base image

    def dockerfile(self):
        return """
        COPY fix.patch test.patch /patches/
        COPY prepare.sh run.sh test-run.sh fix-run.sh /scripts/
        COPY build_and_test.sh apply_patches.sh check_git_changes.sh /scripts/
        COPY pr_info.txt /
        """

    def files(self):
        return [
            File(dir="", name="fix.patch", content=self.pr.fix_patch),
            File(dir="", name="test.patch", content=self.pr.test_patch),
            File(dir="", name="prepare.sh", content=self._prepare_script()),
            File(dir="", name="run.sh", content=self._run_script()),
            File(dir="", name="test-run.sh", content=self._test_run_script()),
            File(dir="", name="fix-run.sh", content=self._fix_run_script()),
            # ... additional scripts
        ]
```

- `dependency()` returns an **Image class** (the base image), establishing the build chain.  
- Includes patches (`fix.patch`, `test.patch`), execution scripts, and PR metadata.

### 3\. Instance Registry Class (extends `Instance`)

Registered via decorator, ties images to execution and log parsing logic.

```py
@Instance.register("AMReX-Codes", "amrex")
class AMReX(Instance):
    def dependency(self):
        return AMReXImageDefault(self.pr, self.config)

    def run(self):
        return "bash /scripts/run.sh"

    def test_patch_run(self):
        return "bash /scripts/test-run.sh"

    def fix_patch_run(self):
        return "bash /scripts/fix-run.sh"

    def parse_log(self, test_log: str) -> TestResult:
        # Parse test output into structured TestResult
        ...
```

---

## Instance Registry

**File**: `multi_swe_bench/harness/instance.py`

The `Instance` class maintains a class-level registry (`_registry = {}`) that maps `"{org}/{repo}"` keys to Instance subclasses.

### Registration

```py
@Instance.register("AMReX-Codes", "amrex")
class AMReX(Instance):
    ...
```

This stores `AMReX` under the key `"AMReX-Codes/amrex"` in `Instance._registry`.

### Factory Method

```py
Instance.create(pr, config)
```

- Looks up `Instance._registry` by `"{pr.org}/{pr.repo}"`.  
- Falls back to variants with `number_interval` or `tag` suffixes if no exact match.  
- Returns an instantiated Instance subclass ready for image building and test execution.

### Abstract Methods

| Method | Returns | Purpose |
| :---- | :---- | :---- |
| `dependency()` | `Image` | The PR Docker image for this instance |
| `run()` | `str` | Command for baseline run (no patches) |
| `test_patch_run()` | `str` | Command for test-patch-only run |
| `fix_patch_run()` | `str` | Command for test+fix patch run |
| `parse_log(test_log)` | `TestResult` | Parse container log into structured result |

---

## Docker Image Architecture

**File**: `multi_swe_bench/harness/image.py`

### Image Naming

```
{prefix}/{org}_m_{repo}:{tag}
```

- Default prefix: `mswebench`  
- Example: `mswebench/AMReX-Codes_m_amrex:pr-1234`

### Image Layer Chain

```
External Image (e.g. ubuntu:22.04)
    └── Base Image (system deps + repo clone)
            └── PR Image (patches + scripts)
```

### Key Classes

**`File` dataclass**: Represents a file to copy into Docker build context.

- `dir`: Subdirectory within context  
- `name`: Filename  
- `content`: File content as string

**`Config` dataclass**: Build configuration.

- `need_clone: bool` \- Whether to clone the repo  
- `global_env: Optional[dict]` \- Environment variables  
- `clear_env: bool` \- Whether to clear existing env

**`Image` abstract class**: Base for all image definitions.

- `dependency()` → `Union[str, Image]` \- Parent image (string \= external, Image \= internal)  
- `dockerfile()` → Dockerfile content  
- `files()` → List of `File` objects for build context  
- `image_full_name()` → Full image name with prefix and tag

### DockerfileEnhancer

`DockerfileEnhancer.enhance(image)` post-processes every generated Dockerfile to inject:

1. **BuildKit syntax directive** \- Enables advanced Dockerfile features  
2. **`TARGETARCH` ARG** \- Multi-architecture support  
3. **`REPO_URL` / `BASE_COMMIT` ARGs** \- Standardized repo fetch (replaces hardcoded clone URLs with `${REPO_URL}` / `${BASE_COMMIT}` variables)  
4. **Proxy ARGs** \- Corporate proxy support  
5. **Environment block** \- From `Config.global_env`  
6. **Certificate symlinks** \- TLS cert handling  
7. **Labels** \- Image metadata

### Special Case: SWEImageDefault

For Python SWE-bench instances, `SWEImageDefault` uses pre-built `swebench` images instead of building from scratch.

---

## Docker Image Building

**File**: `multi_swe_bench/harness/build_dataset.py`

### Build Modes

The `CliArgs` dataclass supports four modes:

| Mode | Description |
| :---- | :---- |
| `dataset` | Full pipeline: images → instances → reports |
| `instance` | Build images, then run instances |
| `instance_only` | Run instances only (images must exist) |
| `image` | Build images only |

### Build Flow

```
run_mode_dataset()
    ├── run_mode_instance()
    │       ├── run_mode_image()        ← Build Docker images
    │       ├── run_mode_instance_only() ← Run test containers
    │       └── ReportBuilder.run()      ← Generate reports
    └── (additional dataset processing)
```

### Image Build Process

1. **Load Dataset**: JSONL raw dataset → `PullRequest` objects → `Instance.create(pr, config)` for each  
2. **Construct Dependency Graph**: Walk each `instance.dependency()` chain to discover all images  
3. **Layer-by-Layer Build**: Using `ThreadPoolExecutor`, build images respecting dependency ordering (base images first, then PR images)  
4. **Per-Image Build**:

```
build_image(image):
    1. Create working directory
    2. Generate Dockerfile via image.dockerfile()
    3. Enhance Dockerfile via DockerfileEnhancer.enhance()
    4. Write image.files() to build context
    5. Call docker_util.build()
```

### Docker Utilities

**File**: `multi_swe_bench/utils/docker_util.py`

**`docker_util.exists(image_name)`**: Checks if a Docker image already exists locally (skips rebuild).

**`docker_util.build(workdir, dockerfile, image_name, ...)`**: Two build paths:

- **SDK path** (`_build_with_sdk`): Uses `docker_client.api.build()` for single-architecture builds.  
- **Buildx path** (`_build_with_buildx`): Uses `docker buildx build` subprocess for multi-architecture support, handles OCI tar export \+ daemon load.

**`docker_util.run(image_name, command, output_path, env, volumes)`**: Runs a container detached, streams logs to a file, returns the output string, and removes the container after completion.

---

## Test Execution (Run Results)

**File**: `multi_swe_bench/harness/build_dataset.py` → `run_instance()`

Each instance undergoes **3 Docker container runs** to produce the run result data:

### The Three Runs

```
┌─────────────────────────────────────────────────────┐
│                    Instance                          │
│                                                      │
│  Run 1: run()            → No patches applied        │
│         Command: bash /scripts/run.sh                │
│         Purpose: Baseline - how tests behave without │
│                  any modifications                   │
│                                                      │
│  Run 2: test_patch_run() → Test patch only           │
│         Command: bash /scripts/test-run.sh           │
│         Purpose: Apply test patch, run tests.        │
│                  Shows which tests fail without fix.  │
│                                                      │
│  Run 3: fix_patch_run()  → Test patch + fix patch    │
│         Command: bash /scripts/fix-run.sh            │
│         Purpose: Apply both patches, run tests.      │
│                  Shows which tests pass with the fix. │
│                                                      │
└─────────────────────────────────────────────────────┘
```

### Execution Modes

- **Human mode**: Runs sequentially (run → test\_patch\_run → fix\_patch\_run)  
- **Envagent mode**: Runs in parallel for throughput

### Container Execution Details

Each run:

1. Starts a detached Docker container from the PR image  
2. Executes the respective command (e.g., `bash /scripts/test-run.sh`)  
3. Streams container logs to a file  
4. Returns the output as a string  
5. Removes the container after completion

### Log Parsing

After all 3 runs complete, each log string is parsed by `instance.parse_log(test_log)` which returns a `TestResult`:

```py
TestResult:
    passed_count: int
    failed_count: int
    skipped_count: int
    passed_tests: set[str]     # Set of test names that passed
    failed_tests: set[str]     # Set of test names that failed
    skipped_tests: set[str]    # Set of test names that were skipped
    _tests: dict[str, TestStatus]  # Full map of test_name → status
```

**`TestStatus` enum values**: `PASS`, `FAIL`, `SKIP`, `NONE`, `FAILED`, `PASSED`, `SKIPPED`, `ERROR`, `XFAIL`

---

## Report Generation & Test State Transitions

**File**: `multi_swe_bench/harness/report.py`

### Report Generation Flow

```py
generate_report(instance, run_result, test_patch_result, fix_patch_result)
```

1. If raw log strings are passed, calls `instance.parse_log()` to convert each to `TestResult`  
2. Creates a `Report` from the three `TestResult` objects

### Report Construction

`Report.__post_init__()`:

1. Merges all test names from the 3 runs into a unified set  
2. For each test name, creates a `Test(run, test, fix)` tuple containing the status from each run

### Test State Transitions (p2p / f2p / s2p / n2p)

The core of the run result data. By comparing the **test patch run** status with the **fix patch run** status for each test:

```
┌────────┬──────────────────┬──────────────────┬───────────────────────────────┐
│ State  │ Test Patch Run   │ Fix Patch Run    │ Meaning                       │
├────────┼──────────────────┼──────────────────┼───────────────────────────────┤
│ p2p    │ PASS             │ PASS             │ Already passing, still passes │
│        │                  │                  │ (no regression)               │
├────────┼──────────────────┼──────────────────┼───────────────────────────────┤
│ f2p    │ FAIL             │ PASS             │ Was failing, now passes       │
│        │                  │                  │ (fix resolved the failure)    │
├────────┼──────────────────┼──────────────────┼───────────────────────────────┤
│ s2p    │ SKIP             │ PASS             │ Was skipped, now passes       │
│        │                  │                  │ (fix enabled a skipped test)  │
├────────┼──────────────────┼──────────────────┼───────────────────────────────┤
│ n2p    │ NONE             │ PASS             │ Test didn't exist, now passes │
│        │                  │                  │ (new test introduced by fix)  │
└────────┴──────────────────┴──────────────────┴───────────────────────────────┘
```

### Validity Checks (`Report.check()`)

A report must pass these checks to be considered valid:

1. **Fix patch must produce results** \- The fix\_patch\_run must have parseable test output  
2. **No regressions** \- A test that was `PASS` in test\_patch\_run must NOT become `FAIL` in fix\_patch\_run  
3. **Must fix something** \- At least one test must transition from non-PASS → PASS (i.e., at least one f2p, s2p, or n2p)  
4. **No anomalous patterns** \- Catches unexpected state combinations

### FinalReport

Aggregates results across all instances:

```
FinalReport:
    resolved: list[str]      # Instance IDs where fix was valid
    unresolved: list[str]    # Instance IDs where fix didn't resolve
    error: list[str]         # Instance IDs with execution errors
    empty: list[str]         # Instance IDs with no test results
```

---

## Evaluation Mode

**File**: `multi_swe_bench/harness/run_evaluation.py`

Evaluation mode is similar to the dataset build flow but is used for evaluating **model predictions** against ground truth.

### Inputs

- `patch_files`: Model-generated fix patches (predictions)  
- `dataset_files`: Ground truth data (expected fixes)

### Evaluation Flow

```
run_mode_evaluation()
    ├── Build Docker images (same as dataset mode)
    ├── run_instance():
    │       1. Write model's fix.patch from patch_files
    │       2. Run container with fix_patch_run command
    │       3. Mount fix.patch as a Docker volume
    │       4. Capture logs
    └── ReportBuilder.run() → Generate final report
```

The key difference: instead of using the ground-truth fix patch baked into the image, evaluation mode **mounts the model's predicted patch** as a volume, allowing the same image to be tested with different fix attempts.

---

## Key Data Models

### PullRequest

**File**: `multi_swe_bench/harness/pull_request.py`

```
Repository(org, repo)
    └── PullRequestBase(org, repo, number)
            └── PullRequest(state, title, body, base, resolved_issues,
                           fix_patch, test_patch, tag, number_interval, lang)
```

- `Base(label, ref, sha)` \- The base commit information  
- PR `id` format: `"{org}/{repo}:pr-{number}"`

### TestResult

**File**: `multi_swe_bench/harness/test_result.py`

```py
TestResult:
    passed_count: int
    failed_count: int
    skipped_count: int
    passed_tests: set[str]
    failed_tests: set[str]
    skipped_tests: set[str]
    _tests: dict[str, TestStatus]
```

`get_modified_files(patch)`: Utility that parses a unified diff to extract modified file paths.

### Report

**File**: `multi_swe_bench/harness/report.py`

```py
Test:
    run: TestStatus    # Baseline run status
    test: TestStatus   # Test-patch-only run status
    fix: TestStatus    # Fix-patch run status

Report:
    tests: dict[str, Test]  # test_name → Test(run, test, fix)

    # State transition sets:
    p2p: set[str]  # pass-to-pass tests
    f2p: set[str]  # fail-to-pass tests
    s2p: set[str]  # skip-to-pass tests
    n2p: set[str]  # none-to-pass tests
```

# Trajectory Generation Pipeline

# Trajectory Generation Pipeline

Technical guide covering the end-to-end process for generating and evaluating coding agent trajectories using the Multi-SWE-Bench harness.

---

## Pipeline Overview

```
                         TRAJECTORY GENERATION PIPELINE
                         ==============================

  Dataset (JSONL)          LLM Config              ECR / Docker Images
       |                      |                           |
       v                      v                           v
  +------------------------------------------------------------------+
  |                    run_custom_eval.sh                             |
  |                  (Main Orchestrator)                              |
  +------------------------------------------------------------------+
       |
       |  PHASE 0: Docker Image Setup
       |  - Pull/build base repo image from ECR
       |  - Build agent-server image (layered on base)
       |  - Pre-build images for all instances (parallel)
       |  - Pre-clone shared repos
       |
       v
  +------------------------------------------------------------------+
  |  PHASE 1: INFERENCE (per instance, k runs each)                  |
  |                                                                  |
  |  For each instance (NUM_WORKERS parallel):                       |
  |    run_1 first (builds image) --> runs 2..K in parallel          |
  |                                                                  |
  |  run_infer.py per run:                                           |
  |    -> Spin up agent-server container                             |
  |    -> AI agent reads code, edits, runs commands                  |
  |    -> Agent submits patch or hits timeout                        |
  |    -> output.jsonl (patch + conversation + metrics)              |
  +------------------------------------------------------------------+
       |
       v
  +------------------------------------------------------------------+
  |  PHASE 2: EVALUATION (per run, parallelized)                     |
  |                                                                  |
  |  convert.py: extract git_patch from output.jsonl                 |
  |  run_evaluation.py:                                              |
  |    -> Apply agent's patch to repo at base commit                 |
  |    -> Apply test patch                                           |
  |    -> Run test suite -> fix-patch-run.log                        |
  |    -> parse_log() extracts pass/fail/skip counts                 |
  |    -> Compare vs gold standard (run/test/fix results)            |
  |    -> output.report.json (resolved / unresolved)                 |
  +------------------------------------------------------------------+
       |
       v
  +------------------------------------------------------------------+
  |  PHASE 3: SUMMARY                                                |
  |  pass_at_8_summary.json per instance                             |
  |  (resolved if ANY of k runs produced correct fix)                |
  +------------------------------------------------------------------+
```

---

## 1\. Repository Layout

The benchmarks repository lives at `/home/ec2-user/traj/benchmarks/` and contains:

```
benchmarks/
├── run_custom_eval.sh              # Main orchestrator (bash)
├── benchmarks/                     # Python package
│   └── multiswebench/
│       ├── run_infer.py            # Inference entry point
│       └── scripts/eval/
│           └── convert.py          # Converts output.jsonl -> eval format
├── .llm_config/
│   └── claude.json                 # LLM configuration
├── datastes/                       # Dataset JSONL files (folder name is intentional)
│   └── *.jsonl
├── eval_outputs/                   # All output goes here
│   ├── .shared_repos/              # Pre-cloned git repos (shared across runs)
│   └── <instance_id>/<model>/      # Per-instance, per-model outputs
├── vendor/
│   └── software-agent-sdk/         # OpenHands agent server (git submodule)
├── patches/                        # Runtime patches for multi-swe-bench
└── .venv/
    └── lib/python3.12/site-packages/
        └── multi_swe_bench/        # Evaluation harness (installed package)
            └── harness/
                ├── run_evaluation.py
                ├── report.py
                ├── gen_report.py
                ├── test_result.py
                └── repos/          # Language-specific test log parsers
```

---

## 2\. The Dataset

Each benchmark instance is a real GitHub pull request stored as one line in a JSONL file. One JSONL file typically covers all instances for a single repository.

**Location:** `datastes/<org>__<repo>_<variant>.jsonl`

**Key fields per instance:**

| Field | Description |
| :---- | :---- |
| `org` | GitHub organization (e.g., `fastify`) |
| `repo` | Repository name (e.g., `fastify`) |
| `number` | PR number |
| `instance_id` | Unique ID: `{org}__{repo}-{number}` |
| `base.sha` | Base commit SHA the agent works against |
| `body` | PR description (the "task" given to the agent) |
| `fix_patch` | Gold-standard fix diff |
| `test_patch` | Test changes that validate the fix |
| `lang` | Programming language |
| `run_result` | Pre-baked baseline test results (counts \+ test names) |
| `test_patch_result` | Pre-baked test-patch results |
| `fix_patch_result` | Pre-baked fix-patch results |
| `f2p_tests` | Tests expected to go from fail to pass |

The `run_result` and `test_patch_result` are used as reference baselines during evaluation. The `fix_patch_result` in the dataset is NOT used during live evaluation \-- it is parsed fresh from actual test output.

---

## 3\. Phase 0: Docker Image Setup

Before any inference or evaluation can happen, the script ensures two Docker images exist:

### 3.1 Base Repository Image

This image contains the repository checked out at the base commit, with all dependencies installed and the build environment configured.

**Naming convention:**

```
mswebench/{org_lowercase}_m_{repo_lowercase}:{tag}
```

Example: `mswebench/fastify_m_fastify:pr-1455`

**Resolution order:**

1. Check if image exists locally (skip everything if yes)  
2. Pull from Amazon ECR: `{ecr_prefix}/{org}_m_{repo}:{tag}`  
3. Build from a local Dockerfile (if `--dockerfile` provided)  
4. Pull from Docker Hub

### 3.2 Agent-Server Image

The agent-server image layers the OpenHands agent runtime on top of the base image. This is what actually runs during inference \-- it contains both the repository testbed and the AI agent's execution environment.

**Naming convention:**

```
ghcr.io/openhands/eval-agent-server:{sdk_sha}-{org}_m_{repo}-{tag}-source-minimal
```

**Build process:**

- Source Dockerfile: `vendor/software-agent-sdk/openhands-agent-server/.../Dockerfile`  
- Multi-stage build with `source-minimal` target  
- Patches file permissions so the `openhands` user (UID 10001\) can read testbed files  
- Retries up to 3 times on build failure

After the agent-server image is built, the script sets `MULTI_SWE_BENCH_SKIP_BUILD=1` to tell the Python harness to skip its own redundant image build.

**Multi-instance datasets:** For datasets with multiple instances (different PRs), Phase 0 builds the base image once from the first instance in the dataset. It then pre-builds agent-server images for all remaining instances in parallel (with controlled concurrency), since each PR requires a different Docker image tag. This happens before any inference starts.

### 3.3 Shared Repository Pre-Clone

The script extracts all unique `org/repo` pairs from the dataset and clones each to:

```
eval_outputs/.shared_repos/{org}/{repo}/
```

These clones are shared across all runs and instances to avoid redundant git operations. Before evaluation, each repo is cleaned (`git reset --hard`, `git clean -fd`, `git fetch --all`).

---

## 4\. Phase 1: Inference

Inference is where the AI agent attempts to fix the bug described in each PR.

### 4.1 Execution Model

For pass@k evaluation (typically k=8), the script runs k independent inference attempts per instance. Each run uses `temperature=1.0` to produce diverse solutions.

**Per-run command (called internally by `run_one_infer()`):**

```
uv run python -m benchmarks.multiswebench.run_infer \
  {llm_config} \
  --dataset {instance_jsonl} \
  --split train \
  --lang {language} \
  --workspace docker \
  --max-iterations 1000 \
  --num-workers 1 \
  --max-retries 3 \
  --max-attempts 1 \
  --output-dir {run_dir}
```

### 4.2 Dispatch Modes

The script has three execution modes depending on `--skip-infer` / `--skip-eval` flags. All three use a two-phase approach for multi-instance datasets.

#### Mode 1: Infer \+ Eval (default)

```
Phase 1 (Inference):
  For each instance (NUM_WORKERS instances in parallel):
    1. Run run_1 first (serial) -- this builds the agent-server image
    2. Launch runs 2..K in parallel (SKIP_BUILD=1, reuse image)
    3. Wait for all K runs to complete

Phase 2 (Evaluation):
  For all instances x all runs (EVAL_WORKERS in parallel):
    1. Convert output, generate config, run eval harness
    2. Copy final_report.json -> output.report.json
```

`--num-workers` controls how many instances run concurrently in Phase 1\. Within each instance, runs 2-K are launched as parallel background processes. Phase 2 uses up to `min(NUM_WORKERS * (K-1), 64)` parallel workers.

#### Mode 2: Eval Only (`--skip-infer`)

```
Phase A (Image Build):
  A-1: Run eval for first instance/run_1 (serial) -- builds base image
  A-2: Run eval for all other instances/run_1 (PHASE_A_WORKERS parallel)

Phase B (Remaining Evals):
  Run eval for all instances, runs 2..K (PHASE_B_WORKERS parallel)
```

Phase A is separated because the first eval builds the shared base Docker image. Once built, all subsequent evals reuse it.

#### Mode 3: Infer Only (`--skip-eval`)

Similar to Mode 1 Phase 1, but skips evaluation entirely. Each instance's run\_1 is executed first (builds the image), then runs 2-K launch in parallel.

### 4.3 What Happens During Inference

1. A Docker container is launched from the agent-server image  
2. The AI agent (e.g., Claude) receives the PR title, body, and issue context as its task  
3. The agent interacts with the codebase inside the container:  
   - Reads source files  
   - Edits code  
   - Runs shell commands (build, test, etc.)  
4. The conversation continues until the agent submits a patch or hits the iteration/timeout limit  
5. The agent's patch and full conversation history are written to `output.jsonl`

### 4.4 Resume Logic

If `output.jsonl` already exists and contains valid JSON, the run is skipped (`run_one_infer()` returns immediately). This enables safe restarts \-- you can re-run the same command and it will only process incomplete runs.

Invalid or truncated `output.jsonl` files are detected and deleted, forcing a re-run.

### 4.5 Stale Critic Cleanup

The inference framework uses "critic" files (`output.critic_attempt_N.jsonl`) to track retries. If all entries in a critic file contain errors (e.g., container health timeout, buildx crash), the file is deleted to allow a clean retry. Without this cleanup, the framework skips the instance because it sees the critic file and believes it was already processed.

### 4.6 Output Flattening

The inference framework produces output in a nested directory structure (e.g., `run_1/eval_outputs__.../{instance_id}/output.jsonl`). The `_flatten_official_output_dir()` function moves all files to the run-level directory for consistent access.

---

## 5\. Phase 2: Evaluation

Evaluation determines whether the agent's patch actually fixes the bug by running the project's test suite.

### 5.1 Patch Conversion

First, `convert.py` extracts the `git_patch` from `output.jsonl` and writes it to `output_converted.jsonl` in the format expected by the eval harness:

```json
{
  "instance_id": "fastify__fastify-1455",
  "org": "fastify",
  "repo": "fastify",
  "number": 1455,
  "fix_patch": "<the agent's git diff>"
}
```

### 5.2 Eval Harness Execution

A `config.json` is generated pointing to the converted patches, dataset, shared repos, and working directories. Then:

```
uv run python -m multi_swe_bench.harness.run_evaluation \
  --config {run_dir}/config.json \
  --mode evaluation
```

### 5.3 What the Eval Harness Does

1. Checks out the repo at the base commit (using the shared clone)  
2. Applies the agent's patch  
3. Applies the test patch (adds/modifies tests that validate the fix)  
4. Runs a language-specific **fix-patch-run command** inside the Docker container, producing `fix-patch-run.log`  
5. Parses the test output using a language-specific `parse_log()` method  
6. Generates `report.json` with detailed test-by-test comparison

The fix-patch-run command is built by `build_fix_cmd()` in the shell script and varies by language. For non-Java languages, it:

- Runs `prepare.sh` (sets up build environment)  
- Applies patches with `patch` instead of `git apply` (more lenient with `--fuzz=5`)  
- Installs test utilities (`pytest-cov`, `pytest-xdist`, etc.)  
- Modifies `fix-run.sh` to remove coverage flags and distribution arguments  
- Executes `fix-run.sh` which runs the project's test suite

### 5.4 Test Result Comparison

The evaluation compares three sets of test results:

| Result Set | Source | Description |
| :---- | :---- | :---- |
| `run_result` | Pre-baked in JSONL dataset | Baseline: tests on unmodified repo |
| `test_patch_result` | Pre-baked in JSONL dataset | Tests after applying test patch only |
| `fix_patch_result` | Parsed LIVE from `fix-patch-run.log` | Tests after applying agent's patch \+ test patch |

**Resolution criteria (from `report.check()`):**

1. Reject if `fix_patch_result.all_count == 0` (tests didn't run at all)  
2. Compare individual test names across run/test/fix stages  
3. All tests that should go from fail-to-pass (`f2p_tests`) must pass  
4. No previously-passing tests should break

### 5.5 Language-Specific Log Parsing

The `parse_log()` method varies by language and test framework:

- **JavaScript (mocha/spec):** Parses `✓ test name` for passing, numbered failures at bottom  
- **JavaScript (node:test):** Parses `✔ test name` for passing, `✖ test name` for failing, `ℹ` summary lines  
- **Java (Maven/Surefire):** Parses Maven test output  
- **Python (pytest):** Parses pytest output  
- **Go (go test):** Parses `--- PASS` / `--- FAIL` lines

The parser returns a `TestResult` dataclass containing `passed_tests`, `failed_tests`, `skipped_tests`, and their counts. A `__post_init__` validator enforces that `len(passed_tests) == passed_count` and that pass/fail/skip sets don't overlap.

---

## 6\. Phase 3: Summary Generation

After all k runs complete for an instance, a `pass_at_{k}_summary.json` is generated:

```json
{
  "metric": "pass@8",
  "k": 8,
  "language": "javascript",
  "model": "claude",
  "dataset": "fastify__fastify-1455",
  "total_instances": 1,
  "instances_with_any_pass": 0,
  "pass_at_k": 0.0,
  "timing_metrics": {
    "total": {
      "api_time_seconds": 3747.55,
      "api_calls": 605,
      "accumulated_cost_usd": 18.09,
      "prompt_tokens": 43753487,
      "completion_tokens": 182857
    }
  },
  "per_run": [
    {"run": 1, "status": "ok", "resolved": 0, "total": 1, ...},
    ...
  ],
  "per_instance": {
    "fastify/fastify:pr-1455": {
      "run_1": "Fail", "run_2": "Fail", ...
    }
  }
}
```

An instance is considered **resolved** if at least one of the k runs produces a correct fix. The pass@k metric is the fraction of instances resolved out of total instances.

Summaries can be regenerated from existing reports without re-running inference or evaluation using the `regen_pass8.py` script.

---

## 7\. Output Directory Structure

```
eval_outputs/
├── .shared_repos/                          # Shared git clones
│   └── {org}/{repo}/                       # e.g., fastify/fastify/
│
├── {instance_id}/                          # e.g., fastify__fastify-1455/
│   └── {model}/                            # e.g., claude/
│       ├── runner.log                      # Master log across all runs
│       ├── pass_at_8_summary.json          # Aggregate pass@k results
│       │
│       ├── run_1/                          # One directory per independent run
│       │   ├── infer.log                   # Inference log
│       │   ├── output.jsonl                # Agent output (patch + conversation)
│       │   ├── output_converted.jsonl      # Patch in eval format
│       │   ├── metadata.json               # LLM config, runtime settings
│       │   ├── config.json                 # Eval harness configuration
│       │   ├── eval.log                    # Evaluation log
│       │   ├── output.report.json          # Final verdict (resolved/unresolved)
│       │   ├── conversations/              # Full conversation transcripts
│       │   ├── logs/                       # Detailed agent logs
│       │   └── eval_files/
│       │       ├── dataset/
│       │       │   └── final_report.json   # Detailed eval report
│       │       ├── workdir/{org}/{repo}/
│       │       │   └── evals/pr-{N}/
│       │       │       ├── report.json     # Test-by-test comparison
│       │       │       └── fix-patch-run.log  # Raw test output
│       │       ├── repos/
│       │       └── logs/
│       │
│       ├── run_2/ ... run_8/               # Same structure as run_1
```

---

## 8\. Command Reference

### Full pipeline (inference \+ evaluation, pass@8)

```shell
cd /home/ec2-user/traj/benchmarks

bash run_custom_eval.sh \
  --llm-config .llm_config/claude.json \
  --dataset datastes/fastify__fastify_fixed.jsonl \
  --ecr-prefix 426628337772.dkr.ecr.ap-south-1.amazonaws.com/rfp-coding-q1-tag \
  --lang javascript \
  -k 8 \
  --num-workers 16
```

### Inference only (skip evaluation)

```shell
bash run_custom_eval.sh \
  --llm-config .llm_config/claude.json \
  --dataset datastes/fastify__fastify_retry7.jsonl \
  --ecr-prefix 426628337772.dkr.ecr.ap-south-1.amazonaws.com/rfp-coding-q1-tag \
  --lang javascript \
  -k 8 --num-workers 7 \
  --skip-eval
```

### Evaluation only (reuse existing inference output)

```shell
bash run_custom_eval.sh \
  --llm-config .llm_config/claude.json \
  --dataset datastes/fastify__fastify_fixed.jsonl \
  --ecr-prefix 426628337772.dkr.ecr.ap-south-1.amazonaws.com/rfp-coding-q1-tag \
  --lang javascript \
  -k 8 --num-workers 16 \
  --skip-infer
```

### Extended timeout for long-running instances

```shell
cd /home/ec2-user/traj/benchmarks

env CONVERSATION_TIMEOUT=43200 bash run_custom_eval.sh \
  --llm-config .llm_config/claude.json \
  --dataset datastes/fastify__fastify_retry7.jsonl \
  --ecr-prefix 426628337772.dkr.ecr.ap-south-1.amazonaws.com/rfp-coding-q1-tag \
  --lang javascript \
  -k 8 --num-workers 7 \
  --skip-eval
```

### Running as a background job

```shell
cd /home/ec2-user/traj/benchmarks

nohup env CONVERSATION_TIMEOUT=43200 bash run_custom_eval.sh \
  --llm-config .llm_config/claude.json \
  --dataset datastes/fastify__fastify_retry7.jsonl \
  --ecr-prefix 426628337772.dkr.ecr.ap-south-1.amazonaws.com/rfp-coding-q1-tag \
  --lang javascript \
  -k 8 --num-workers 7 --skip-eval \
  > /home/ec2-user/fastify_retry.log 2>&1 &
```

---

## 9\. Key Configuration

### LLM Config (`.llm_config/claude.json`)

```json
{
  "model": "bedrock/converse/<inference-profile-arn>",
  "api_key": "<base64-encoded-key>",
  "model_canonical_name": "anthropic.claude-sonnet-4-6",
  "aws_region_name": "us-east-1",
  "temperature": 1.0,
  "top_p": null
}
```

- `temperature: 1.0` ensures diverse outputs across the 8 independent runs  
- The model name is extracted and shortened to `claude` for directory naming  
- The canonical name is used for model identification in reports

### Script Flags

| Flag | Default | Description |
| :---- | :---- | :---- |
| `--llm-config` | required | Path to LLM JSON config |
| `--dataset` | required | Path to task instances JSONL |
| `--ecr-prefix` | none | ECR registry prefix for images |
| `--lang` | `rust` | Language: rust, cpp, java, python, go, javascript |
| `-k` | `1` | Number of independent runs (pass@k) |
| `--num-workers` | `1` | Parallel instances (each spawns k-1 parallel runs) |
| `--max-iter` | `1000` | Max agent iterations per instance |
| `--max-retries` | `3` | Retries for crashed instances |
| `--skip-infer` | false | Skip inference, run eval only |
| `--skip-eval` | false | Skip eval, run inference only |
| `--start-run` | `1` | Resume from a specific run number |

### Environment Variables

| Variable | Default | Description |
| :---- | :---- | :---- |
| `CONVERSATION_TIMEOUT` | `3600` (1h) | Max seconds for agent conversation |
| `SKIP_ORPHAN_CLEANUP` | `0` | Set to `1` to prevent killing existing containers on startup |
| `MULTI_SWE_BENCH_SKIP_BUILD` | set by script | Tells harness to skip agent-server build |

---

## 10\. Container Lifecycle and Concurrency

### Startup Cleanup

On startup, `_cleanup_orphaned_containers()` removes ALL Docker containers matching `name=agent-server-*`. This prevents stale containers from consuming resources.

**Critical implication:** Launching a new `run_custom_eval.sh` while inference containers from a previous run are still active will kill those containers. The inference processes will then fail with `Connection refused` errors as they try to communicate with the now-dead containers.

**Mitigation:** Set `SKIP_ORPHAN_CLEANUP=1` when running concurrently:

```shell
env SKIP_ORPHAN_CLEANUP=1 bash run_custom_eval.sh ...
```

### Exit Cleanup

On exit, the script:

1. Stops all containers it tracked during execution  
2. Checks if other `run_custom_eval.sh` sessions are running  
3. If no other sessions exist, removes ALL remaining `agent-server-*` containers  
4. If other sessions exist, skips the global cleanup

---

## 11\. Post-Processing for Push

Before pushing trajectories to the trajectory repository, several cleanup steps are needed:

1. **Remove nested `.git` directories** in `.shared_repos/` and any eval workdirs  
2. **Normalize model names** in `output.jsonl` to a canonical form (e.g., `bedrock/us.anthropic.claude-sonnet-4-6`)  
3. **Convert absolute paths** to relative paths in output files  
4. **Regenerate pass@k summaries** to reflect any corrections  
5. **Verify completeness**: every instance should have k runs with `output.jsonl`, `output.report.json`, and a `pass_at_k_summary.json`

The trajectories are then copied to the trajectory repository:

```shell
rsync -av --include='fastify__fastify-*/' --include='fastify__fastify-*/**' \
  --exclude='*' \
  /home/ec2-user/traj/benchmarks/eval_outputs/ \
  /home/ec2-user/jaeger-ii/trajectories/LHT/
```

---

## 12\. Troubleshooting

| Symptom | Likely Cause | Fix |
| :---- | :---- | :---- |
| All `fix_patch_result` are `(0,0,0)` | `parse_log()` doesn't match test output format | Check `fix-patch-run.log` format, update the language-specific parser |
| Inference exits with `Connection refused` | Container was killed by another eval session's startup cleanup | Use `SKIP_ORPHAN_CLEANUP=1` or don't run eval and infer concurrently |
| Inference times out at 1 hour | Default `CONVERSATION_TIMEOUT=3600` | Set `CONVERSATION_TIMEOUT=43200` for up to 12 hours |
| `output.jsonl` missing after inference | Container crash, OOM, or network failure | Check `infer.log`; script auto-retries up to `--max-retries` times |
| `ModuleNotFoundError: No module named 'benchmarks'` | Script not run from the correct directory | Must `cd /home/ec2-user/traj/benchmarks` before running |
| Docker build fails with buildx error | BuildKit driver can't see local images | Script retries 3 times with `docker buildx prune` between attempts |
| `report.json` shows resolved but `output.report.json` shows unresolved | Stale report from previous run | Delete old reports and re-run eval with `--skip-infer` |

# Data Collection Phase

![][image1]  


[image1]: <data:image/png;base64,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>

---

# As-Built System Reference (verified against the codebase, 2026-08-17)

*This section documents the checkout at `b0e2dacc` and supersedes the historical LHT design and older `run_custom_eval.sh` EC2 instructions above. It is the initial context for the current Milo-format delivery pipeline. Claims below were checked against source, tests, workflows, and the pinned SDK gitlink; known failing contracts are called out rather than described as working.*

---

## A. What this repository is

`aurora-harness` (Python package name: `openhands-benchmarks`, v0.1.0, Python >= 3.12) is the Aurora project's benchmark evaluation infrastructure. Its production job today:

> **dataset JSONL → agent trajectory (Docker, OpenHands SDK agent) → outcome evaluation (Multi-SWE-bench harness) → Harbor package → rubric-scored Milo bundle → staged in `EtharaOrion/milo-bench-samples`.** `run_eval.sh` stops at staging and requires a manual commit/push; the legacy `run_custom_eval.sh` still creates local commits and may push conditionally.

Two scoring channels ship per run:

- **Channel A / outcome** — `score_v2g` and the resolved/unresolved verdict from applying the agent's patch and running the gold tests. Authoritative, never recomputed by later stages.
- **Channel B / process** — an LLM-judged rubric plus 28 deterministic checks, produced by the vendored `assay/` scorer, composed into `score_eval` / `score_rl`. Added because the outcome signal is sparse (the 5-instance tortoise-orm corpus scored 0.0 on every run).

Proven end-to-end: the dapr Go batch (41 instances) and the tortoise-orm pilot (instances 538 and 943, pinned as regression fixtures).

## B. Repository map

```
run_eval.sh                  # CURRENT driver (~1600 lines): multi-dataset, parallel, milo delivery
run_custom_eval.sh           # legacy but executable single-dataset runner (MAX_ITER 300);
                             #   stages old dataset/<uuid> + trajectory/<uuid> layout,
                             #   creates local commits, and may push unless --no-push
benchmarks/
  multiswebench/             # the actively used suite
    run_infer.py             # inference entry (MultiSWEBenchEvaluation; prompts/default.j2)
    eval_infer.py            # standalone eval CLI (run_eval.sh does NOT call it — it inlines
                             #   config generation and calls multi_swe_bench directly)
    scripts/data/split_dataset.py      # 1 record → 1 file; --backfill-interval fills
                                       #   number_interval from the MSB registry
    scripts/eval/convert.py            # output.jsonl → eval patch format (fails w/o uuid)
    scripts/eval/env_dep_inject.py     # per-language run/test/fix commands
    scripts/eval/update_multi_swe_bench_config.py  # escalating patch-apply command
    scripts/eval/score_v2g.py          # v2g continuous score — single source of truth
    scripts/harbor/converter.py        # harbor/milo task+trajectory builder (~1755 lines;
                                       #   ATIF-v1.7, recording.cast, task_checksum)
    scripts/harbor/backfill_cost.py    # repair total_cost_usd where SDK cost was 0.0
    scripts/rubric/                    # rubric layer (see section E)
  swebench/ swtbench/ commit0/ gaia/ openagentsafety/ swebenchmultimodal/
                             # inherited rollout suites; not driven by run_eval.sh
  swegym/ swesmith/          # image-build infrastructure only; no rollout implementation
  utils/                     # shared Evaluation base, critics, modal_patches, version.py
assay/                       # VENDORED milo corpus scorer (~8.5k LOC) — see section F
milo_bundles/                # bundle output; sibling verdicts/ + .anchoring/ never published
proxy/                       # OAuth bridges: claude_code_bridge (8765), codex_bridge (8766)
vendor/software-agent-sdk/   # git submodule: Ethara-AI fork of the OpenHands agent SDK
patches/registry/c/libuv/libuv.py  # out-of-tree MSB instance def; copied into
                                   #   site-packages MANUALLY (no automation)
dataset/                     # team dataset files (tortoise, dapr 41-PR combined, smoke)
eval_outputs/                # per-instance working dirs; regenerable, safe to delete
tests/                       # root contracts; CI also runs benchmarks/multiswebench/tests/
legacy/                      # cold archive of old OpenHands benchmarks; excluded from tooling
sitecustomize.py             # auto-imported; applies Modal/swebench host patches
.llm_config/                 # claude-code.json, codex.json, rubric-judge.json, example.json
RUBRIC.md                    # canonical rubric-layer doc  ·  AGENTS.md  # agent conventions
```

Console entry points (`pyproject.toml [project.scripts]`), active-suite subset: `multiswebench-infer`, `multiswebench-eval`, `multiswebench-harbor-convert`, `multiswebench-rubric`, and `validate-cfg`. `validate-dataset` is registered but currently broken because `benchmarks.scripts.validate_dataset` does not exist.

## C. The current pipeline: `run_eval.sh`

### C.1 Canonical invocation

```bash
EGRESS_FILTER_DISABLE=1 RUBRIC_ENABLE=1 bash run_eval.sh \
  --llm-config .llm_config/claude-code.json \
  --dataset dataset/<file>.jsonl \
  --ecr-prefix <acct>.dkr.ecr.<region>.amazonaws.com/<repo-prefix> \
  --lang go --data-dir ../milo-bench-dataset
```

Key flags: `--parallel N` (datasets concurrently; 2–3 max on a laptop — each instance can spawn ~5 containers and parallelism burns the subscription cap N× faster), `-k N` (pass@k, default 1), `--max-iter` (default **1000** — load-bearing, see C.4), `--skip-infer/--skip-eval/--skip-summary`, `--force`, `--start-run`. `RUBRIC_ENABLE` defaults **off**; set it to `1` for the Milo rubric/assay tail.

### C.2 Startup (once per invocation)

1. `uv lock --upgrade-package multi-swe-bench && uv sync` (falls back to `uv sync --frozen`; hard-fails if both break). **This can rewrite `uv.lock` and is not a hermetic startup step**; run from a clean checkout and review any lockfile diff.
2. Every `--dataset` runs through `split_dataset.py --out-base eval_outputs/_split --backfill-interval`: multi-record files expand to one file per instance; empty `number_interval` is backfilled from the multi-swe-bench registry (warn-only on failure). Downstream is keyed on the first record of each file, so the split is mandatory correctness, not convenience.
3. Collision guard: duplicate basenames and duplicate `<org>_<repo>-pr-<number>` identities rejected; every record must carry a non-empty `uuid`.
4. `MODEL_NAME/MODEL_SHORT/MODEL_SLUG` derived from the LLM config's `model`; `SDK_SHORT_SHA` from `benchmarks.utils.version` (fallback: `git rev-parse` in the submodule; hard-fail if neither works, to avoid mis-tagged agent-server images).
5. Data-dir validation: the resolved staging directory (`--data-dir`, default `<script dir>/../milo-bench-dataset/`) must already exist as a writable directory; the script fails with actionable manual-preparation instructions (`mkdir -p` / `chmod u+w`) before any uv/ECR/Docker/eval work if the path is missing, not a directory, or not writable. No git clone, mkdir, or remote checks are performed on this directory; any non-Git directory is accepted.
6. Optional: ECR `docker login`; optional headroom compression proxy (`base_url` rewritten to `http://host.docker.internal:8787` in a temp LLM config, with a watchdog).

Dispatch is a rolling-window scheduler (pure PID polling, bash-3.2-safe) keeping `--parallel` `process_dataset` subshells busy; per-dataset logs at `eval_outputs/_parallel_logs/<name>.log`.

### C.3 Per-dataset phases (`process_dataset`)

| Phase | What happens |
|---|---|
| 0 · base image | Pull `<ecr>/<org>_m_<repo>:pr-<n>` (or `docker build --dockerfile`), retag to `mswebench/<org>_m_<repo>:pr-<n>` |
| 0 · agent-server | Buildx-build `ghcr.io/openhands/eval-agent-server:<SDK_SHORT_SHA>-<org>_m_<repo>-pr-<n>-source-minimal` matching the base image's architecture; then export `MULTI_SWE_BENCH_SKIP_BUILD=1`, `DOCKER_PLATFORM`, `EVAL_DOCKER_IMAGE_PREFIX=mswebench`, `LANGUAGE` |
| resume | A run counts as done iff `run_<i>/output.report.json` exists; if all of `START_RUN..K` are done and `--force` absent, images+inference are skipped |
| 1 · inference | `uv run python -m benchmarks.multiswebench.run_infer <llm_config> --dataset <staged> ... --max-iterations $MAX_ITER --max-attempts 1 --output-dir run_<i>`; non-zero exit is a WARN, not fatal |
| sidecars | `metadata.json` (LLM config minus `api_key`, plus `max_iterations`, lang, workspace) and `phase_times.json` (8 ISO timestamps) — both consumed by the harbor converter |
| 2 · evaluation | Generate `run_<i>/config.json`, then `uv run python -m multi_swe_bench.harness.run_evaluation --config ... --mode evaluation`; `eval_files/dataset/final_report.json` → `output.report.json` |
| 3 · summary | For K>1, pass@k (instance passes if resolved in any run) → `pass_at_<K>_summary.json` |
| 4 · harbor | `multiswebench-harbor-convert <OUTPUT_BASE> --out <tag>_harbor --dataset-dir <tag>_harbor/_dataset --instance <TAG> --task-uuid <UUID>` |
| 5 · rubric | Only if `RUBRIC_ENABLE=1` — see section E; failure is a WARN, logged to `<model_slug>/rubric.log` |
| 6 · staging | `stage_dataset()` copies `milo_bundles/<uuid>/.` FLAT to `<data-dir>/<uuid>/`; strips nested `.git`; drops files ≥ 100 MiB; excludes the sibling `verdicts/` store. Legacy `dataset/`+`trajectory/` split is staged only when no bundle exists (e.g. `RUBRIC_ENABLE=0`) |

**Publish gate (phases 4–6).** Harbor conversion, the rubric chain, and staging share a single gate (`PUBLISH_TAIL`): they run only when the invocation was not `--skip-eval` / `--docker-build-only` **and** at least one `run_<i>/output.report.json` exists under the model dir. Partial coverage is a WARN, not a skip (uncovered runs carry `no_signal` in `result.json`; assay's B1 gate voids them downstream). An infer-only (`--skip-eval`) pass therefore never creates or refreshes `<tag>_harbor/`, never enters the rubric chain, and never (re-)stages bundles; an eval that produced zero reports skips the tail with an explicit `harbor: skip` log line. Resume invocations with reports already on disk pass the gate and re-export as before. Pinned by `tests/test_harbor_gating.py`.

**`run_eval.sh` performs no Git operations on the staging directory** — no clone, fetch, pull, add, commit, or push. All publishing-related code (including GitHub API/token verification, `.env` reading for tokens, push locks, and associated status variables) has been removed. Publish manually from `--data-dir` when ready. The only Git usage is the SDK read-only `git rev-parse` for determining `SDK_SHORT_SHA`. This statement does **not** apply to `run_custom_eval.sh`, whose local commit and conditional push paths remain active.

### C.4 Non-negotiable run constraints

- **`--max-iter 1000` for delivery runs** (the default). assay's hard gate `B4-not-at-turn-ceiling` compares `n_episodes` (raw event count, ≈2× agent steps — the corpus's own unit) against `max_turns`; every corpus run used 1000. Runs recorded at a 100-iteration ceiling read as cut off and are **voided by the corpus scorer itself**. The pilot bundles (recorded at 100) are pinned proof.
- **`EGRESS_FILTER_DISABLE=1` on macOS** — the container egress path hard-fails under Docker Desktop. More broadly, the checked-in SDK filter does not satisfy the repository's intended full-block contract; do not assume enabled filtering is effective (see K.6).
- The OAuth bridge (8765) must be up before the run and before any rubric authoring/judging.
- If `rate_limit_error` lines appear in `eval_outputs/_parallel_logs/*.log`, the Claude subscription cap is hit — stop (Ctrl-C) and resume after the window resets. Capped instances produce empty trajectories, not partial ones; the resume logic (C.3) makes re-runs safe.
- **Two-phase workflow is first-class**: an infer-only pass (`--skip-eval`) generates trajectories and nothing else — the publish gate (C.3) guarantees no `_harbor`, no rubric calls, no staging. A later `--skip-infer` pass then runs eval → harbor → rubric → staging off the trajectories on disk.

### C.5 Output layout

```
eval_outputs/_split/<stem>/<org>__<repo>-<n>.jsonl      split inputs
eval_outputs/_parallel_logs/<name>.log                  per-dataset driver log
eval_outputs/<org>_<repo>-pr-<n>/<model_slug>/run_<i>/  output.jsonl, output.report.json,
                                                        config.json, metadata.json,
                                                        phase_times.json, eval_files/,
                                                        infer.log, eval.log
eval_outputs/<org>_<repo>-pr-<n>/<tag>_harbor/          task/, trajectory/, _dataset/
milo_bundles/<uuid>/                                    the deliverable bundle
milo_bundles/verdicts/<uuid>/<alias>__run_N.jsonl       judge store (NEVER published)
milo_bundles/.anchoring/<uuid>.json                     anchoring reports
<data-dir>/<uuid>/                                      staged flat for manual publish
```

`eval_outputs/` is regenerable and safe to delete between runs. `run_eval.sh` does **not** globally wipe `milo_bundles/`; bundles and sibling verdict/anchoring state can persist across invocations, so remove them explicitly only when a clean regeneration is intended. The staging directory accumulates across runs; publish manually.

## D. Models and configuration

| Role | Config | Value (committed) |
|---|---|---|
| Trajectory agent | `.llm_config/claude-code.json` → `model` | `anthropic/claude-opus-4-8`, `base_url http://host.docker.internal:8765`, `caching_prompt true`, `force_adaptive_thinking true`, `temperature 1.0`, stub `api_key` (bridge strips it) |
| Rubric author | `.llm_config/rubric-judge.json` → `author_model` | `claude-opus-5` (bare bridge id; fallback `claude-sonnet-5` if absent) |
| Judge + anchoring gate | `.llm_config/rubric-judge.json` → `judge_model` | `anthropic/claude-sonnet-5` (litellm id; legacy key `model` still honored) |
| Codex alternative | `.llm_config/codex.json` → `model` | `openai/gpt-5.6-sol`, `base_url http://host.docker.internal:8766`, `reasoning_effort high` |

Critical details:

- **`base_url` split**: `claude-code.json` uses `host.docker.internal:8765` (bridge as seen from inside a container; plain-Linux hosts use `172.17.0.1:8765`), while `rubric-judge.json` uses `127.0.0.1:8765` (authoring/judging run host-side).
- **Claude 5 models reject the `temperature` parameter.** `rubric-judge.json` deliberately omits it; a test pins that judge requests never send it.
- The judge **council name is derived from `judge_model`** (`anthropic/claude-sonnet-5` → `sonnet-5=claude-sonnet-5`) once per task by `run_eval.sh` and exported as `ASSAY_COUNCIL`, so judge-time and score-time can never disagree. `ASSAY_PROXY` defaults to `http://127.0.0.1:8765/v1/messages` (override: `RUBRIC_PROXY`).
- Codex config caveat (recorded in the file itself): use `openai/<model>`, **not** `openai/responses/<model>` — the SDK already routes `gpt-5*` through its native Responses path; the extra segment leaks into the request body, breaks cost lookup, and nests output dirs. Only `gpt-5.6-sol` is accepted by the ChatGPT-account Codex backend.
- `.env` (repo root, never committed) carries AWS credentials for ECR login. **The AWS variable names are misleading and this is intentional-legacy**: `AWS_SECRET_KEY` holds the ACCESS KEY ID (`AKIA...`); `AWS_ACCESS_SECRET_KEY` holds the SECRET ACCESS KEY. `run_eval.sh` does not read `GITHUB_TOKEN` or `GH_TOKEN` from `.env`; publish operations are fully manual.

## E. The rubric layer (Channel B) — mechanism

Canonical doc: `RUBRIC.md`. Status: implemented and covered by root plus Multi-SWE contract tests; piloted live on tortoise-orm 538/943 and run at scale on the dapr batch.

With `RUBRIC_ENABLE=1`, after harbor conversion each task flows through four steps (all automatic, all idempotent):

1. **`multiswebench-rubric export-bundle`** (`scripts/rubric/export_bundle.py`) — pure reshape of the harbor package into the flat `<uuid>/` bundle: `task/*` flattened, `trajectory/` → `trajectories/`, model dir names mapped to corpus aliases (`claude-opus-4-8` → `opus-4.8`), `verifier/score.md` rewritten to a bare float, retired WCB-schema artifacts stripped. Byte-compare-before-write → idempotent.
2. **`multiswebench-rubric author-milo`** (`scripts/rubric/assay_author.py`, once per task; skipped if `tests/rubrics.json` already has `"mode": "judged"`) — fully automatic, **fail-closed** authoring:
   - `assay author` builds the deterministic skeleton (patch → sites/probes → TRUTH template → G1–G7 guardrails);
   - **narration**: `author_model` writes the TRUTH.md expert prose (Root cause / Solution shape / Ordered plan / Pitfalls), gated by `assay/narrate.py::validate_narration` (rejects placeholders, generic phrases, verbatim patch quotes ≥ 12 chars, oracle leaks; retried with feedback);
   - **item drafting**: `author_model` drafts 5–9 task-specific R-items (weights 5/3/1, positive only; dimensions issue_coverage/verification/adherence/maintainability; targets final_diff/trajectory/verification_output), gated by `assay lint`;
   - **anchoring gate** (kaiju-style, `scripts/rubric/anchor.py`): every R-item is judged against the gold `fix_patch` AND an empty stub. Gold fails a positive item → drop (too strict); stub passes it → drop (asserts nothing); guardrail fires on gold/stub → drop; `evaluation_target: trajectory` → not anchorable, kept. One redraft-with-feedback round, then pruning; the whole task is **rejected (exit 2) if < 3 R-items survive** — never graded with an unsound rubric. Report: `milo_bundles/.anchoring/<uuid>.json`;
   - `assay certify` (verifies gold from recorded test results) → `assay emit-tests` → `assay validate`.
3. **`python -m assay ... judge`** — one judge call per rubric item per run through the bridge, with a prompt-cached evidence packet. The packet (`assay/packet.py`) contains the instruction, the prose half of TRUTH.md, the reconstructed edit set, and a compacted ATIF trajectory — and deliberately **excludes the outcome score and all verifier diagnostics (judge blindness, pinned by a source-level test)**. Strict verdict format `[[RATIONALE:..]] [[SATISFIED: Yes|No]] [[TRUNCATION_AFFECTED: Yes|No]] [[EVIDENCE: step n]]`; verdicts without an evidence citation abstain; every verdict carries a `bundle_fingerprint` so a rubric/TRUTH edit invalidates stale verdicts.
4. **`python -m assay ... score --write`** — deterministic Channel A (28 checks: A1–A5 admissibility, B1–B4 completion gates, C-series scope/anti-cheat, D1–D3 record quality, E-series issue coverage) + composition; writes `process.json` / `final_score.md` and merges `score_outcome ... score_rl` + the `assay{}` block into each run's `result.json`. Composition: `process = (det + rubric)/2`; per-task `alpha` (cap 0.05); `score_eval = gate·((1−2α)·outcome + 2α·process)` (absolute); `score_rl` = same form with process min-max normalized inside the run's outcome stratum. Any hard-gate failure → `gate = 0`; run status is `scored` / `voided` / `unverifiable`.

Env knobs: `RUBRIC_BUNDLE_DEST` (default `<repo>/milo_bundles` — must stay under the repo so each bundle's emitted `test_output.py` can self-locate the vendored assay), `RUBRIC_COUNCIL`, `RUBRIC_PROXY`, `RUBRIC_LLM_CONFIG` (default `.llm_config/rubric-judge.json`).

Cost: authoring ≈ 6–10 bridge calls/task; judging ≈ 1 call per item per run (pilot: 11–13/run) — effectively covered by the subscription.

**Legacy WCB layer**: `scripts/rubric/{attach,runner,author,...}.py` implement the older WildClawBench-schema flow (`attach`/`judge` into `task/rubric/`). Retired from delivery — `export-bundle` strips its artifacts — but kept as internal libraries; the anchoring gate reuses `anchor.py`, `evidence.py`, `scoring.py`, `verdict_parser.py`, `judge_client.py` (`judge_client.py` is the only rubric module that talks to the bridge; it never raises, retries 429/5xx/timeout, never retries 400/401/403).

## F. `assay/` — the vendored scorer and why we trust it

`assay/` is a vendored copy of the scorer that generated the `milo-bench-samples` reference corpus (installed as a package alongside `benchmarks`). The corpus was produced by a newer assay than the copy originally on hand, so schema-drift patches were applied (item key `evaluation_rule`, `tests/test_output.py` filename, per-task G7 after the shared G1–G6 preamble, decoupled fingerprint prose recipe, `test-stdout.md`, opt-in pruning, bridge request shaping).

**The compatibility proof** is `tests/test_assay_replay.py`: it replays 4 corpus bundles × 9 runs spanning scored, voided-C1, voided-C3, and unverifiable-B1 cases using recorded verdicts. The current contract is **not whole-corpus byte identity**: single-judge composition and the deterministic weight-ladder change intentionally alter deterministic/composed fields, so tests pin unaffected channels and recompute changed fields. Each schema-drift patch remains pinned in `tests/test_assay_vendor_patches.py`. `SCORE_MATH.md` is stale where it lists deterministic weights `8` and `2`; code/tests enforce the `{1,3,5}` ladder.

Channel-separation rule (enforced by `assay lint`): an assertion belongs to pytest iff its truth is decidable from bytes on disk by a total function with no natural-language understanding; everything else, and only that, belongs to the rubric. A rubric criterion built purely from mechanical predicates is a lint error.

## G. The milo bundle format (the deliverable)

```
<task-uuid>/
├── TRUTH.md                     # Defect, Load-bearing work, Verification, Root cause,
│                                #   Solution shape, Ordered plan, Pitfalls, Provenance
├── instruction.md · task.toml · environment/Dockerfile
├── solution/{fix.patch, solve.sh}
├── tests/
│   ├── config.json · test.patch · test.sh · run_tests.py
│   ├── rubrics.json             # R1..Rn judged items (weights 5/3/1) + G1–G7 guardrails
│   │                            #   (negative weights) + 28 check descriptors + sites[]
│   └── test_output.py           # emitted pytest: re-runs Channel A standalone
└── trajectories/<model-alias>/run_N/
    ├── config.json · result.json          # scores + assay{} block written back
    ├── agent/{trajectory.json (ATIF-v1.7), recording.cast, *.pane}
    ├── artifacts/manifest.json
    └── verifier/{score.md, test-stdout.md, verdicts.jsonl, process.json, final_score.md}
```

Structural equality with the reference corpus is enforced by `tests/test_bundle_structure.py`: identical file set, identical JSON key sets AND key order (rubrics.json, process.json, result.json writeback), identical enums, verdict-line key order, `final_score.md` template, bare-float `score.md`. Each bundle's `tests/test_output.py` runs standalone: `pytest <bundle>/tests/test_output.py --import-mode=importlib`.

## H. The OAuth bridges (`proxy/`)

Both bridges front subscription accounts so runs bill to subscriptions instead of metered API keys. Both are FastAPI apps run from the repo venv, managed by near-identical shell wrappers (`start|stop|status|check|monitor|__run`) with a health-poll watchdog that restarts after 3 consecutive `/healthz` failures. PIDs live in `proxy/`; logs in `proxy/logs/` are gitignored. The wrappers bind `0.0.0.0` by default for container reachability and neither bridge authenticates inbound clients: any reachable process/peer can consume the subscription, so restrict host/firewall exposure. `--workspace docker` only — host-local bridges are unreachable from `--workspace remote`.

### H.1 Claude Code bridge — port 8765 (`proxy/claude_code_bridge/`)

- **Transparent Anthropic-native passthrough** (NOT OpenAI-compatible): catch-all route forwards any path to `https://api.anthropic.com`; real traffic is `POST /v1/messages`. Extra endpoints: `GET /healthz`, `GET /quota`.
- Per request: strips inbound auth headers, sets `Authorization: Bearer <oauth token>`, merges the `oauth-2025-04-20` beta header, and on `/v1/messages` injects the mandatory system prefix `"You are Claude Code, Anthropic's official CLI for Claude."` (idempotent; Anthropic rejects OAuth-scoped requests without it).
- Credentials: same source the `claude` CLI writes — macOS Keychain service `Claude Code-credentials` (also: `CLAUDE_CODE_CREDENTIALS` inline env, `AURORA_CC_CREDS_PATH`, `~/.claude/.credentials.json`, refresh cache). Self-refresh via the public Claude Code client id against `console.anthropic.com/v1/oauth/token`. **Anthropic rotates the refresh token on every grant**, so a bridge self-refresh can log out the interactive CLI (mitigations: `AURORA_CC_WRITE_BACK_KEYCHAIN=1`, the account-pool file form, or a dedicated account).
- Errors are classified (`transient_throttle`, `subscription_cap`, `oauth_token_invalid`, `overloaded`, ...) and re-emitted in an `aurora_bridge` JSON envelope with `X-Aurora-Bridge-Error` / `Retry-After` / `X-Aurora-Reset-At` headers. `assay/judge.py` reads `kind == "subscription_cap"` to pause on caps. Multi-account pool via `AURORA_CC_ACCOUNT_POOL` with exhaustion tracking and failover.
- **Operational rule: the bridge locks onto whichever Claude account is logged in when it starts and never re-reads the keychain. After `claude /login`, always `proxy/claude_code_bridge.sh stop` then `start`.**

### H.2 Codex bridge — port 8766 (`proxy/codex_bridge/`)

- Fronts the **ChatGPT-subscription Codex backend** (`https://chatgpt.com/backend-api/codex`) speaking the **OpenAI Responses API**. Only `POST /responses`, `POST /v1/responses`, `GET /healthz` exist; everything else 404s with a message redirecting Anthropic-shaped traffic to port 8765.
- Header injection: real bearer, `originator: codex_cli_rs`, `OpenAI-Beta: responses=experimental`, `chatgpt-account-id`. Body shaping (empirically probed against the live backend, 2026-08-10): `stream` MUST be true, `store` MUST be false; `temperature`/`max_output_tokens`/`max_tokens`/`top_p`/`prompt_cache_retention` are stripped (all rejected upstream — necessary because the SDK hardcodes `temperature 1.0` for non-subscription LLMs); the `instructions` system prompt is folded into the first user input item (non-idempotent, so shaping happens exactly once, before the retry loop).
- Always streams upstream; for `stream:false` clients it aggregates the SSE into one Responses JSON. Backend quirk handled: `response.completed` arrives with an empty `response.output` — the real items come from `response.output_item.done` events.
- Credentials: `~/.codex/auth.json` (plain JSON, all OSes); expiry read from the access-token JWT `exp`; form-encoded refresh against `auth.openai.com/oauth/token`; OpenAI also rotates refresh tokens, so write-back is an atomic read-modify-write preserving untouched fields (`id_token`, `account_id`).
- Reuses `claude_code_bridge.errors` (the `subscription_cap` string value is load-bearing for assay) — same `aurora_bridge` envelope, so downstream handling is provider-agnostic.
- **Integration status: integrated.** `.llm_config/codex.json`, `README.md`, and `run_eval.sh` support Codex trajectories; `run_eval.sh` also routes an `openai/` rubric model to `:8766/responses`. Keep author/judge models fixed within a delivery batch for comparability. `proxy/codex_bridge/probe.py` remains a disposable diagnostic, not a pipeline component.

## I. Pinned dependencies and vendored code (do not casually bump)

| Component | Pin | Why |
|---|---|---|
| `multi-swe-bench` | `Ethara-Ai/multi-swe-bench` @ `83e1868` (`[tool.uv.sources]`) | Later upstream main (`13f0929`) re-keys the tortoise instance registry to interval names and **breaks evaluation lookup** |
| `litellm` | `Ethara-Ai/litellm` @ `a276b06`, forced everywhere via `[tool.uv] override-dependencies` | Fork carries harness-required changes |
| `vendor/software-agent-sdk` | gitlink @ `3ab822f5` (`v1.12.0-2-g3ab822f5`), `Ethara-AI` fork | uv workspace members (`openhands-sdk/tools/workspace/agent-server`). The checked-in egress filter/entrypoint does **not** satisfy first-party full-block/carve-out tests; see K.6 before relying on it. |
| `commit0` | `Ethara-Ai/commit0` @ `1bd6bf3` | fork pin |
| `swt-bench` | `logic-star-ai/swt-bench` @ `5fdcd44` | pin |
| `swebench` | `== 4.1.0` | exact pin |
| headroom | optional extra `compression = headroom-ai[proxy]>=0.24,<0.25` | compression proxy |
| `patches/registry/c/libuv/libuv.py` | manual drop-in | Out-of-tree MSB instance definition (Docker image + test commands + log parsing for libuv). **No code copies it automatically** — it must be placed into the installed `multi_swe_bench` package in `.venv/.../site-packages/` by hand |

`sitecustomize.py` (repo root, auto-imported by Python) applies `benchmarks/utils/modal_patches.apply_host_patches()`: fixes the Modal scikit-learn `--no-use-pep517` install break (pip ≥ 25), persists logs/reports for pre-report sandbox exceptions, and applies cgroup-retry/timeout/timing patches. Exceptions are swallowed to avoid startup failure, but the import is global and can emit logs/warnings or mutate Modal functions during unrelated Python/test startup; treat these monkeypatches as a brittle upstream-compatibility layer.

## J. Testing and engineering conventions

- Type checking: **pyright** (never mypy). Lint/format: ruff (line 88, `E,F,I`, E501 ignored). Pyright currently includes only `benchmarks`; pre-commit excludes `legacy/`, `assay/`, and fixture bundles, so active `assay/` code is outside lint/type gates. After editing a checked path run `uv run pre-commit run --files <path>`.
- Tests: `uv run pytest`. Focused edge-case tests, no test classes unless necessary, shared setup in `conftest.py` fixtures, test only this codebase's logic.
- Commits: only relevant files; `Co-authored-by: openhands <openhands@all-hands.dev>` on every commit; real newlines in messages.
- No `sys.path.insert` hacks; no `# type: ignore` unless unavoidable; explicit type hints over `getattr`/`hasattr`; inline imports only for circular deps.
- New benchmark = new dir under `benchmarks/` + `run_infer.py` + eval script + `[project.scripts]` entry + README update. LLM configs follow the SDK `LLM` schema; validate with `uv run validate-cfg <path>`.
- `make build` requires uv ≥ 0.8.13, then runs `git submodule update --init --recursive --remote`, non-frozen `uv sync --dev`, and pre-commit install. Because `.gitmodules` defines no branch, `--remote` can move the SDK away from the committed gitlink and can override a workflow's selected `sdk-commit`; this is a reproducibility hazard. `.DEFAULT_GOAL := help` has no matching target, so use explicit targets (`build`, `format`, `lint`, `clean`, `update-sdk`).

**The test suite is the specification, but the current checkout is not fully green.** CI runs `tests/` plus `benchmarks/multiswebench/tests/` behind changed-file detection with a 15% `benchmarks` coverage floor. On 2026-08-17, `uv lock --check` passed and a representative scoring/rubric/bridge/metrics set passed 166 tests; the focused anti-reward-hacking suite passed 29 and failed 7 because of the SDK egress mismatch in K.6. Key contracts:

| Test file | Invariant it locks |
|---|---|
| `test_assay_replay.py` | Corpus compatibility replay; pins unaffected fields and recomputes intentionally changed deterministic/composed fields |
| `test_assay_vendor_patches.py` | Each schema-drift vendor patch individually (incl. "judge requests never send temperature") |
| `test_bundle_structure.py` | Bundle == corpus structure: file set, JSON key sets and order, enums, templates |
| `test_milo_pilot_regression.py` | tortoise 943 reward-hacker caught via B1 (not C3); B4 voids 100-ceiling runs; 1000-ceiling counterfactuals; deterministic rescoring |
| `test_rubric_regression_tortoise.py` | Pinned pilot ground truth; `RUBRIC_LIVE=1` re-judges through the bridge as a drift canary |
| `test_rubric_anchoring.py` | Gold/stub gate classification; redraft-once-then-prune-then-reject; transport failure ≠ rejection |
| `test_rubric_mockjudge.py` | Judging idempotent; judge blindness (runner source never opens outcome files); errors leave `result.json` untouched |
| `test_rubric_scoring.py` / `_parser.py` / `_evidence.py` / `_schema.py` | Score math exact; parser total under fuzz (abstain over guess); evidence packet deterministic; lint rules L1–L7 |
| `test_rubric_wiring.py` | `run_eval.sh` wiring: RUBRIC_ENABLE defaults OFF, phase order, once-per-task authoring, council derivation, WCB retired, bundle-first staging |
| `test_rubric_model_config.py` | `rubric-judge.json` is the single source of model truth; fallback behavior |
| `test_dataset_split.py`, `test_iterative_resume.py`, `test_workspace_cleanup.py`, `test_metrics.py`, `test_aggregate_results.py`, `test_codex_bridge.py`, `test_security_fixes.py`, `test_env_dep_inject.py`, `test_anti_reward_hacking_wiring.py` | Pipeline mechanics: splitting, resume, cleanup, metrics, codex bridge, security fixes |

Notable finding on the tortoise 943 pilot (recorded in RUBRIC.md §5): the reward-hacking run edited `tortoise/contrib/test/nose2.py` (test *infrastructure*, not a `test_*.py` file), so `C3-no-graded-test-write` stays silent by corpus semantics (`TEST_PATH_RE` matches test files only — deliberately not forked); the run is caught anyway via `B1-scored-status` because the tampering broke the verifier, making it `unverifiable`.

## K. Known caveats and sharp edges (all verified in-code)

1. **Bridge account lock-in** — restart the 8765 bridge after every `claude /login` (H.1).
2. **Bridge exposure** — both wrappers bind `0.0.0.0` and provide no inbound authentication. Restrict network access; a reachable peer can spend the linked subscription.
3. **B4 turn ceiling** — never deliver runs recorded below `--max-iter 1000` (C.4).
4. **`run_custom_eval.sh` is legacy but not inert** — MAX_ITER defaults to 300, it lacks `--parallel`, stages the old `dataset/<uuid>` + `trajectory/<uuid>` layout, creates local Git commits, and conditionally pushes unless `--no-push` or another guard prevents it. Use `run_eval.sh` for current Milo delivery.
5. **Dependency setup is mutable** — both root runners invoke `uv lock --upgrade-package multi-swe-bench`; `make build` follows the SDK remote rather than strictly preserving the gitlink. Use clean checkouts and inspect lock/submodule diffs.
6. **Egress contract is currently broken at the pinned SDK boundary** — first-party tests require an unconditional full block plus an `LLM_DIRECT_HOST/PORT` iptables/`NO_PROXY` carve-out. SDK `3ab822f5` instead contains task-selective `TASK_BLOCK_*` logic and no entrypoint carve-out, while `run_infer.py` no longer forwards `TASK_BLOCK_*`. With task identity absent the addon returns without denying, and the entrypoint preflight is expected to abort; `tests/test_anti_reward_hacking_wiring.py` currently has 7 failures. `EGRESS_FILTER_DISABLE=1` bypasses the filter entirely. Do not claim anti-cheat egress isolation until this is reconciled and tests pass. Harbor verifier tasks separately use `network_mode = "none"`.
7. **Privileged image-build workflows** — label-triggered `pull_request_target` jobs check out PR-head code and execute `make build`/Python while holding `packages:write`, `issues:write`, and `GITHUB_TOKEN`. A maintainer applying a build label is authorizing privileged execution of contributor-controlled code; redesign before treating untrusted PRs as safe. Action references are version tags, not immutable SHAs.
8. **Broken CLI registration** — `validate-dataset` points to the missing `benchmarks.scripts.validate_dataset` module.
9. **`.env` AWS variable names are swapped** relative to what they hold (section D).
10. **Bare `make` fails** because `.DEFAULT_GOAL := help` has no `help` target.
11. **`AGENTS.md` is partially stale**: it references `benchmarks/swe_bench/` (actual: `benchmarks/swebench/`) and `vendor/agent-sdk/` (actual: `vendor/software-agent-sdk/`), and predates `proxy/` and `assay/`. Its pyright/test/commit conventions otherwise remain applicable.
12. **Account-pool `keychain:` form is broken** — `load_account_pool()` splits `AURORA_CC_ACCOUNT_POOL` on `:` before detecting `keychain:<service>`, producing bogus file entries. File-path pool entries and the default single-account path work.
13. **Codex is integrated, but measurement discipline still matters** — trajectory models may vary; keep author/judge provider and model fixed within a delivery batch. An OpenAI judge uses the Responses endpoint on port 8766 and cannot be mixed arbitrarily with Anthropic seats in one council.
14. **Concurrent-run container cleanup** — a fresh driver start can kill `agent-server-*` containers unless `SKIP_ORPHAN_CLEANUP=1`; do not overlap runs casually.
15. **Publishing differs by runner** — `run_eval.sh` performs no Git operations on the staging directory (no clone, fetch, pull, add, commit, or push); all publishing code, GitHub API/token verification, and associated locks/status have been removed; the `--data-dir` must already exist as a writable directory. `run_custom_eval.sh` retains active commit and conditional push behavior.
16. **Documentation drift remains outside this SOP** — `SCORE_MATH.md` has stale deterministic weights; `README.md` undercounts available suites and contains some stale defaults/cleanup language. Prefer source and green contract tests.

## L. State snapshot (2026-08-17)

- Repository revision inspected: `b0e2dacc4b905e0d327c40891835b4159daacdac` (`task.toml template: drop Aditya Pathak (9 contributors)`).
- SDK gitlink and checkout inspected: `3ab822f519d21d0ec77a6ddb0c0fc7cc115d66f2` (`v1.12.0-2-g3ab822f5`).
- Dependency check: `uv lock --check` passed.
- Representative validation: 166 tests passed across Multi-SWE scoring/conversion, assay composition, rubric authoring/anchoring, Codex bridge, and cross-benchmark metrics.
- Known red contract: anti-reward-hacking wiring suite = 29 passed / 7 failed (K.6). Treat this as a release blocker for claims of egress isolation.
- CI test scope: root tests plus Multi-SWE local tests, changed-file gated, with a 15% coverage floor over `benchmarks`; `assay/`, proxies, shell orchestration, and workflows are not comprehensively type/coverage gated.
- Proven historical runs remain the dapr Go 41-instance batch and tortoise-orm 538/943 pilot fixtures; runtime output directories are mutable artifacts and are intentionally not enumerated here.
