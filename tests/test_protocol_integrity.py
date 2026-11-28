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
        "scripts/remote_gpu.py",
        "scripts/run_matrix.py",
        "scripts/audit_exp.py",
        "templates/01_scope.md",
        "templates/02_paper_map.md",
        "templates/03_idea_discussion.md",
        "templates/04_handoff.md",
        "templates/05_pilot_report.md",
        "templates/06_exp_plan.md",
        "templates/07_exp_results.md",
        "templates/figure_plan.md",
        "templates/paper_note.md",
        "templates/search_audit.md",
        "skills/idea-stage1-landscape/SKILL.md",
        "skills/idea-stage2-literature-map/SKILL.md",
        "skills/idea-stage3-ideation/SKILL.md",
        "skills/idea-stage4-review-handoff/SKILL.md",
        "skills/exp-stage5-pilot/SKILL.md",
        "skills/exp-stage6-design/SKILL.md",
        "skills/exp-stage7a-coding/SKILL.md",
        "skills/exp-stage7b-execution/SKILL.md",
    ]
    for rel in expected:
        path = REPO_ROOT / rel
        assert path.is_file(), f"Missing protocol file: {rel}"


def test_skills_have_valid_yaml_frontmatter() -> None:
    skills_dir = REPO_ROOT / "skills"
    skill_files = list(skills_dir.glob("*/SKILL.md"))
    assert len(skill_files) == 8
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


def test_v02_anti_accretion_and_pilot_handoff_invariants() -> None:
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    s2 = (REPO_ROOT / "skills/idea-stage2-literature-map/SKILL.md").read_text(encoding="utf-8")
    s3 = (REPO_ROOT / "skills/idea-stage3-ideation/SKILL.md").read_text(encoding="utf-8")
    s4 = (REPO_ROOT / "skills/idea-stage4-review-handoff/SKILL.md").read_text(encoding="utf-8")
    t4 = (REPO_ROOT / "templates/04_handoff.md").read_text(encoding="utf-8")

    assert "奥卡姆剃刀" in agents
    assert "--scan-bib" in s2 and "--arxiv-recent" in s2
    assert "Mandatory Component Search-Back" in s3
    assert "Minimum Novel Core" in s4 and "Coupled Simulation" in s4
    assert "READY_FOR_PILOT" in s4 and "NEEDS_SIMPLIFICATION" in s4
    assert "Gate 0" in t4 and "Go / No-Go" in t4


def test_v03_experiment_phase_invariants() -> None:
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    s5 = (REPO_ROOT / "skills/exp-stage5-pilot/SKILL.md").read_text(encoding="utf-8")
    s6 = (REPO_ROOT / "skills/exp-stage6-design/SKILL.md").read_text(encoding="utf-8")
    s7a = (REPO_ROOT / "skills/exp-stage7a-coding/SKILL.md").read_text(encoding="utf-8")
    s7b = (REPO_ROOT / "skills/exp-stage7b-execution/SKILL.md").read_text(encoding="utf-8")

    assert "工程自主权与科学决策权严格分离" in agents
    assert "严禁未经用户明确授权直接在宿主本机" in s5
    assert "02_paper_map.md" in s6 and "figure_plan.md" in s6 and "Derived Views" in s6
    assert "test_claims.py" in s7a and "Worst-Case Resource Probe" in s7a
    assert "run_matrix.py" in s7b and "audit_exp.py" in s7b and "invalidate" in s7b
