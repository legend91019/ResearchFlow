from __future__ import annotations

from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_required_protocol_files_exist() -> None:
    expected = [
        "AGENTS.md",
        "CLAUDE.md",
        "README.md",
        "docs/README_CN.md",
        "docs/assets/banner.svg",
        "pyproject.toml",
        "scripts/cite_graph.py",
        "scripts/fetch_paper.py",
        "templates/01_scope.md",
        "templates/02_paper_map.md",
        "templates/03_idea_discussion.md",
        "templates/04_handoff.md",
        "templates/paper_note.md",
        "templates/search_audit.md",
        "skills/idea-stage1-landscape/SKILL.md",
        "skills/idea-stage2-literature-map/SKILL.md",
        "skills/idea-stage3-ideation/SKILL.md",
        "skills/idea-stage4-review-handoff/SKILL.md",
    ]
    for rel in expected:
        path = REPO_ROOT / rel
        assert path.is_file(), f"Missing protocol file: {rel}"


def test_skills_have_valid_yaml_frontmatter() -> None:
    skills_dir = REPO_ROOT / "skills"
    skill_files = list(skills_dir.glob("*/SKILL.md"))
    assert len(skill_files) == 4
    for sf in skill_files:
        text = sf.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        assert m is not None, f"Missing YAML frontmatter in {sf}"
        header = m.group(1)
        assert f"name: {sf.parent.name}" in header
        assert "description:" in header


def test_bilingual_readme_cross_links() -> None:
    en_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    cn_text = (REPO_ROOT / "docs/README_CN.md").read_text(encoding="utf-8")
    assert "docs/README_CN.md" in en_text
    assert "../README.md" in cn_text
