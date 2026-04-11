"""Pure-function PR review checks.

Each check operates on diff text (strings) and returns ReviewFindings.
No I/O, no GitHub API — the tool layer handles fetching diffs.
This makes every check trivially testable.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from stronghold.types.feedback import ReviewFinding, Severity, ViolationCategory

# Project root used to resolve `stronghold.X.Y` import paths against the
# actual filesystem during check_test_imports_exist. Defaults to cwd so
# tests and CI both work without configuration; override via the keyword
# argument for unusual layouts.
_DEFAULT_REPO_ROOT = Path.cwd()

# ---------------------------------------------------------------------------
# Pattern banks
# ---------------------------------------------------------------------------

_MOCK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"from\s+unittest\.mock\s+import"),
    re.compile(r"import\s+unittest\.mock"),
    re.compile(r"\bMagicMock\b"),
    re.compile(r"\bAsyncMock\b"),
    re.compile(r"@patch\("),
    re.compile(r"with\s+patch\("),
    re.compile(r"mock\.patch"),
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"""(?:api_key|secret|password|token)\s*=\s*["'][^"']{8,}["']""", re.IGNORECASE),
    re.compile(r"\bsk-[a-zA-Z0-9]{20,}\b"),
    re.compile(r"\bghp_[a-zA-Z0-9]{36}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
)

_ANY_IN_BUSINESS: re.Pattern[str] = re.compile(r":\s*Any\b|-> Any\b")

_PRIVATE_FIELD: re.Pattern[str] = re.compile(r"\.\s*_[a-z]\w*\b")

# Files that are always exempt from "production code in test PR" checks
_TEST_EXEMPT: frozenset[str] = frozenset(
    {
        "tests/fakes.py",
        "tests/conftest.py",
        "tests/factories.py",
    }
)


# ---------------------------------------------------------------------------
# Individual checks — each returns a list of findings
# ---------------------------------------------------------------------------


def check_mock_usage(
    diff_lines: list[str],
    *,
    file_path: str,
) -> list[ReviewFinding]:
    """Detect unittest.mock usage for internal classes."""
    findings: list[ReviewFinding] = []
    for i, line in enumerate(diff_lines, start=1):
        if not line.startswith("+"):
            continue
        content = line[1:]  # strip the '+' prefix
        for pattern in _MOCK_PATTERNS:
            if pattern.search(content):
                findings.append(
                    ReviewFinding(
                        category=ViolationCategory.MOCK_USAGE,
                        severity=Severity.HIGH,
                        file_path=file_path,
                        description=f"unittest.mock usage detected: {content.strip()}",
                        suggestion=(
                            "Use real classes or fakes from tests/fakes.py. "
                            "Only mock external HTTP calls (use respx)."
                        ),
                        line_number=i,
                    )
                )
                break  # one finding per line is enough
    return findings


def check_architecture_update(
    changed_files: list[str],
) -> list[ReviewFinding]:
    """Check if new src/ modules are accompanied by ARCHITECTURE.md updates."""
    has_new_src_module = False
    has_arch_update = False

    for path in changed_files:
        if path == "ARCHITECTURE.md":
            has_arch_update = True
        # New directory under src/stronghold/ (new __init__.py = new module)
        if path.startswith("src/stronghold/") and path.endswith("__init__.py"):
            has_new_src_module = True

    if has_new_src_module and not has_arch_update:
        return [
            ReviewFinding(
                category=ViolationCategory.ARCHITECTURE_UPDATE,
                severity=Severity.HIGH,
                file_path="ARCHITECTURE.md",
                description="New module added without ARCHITECTURE.md update",
                suggestion=(
                    "Build Rule #1: 'No Code Without Architecture.' "
                    "Add a section describing the new module before implementation."
                ),
            ),
        ]
    return []


def check_protocol_compliance(
    changed_files: list[str],
) -> list[ReviewFinding]:
    """Check if new src/ modules have corresponding protocols."""
    new_modules: list[str] = []
    has_protocol_change = False

    for path in changed_files:
        if path.startswith("src/stronghold/protocols/"):
            has_protocol_change = True
        elif (
            path.startswith("src/stronghold/")
            and path.endswith("__init__.py")
            and "protocols/" not in path
            and "types/" not in path
        ):
            new_modules.append(path)

    findings: list[ReviewFinding] = []
    if new_modules and not has_protocol_change:
        for mod_path in new_modules:
            findings.append(
                ReviewFinding(
                    category=ViolationCategory.PROTOCOL_MISSING,
                    severity=Severity.MEDIUM,
                    file_path=mod_path,
                    description="New module without corresponding protocol",
                    suggestion=(
                        "Add a protocol to src/stronghold/protocols/ for "
                        "new interfaces. Business logic depends on "
                        "protocols, not concrete implementations."
                    ),
                ),
            )
    return findings


def check_production_code_in_test_pr(
    changed_files: list[str],
    *,
    is_test_pr: bool,
) -> list[ReviewFinding]:
    """Check if a test: PR modifies production code."""
    if not is_test_pr:
        return []

    findings: list[ReviewFinding] = []
    for path in changed_files:
        if path.startswith("src/") and path not in _TEST_EXEMPT:
            findings.append(
                ReviewFinding(
                    category=ViolationCategory.PRODUCTION_CODE_IN_TEST,
                    severity=Severity.HIGH,
                    file_path=path,
                    description="Test PR modifies production code",
                    suggestion=(
                        "Test PRs (test: prefix) must not modify files under src/. "
                        "Split production changes into a separate PR."
                    ),
                ),
            )
    return findings


def check_type_annotations(
    diff_lines: list[str],
    *,
    file_path: str,
) -> list[ReviewFinding]:
    """Flag Any usage in business logic (not tests)."""
    if "/tests/" in file_path or file_path.startswith("tests/"):
        return []

    findings: list[ReviewFinding] = []
    for i, line in enumerate(diff_lines, start=1):
        if not line.startswith("+"):
            continue
        content = line[1:]
        # Skip TYPE_CHECKING guard imports and comments
        if "TYPE_CHECKING" in content or content.strip().startswith("#"):
            continue
        # Skip noqa annotations
        if "noqa" in content:
            continue
        if _ANY_IN_BUSINESS.search(content):
            findings.append(
                ReviewFinding(
                    category=ViolationCategory.TYPE_ANNOTATIONS,
                    severity=Severity.MEDIUM,
                    file_path=file_path,
                    description=f"Any usage in business logic: {content.strip()}",
                    suggestion=(
                        "Use specific types instead of Any. "
                        "If needed for protocol flexibility, use TYPE_CHECKING guards."
                    ),
                    line_number=i,
                ),
            )
    return findings


def check_hardcoded_secrets(
    diff_lines: list[str],
    *,
    file_path: str,
) -> list[ReviewFinding]:
    """Detect hardcoded secrets in code."""
    if "/tests/" in file_path or file_path.startswith("tests/"):
        return []

    findings: list[ReviewFinding] = []
    for i, line in enumerate(diff_lines, start=1):
        if not line.startswith("+"):
            continue
        content = line[1:]
        for pattern in _SECRET_PATTERNS:
            if pattern.search(content):
                findings.append(
                    ReviewFinding(
                        category=ViolationCategory.HARDCODED_SECRETS,
                        severity=Severity.CRITICAL,
                        file_path=file_path,
                        description=f"Potential hardcoded secret: {content.strip()[:60]}...",
                        suggestion=(
                            "Use environment variables or K8s secrets. "
                            "Defaults must be example values."
                        ),
                        line_number=i,
                    ),
                )
                break
    return findings


def check_missing_tests(
    changed_files: list[str],
    *,
    is_test_pr: bool,
) -> list[ReviewFinding]:
    """Check that feature PRs include test files."""
    if is_test_pr:
        return []

    has_src_changes = any(f.startswith("src/") for f in changed_files)
    has_test_files = any(f.startswith("tests/") and f.endswith(".py") for f in changed_files)

    if has_src_changes and not has_test_files:
        return [
            ReviewFinding(
                category=ViolationCategory.MISSING_TESTS,
                severity=Severity.HIGH,
                file_path="tests/",
                description="Feature PR has no test files",
                suggestion="Build Rule #2: 'No Code Without Tests (TDD).' Add tests first.",
            ),
        ]
    return []


def check_private_field_access(
    diff_lines: list[str],
    *,
    file_path: str,
) -> list[ReviewFinding]:
    """Flag access to private fields on classes you don't own."""
    # Only check production code, not tests (tests may legitimately inspect internals)
    if "/tests/" in file_path or file_path.startswith("tests/"):
        return []

    findings: list[ReviewFinding] = []
    for i, line in enumerate(diff_lines, start=1):
        if not line.startswith("+"):
            continue
        content = line[1:]
        if content.strip().startswith("#"):
            continue
        # Look for self._field (OK) vs other._field (not OK)
        # Heuristic: flag if accessing _field on a variable that isn't self
        matches = _PRIVATE_FIELD.findall(content)
        for match in matches:
            # self._field is fine, store._field is not
            prefix_idx = content.find(match)
            if prefix_idx > 0:
                before = content[:prefix_idx].rstrip()
                if before.endswith("self"):
                    continue
            findings.append(
                ReviewFinding(
                    category=ViolationCategory.PRIVATE_FIELD_ACCESS,
                    severity=Severity.MEDIUM,
                    file_path=file_path,
                    description=f"Private field access: {content.strip()[:80]}",
                    suggestion=(
                        "Access data through public methods or protocols, "
                        "not private fields. This breaks when implementations change."
                    ),
                    line_number=i,
                ),
            )
            break  # one per line
    return findings


