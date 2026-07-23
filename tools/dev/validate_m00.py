from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]

REQUIRED_FILES = (
    "README.md",
    "LICENSE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "AGENTS.md",
    "HINA_AI_MASTER_PLAN_VI.md",
    "deep-research-report.md",
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    ".env.example",
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "pnpm-workspace.yaml",
    "pnpm-lock.yaml",
    ".codex/config.toml",
    "docs/schemas/module-brief.schema.json",
    "docs/schemas/agent-result.schema.json",
    "docs/templates/MODULE_BRIEF.example.json",
    "docs/templates/AGENT_RESULT.example.json",
    "docs/modules/M00-governance.md",
    "third_party/code.lock.json",
    "third_party/candidates.json",
    "third_party/THIRD_PARTY_NOTICES.md",
    "ml/models/manifests/candidates.json",
    "configs/base/security.toml",
)

EXPECTED_AGENTS = {
    "architecture-contracts.toml": ("architecture_contracts", "gpt-5.5", "xhigh", "read-only"),
    "oss-researcher.toml": ("oss_researcher", "gpt-5.4", "medium", "read-only"),
    "module-builder.toml": ("module_builder", "gpt-5.5", "high", "workspace-write"),
    "qa-designer.toml": ("qa_designer", "gpt-5.4", "high", "read-only"),
    "qa-runner.toml": ("qa_runner", "gpt-5.4", "high", "workspace-write"),
    "safety-reviewer.toml": ("safety_reviewer", "gpt-5.5", "xhigh", "read-only"),
    "integration-release.toml": ("integration_release", "gpt-5.5", "high", "workspace-write"),
}

MODULE_BRANCH_PATTERN = re.compile(
    r"^(?:module|integration)/M[0-9]{2}-[A-Za-z0-9._/-]+$"
)

MODULE_BRIEF_REQUIRED = {
    "schema_version",
    "task_id",
    "module_id",
    "objective",
    "non_goals",
    "base_sha",
    "branch",
    "worktree",
    "owned_paths",
    "forbidden_paths",
    "contracts",
    "allowed_dependencies",
    "oss_candidates",
    "acceptance_criteria",
    "required_test_commands",
    "output_artifact_dir",
}

AGENT_RESULT_REQUIRED = {
    "schema_version",
    "task_id",
    "brief_sha256",
    "role",
    "module_id",
    "status",
    "base_sha",
    "head_sha",
    "tree_hash",
    "git_status",
    "runtime",
    "changed_files",
    "decisions",
    "commands_run",
    "tests",
    "provenance",
    "risks",
    "blockers",
    "recommended_next_action",
}


