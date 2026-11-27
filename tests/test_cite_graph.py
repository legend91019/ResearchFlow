from __future__ import annotations

import json
from pathlib import Path

from scripts.cite_graph import (
    PaperNode,
    _select_balanced_citations,
    build_citation_graph,
    deduplicate_nodes,
    main,
    parse_identifier,
    query_arxiv_recent,
    render_markdown,
    scan_local_bibliographies,
)


def test_parse_identifier_variants() -> None:
    assert parse_identifier("2310.14152") == ("arxiv", "2310.14152")
    assert parse_identifier("arXiv:2310.14152v3") == ("arxiv", "2310.14152")
    assert parse_identifier("https://arxiv.org/pdf/2403.01234v2.pdf") == ("arxiv", "2403.01234")
    assert parse_identifier("https://doi.org/10.48550/arXiv.2310.14152") == ("arxiv", "2310.14152")
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
        arxiv_id="2310.14152",
        s2_id="abc",
        sources=["semantic_scholar"],
    )
    oa_node = PaperNode(
        title="Orthogonal Subspace Learning!",
        year=2023,
        venue="EMNLP",
        citation_count=48,
        doi="10.48550/arxiv.2310.14152",
        arxiv_id="2310.14152",
        openalex_id="https://openalex.org/W1",
        abstract="Detailed abstract from OpenAlex.",
        published_date="2023-10-22",
        sources=["openalex"],
    )
    merged = deduplicate_nodes([s2_node, oa_node])
    assert len(merged) == 1
    assert merged[0].citation_count == 48
    assert merged[0].venue == "EMNLP"
    assert merged[0].published_date == "2023-10-22"
    assert merged[0].abstract == "Detailed abstract from OpenAlex."
    assert merged[0].sources == ["semantic_scholar", "openalex"]


def test_s2_rate_limit_falls_back_to_openalex_with_explicit_warning() -> None:
    def fake_fetcher(url: str, headers: dict[str, str]) -> dict:
        if "semanticscholar.org" in url:
            raise RuntimeError("HTTP 429 for Semantic Scholar")
        if "/works/https://doi.org/10.48550/arXiv.2310.14152" in url:
            return {
                "id": "https://openalex.org/W100",
                "display_name": "O-LoRA: Orthogonal Subspace Learning",
                "publication_year": 2023,
                "cited_by_count": 65,
                "doi": "https://doi.org/10.48550/arXiv.2310.14152",
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

    graph = build_citation_graph("2310.14152", fetcher=fake_fetcher)
    assert graph["seed"]["title"] == "O-LoRA: Orthogonal Subspace Learning"
    assert graph["seed"]["abstract"] == "Orthogonal LoRA continual"
    assert any("HTTP 429" in w for w in graph["warnings"])
    assert graph["counts"]["references"] == 1
    assert graph["counts"]["citations"] == 2
    assert graph["citations"][0]["arxiv_id"] == "2602.12345"

    md = render_markdown(graph, with_abstracts=True)
    assert "Provider Diagnostics" in md
    assert "2602.12345" in md
    assert "InfLoRA" in md


def test_s2_future_flood_does_not_short_circuit_openalex() -> None:
    """Regression test for Exp2 root cause: S2 returning post-cutoff items must never skip OpenAlex."""

    def fake_fetcher(url: str, headers: dict[str, str]) -> dict:
        if "semanticscholar.org/graph/v1/paper/ARXIV:2404.00228?" in url:
            return {
                "paperId": "c" * 40,
                "title": "InfLoRA",
                "year": 2024,
                "citationCount": 90,
                "externalIds": {"ArXiv": "2404.00228"},
            }
        if "semanticscholar.org/graph/v1/paper/" in url and "/citations" in url:
            # 30 post-cutoff citations that would have previously satisfied len(raw_cites) >= limit // 2
            return {
                "data": [
                    {
                        "citingPaper": {
                            "paperId": f"f{i:039d}",
                            "title": f"Future Paper {i}",
                            "year": 2026,
                            "publicationDate": "2026-10-15",
                            "citationCount": 0,
                            "externalIds": {"ArXiv": f"2610.{10000 + i}"},
                        }
                    }
                    for i in range(30)
                ]
            }
        if "semanticscholar.org/graph/v1/paper/" in url and "/references" in url:
            return {"data": []}
        if "api.openalex.org/works/https://doi.org/10.48550/arXiv.2404.00228" in url:
            return {
                "id": "https://openalex.org/W2404",
                "display_name": "InfLoRA",
                "publication_year": 2024,
                "cited_by_count": 90,
                "doi": "https://doi.org/10.48550/arXiv.2404.00228",
                "referenced_works": [],
            }
        if "api.openalex.org/works?" in url and "cites%3AW2404" in url:
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W_CLORA",
                        "display_name": "CLoRA: Continual Low-Rank Adaptation",
                        "publication_year": 2025,
                        "publication_date": "2025-07-01",
                        "cited_by_count": 35,
                        "doi": "https://doi.org/10.48550/arXiv.2410.16801",
                    }
                ]
            }
        return {"results": []}

    graph = build_citation_graph(
        "2404.00228",
        direction="citations",
        limit=20,
        before_date="2026-10-01",
        fetcher=fake_fetcher,
    )
    titles = [c["title"] for c in graph["citations"]]
    assert "CLoRA: Continual Low-Rank Adaptation" in titles
    assert all("Future Paper" not in t for t in titles)


