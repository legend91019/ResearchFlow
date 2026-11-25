#!/usr/bin/env python3
"""Fetch bidirectional citation graphs (References & Citations) via Semantic Scholar + OpenAlex.

Zero third-party dependencies (Python 3.10+ standard library only).
Explicitly reports partial provider failures or rate limits without silent fallbacks.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "ResearchFlow/0.1 (Academic Research Workspace Protocol)"
S2_BASE = "https://api.semanticscholar.org/graph/v1"
OA_BASE = "https://api.openalex.org"
S2_FIELDS = "paperId,title,year,venue,citationCount,externalIds,url,abstract,authors"

_ARXIV_NEW_RE = re.compile(r"(?:arxiv[:/]|abs/|pdf/)?(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?$", re.I)
_ARXIV_OLD_RE = re.compile(r"(?:arxiv[:/]|abs/|pdf/)?([a-z-]+/\d{7})(?:v\d+)?(?:\.pdf)?$", re.I)
_DOI_RE = re.compile(r"(10\.\d{4,9}/\S+)", re.I)
_S2_HEX_RE = re.compile(r"^[0-9a-f]{40}$", re.I)

JsonFetcher = Callable[[str, dict[str, str]], dict[str, Any]]


@dataclass
class PaperNode:
    title: str
    year: int = 0
    venue: str = ""
    citation_count: int = 0
    arxiv_id: str = ""
    doi: str = ""
    s2_id: str = ""
    openalex_id: str = ""
    url: str = ""
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    sources: list[str] = field(default_factory=list)

    def primary_id(self) -> str:
        if self.arxiv_id:
            return f"arXiv:{self.arxiv_id}"
        if self.doi:
            return f"DOI:{self.doi}"
        return self.s2_id or self.openalex_id or "unknown"


def parse_identifier(raw: str) -> tuple[str, str]:
    """Normalize an input identifier into ('arxiv'|'doi'|'s2'|'title', normalized_value)."""
    text = raw.strip()
    if not text:
        raise ValueError("Empty paper identifier")

    parsed = urllib.parse.urlparse(text)
    if parsed.scheme in {"http", "https"} and "arxiv.org" in parsed.netloc.lower():
        path = parsed.path.strip("/")
        for regex in (_ARXIV_NEW_RE, _ARXIV_OLD_RE):
            m = regex.search(path)
            if m:
                return "arxiv", m.group(1)

    arxiv_doi = re.search(r"10\.48550/arxiv\.(\d{4}\.\d{4,5}|[a-z-]+/\d{7})", text, re.I)
    if arxiv_doi:
        return "arxiv", arxiv_doi.group(1)

    for regex in (_ARXIV_NEW_RE, _ARXIV_OLD_RE):
        m = regex.fullmatch(text)
        if m:
            return "arxiv", m.group(1)

    doi_match = _DOI_RE.search(text)
    if doi_match and ("doi.org" in text.lower() or text.lower().startswith(("10.", "doi:"))):
        return "doi", doi_match.group(1).rstrip(".,;)")

    if _S2_HEX_RE.fullmatch(text):
        return "s2", text.lower()

    return "title", text


def default_http_json(url: str, headers: dict[str, str], retries: int = 2) -> dict[str, Any]:
    """Fetch JSON over HTTPS with explicit retry on HTTP 429 / 5xx."""
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **headers}
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_err = exc
            if exc.code in {429, 502, 503, 504} and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {exc.code} for {url}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            raise RuntimeError(f"Request failed for {url}: {exc}") from exc
    raise RuntimeError(f"Unreachable URL {url}: {last_err}")


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def _reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str:
    if not isinstance(inverted, dict) or not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        if isinstance(idxs, list):
            for idx in idxs:
                if isinstance(idx, int):
                    positions.append((idx, word))
    if not positions:
        return ""
    positions.sort(key=lambda item: item[0])
    return " ".join(word for _, word in positions)


def _node_from_s2(raw: dict[str, Any]) -> PaperNode | None:
    title = str(raw.get("title") or "").strip()
    if not title:
        return None
    ext = raw.get("externalIds") or {}
    arxiv_id = str(ext.get("ArXiv") or "").strip()
    doi = str(ext.get("DOI") or "").strip()
    authors = [
        str(a.get("name", "")).strip()
        for a in (raw.get("authors") or [])
        if isinstance(a, dict) and str(a.get("name", "")).strip()
    ]
    s2_id = str(raw.get("paperId") or "").strip()
    url = str(raw.get("url") or "").strip()
    if arxiv_id and not url:
        url = f"https://arxiv.org/abs/{arxiv_id}"
    return PaperNode(
        title=title,
        year=int(raw["year"]) if isinstance(raw.get("year"), int) else 0,
        venue=str(raw.get("venue") or "").strip(),
        citation_count=int(raw["citationCount"]) if isinstance(raw.get("citationCount"), int) else 0,
        arxiv_id=arxiv_id,
        doi=doi,
        s2_id=s2_id,
        url=url,
        authors=authors[:8],
        abstract=str(raw.get("abstract") or "").strip(),
        sources=["semantic_scholar"],
    )


def _node_from_openalex(raw: dict[str, Any]) -> PaperNode | None:
    title = str(raw.get("display_name") or raw.get("title") or "").strip()
    if not title:
        return None
    ids = raw.get("ids") or {}
    doi_raw = str(raw.get("doi") or ids.get("doi") or "").strip()
    doi = re.sub(r"^https?://doi\.org/", "", doi_raw, flags=re.I)
    arxiv_id = ""
    m = re.search(r"10\.48550/arxiv\.(\d{4}\.\d{4,5}|[a-z-]+/\d{7})", doi, re.I)
    if m:
        arxiv_id = m.group(1)
    else:
        loc = raw.get("primary_location") or {}
        landing = str(loc.get("landing_page_url") or "")
        am = _ARXIV_NEW_RE.search(landing) or _ARXIV_OLD_RE.search(landing)
        if am:
            arxiv_id = am.group(1)
    venue = ""
    loc = raw.get("primary_location") or {}
    src = loc.get("source") or {}
    if isinstance(src, dict):
        venue = str(src.get("display_name") or "").strip()
    authors = [
        str((a.get("author") or {}).get("display_name") or "").strip()
        for a in (raw.get("authorships") or [])
        if isinstance(a, dict) and str((a.get("author") or {}).get("display_name") or "").strip()
    ]
    oa_id = str(raw.get("id") or "").strip()
    url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else (f"https://doi.org/{doi}" if doi else oa_id)
    return PaperNode(
        title=title,
        year=int(raw["publication_year"]) if isinstance(raw.get("publication_year"), int) else 0,
        venue=venue,
        citation_count=int(raw["cited_by_count"]) if isinstance(raw.get("cited_by_count"), int) else 0,
        arxiv_id=arxiv_id,
        doi=doi,
        openalex_id=oa_id,
        url=url,
        authors=authors[:8],
        abstract=_reconstruct_abstract(raw.get("abstract_inverted_index")),
        sources=["openalex"],
    )


def deduplicate_nodes(nodes: list[PaperNode], *, year_min: int = 0) -> list[PaperNode]:
    """Merge duplicate PaperNodes across providers by arXiv ID -> DOI -> normalized title."""
    merged: list[PaperNode] = []
    by_arxiv: dict[str, int] = {}
    by_doi: dict[str, int] = {}
    by_title: dict[str, int] = {}

    for node in nodes:
        if year_min > 0 and node.year and node.year < year_min:
            continue
        idx: int | None = None
        ak = node.arxiv_id.lower()
        dk = node.doi.lower()
        tk = _norm_title(node.title)
        if ak and ak in by_arxiv:
            idx = by_arxiv[ak]
        elif dk and dk in by_doi:
            idx = by_doi[dk]
        elif tk and tk in by_title:
            idx = by_title[tk]

        if idx is None:
            idx = len(merged)
            merged.append(node)
        else:
            cur = merged[idx]
            cur.year = cur.year or node.year
            cur.venue = cur.venue or node.venue
            cur.citation_count = max(cur.citation_count, node.citation_count)
            cur.arxiv_id = cur.arxiv_id or node.arxiv_id
            cur.doi = cur.doi or node.doi
            cur.s2_id = cur.s2_id or node.s2_id
            cur.openalex_id = cur.openalex_id or node.openalex_id
            cur.url = cur.url or node.url
            cur.authors = cur.authors or node.authors
            if len(node.abstract) > len(cur.abstract):
                cur.abstract = node.abstract
            for s in node.sources:
                if s not in cur.sources:
                    cur.sources.append(s)

        if merged[idx].arxiv_id:
            by_arxiv[merged[idx].arxiv_id.lower()] = idx
        if merged[idx].doi:
            by_doi[merged[idx].doi.lower()] = idx
        if tk:
            by_title[tk] = idx

    return merged


def _fetch_s2_graph(
    kind: str,
    value: str,
    *,
    direction: str,
    limit: int,
    api_key: str,
    fetcher: JsonFetcher,
) -> tuple[PaperNode | None, list[PaperNode], list[PaperNode], list[str]]:
    headers = {"x-api-key": api_key} if api_key else {}
    warnings: list[str] = []
    if kind == "title":
        q = urllib.parse.urlencode({"query": value, "limit": 1, "fields": S2_FIELDS})
        search_data = fetcher(f"{S2_BASE}/paper/search?{q}", headers)
        rows = search_data.get("data") or []
        if not rows:
            return None, [], [], ["Semantic Scholar: no paper matched title query"]
        seed_raw = rows[0]
        s2_key = seed_raw["paperId"]
    else:
        prefix = {"arxiv": "ARXIV:", "doi": "DOI:", "s2": ""}[kind]
        s2_key = urllib.parse.quote(f"{prefix}{value}", safe=":")
        seed_raw = fetcher(f"{S2_BASE}/paper/{s2_key}?fields={S2_FIELDS}", headers)

    seed = _node_from_s2(seed_raw)
    if seed is None:
        return None, [], [], ["Semantic Scholar: malformed seed paper payload"]

    refs: list[PaperNode] = []
    cites: list[PaperNode] = []
    paper_id = urllib.parse.quote(seed.s2_id or s2_key, safe=":")

    for edge_dir, target, field_key in (
        ("references", refs, "citedPaper"),
        ("citations", cites, "citingPaper"),
    ):
        if direction not in {"both", edge_dir}:
            continue
        try:
            params = urllib.parse.urlencode({"fields": S2_FIELDS, "limit": min(limit, 100)})
            data = fetcher(f"{S2_BASE}/paper/{paper_id}/{edge_dir}?{params}", headers)
            for item in data.get("data") or []:
                if isinstance(item, dict) and isinstance(item.get(field_key), dict):
                    node = _node_from_s2(item[field_key])
                    if node is not None:
                        target.append(node)
        except Exception as exc:
            warnings.append(f"Semantic Scholar {edge_dir} failed: {exc}")

    return seed, refs, cites, warnings


def _oa_url(path: str, params: dict[str, Any], email: str) -> str:
    p = dict(params)
    if email:
        p["mailto"] = email
    return f"{OA_BASE}{path}?{urllib.parse.urlencode(p)}"


def _fetch_openalex_graph(
    kind: str,
    value: str,
    *,
    direction: str,
    limit: int,
    email: str,
    fetcher: JsonFetcher,
) -> tuple[PaperNode | None, list[PaperNode], list[PaperNode], list[str]]:
    warnings: list[str] = []
    seed_raw: dict[str, Any] | None = None
    if kind == "arxiv":
        doi_url = f"https://doi.org/10.48550/arXiv.{value}"
        try:
            seed_raw = fetcher(_oa_url(f"/works/{urllib.parse.quote(doi_url, safe=':/')}", {}, email), {})
        except Exception:
            data = fetcher(_oa_url("/works", {"search": value, "per-page": 3}, email), {})
            results = data.get("results") or []
            seed_raw = results[0] if results else None
    elif kind == "doi":
        doi_url = f"https://doi.org/{value}"
        seed_raw = fetcher(_oa_url(f"/works/{urllib.parse.quote(doi_url, safe=':/')}", {}, email), {})
    else:
        data = fetcher(_oa_url("/works", {"search": value, "per-page": 1}, email), {})
        results = data.get("results") or []
        seed_raw = results[0] if results else None

    if not seed_raw:
        return None, [], [], ["OpenAlex: seed paper not found"]
    seed = _node_from_openalex(seed_raw)
    if seed is None or not seed.openalex_id:
        return None, [], [], ["OpenAlex: invalid seed record"]

    work_short_id = seed.openalex_id.rsplit("/", 1)[-1]
    refs: list[PaperNode] = []
    cites: list[PaperNode] = []

    if direction in {"both", "references"}:
        ref_ids = [
            str(r).rsplit("/", 1)[-1]
            for r in (seed_raw.get("referenced_works") or [])[:limit]
            if isinstance(r, str) and r.strip()
        ]
        if ref_ids:
            try:
                batch = "|".join(ref_ids[:50])
                ref_data = fetcher(
                    _oa_url("/works", {"filter": f"openalex:{batch}", "per-page": min(limit, 50)}, email),
                    {},
                )
                for row in ref_data.get("results") or []:
                    node = _node_from_openalex(row)
                    if node is not None:
                        refs.append(node)
            except Exception as exc:
                warnings.append(f"OpenAlex references failed: {exc}")

    if direction in {"both", "citations"}:
        # Dual-bucket citation query: recent-first + influential-first so 0-citation new papers are never buried.
        per_bucket = max(10, (limit + 1) // 2)
        for sort_rule in ("publication_year:desc", "cited_by_count:desc"):
            try:
                cite_data = fetcher(
                    _oa_url(
                        "/works",
                        {"filter": f"cites:{work_short_id}", "sort": sort_rule, "per-page": min(per_bucket, 50)},
                        email,
                    ),
                    {},
                )
                for row in cite_data.get("results") or []:
                    node = _node_from_openalex(row)
                    if node is not None:
                        cites.append(node)
            except Exception as exc:
                warnings.append(f"OpenAlex citations ({sort_rule}) failed: {exc}")

    return seed, refs, cites, warnings


def _select_balanced_citations(cites: list[PaperNode], limit: int) -> list[PaperNode]:
    """Select half high-impact milestones (B) and half latest frontier papers (C) to preserve A->B->C lineage."""
    if len(cites) <= limit:
        return sorted(cites, key=lambda n: (n.year, n.citation_count), reverse=True)
    half = max(1, limit // 2)
    by_impact = sorted(cites, key=lambda n: (n.citation_count, n.year), reverse=True)
    by_recent = sorted(cites, key=lambda n: (n.year, n.citation_count), reverse=True)
    picked: list[PaperNode] = []
    seen: set[int] = set()
    for bucket, quota in ((by_impact, half), (by_recent, limit)):
        for node in bucket:
            if len(picked) >= quota:
                break
            if id(node) not in seen:
                seen.add(id(node))
                picked.append(node)
    picked.sort(key=lambda n: (n.year, n.citation_count), reverse=True)
    return picked


def build_citation_graph(
    identifier: str,
    *,
    is_title: bool = False,
    direction: str = "both",
    limit: int = 40,
    year_min: int = 0,
    s2_api_key: str = "",
    openalex_email: str = "",
    fetcher: JsonFetcher | None = None,
) -> dict[str, Any]:
    """Query S2 and OpenAlex, deduplicate, and return structured citation graph."""
    if fetcher is None:
        fetcher = default_http_json
    kind, value = ("title", identifier.strip()) if is_title else parse_identifier(identifier)
    warnings: list[str] = []
    seeds: list[PaperNode] = []
    raw_refs: list[PaperNode] = []
    raw_cites: list[PaperNode] = []

    try:
        s2_seed, s2_refs, s2_cites, s2_warn = _fetch_s2_graph(
            kind, value, direction=direction, limit=limit, api_key=s2_api_key, fetcher=fetcher
        )
        warnings.extend(s2_warn)
        if s2_seed:
            seeds.append(s2_seed)
        raw_refs.extend(s2_refs)
        raw_cites.extend(s2_cites)
    except Exception as exc:
        warnings.append(f"Semantic Scholar unavailable: {exc}")

    # Always supplement with OpenAlex when S2 missed edges or had warnings, or when key is absent
    need_oa = (
        not seeds
        or bool(warnings)
        or (direction in {"both", "references"} and not raw_refs)
        or (direction in {"both", "citations"} and len(raw_cites) < limit // 2)
    )
    if need_oa:
        oa_kind, oa_val = (
            ("arxiv", seeds[0].arxiv_id)
            if seeds and seeds[0].arxiv_id
            else (("doi", seeds[0].doi) if seeds and seeds[0].doi else (kind, value))
        )
        try:
            oa_seed, oa_refs, oa_cites, oa_warn = _fetch_openalex_graph(
                oa_kind, oa_val, direction=direction, limit=limit, email=openalex_email, fetcher=fetcher
            )
            warnings.extend(oa_warn)
            if oa_seed:
                seeds.append(oa_seed)
            raw_refs.extend(oa_refs)
            raw_cites.extend(oa_cites)
        except Exception as exc:
            warnings.append(f"OpenAlex unavailable: {exc}")

    if not seeds:
        raise RuntimeError(f"Could not resolve seed paper {identifier!r}. Warnings: {'; '.join(warnings)}")

    merged_seed = deduplicate_nodes(seeds)[0]
    refs = deduplicate_nodes(raw_refs, year_min=year_min)
    cites = deduplicate_nodes(raw_cites, year_min=year_min)

    refs.sort(key=lambda n: (n.year, n.citation_count), reverse=True)
    selected_refs = refs[:limit]
    selected_cites = _select_balanced_citations(cites, limit)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query": {"input": identifier, "kind": kind, "normalized": value, "direction": direction, "year_min": year_min},
        "seed": asdict(merged_seed),
        "references": [asdict(n) for n in selected_refs],
        "citations": [asdict(n) for n in selected_cites],
        "counts": {"references": len(selected_refs), "citations": len(selected_cites)},
        "warnings": warnings,
    }


def render_markdown(graph: dict[str, Any], *, with_abstracts: bool = False) -> str:
    seed = graph["seed"]
    authors = ", ".join(seed.get("authors") or []) or "Unknown"
    lines = [
        f"# Citation Graph — {seed['title']}",
        "",
        f"- **Seed ID**: `{seed.get('arxiv_id') or seed.get('doi') or seed.get('s2_id')}`",
        f"- **Authors / Year / Venue**: {authors} ({seed.get('year') or '?'}, {seed.get('venue') or 'n/a'})",
        f"- **Total Citations Reported**: {seed.get('citation_count', 0)}",
        f"- **Retrieved**: {graph['counts']['references']} references, {graph['counts']['citations']} citing papers",
    ]
    if graph.get("warnings"):
        lines.append(f"- **Provider Diagnostics**: {'; '.join(graph['warnings'])}")
    lines.append("")

    for section_key, heading in (
        ("citations", "## Forward Citations (Who Followed / Improved / Challenged This Work)"),
        ("references", "## Backward References (Prior Work This Paper Builds Upon)"),
    ):
        items = graph.get(section_key) or []
        if not items and graph["query"]["direction"] not in {"both", section_key}:
            continue
        lines.append(heading)
        lines.append("")
        if not items:
            lines.append("_No records returned within current filter/provider coverage._")
            lines.append("")
            continue
        for idx, item in enumerate(items, 1):
            ident = (
                f"arXiv:{item['arxiv_id']}"
                if item.get("arxiv_id")
                else (f"DOI:{item['doi']}" if item.get("doi") else item.get("url", ""))
            )
            venue_str = f", {item['venue']}" if item.get("venue") else ""
            lines.append(
                f"{idx}. **[{item.get('year') or '?'}]** {item['title']} "
                f"(`{ident}`{venue_str}, cites={item.get('citation_count', 0)})"
            )
            if with_abstracts and item.get("abstract"):
                snippet = " ".join(str(item["abstract"]).split())[:360]
                lines.append(f"   - Abstract: {snippet}...")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch bidirectional citation graph (S2 + OpenAlex).")
    parser.add_argument("identifier", nargs="?", default="", help="arXiv ID/URL, DOI, or S2 Paper ID")
    parser.add_argument("--title", default="", help="Resolve seed paper by exact/approximate title")
    parser.add_argument("--direction", choices=("both", "references", "citations"), default="both")
    parser.add_argument("--limit", type=int, default=40, help="Max papers per direction (default: 40)")
    parser.add_argument("--year-min", type=int, default=0, help="Minimum publication year filter")
    parser.add_argument("--with-abstracts", action="store_true", help="Include abstract snippets in Markdown")
    parser.add_argument("--out", default="", help="Write Markdown report to file path")
    parser.add_argument("--json-out", default="", help="Write structured JSON payload to file path")
    args = parser.parse_args(argv)

    target = args.title.strip() or args.identifier.strip()
    if not target:
        parser.error("Provide a positional paper identifier or --title '<paper title>'")

    s2_key = os.environ.get("S2_API_KEY", "").strip()
    oa_email = os.environ.get("OPENALEX_EMAIL", "").strip()

    graph = build_citation_graph(
        target,
        is_title=bool(args.title.strip()),
        direction=args.direction,
        limit=max(1, args.limit),
        year_min=max(0, args.year_min),
        s2_api_key=s2_key,
        openalex_email=oa_email,
    )
    md = render_markdown(graph, with_abstracts=args.with_abstracts)

    if args.json_out:
        json_path = Path(args.json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(graph, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
    else:
        sys.stdout.write(md)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