def load_json(relative_path: str) -> Any:
    with (ROOT / relative_path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_toml(relative_path: str) -> dict[str, Any]:
    with (ROOT / relative_path).open("rb") as handle:
        return tomllib.load(handle)


def git_output(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def validate_required_files(errors: list[str]) -> None:
    for relative_path in REQUIRED_FILES:
        if not (ROOT / relative_path).is_file():
            errors.append(f"missing required file: {relative_path}")


def validate_project_config(errors: list[str]) -> None:
    config = load_toml(".codex/config.toml")
    if config.get("model") != "gpt-5.6-sol":
        errors.append("primary model must be gpt-5.6-sol")
    if config.get("model_reasoning_effort") != "high":
        errors.append("primary reasoning effort must be high")
    if config.get("sandbox_mode") != "workspace-write":
        errors.append("project sandbox default must be workspace-write")

    agents = config.get("agents", {})
    expected_names = {values[0] for values in EXPECTED_AGENTS.values()}
    if set(agents) != expected_names:
        errors.append(
            "project agent declarations differ: "
            f"expected {sorted(expected_names)}, got {sorted(agents)}"
        )
    for filename, (name, *_rest) in EXPECTED_AGENTS.items():
        declaration = agents.get(name, {})
        if not isinstance(declaration, dict):
            errors.append(f"agents.{name} must be a table")
            continue
        if not str(declaration.get("description", "")).strip():
            errors.append(f"agents.{name}.description must be non-empty")
        if declaration.get("config_file") != f"agents/{filename}":
            errors.append(
                f"agents.{name}.config_file must reference agents/{filename}"
            )


def validate_custom_agents(errors: list[str]) -> None:
    agents_dir = ROOT / ".codex" / "agents"
    actual_files = {path.name for path in agents_dir.glob("*.toml")}
    expected_files = set(EXPECTED_AGENTS)
    if actual_files != expected_files:
        errors.append(
            f"custom agent files differ: expected {sorted(expected_files)}, got {sorted(actual_files)}"
        )

    for filename, expected in EXPECTED_AGENTS.items():
        path = agents_dir / filename
        if not path.is_file():
            continue
        data = load_toml(f".codex/agents/{filename}")
        name, model, effort, sandbox = expected
        for key in ("name", "description", "developer_instructions"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                errors.append(f"{filename}: missing non-empty {key}")
        if data.get("name") != name:
            errors.append(f"{filename}: expected name {name}")
        if data.get("model") != model:
            errors.append(f"{filename}: expected model {model}")
        if data.get("model_reasoning_effort") != effort:
            errors.append(f"{filename}: expected effort {effort}")
        if data.get("sandbox_mode") != sandbox:
            errors.append(f"{filename}: expected sandbox {sandbox}")


def validate_handoff_contracts(errors: list[str]) -> None:
    for schema_path in (
        "docs/schemas/module-brief.schema.json",
        "docs/schemas/agent-result.schema.json",
    ):
        schema = load_json(schema_path)
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(f"{schema_path}: must use JSON Schema draft 2020-12")
        if schema.get("additionalProperties") is not False:
            errors.append(f"{schema_path}: top-level additionalProperties must be false")

    brief = load_json("docs/templates/MODULE_BRIEF.example.json")
    if set(brief) - (MODULE_BRIEF_REQUIRED | {"latency_or_quality_budget"}):
        errors.append("module brief example contains unknown top-level fields")
    missing_brief = MODULE_BRIEF_REQUIRED - set(brief)
    if missing_brief:
        errors.append(f"module brief example missing: {sorted(missing_brief)}")
    if not re.fullmatch(r"M[0-9]{2}", str(brief.get("module_id", ""))):
        errors.append("module brief module_id must match MNN")
    if not re.fullmatch(r"[0-9a-f]{7,40}", str(brief.get("base_sha", ""))):
        errors.append("module brief base_sha is invalid")

    result = load_json("docs/templates/AGENT_RESULT.example.json")
    if set(result) != AGENT_RESULT_REQUIRED:
        errors.append(
            "agent result example fields differ from required contract: "
            f"missing={sorted(AGENT_RESULT_REQUIRED - set(result))}, "
            f"extra={sorted(set(result) - AGENT_RESULT_REQUIRED)}"
        )
    if result.get("status") not in {"passed", "failed", "blocked"}:
        errors.append("agent result status is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(result.get("brief_sha256", ""))):
        errors.append("agent result brief_sha256 is invalid")

    runtime_required = {
        "codex_version",
        "model_slug",
        "reasoning_effort",
        "sandbox_mode",
        "effective_sandbox_mode",
        "approval_policy",
        "permission_source",
        "cwd",
        "worktree_root",
        "branch",
        "observed_base_sha",
    }
    runtime = result.get("runtime", {})
    if set(runtime) != runtime_required:
        errors.append("agent result runtime fields differ from required contract")
    if result.get("status") == "passed":
        if runtime.get("effective_sandbox_mode") == "danger-full-access":
            errors.append("passed agent result cannot use danger-full-access")
        if runtime.get("permission_source") == "live_override":
            errors.append("passed agent result cannot rely on a live permission override")


def validate_security_defaults(errors: list[str]) -> None:
    security = load_toml("configs/base/security.toml")
    if security.get("host") != "127.0.0.1":
        errors.append("default host must be 127.0.0.1")
    if security.get("allow_remote") is not False:
        errors.append("allow_remote must default to false")
    if security.get("execute_model_generated_code") is not False:
        errors.append("model-generated code execution must default to false")
    if security.get("minimum_free_vram_mib") != 2048:
        errors.append("minimum_free_vram_mib must be 2048")

    for profile in ("development", "private", "livestream"):
        data = load_toml(f"configs/profiles/{profile}/profile.toml")
        if data.get("public_output_enabled") is not False:
            errors.append(f"{profile}: public output must default to false")

    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for required_pattern in (
        ".env",
        "var/",
        "ml/datasets/raw/",
        "ml/datasets/staged/",
        "ml/datasets/curated/",
        "*.safetensors",
        "*.gguf",
    ):
        if required_pattern not in ignore:
            errors.append(f".gitignore missing safety pattern: {required_pattern}")


def validate_provenance(errors: list[str]) -> None:
    code_lock = load_json("third_party/code.lock.json")
    if code_lock.get("schema_version") != "1.0":
        errors.append("third_party/code.lock.json schema_version must be 1.0")
    components = code_lock.get("components")
    if not isinstance(components, list):
        errors.append("third_party/code.lock.json components must be an array")
        return
    required = {
        "name",
        "source_url",
        "revision",
        "license_spdx",
        "source_hash",
        "destination_paths",
        "modifications",
    }
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            errors.append(f"code lock component {index} must be an object")
            continue
        missing = required - set(component)
        if missing:
            errors.append(f"code lock component {index} missing {sorted(missing)}")

    for candidate_path in (
        "third_party/candidates.json",
        "ml/models/manifests/candidates.json",
    ):
        registry = load_json(candidate_path)
        if registry.get("status") != "research_only":
            errors.append(f"{candidate_path}: status must be research_only")
        if registry.get("frozen") is not False:
            errors.append(f"{candidate_path}: frozen must be false in M00")
        candidates = registry.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            errors.append(f"{candidate_path}: candidates must be a non-empty array")
            continue
        for index, candidate in enumerate(candidates):
            if candidate.get("revision") is not None:
                errors.append(
                    f"{candidate_path}: candidate {index} must remain unfrozen"
                )
            if not candidate.get("source_url"):
                errors.append(
                    f"{candidate_path}: candidate {index} missing source_url"
                )


def canonical_repository(value: str) -> str:
    raw = value.strip().rstrip("/")
    if raw.startswith("git@github.com:"):
        path = raw.removeprefix("git@github.com:")
        return f"github.com/{path.removesuffix('.git').lower()}"
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https", "ssh"} and parsed.hostname:
        path = parsed.path.lstrip("/").removesuffix(".git")
        return f"{parsed.hostname.lower()}/{path.lower()}"
    return raw.removesuffix(".git").lower()


def is_allowed_m00_checkout(branch: str) -> bool:
    # Independent validation and CI intentionally check out a frozen commit in
    # detached-HEAD state. The M00 invariants also remain active on every later
    # versioned module/integration branch.
    return branch == "" or branch == "main" or bool(MODULE_BRANCH_PATTERN.fullmatch(branch))


def validate_git(errors: list[str]) -> None:
    try:
        if git_output("rev-parse", "--is-inside-work-tree") != "true":
            errors.append("workspace is not a Git worktree")
        branch = git_output("branch", "--show-current")
        if not is_allowed_m00_checkout(branch):
            errors.append(f"unexpected M00 branch: {branch}")
        remotes = git_output("remote", "get-url", "origin")
        if canonical_repository(remotes) != "github.com/vubaolinh123/ai-hina":
            errors.append(f"unexpected origin: {remotes}")
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        errors.append(f"Git validation failed: {exc}")


def collect_errors() -> list[str]:
    errors: list[str] = []
    validate_required_files(errors)
    if errors:
        return errors
    validate_project_config(errors)
    validate_custom_agents(errors)
    validate_handoff_contracts(errors)
    validate_security_defaults(errors)
    validate_provenance(errors)
    validate_git(errors)
    return errors


def main() -> int:
    errors = collect_errors()
    if errors:
        print("M00 validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("M00 validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