def test_three_tier_bucketing_preserves_mid_horizon_papers() -> None:
    """Ensure 2025 venue papers are not starved between 2026 0-cite preprints and 2023 classics."""
    cites = [
        PaperNode(title=f"New2026_{i}", year=2026, citation_count=0, published_date=f"2026-09-{20 - i:02d}")
        for i in range(10)
    ] + [
        PaperNode(title=f"Classic2023_{i}", year=2023, citation_count=100 - i, published_date="2023-05-01")
        for i in range(10)
    ] + [
        PaperNode(title="Mid2025_CLoRA", year=2025, citation_count=35, published_date="2025-06-15"),
        PaperNode(title="Mid2024_SDLoRA", year=2024, citation_count=40, published_date="2024-11-10"),
    ]
    picked = _select_balanced_citations(cites, limit=10)
    picked_titles = {p.title for p in picked}
    assert "Mid2025_CLoRA" in picked_titles
    assert "Mid2024_SDLoRA" in picked_titles
    assert any(t.startswith("New2026_") for t in picked_titles)
    assert any(t.startswith("Classic2023_") for t in picked_titles)


def test_scan_local_bibliographies_ranks_unarchived_cocitations(tmp_path: Path) -> None:
    ws = tmp_path / "exp_demo"
    p1 = ws / "papers" / "2026_anchor"
    p2 = ws / "papers" / "2026_memtrim"
    (p1 / "source").mkdir(parents=True)
    (p2 / "source").mkdir(parents=True)

    (p1 / "metadata.json").write_text(
        json.dumps({"title": "Anchor Paper", "arxiv_id": "2611.10382"}),
        encoding="utf-8",
    )
    (p2 / "metadata.json").write_text(
        json.dumps({"title": "MemTrim Paper", "arxiv_id": "2610.07311"}),
        encoding="utf-8",
    )

    bib1 = """
    @article{faulty2026,
      title = {Useful Memories Become Faulty When Continuously Updated by {LLMs}},
      author = {Doe, Jane},
      year = {2026},
      eprint = {2605.12978},
      booktitle = {NeurIPS 2026}
    }
    @article{memtrim,
      title = {MemTrim Paper},
      year = {2026},
      eprint = {2610.07311}
    }
    @article{future2026,
      title = {Post Cutoff Leakage Paper},
      year = {2026},
      eprint = {2611.30102}
    }
    """
    bib2 = """
    @inproceedings{faulty2026_dup,
      title = "Useful Memories Become Faulty When Continuously Updated by LLMs",
      year = "2026",
      note = "arXiv:2605.12978"
    }
    @article{drift2026,
      title = {Skill Drift Is Contract Violation},
      year = {2026},
      eprint = {2605.10990}
    }
    """
    (p1 / "source" / "refs.bib").write_text(bib1, encoding="utf-8")
    (p2 / "source" / "main.bib").write_text(bib2, encoding="utf-8")

    res = scan_local_bibliographies(ws, before_date="2026-11-01")
    assert res["bib_files_scanned"] == 2
    assert res["total_unarchived_candidates"] == 2
    assert res["results"][0]["arxiv_id"] == "2605.12978"
    assert res["results"][0]["co_citation_count"] == 2
    assert set(res["results"][0]["cited_by_local"]) == {"2026_anchor", "2026_memtrim"}

    kw_res = scan_local_bibliographies(ws, keyword="contract", before_date="2026-11-01")
    assert len(kw_res["results"]) == 1
    assert kw_res["results"][0]["arxiv_id"] == "2605.10990"


def test_query_arxiv_recent_parses_atom_and_enforces_cutoff() -> None:
    sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>http://arxiv.org/abs/2611.32085v1</id>
        <published>2026-11-24T17:59:00Z</published>
        <title>ExpGuard: Guarding Long-Horizon LLM Agents</title>
        <summary>Counterfactual experience risk control.</summary>
        <author><name>Alice Zhang</name></author>
        <category term="cs.AI"/>
      </entry>
      <entry>
        <id>http://arxiv.org/abs/2609.34453v1</id>
        <published>2026-09-28T12:00:00Z</published>
        <title>SPACE-LoRA: Allocating Activation-Subspace Protection</title>
        <summary>Interference upper bound in Appendix A.2.</summary>
        <author><name>Bob Li</name></author>
        <category term="cs.LG"/>
      </entry>
    </feed>
    """
    live = query_arxiv_recent("agent memory", categories="cs.AI,cs.LG", days=30, text_fetcher=lambda u, h: sample_xml)
    assert live["count"] == 2
    assert live["results"][0]["arxiv_id"] == "2611.32085"

    cut = query_arxiv_recent("lora", days=30, before_date="2026-10-01", text_fetcher=lambda u, h: sample_xml)
    assert cut["count"] == 1
    assert cut["results"][0]["arxiv_id"] == "2609.34453"


def test_cli_writes_markdown_and_json(tmp_path: Path, monkeypatch) -> None:
    def fake_http(url: str, headers: dict[str, str]) -> dict:
        if "/paper/ARXIV:2310.14152?" in url:
            return {
                "paperId": "b" * 40,
                "title": "Seed Paper",
                "year": 2023,
                "venue": "ICLR",
                "citationCount": 10,
                "externalIds": {"ArXiv": "2310.14152"},
                "authors": [{"name": "Alice"}],
            }
        return {"data": [], "results": []}

    monkeypatch.setattr("scripts.cite_graph.default_http_json", fake_http)
    md_out = tmp_path / "out.md"
    json_out = tmp_path / "out.json"
    rc = main(["2310.14152", "--direction", "references", "--out", str(md_out), "--json-out", str(json_out)])
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