def check_bundled_changes(
    changed_files: list[str],
    *,
    commit_count: int,
) -> list[ReviewFinding]:
    """Flag PRs with too many unrelated commits or files."""
    # Heuristic: if a PR touches more than 5 distinct top-level source directories
    # in a single commit, it's likely bundled
    src_dirs: set[str] = set()
    for path in changed_files:
        if path.startswith("src/stronghold/"):
            parts = path.split("/")
            if len(parts) >= 4:
                src_dirs.add(parts[2])  # e.g., "agents", "security", "router"

    findings: list[ReviewFinding] = []
    if len(src_dirs) > 4:
        findings.append(
            ReviewFinding(
                category=ViolationCategory.BUNDLED_CHANGES,
                severity=Severity.MEDIUM,
                file_path="",
                description=(
                    f"PR touches {len(src_dirs)} distinct modules: {', '.join(sorted(src_dirs))}. "
                    "This may indicate bundled unrelated changes."
                ),
                suggestion="Split into focused PRs, one per module or issue.",
            ),
        )
    return findings


# ---------------------------------------------------------------------------
# check_test_imports_exist
# ---------------------------------------------------------------------------
#
# Bug 6: Mason's impl stage sometimes writes test files that import modules
# that don't exist (e.g. `from stronghold.builders.pipeline import X` when
# the `stronghold.builders.pipeline` module was never created). The test
# then crashes at collection time and pollutes the CI signal. This check
# resolves every `from stronghold.x import y` / `import stronghold.x` in
# the added lines against the real filesystem under `src/stronghold/` and
# raises a HALLUCINATED_IMPORT finding if the module cannot be found.

