#!/usr/bin/env python3
"""Resilient literature graph & discovery CLI (Semantic Scholar + OpenAlex + arXiv + Local .bib Radar).

Capabilities:
1. Bidirectional Citation Graph (default): S2 + OpenAlex dual-provider merge with 3-tier temporal
   balancing (latest frontier C + mid-horizon venue backbone B_recent + foundational milestones B_early)
   and strict `--before-date` cutoff enforcement.
2. Local 2-Hop Co-Citation Radar (`--scan-bib <workspace>`): Zero-API scan across downloaded
   `papers/*/source/*.bib` files to surface frequently co-cited external papers missed in Stage 1-2.
3. Zero-Lag arXiv Preprint Stream (`--arxiv-recent "<query>"`): Direct `export.arxiv.org` query sorted
   by submission date to catch 24-72h preprints before web/citation indexers ingest them.

Zero third-party dependencies (Python 3.10+ standard library only).
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
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
import xml.etree.ElementTree as ET

USER_AGENT = "ResearchFlow/0.2 (Academic Research Workspace Protocol)"
S2_BASE = "https://api.semanticscholar.org/graph/v1"
OA_BASE = "https://api.openalex.org"
ARXIV_API_BASE = "http://export.arxiv.org/api/query"
S2_FIELDS = "paperId,title,year,publicationDate,venue,citationCount,externalIds,url,abstract,authors"

_ARXIV_NEW_RE = re.compile(r"(?:arxiv[:/]|abs/|pdf/)?(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?$", re.I)
_ARXIV_OLD_RE = re.compile(r"(?:arxiv[:/]|abs/|pdf/)?([a-z-]+/\d{7})(?:v\d+)?(?:\.pdf)?$", re.I)
_ARXIV_ANYWHERE_RE = re.compile(r"(?:arxiv\s*[:/]\s*|abs/|10\.48550/arxiv\.)(\d{4}\.\d{4,5}|[a-z-]+/\d{7})", re.I)
_ARXIV_BARE_ID_RE = re.compile(r"\b(\d{4}\.\d{4,5})(?:v\d+)?\b")
_DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"{}<>]+)", re.I)
_S2_HEX_RE = re.compile(r"^[0-9a-f]{40}$", re.I)

JsonFetcher = Callable[[str, dict[str, str]], dict[str, Any]]
TextFetcher = Callable[[str, dict[str, str]], str]


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
    published_date: str = ""
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
    """Fetch JSON over HTTP(S) with explicit retry on HTTP 429 / 5xx."""
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


def default_http_text(url: str, headers: dict[str, str], retries: int = 2) -> str:
    """Fetch XML/text over HTTP(S) with explicit retry on HTTP 429 / 5xx."""
    req_headers = {"User-Agent": USER_AGENT, **headers}
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            last_err = exc
            if exc.code in {429, 502, 503, 504} and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {exc.code} for {url}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
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
        published_date=str(raw.get("publicationDate") or "").strip()[:10],
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
        published_date=str(raw.get("publication_date") or "").strip()[:10],
        sources=["openalex"],
    )


def _arxiv_date_floor(arxiv_id: str) -> str:
    """Infer 'YYYY-MM-01' lower-bound date from modern YYMM.NNNNN arXiv IDs when exact date is absent."""
    m = re.match(r"^(\d{2})(\d{2})\.\d{4,5}", arxiv_id.strip())
    if not m:
        return ""
    yy, mm = int(m.group(1)), int(m.group(2))
    if 1 <= mm <= 12:
        year = 2000 + yy if yy < 90 else 1900 + yy
        return f"{year:04d}-{mm:02d}-01"
    return ""


def _is_on_or_after_cutoff(node: PaperNode, *, year_max: int, before_date: str) -> bool:
    if year_max > 0 and node.year and node.year > year_max:
        return True
    if before_date:
        cutoff_year = int(before_date[:4])
        if node.year and node.year > cutoff_year:
            return True
        if node.published_date and node.published_date >= before_date:
            return True
        inferred = _arxiv_date_floor(node.arxiv_id)
        if inferred and inferred >= before_date[:7] + "-01" and (
            inferred[:7] > before_date[:7] or before_date.endswith("-01")
        ):
            return True
    return False


def deduplicate_nodes(
    nodes: list[PaperNode],
    *,
    year_min: int = 0,
    year_max: int = 0,
    before_date: str = "",
) -> list[PaperNode]:
    """Merge duplicate PaperNodes across providers by arXiv ID -> DOI -> normalized title."""
    merged: list[PaperNode] = []
    by_arxiv: dict[str, int] = {}
    by_doi: dict[str, int] = {}
    by_title: dict[str, int] = {}

    for node in nodes:
        if year_min > 0 and node.year and node.year < year_min:
            continue
        if _is_on_or_after_cutoff(node, year_max=year_max, before_date=before_date):
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
            cur.published_date = cur.published_date or node.published_date
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
            # Request up to 100 from S2 so temporal cutoff filtering does not starve valid citations.
            params = urllib.parse.urlencode({"fields": S2_FIELDS, "limit": min(max(limit * 2, 60), 100)})
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
    year_max: int = 0,
    before_date: str = "",
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
            for r in (seed_raw.get("referenced_works") or [])[: max(limit, 50)]
            if isinstance(r, str) and r.strip()
        ]
        for start in range(0, len(ref_ids), 50):
            batch = "|".join(ref_ids[start : start + 50])
            if not batch:
                continue
            try:
                ref_data = fetcher(
                    _oa_url("/works", {"filter": f"openalex:{batch}", "per-page": 50}, email),
                    {},
                )
                for row in ref_data.get("results") or []:
                    node = _node_from_openalex(row)
                    if node is not None:
                        refs.append(node)
            except Exception as exc:
                warnings.append(f"OpenAlex references failed: {exc}")
                break

    if direction in {"both", "citations"}:
        # Three-tier citation retrieval prevents year-bucket starvation:
        # (1) Latest frontier by exact publication_date:desc (captures 0-citation preprints C)
        # (2) Mid-horizon venue backbone (anchor_year-2 .. anchor_year-1) by cited_by_count:desc
        # (3) All-time high-impact milestones by cited_by_count:desc
        anchor_year = (
            int(before_date[:4])
            if before_date
            else (year_max if year_max > 0 else datetime.now(timezone.utc).year)
        )
        per_bucket = max(12, (limit + 1) // 2)
        base_filter = f"cites:{work_short_id}"
        if before_date:
            base_filter += f",to_publication_date:{before_date}"
        elif year_max > 0:
            base_filter += f",to_publication_date:{year_max:04d}-12-31"

        mid_end = f"{anchor_year - 1:04d}-12-31"
        if before_date and before_date < mid_end:
            mid_end = before_date
        mid_filter = (
            f"cites:{work_short_id},"
            f"from_publication_date:{anchor_year - 2:04d}-01-01,"
            f"to_publication_date:{mid_end}"
        )

        queries = [
            ("latest", base_filter, "publication_date:desc"),
            ("mid_horizon", mid_filter, "cited_by_count:desc"),
            ("high_impact", base_filter, "cited_by_count:desc"),
        ]
        for label, q_filter, sort_rule in queries:
            try:
                cite_data = fetcher(
                    _oa_url(
                        "/works",
                        {"filter": q_filter, "sort": sort_rule, "per-page": min(per_bucket, 50)},
                        email,
                    ),
                    {},
                )
                for row in cite_data.get("results") or []:
                    node = _node_from_openalex(row)
                    if node is not None:
                        cites.append(node)
            except Exception as exc:
                warnings.append(f"OpenAlex citations ({label}) failed: {exc}")

    return seed, refs, cites, warnings


def _effective_date_key(node: PaperNode) -> str:
    if node.published_date:
        return node.published_date
    floor = _arxiv_date_floor(node.arxiv_id)
    if floor:
        return floor
    if node.year:
        return f"{node.year:04d}-00-00"
    return "0000-00-00"


def _select_balanced_citations(cites: list[PaperNode], limit: int) -> list[PaperNode]:
    """3-tier balanced selection: latest frontier (40%) + mid-horizon backbone (30%) + all-time impact (30%)."""
    if len(cites) <= limit:
        return sorted(cites, key=lambda n: (n.year, _effective_date_key(n), n.citation_count), reverse=True)

    valid_years = [n.year for n in cites if n.year > 0]
    frontier_year = max(valid_years) if valid_years else datetime.now(timezone.utc).year

    q_recent = max(1, int(round(limit * 0.4)))
    q_mid = max(1, int(round(limit * 0.3)))

    by_recent = sorted(cites, key=lambda n: (_effective_date_key(n), n.year, n.citation_count), reverse=True)
    mid_pool = [n for n in cites if frontier_year - 2 <= n.year <= frontier_year - 1]
    by_mid = sorted(mid_pool, key=lambda n: (n.citation_count, _effective_date_key(n)), reverse=True)
    by_impact = sorted(cites, key=lambda n: (n.citation_count, n.year), reverse=True)

    picked: list[PaperNode] = []
    seen: set[int] = set()
    for bucket, target_total in (
        (by_recent, q_recent),
        (by_mid, min(limit, q_recent + q_mid)),
        (by_impact, limit),
        (by_recent, limit),
    ):
        for node in bucket:
            if len(picked) >= target_total:
                break
            if id(node) not in seen:
                seen.add(id(node))
                picked.append(node)

    picked.sort(key=lambda n: (n.year, _effective_date_key(n), n.citation_count), reverse=True)
    return picked


def build_citation_graph(
    identifier: str,
    *,
    is_title: bool = False,
    direction: str = "both",
    limit: int = 40,
    year_min: int = 0,
    year_max: int = 0,
    before_date: str = "",
    s2_api_key: str = "",
    openalex_email: str = "",
    fetcher: JsonFetcher | None = None,
) -> dict[str, Any]:
    """Query S2 + OpenAlex Dual-Provider Graph, deduplicate after cutoff filtering, and balance 3 tiers."""
    if before_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", before_date):
        raise ValueError(f"--before-date must use YYYY-MM-DD format, got {before_date!r}")
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

    # Filter S2 results BEFORE deciding coverage, and always query OpenAlex to prevent S2 single-page
    # recency truncation or year-bucket starvation from hiding mid-horizon venue papers.
    oa_kind, oa_val = (
        ("arxiv", seeds[0].arxiv_id)
        if seeds and seeds[0].arxiv_id
        else (("doi", seeds[0].doi) if seeds and seeds[0].doi else (kind, value))
    )
    try:
        oa_seed, oa_refs, oa_cites, oa_warn = _fetch_openalex_graph(
            oa_kind,
            oa_val,
            direction=direction,
            limit=limit,
            email=openalex_email,
            year_max=year_max,
            before_date=before_date,
            fetcher=fetcher,
        )
        if not seeds:
            warnings.extend(oa_warn)
        else:
            # Only surface OpenAlex warnings when S2 also had issues or missed edges
            for w in oa_warn:
                if "seed paper not found" not in w:
                    warnings.append(w)
        if oa_seed:
            seeds.append(oa_seed)
        raw_refs.extend(oa_refs)
        raw_cites.extend(oa_cites)
    except Exception as exc:
        warnings.append(f"OpenAlex unavailable: {exc}")

    if not seeds:
        raise RuntimeError(f"Could not resolve seed paper {identifier!r}. Warnings: {'; '.join(warnings)}")

    merged_seed = deduplicate_nodes(seeds)[0]
    refs = deduplicate_nodes(raw_refs, year_min=year_min, year_max=year_max, before_date=before_date)
    cites = deduplicate_nodes(raw_cites, year_min=year_min, year_max=year_max, before_date=before_date)

    refs.sort(key=lambda n: (n.year, n.citation_count), reverse=True)
    selected_refs = refs[:limit]
    selected_cites = _select_balanced_citations(cites, limit)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query": {
            "input": identifier,
            "kind": kind,
            "normalized": value,
            "direction": direction,
            "year_min": year_min,
            "year_max": year_max,
            "before_date": before_date,
        },
        "seed": asdict(merged_seed),
        "references": [asdict(n) for n in selected_refs],
        "citations": [asdict(n) for n in selected_cites],
        "counts": {"references": len(selected_refs), "citations": len(selected_cites)},
        "warnings": warnings,
    }


def _clean_latex_text(raw: str) -> str:
    text = raw.replace("\n", " ").replace("\r", " ")
    text = re.sub(r"\\[a-zA-Z]+\s*\{([^}]*)\}", r"\1", text)
    text = text.replace("{", "").replace("}", "").replace("\\&", "&")
    return " ".join(text.split()).strip(" ,.")


def _iter_bibtex_entries(content: str) -> list[tuple[str, str]]:
    """Extract (cite_key, body) pairs from a .bib file using balanced brace counting."""
    entries: list[tuple[str, str]] = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s{}]+)\s*,", content):
        kind = m.group(1).lower()
        if kind in {"comment", "preamble", "string"}:
            continue
        cite_key = m.group(2).strip()
        pos = m.end()
        depth = 1
        n = len(content)
        while pos < n and depth > 0:
            ch = content[pos]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            pos += 1
        entries.append((cite_key, content[m.end() : max(m.end(), pos - 1)]))
    return entries


def _parse_bibtex_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    i = 0
    n = len(body)
    while i < n:
        m = re.search(r"([a-zA-Z_][a-zA-Z0-9_-]*)\s*=\s*", body[i:])
        if not m:
            break
        fname = m.group(1).lower()
        i += m.end()
        if i >= n:
            break
        if body[i] == "{":
            depth = 1
            start = i + 1
            i += 1
            while i < n and depth > 0:
                if body[i] == "{":
                    depth += 1
                elif body[i] == "}":
                    depth -= 1
                i += 1
            fields[fname] = body[start : max(start, i - 1)]
        elif body[i] == '"':
            start = i + 1
            i += 1
            while i < n and (body[i] != '"' or body[i - 1] == "\\"):
                i += 1
            fields[fname] = body[start:i]
            i += 1
        else:
            start = i
            while i < n and body[i] not in ",\n\r":
                i += 1
            fields[fname] = body[start:i].strip()
    return fields


def scan_local_bibliographies(
    workspace_or_papers: str | Path,
    *,
    limit: int = 30,
    keyword: str = "",
    year_min: int = 0,
    year_max: int = 0,
    before_date: str = "",
) -> dict[str, Any]:
    """Scan local `papers/*/source/**/*.bib` files to rank unarchived 2-hop co-cited papers."""
    if before_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", before_date):
        raise ValueError(f"--before-date must use YYYY-MM-DD format, got {before_date!r}")

    base = Path(workspace_or_papers)
    papers_dir = base / "papers" if (base / "papers").is_dir() else base
    if not papers_dir.is_dir():
        raise FileNotFoundError(f"Papers directory not found: {papers_dir}")

    archived_arxiv: set[str] = set()
    archived_doi: set[str] = set()
    archived_titles: set[str] = set()

    for slug_dir in sorted(papers_dir.iterdir()):
        if not slug_dir.is_dir():
            continue
        meta_path = slug_dir / "metadata.json"
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                aid = str(meta.get("arxiv_id") or "").strip().lower()
                aid = re.sub(r"v\d+$", "", aid)
                if aid:
                    archived_arxiv.add(aid)
                doi = str(meta.get("doi") or "").strip().lower()
                if doi:
                    archived_doi.add(doi)
                nt = _norm_title(str(meta.get("title") or ""))
                if nt:
                    archived_titles.add(nt)
            except Exception:
                pass

    kw_re = re.compile(keyword, re.I) if keyword.strip() else None
    candidates: list[dict[str, Any]] = []
    by_arxiv: dict[str, int] = {}
    by_doi: dict[str, int] = {}
    by_title: dict[str, int] = {}
    bib_files_scanned = 0

    for slug_dir in sorted(papers_dir.iterdir()):
        src_dir = slug_dir / "source"
        if not src_dir.is_dir():
            continue
        slug = slug_dir.name
        for bib_path in sorted(src_dir.rglob("*.bib")):
            bib_files_scanned += 1
            raw_text = bib_path.read_text(encoding="utf-8", errors="replace")
            for cite_key, body in _iter_bibtex_entries(raw_text):
                fields = _parse_bibtex_fields(body)
                title = _clean_latex_text(fields.get("title", ""))
                if len(title) < 8:
                    continue
                nt = _norm_title(title)
                if not nt:
                    continue

                arxiv_id = ""
                eprint = fields.get("eprint", "").strip()
                if eprint:
                    m_ep = _ARXIV_NEW_RE.search(eprint) or _ARXIV_OLD_RE.search(eprint)
                    if m_ep:
                        arxiv_id = m_ep.group(1)
                if not arxiv_id:
                    m_any = _ARXIV_ANYWHERE_RE.search(body)
                    if m_any:
                        arxiv_id = m_any.group(1)

                doi = ""
                if fields.get("doi"):
                    dm = _DOI_RE.search(fields["doi"])
                    if dm:
                        doi = re.sub(r"^https?://doi\.org/", "", dm.group(1), flags=re.I).rstrip(".,;)")

                year = 0
                ym = re.search(r"\b(19\d{2}|20\d{2})\b", fields.get("year", ""))
                if ym:
                    year = int(ym.group(1))
                elif arxiv_id:
                    floor = _arxiv_date_floor(arxiv_id)
                    if floor:
                        year = int(floor[:4])

                venue = _clean_latex_text(
                    fields.get("booktitle") or fields.get("journal") or fields.get("howpublished") or ""
                )

                # Skip papers already unpacked in local `papers/`
                if (
                    (arxiv_id and arxiv_id.lower() in archived_arxiv)
                    or (doi and doi.lower() in archived_doi)
                    or (nt in archived_titles)
                ):
                    continue

                probe_node = PaperNode(title=title, year=year, venue=venue, arxiv_id=arxiv_id, doi=doi)
                if year_min > 0 and year and year < year_min:
                    continue
                if _is_on_or_after_cutoff(probe_node, year_max=year_max, before_date=before_date):
                    continue
                if kw_re and not kw_re.search(f"{title} {venue} {cite_key}"):
                    continue

                idx: int | None = None
                ak = arxiv_id.lower()
                dk = doi.lower()
                if ak and ak in by_arxiv:
                    idx = by_arxiv[ak]
                elif dk and dk in by_doi:
                    idx = by_doi[dk]
                elif nt in by_title:
                    idx = by_title[nt]

                if idx is None:
                    idx = len(candidates)
                    candidates.append(
                        {
                            "title": title,
                            "year": year,
                            "venue": venue,
                            "arxiv_id": arxiv_id,
                            "doi": doi,
                            "cited_by_local": [slug],
                            "cite_keys": [cite_key],
                        }
                    )
                else:
                    rec = candidates[idx]
                    rec["year"] = rec["year"] or year
                    rec["venue"] = rec["venue"] or venue
                    rec["arxiv_id"] = rec["arxiv_id"] or arxiv_id
                    rec["doi"] = rec["doi"] or doi
                    if slug not in rec["cited_by_local"]:
                        rec["cited_by_local"].append(slug)
                    if cite_key not in rec["cite_keys"] and len(rec["cite_keys"]) < 5:
                        rec["cite_keys"].append(cite_key)

                if candidates[idx]["arxiv_id"]:
                    by_arxiv[candidates[idx]["arxiv_id"].lower()] = idx
                if candidates[idx]["doi"]:
                    by_doi[candidates[idx]["doi"].lower()] = idx
                by_title[nt] = idx

    for rec in candidates:
        rec["co_citation_count"] = len(rec["cited_by_local"])

    candidates.sort(
        key=lambda r: (r["co_citation_count"], r["year"], 1 if r["arxiv_id"] else 0),
        reverse=True,
    )
    top = candidates[: max(1, limit)]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "scan_bib",
        "papers_dir": str(papers_dir),
        "bib_files_scanned": bib_files_scanned,
        "archived_papers_excluded": max(len(archived_titles), len(archived_arxiv)),
        "keyword": keyword,
        "before_date": before_date,
        "total_unarchived_candidates": len(candidates),
        "results": top,
    }


def render_bib_scan_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Local 2-Hop Co-Citation Radar (`--scan-bib`)",
        "",
        f"- **Scanned Directory**: `{payload['papers_dir']}` ({payload['bib_files_scanned']} `.bib` files)",
        f"- **Already Archived Papers Excluded**: {payload['archived_papers_excluded']}",
        f"- **Unarchived Candidates Found**: {payload['total_unarchived_candidates']}",
    ]
    if payload.get("keyword"):
        lines.append(f"- **Keyword Filter**: `{payload['keyword']}`")
    if payload.get("before_date"):
        lines.append(f"- **Strict Cutoff**: `< {payload['before_date']}`")
    lines.append("")
    lines.append("## Top Co-Cited Unarchived Papers (Inspect Before Finalizing Map / Idea)")
    lines.append("")
    results = payload.get("results") or []
    if not results:
        lines.append("_No unarchived bibliography entries matched the current filters._")
        lines.append("")
        return "\n".join(lines)

    for idx, r in enumerate(results, 1):
        ident = (
            f"arXiv:{r['arxiv_id']}"
            if r.get("arxiv_id")
            else (f"DOI:{r['doi']}" if r.get("doi") else "no-id")
        )
        venue = f", {r['venue']}" if r.get("venue") else ""
        local_srcs = ", ".join(r["cited_by_local"])
        lines.append(
            f"{idx}. **[co-cited={r['co_citation_count']} | {r.get('year') or '?'}]** "
            f"{r['title']} (`{ident}`{venue}) — cited in: `{local_srcs}`"
        )
    lines.append("")
    return "\n".join(lines)


def query_arxiv_recent(
    query: str,
    *,
    categories: str = "",
    days: int = 30,
    limit: int = 30,
    before_date: str = "",
    text_fetcher: TextFetcher | None = None,
) -> dict[str, Any]:
    """Query `export.arxiv.org` directly sorted by submittedDate descending to avoid indexing lag."""
    if not query.strip():
        raise ValueError("--arxiv-recent requires a non-empty search query")
    if before_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", before_date):
        raise ValueError(f"--before-date must use YYYY-MM-DD format, got {before_date!r}")
    if text_fetcher is None:
        text_fetcher = default_http_text

    q_expr = query.strip()
    if not any(tok in q_expr for tok in ("all:", "ti:", "abs:", "cat:", "au:")):
        # Treat whitespace terms/phrases cleanly as an all-fields query
        q_expr = f"({q_expr})"

    cats = [c.strip() for c in categories.split(",") if c.strip()]
    if cats:
        cat_clause = " OR ".join(f"cat:{c}" for c in cats)
        q_expr = f"({q_expr}) AND ({cat_clause})"

    if days > 0:
        if before_date:
            end_dt = datetime.strptime(before_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) - timedelta(days=1)
        else:
            end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=max(1, days))
        date_clause = f"submittedDate:[{start_dt:%Y%m%d}0000 TO {end_dt:%Y%m%d}2359]"
        q_expr = f"({q_expr}) AND {date_clause}"

    params = urllib.parse.urlencode(
        {
            "search_query": q_expr,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": min(max(limit * 2, 30), 100),
        }
    )
    xml_text = text_fetcher(f"{ARXIV_API_BASE}?{params}", {})
    root = ET.fromstring(xml_text)
    ns = {"a": "http://www.w3.org/2005/Atom"}

    nodes: list[PaperNode] = []
    for entry in root.findall("a:entry", ns):
        raw_id = (entry.findtext("a:id", "", ns) or "").strip()
        if "/abs/" not in raw_id:
            continue
        aid_ver = raw_id.rsplit("/abs/", 1)[-1]
        aid = re.sub(r"v\d+$", "", aid_ver)
        title = " ".join((entry.findtext("a:title", "", ns) or "").split())
        if not title:
            continue
        pub = (entry.findtext("a:published", "", ns) or "").strip()[:10]
        year = int(pub[:4]) if len(pub) >= 4 and pub[:4].isdigit() else 0
        summary = " ".join((entry.findtext("a:summary", "", ns) or "").split())
        authors = [
            " ".join((au.findtext("a:name", "", ns) or "").split())
            for au in entry.findall("a:author", ns)
            if (au.findtext("a:name", "", ns) or "").strip()
        ]
        prim_cat = ""
        for cat_el in entry.findall("a:category", ns):
            term = cat_el.attrib.get("term", "").strip()
            if term:
                prim_cat = term
                break
        nodes.append(
            PaperNode(
                title=title,
                year=year,
                venue=f"arXiv ({prim_cat})" if prim_cat else "arXiv",
                arxiv_id=aid,
                url=f"https://arxiv.org/abs/{aid}",
                authors=authors[:8],
                abstract=summary,
                published_date=pub,
                sources=["arxiv_api"],
            )
        )

    filtered = deduplicate_nodes(nodes, before_date=before_date)[: max(1, limit)]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "arxiv_recent",
        "search_query": q_expr,
        "before_date": before_date,
        "count": len(filtered),
        "results": [asdict(n) for n in filtered],
    }


def render_arxiv_recent_markdown(payload: dict[str, Any], *, with_abstracts: bool = False) -> str:
    lines = [
        "# Direct arXiv Preprint Stream (`--arxiv-recent`)",
        "",
        f"- **Compiled Query**: `{payload['search_query']}`",
        f"- **Returned**: {payload['count']} preprints",
    ]
    if payload.get("before_date"):
        lines.append(f"- **Strict Cutoff**: `< {payload['before_date']}`")
    lines.append("")
    items = payload.get("results") or []
    if not items:
        lines.append("_No arXiv preprints matched within the requested window._")
        lines.append("")
        return "\n".join(lines)

    for idx, item in enumerate(items, 1):
        lines.append(
            f"{idx}. **[{item.get('published_date') or item.get('year') or '?'}]** "
            f"{item['title']} (`arXiv:{item['arxiv_id']}`, {item.get('venue', 'arXiv')})"
        )
        if with_abstracts and item.get("abstract"):
            snippet = " ".join(str(item["abstract"]).split())[:360]
            lines.append(f"   - Abstract: {snippet}...")
    lines.append("")
    return "\n".join(lines)


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
    if graph["query"].get("before_date"):
        lines.append(f"- **Temporal Cutoff**: `< {graph['query']['before_date']}`")
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


def _write_outputs(md: str, payload: dict[str, Any], out: str, json_out: str) -> None:
    if json_out:
        json_path = Path(json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
    else:
        sys.stdout.write(md)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bidirectional citation graph (S2 + OpenAlex), local 2-hop .bib radar, and zero-lag arXiv stream."
    )
    parser.add_argument("identifier", nargs="?", default="", help="arXiv ID/URL, DOI, or S2 Paper ID")
    parser.add_argument("--title", default="", help="Resolve seed paper by exact/approximate title")
    parser.add_argument("--scan-bib", default="", help="Scan workspace/papers .bib files for unarchived co-citations")
    parser.add_argument("--keyword", default="", help="Regex filter for --scan-bib (e.g. 'drift|contract|merge')")
    parser.add_argument("--arxiv-recent", default="", help="Direct arXiv API query sorted by submittedDate descending")
    parser.add_argument("--categories", default="", help="Comma-separated arXiv categories for --arxiv-recent")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days for --arxiv-recent (0 = all time)")
    parser.add_argument("--direction", choices=("both", "references", "citations"), default="both")
    parser.add_argument("--limit", type=int, default=40, help="Max items returned (default: 40)")
    parser.add_argument("--year-min", type=int, default=0, help="Minimum publication year filter")
    parser.add_argument("--year-max", type=int, default=0, help="Maximum publication year filter")
    parser.add_argument("--before-date", default="", help="Strict exclusive cutoff date YYYY-MM-DD for backtesting")
    parser.add_argument("--with-abstracts", action="store_true", help="Include abstract snippets in Markdown")
    parser.add_argument("--out", default="", help="Write Markdown report to file path")
    parser.add_argument("--json-out", default="", help="Write structured JSON payload to file path")
    args = parser.parse_args(argv)

    if args.scan_bib.strip():
        payload = scan_local_bibliographies(
            args.scan_bib.strip(),
            limit=max(1, args.limit),
            keyword=args.keyword.strip(),
            year_min=max(0, args.year_min),
            year_max=max(0, args.year_max),
            before_date=args.before_date.strip(),
        )
        md = render_bib_scan_markdown(payload)
        _write_outputs(md, payload, args.out, args.json_out)
        return 0

    if args.arxiv_recent.strip():
        payload = query_arxiv_recent(
            args.arxiv_recent.strip(),
            categories=args.categories.strip(),
            days=max(0, args.days),
            limit=max(1, args.limit),
            before_date=args.before_date.strip(),
        )
        md = render_arxiv_recent_markdown(payload, with_abstracts=args.with_abstracts)
        _write_outputs(md, payload, args.out, args.json_out)
        return 0

    target = args.title.strip() or args.identifier.strip()
    if not target:
        parser.error(
            "Provide a paper identifier, --title '<paper title>', --scan-bib <workspace>, or --arxiv-recent '<query>'"
        )

    s2_key = os.environ.get("S2_API_KEY", "").strip()
    oa_email = os.environ.get("OPENALEX_EMAIL", "").strip()

    graph = build_citation_graph(
        target,
        is_title=bool(args.title.strip()),
        direction=args.direction,
        limit=max(1, args.limit),
        year_min=max(0, args.year_min),
        year_max=max(0, args.year_max),
        before_date=args.before_date.strip(),
        s2_api_key=s2_key,
        openalex_email=oa_email,
    )
    md = render_markdown(graph, with_abstracts=args.with_abstracts)
    _write_outputs(md, graph, args.out, args.json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
