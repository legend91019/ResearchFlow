from __future__ import annotations

import json
from pathlib import Path

from scripts.cite_graph import (
    PaperNode,
    build_citation_graph,
    deduplicate_nodes,
    main,
    parse_identifier,
    render_markdown,
)


def test_parse_identifier_variants() -> None:
    assert parse_identifier("2310.06762") == ("arxiv", "2310.06762")
    assert parse_identifier("arXiv:2310.06762v3") == ("arxiv", "2310.06762")
    assert parse_identifier("https://arxiv.org/pdf/2403.01234v2.pdf") == ("arxiv", "2403.01234")
    assert parse_identifier("https://doi.org/10.48550/arXiv.2310.06762") == ("arxiv", "2310.06762")
    assert parse_identifier("10.1145/1234567.1234568") == ("doi", "10.1145/1234567.1234568")
    assert parse_identifier("a" * 40) == ("s2", "a" * 40)
    assert parse_identifier("Gradient Projection Memory for Continual Learning") == (
        "title",
        "Gradient Projection Memory for Continual Learning",
    )


def test_deduplicate_merges_across_providers() -> None:
    s2_node = PaperNode(
        title="Orthogonal Subspace Learning",
        year=2023,
        venue="",
        citation_count=42,
        arxiv_id="2310.06762",
        s2_id="abc",
        sources=["semantic_scholar"],
    )
    oa_node = PaperNode(
        title="Orthogonal Subspace Learning!",
        year=2023,
        venue="EMNLP",
        citation_count=48,
        doi="10.48550/arxiv.2310.06762",
        arxiv_id="2310.06762",
        openalex_id="https://openalex.org/W1",
        abstract="Detailed abstract from OpenAlex.",
        sources=["openalex"],
    )
    merged = deduplicate_nodes([s2_node, oa_node])
    assert len(merged) == 1
    assert merged[0].citation_count == 48
    assert merged[0].venue == "EMNLP"
    assert merged[0].abstract == "Detailed abstract from OpenAlex."
    assert merged[0].sources == ["semantic_scholar", "openalex"]


def test_s2_rate_limit_falls_back_to_openalex_with_explicit_warning(tmp_path: Path) -> None:
    def fake_fetcher(url: str, headers: dict[str, str]) -> dict:
        if "semanticscholar.org" in url:
            raise RuntimeError("HTTP 429 for Semantic Scholar")
        if "/works/https://doi.org/10.48550/arXiv.2310.06762" in url:
            return {
                "id": "https://openalex.org/W100",
                "display_name": "O-LoRA: Orthogonal Subspace Learning",
                "publication_year": 2023,
                "cited_by_count": 65,
                "doi": "https://doi.org/10.48550/arXiv.2310.06762",
                "authorships": [{"author": {"display_name": "Xiao Wang"}}],
                "referenced_works": ["https://openalex.org/W50"],
                "abstract_inverted_index": {"Orthogonal": [0], "LoRA": [1], "continual": [2]},
            }
        if "filter=openalex%3AW50" in url or "filter=openalex:W50" in url:
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W50",
                        "display_name": "LoRA: Low-Rank Adaptation",
                        "publication_year": 2022,
                        "cited_by_count": 5000,
                        "doi": "https://doi.org/10.48550/arXiv.2106.09685",
                    }
                ]
            }
        if "filter=cites%3AW100" in url or "filter=cites:W100" in url:
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W200",
                        "display_name": "InfLoRA: Interference-Free Low-Rank Adaptation",
                        "publication_year": 2024,
                        "cited_by_count": 19,
                        "doi": "https://doi.org/10.48550/arXiv.2404.00228",
                    },
                    {
                        "id": "https://openalex.org/W201",
                        "display_name": "Zero-Citation Brand New Followup",
                        "publication_year": 2026,
                        "cited_by_count": 0,
                        "doi": "https://doi.org/10.48550/arXiv.2602.12345",
                    },
                ]
            }
        raise AssertionError(f"Unexpected URL: {url}")

    graph = build_citation_graph("2310.06762", fetcher=fake_fetcher)
    assert graph["seed"]["title"] == "O-LoRA: Orthogonal Subspace Learning"
    assert graph["seed"]["abstract"] == "Orthogonal LoRA continual"
    assert any("HTTP 429" in w for w in graph["warnings"])
    assert graph["counts"]["references"] == 1
    assert graph["counts"]["citations"] == 2
    # Recent 2026 zero-citation paper must appear first rather than being buried
    assert graph["citations"][0]["arxiv_id"] == "2602.12345"

    md = render_markdown(graph, with_abstracts=True)
    assert "Provider Diagnostics" in md
    assert "2602.12345" in md
    assert "InfLoRA" in md


def test_cli_writes_markdown_and_json(tmp_path: Path, monkeypatch) -> None:
    def fake_http(url: str, headers: dict[str, str]) -> dict:
        if "/paper/ARXIV:2310.06762?" in url:
            return {
                "paperId": "b" * 40,
                "title": "Seed Paper",
                "year": 2023,
                "venue": "ICLR",
                "citationCount": 10,
                "externalIds": {"ArXiv": "2310.06762"},
                "authors": [{"name": "Alice"}],
            }
        return {"data": [], "results": []}

    monkeypatch.setattr("scripts.cite_graph.default_http_json", fake_http)
    md_out = tmp_path / "out.md"
    json_out = tmp_path / "out.json"
    rc = main(["2310.06762", "--direction", "references", "--out", str(md_out), "--json-out", str(json_out)])
    assert rc == 0
    assert md_out.exists()
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["seed"]["title"] == "Seed Paper"


def test_before_date_strips_future_papers() -> None:
    nodes = [
        PaperNode(title="Prior 2024", year=2024, arxiv_id="2404.00228", published_date="2024-04-01"),
        PaperNode(title="Future by date", year=2026, arxiv_id="2609.00001", published_date="2026-10-06"),
        PaperNode(title="Future by arXiv YYMM", year=2026, arxiv_id="2611.30102"),
    ]
    kept = deduplicate_nodes(nodes, before_date="2026-10-01")
    assert [n.title for n in kept] == ["Prior 2024"]