# Matches `from stronghold.x.y import z` at the start of an added diff line.
# Requires at least one dot after `stronghold` so bare `from stronghold import`
# (which maps to the package itself) is ignored.
_FROM_IMPORT_RE = re.compile(
    r"^\+\s*from\s+(stronghold(?:\.[a-zA-Z_]\w*)+)\s+import\s+"
)
# Matches `import stronghold.x.y` (with optional `as alias`).
_BARE_IMPORT_RE = re.compile(
    r"^\+\s*import\s+(stronghold(?:\.[a-zA-Z_]\w*)+)(?:\s+as\s+\w+)?\s*(?:#.*)?$"
)


def _module_exists(module: str, repo_root: Path) -> bool:
    """True if a dotted ``stronghold.x.y`` path resolves to a real module.

    Resolution rule::

        stronghold.x.y  →  repo_root/src/stronghold/x/y.py
                        OR repo_root/src/stronghold/x/y/__init__.py

    A namespace package directory without ``__init__.py`` is rejected
    because Python's import system will not find symbols inside it.
    """
    parts = module.split(".")
    base = repo_root / "src" / Path(*parts)
    return base.with_suffix(".py").exists() or (base / "__init__.py").exists()


def _is_test_scope(file_path: str) -> bool:
    """True if the diff file is a test file the check should scan."""
    if not file_path:
        return False
    p = Path(file_path)
    if file_path.startswith("tests/") or "/tests/" in f"/{file_path}":
        return True
    return p.name.startswith("test_")


def check_test_imports_exist(
    diff_lines: list[str],
    *,
    file_path: str,
    repo_root: Path | None = None,
) -> list[ReviewFinding]:
    """Detect hallucinated ``stronghold.*`` imports in added test file lines.

    Only in scope:
      - Files under ``tests/`` or named ``test_*.py``.
      - Added lines (prefix ``+``), not context (prefix `` ``) or removals (``-``).
      - Imports whose root package is ``stronghold`` (stdlib / third-party ignored).
      - Absolute imports (relative ``from .foo`` is local and out of scope).

    The check is pure — it reads the filesystem only to resolve modules,
    never writes, and is safe to call from any thread.

    Dedupes violations per (module, file_path) so a test file that
    mentions the same bad module five times produces one finding.
    """
    if not _is_test_scope(file_path):
        return []

    root = repo_root or _DEFAULT_REPO_ROOT
    findings: list[ReviewFinding] = []
    seen: set[str] = set()

    for line in diff_lines:
        if not line.startswith("+"):
            continue
        m = _FROM_IMPORT_RE.match(line) or _BARE_IMPORT_RE.match(line)
        if not m:
            continue
        module = m.group(1)
        if module in seen:
            continue
        seen.add(module)
        if _module_exists(module, root):
            continue
        findings.append(
            ReviewFinding(
                category=ViolationCategory.HALLUCINATED_IMPORT,
                severity=Severity.HIGH,
                file_path=file_path,
                description=(
                    f"Test imports non-existent module `{module}` — "
                    "the module does not exist under src/stronghold/."
                ),
                suggestion=(
                    "Grep the codebase before writing the test: "
                    f"`grep -r 'class ' src/stronghold/ | grep -i <ClassName>`. "
                    "Do not invent module paths — verify with `ls` first."
                ),
            ),
        )
    return findings
