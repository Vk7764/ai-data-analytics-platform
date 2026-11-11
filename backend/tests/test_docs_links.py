# backend/tests/test_docs_links.py
# Documentation integrity check. Reads only local Markdown files under the repository root.
# Does not read secrets, does not contact external services, and does not modify any file.
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs"

REQUIRED_DOCS = [
    "README.md",
    "docs/README.md",
    "docs/QUICKSTART.md",
    "docs/OPERATOR_RUNBOOK.md",
    "docs/RELEASE_CHECKLIST.md",
    "docs/USER_GUIDE.md",
    "docs/SUPPORT_GUIDE.md",
    "docs/CHANGELOG.md",
    "docs/DEPLOYMENT_CHECKLIST.md",
    "docs/SECURITY.md",
    "docs/RELEASE_VALIDATION.md",
    "docs/KNOWN_LIMITATIONS.md",
    "docs/TECH_DEBT.md",
]

# Matches Markdown links such as [Label](Target.md). Anchors and URLs are ignored by the target check below.
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


@pytest.mark.parametrize("relative_path", REQUIRED_DOCS)
def test_required_documentation_file_exists(relative_path):
    path = REPO_ROOT / relative_path
    assert path.is_file(), (
        f"Required documentation file is missing: {relative_path}. "
        "Create it or restore it from version control."
    )


def test_docs_index_links_point_to_existing_markdown_files():
    index_path = DOCS_DIR / "README.md"
    assert index_path.is_file(), "docs/README.md is missing, so its links cannot be checked."

    content = index_path.read_text(encoding="utf-8")
    targets = []
    for raw_target in MARKDOWN_LINK_PATTERN.findall(content):
        target = raw_target.split("#", 1)[0].strip()
        if not target or "://" in target or target.startswith("mailto:"):
            continue  # Skip external URLs, mail links, and pure in-page anchors.
        if target.lower().endswith(".md"):
            targets.append(target)

    assert targets, "docs/README.md contains no Markdown links to documentation files."

    for target in targets:
        linked = (DOCS_DIR / target).resolve()
        assert DOCS_DIR.resolve() in linked.parents, (
            f"Link in docs/README.md escapes the docs directory: {target}"
        )
        assert linked.is_file(), (
            f"Link in docs/README.md points to a missing file: {target}. "
            "Fix the link or create the document."
        )


def test_root_readme_links_to_docs_point_to_existing_markdown_files():
    readme_path = REPO_ROOT / "README.md"
    assert readme_path.is_file(), "README.md is missing, so its links cannot be checked."

    content = readme_path.read_text(encoding="utf-8")
    targets = []
    for raw_target in MARKDOWN_LINK_PATTERN.findall(content):
        target = raw_target.split("#", 1)[0].strip()
        if not target or "://" in target or target.startswith("mailto:"):
            continue  # Skip external URLs, mail links, and pure in-page anchors.
        if target.startswith("docs/") and target.lower().endswith(".md"):
            targets.append(target)

    assert targets, "README.md contains no Markdown links to files under docs/."

    for target in targets:
        linked = (REPO_ROOT / target).resolve()
        assert DOCS_DIR.resolve() in linked.parents, (
            f"Link in README.md escapes the docs directory: {target}"
        )
        assert linked.is_file(), (
            f"Link in README.md points to a missing file: {target}. "
            "Fix the link or create the document."
        )