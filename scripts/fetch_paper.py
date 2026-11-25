#!/usr/bin/env python3
"""Download unmodified paper sources (arXiv e-print / PDF), build index.md, and optionally clone repo.

Preserves `papers/<slug>/source/` 100% untouched as the ground-truth source of truth,
while generating a line-accurate `index.md` for sections, macros, tables, and formal blocks.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import ipaddress
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tarfile
from typing import Any, Callable
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

USER_AGENT = "ResearchFlow/0.1 (Academic Research Workspace Protocol)"
ARXIV_ID_RE = re.compile(r"(?:arxiv[:/]|abs/|pdf/|e-print/)?(\d{4}\.\d{4,5}|[a-z-]+/\d{7})(?:v\d+)?(?:\.pdf)?$", re.I)
INPUT_RE = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")
MACRO_RE = re.compile(r"\\(?:newcommand|renewcommand|providecommand|DeclareMathOperator)\*?\s*\{?\\([A-Za-z@]+)")
SECTION_RE = re.compile(r"\\(section|subsection|subsubsection)\*?\{([^}]*)\}")
APPENDIX_RE = re.compile(r"\\appendix\b")
ENV_BEGIN_RE = re.compile(
    r"\\begin\{(table\*?|wraptable|equation\*?|align\*?|gather\*?|algorithm\*?|theorem|lemma|proposition|assumption|corollary|definition)\}"
)
CAPTION_RE = re.compile(r"\\caption(?:\[[^\]]*\])?\{([^}]*)\}")
LABEL_RE = re.compile(r"\\label\{([^}]+)\}")

BytesDownloader = Callable[[str], bytes]


def validate_public_url(url: str) -> None:
    """Reject non-HTTP(S) schemes and private/loopback/link-local addresses (SSRF guard)."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"Unsupported or invalid URL: {url!r}")
    host = parsed.hostname
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return
    for info in infos:
        ip_obj = ipaddress.ip_address(info[4][0])
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved:
            raise ValueError(f"Blocked non-public address {ip_obj} for host {host!r}")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def default_download(url: str, max_bytes: int = 60 * 1024 * 1024) -> bytes:
    validate_public_url(url)
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with opener.open(req, timeout=30) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"Payload from {url} exceeds {max_bytes} bytes limit")
    return data


def normalize_arxiv_id(raw: str) -> str:
    text = raw.strip()
    parsed = urllib.parse.urlparse(text)
    target = parsed.path.strip("/") if parsed.scheme in {"http", "https"} else text
    m = ARXIV_ID_RE.search(target)
    if not m:
        raise ValueError(f"Invalid arXiv identifier: {raw!r}")
    return m.group(1)


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", text.strip()).strip("_").lower()
    return cleaned[:60] or "paper"


def fetch_arxiv_metadata(arxiv_id: str, downloader: BytesDownloader | None = None) -> dict[str, Any]:
    if downloader is None:
        downloader = default_download
    url = f"https://export.arxiv.org/api/query?id_list={urllib.parse.quote(arxiv_id)}"
    xml_bytes = downloader(url)
    root = ET.fromstring(xml_bytes)
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        return {"arxiv_id": arxiv_id, "title": arxiv_id, "authors": [], "year": 0, "abstract": ""}
    title = " ".join((entry.findtext("atom:title", "", ns) or "").split())
    abstract = " ".join((entry.findtext("atom:summary", "", ns) or "").split())
    published = (entry.findtext("atom:published", "", ns) or "").strip()
    updated = (entry.findtext("atom:updated", "", ns) or "").strip()
    year = int(published[:4]) if len(published) >= 4 and published[:4].isdigit() else 0
    authors = [
        (a.findtext("atom:name", "", ns) or "").strip()
        for a in entry.findall("atom:author", ns)
        if (a.findtext("atom:name", "", ns) or "").strip()
    ]
    doi = (entry.findtext("arxiv:doi", "", ns) or "").strip()
    return {
        "arxiv_id": arxiv_id,
        "title": title or arxiv_id,
        "authors": authors,
        "published": published,
        "updated": updated,
        "year": year,
        "abstract": abstract,
        "doi": doi,
        "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
    }


def _safe_target(root: Path, rel_name: str) -> Path:
    clean = rel_name.lstrip("/\\")
    if not clean or "\x00" in clean:
        raise ValueError(f"Unsafe archive entry name: {rel_name!r}")
    parts = Path(clean).parts
    if any(p in {"..", ""} or ":" in p for p in parts):
        raise ValueError(f"Path traversal blocked in archive entry: {rel_name!r}")
    dest = (root / Path(*parts)).resolve()
    if not dest.is_relative_to(root.resolve()):
        raise ValueError(f"Archive path escapes destination: {rel_name!r}")
    return dest


def unpack_eprint_payload(payload: bytes, source_dir: Path, pdf_fallback_path: Path) -> str:
    """Unpack arXiv e-print bytes into `source_dir` without modifying contents.

    Returns payload kind: 'latex_archive' | 'latex_single' | 'pdf_only'.
    """
    if payload.startswith(b"%PDF-"):
        pdf_fallback_path.write_bytes(payload)
        return "pdf_only"

    source_dir.mkdir(parents=True, exist_ok=True)
    bio = io.BytesIO(payload)
    if tarfile.is_tarfile(bio):
        bio.seek(0)
        with tarfile.open(fileobj=bio, mode="r:*") as tf:
            for member in tf.getmembers():
                if member.isdir():
                    continue
                if member.issym() or member.islnk() or not member.isfile():
                    continue
                dest = _safe_target(source_dir, member.name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                extracted = tf.extractfile(member)
                if extracted is not None:
                    dest.write_bytes(extracted.read())
        return "latex_archive"

    bio.seek(0)
    if zipfile.is_zipfile(bio):
        bio.seek(0)
        with zipfile.ZipFile(bio) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                dest = _safe_target(source_dir, info.filename)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(info.filename))
        return "latex_archive"

    # Single-file gzipped TeX or plain TeX submission
    raw_tex = gzip.decompress(payload) if payload[:2] == b"\x1f\x8b" else payload
    if raw_tex.startswith(b"%PDF-"):
        pdf_fallback_path.write_bytes(raw_tex)
        return "pdf_only"
    (source_dir / "main.tex").write_bytes(raw_tex)
    return "latex_single"


def _strip_tex_comment(line: str) -> str:
    return re.sub(r"(?<!\\)%.*$", "", line)


def _find_root_tex(source_dir: Path) -> Path | None:
    tex_files = sorted(source_dir.rglob("*.tex"))
    if not tex_files:
        return None
    candidates: list[tuple[int, int, Path]] = []
    for path in tex_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        has_doc = int("\\begin{document}" in text)
        has_cls = int("\\documentclass" in text)
        preferred_name = int(path.name.lower() in {"main.tex", "paper.tex", "ms.tex", "article.tex"})
        score = has_doc * 4 + has_cls * 2 + preferred_name
        candidates.append((score, len(text), path))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _resolve_tex_order(root_tex: Path, source_dir: Path) -> list[Path]:
    ordered: list[Path] = []
    visited: set[Path] = set()

    def visit(tex_path: Path) -> None:
        resolved = tex_path.resolve()
        if resolved in visited or not resolved.is_file() or not resolved.is_relative_to(source_dir.resolve()):
            return
        visited.add(resolved)
        ordered.append(resolved)
        lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
        for raw_line in lines:
            clean = _strip_tex_comment(raw_line)
            for match in INPUT_RE.finditer(clean):
                ref = match.group(1).strip()
                for base in (resolved.parent, source_dir):
                    cand = base / (ref if ref.endswith(".tex") else f"{ref}.tex")
                    if cand.is_file():
                        visit(cand)
                        break

    visit(root_tex)
    for extra in sorted(source_dir.rglob("*.tex")):
        if extra.resolve() not in visited:
            ordered.append(extra.resolve())
    return ordered


def build_latex_index(source_dir: Path, paper_dir: Path) -> dict[str, Any]:
    """Scan unmodified `.tex` files under `source_dir` and build structured line-range index."""
    root_tex = _find_root_tex(source_dir)
    if root_tex is None:
        return {"mode": "empty", "files": [], "macros": [], "sections": [], "tables": [], "blocks": []}

    ordered_files = _resolve_tex_order(root_tex, source_dir)
    macros: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []

    for fpath in ordered_files:
        rel = fpath.relative_to(paper_dir).as_posix()
        lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        macro_lines: list[int] = []
        macro_names: list[str] = []
        open_sections: list[dict[str, Any]] = []
        active_env: dict[str, Any] | None = None

        for lineno, raw_line in enumerate(lines, 1):
            clean = _strip_tex_comment(raw_line)
            if not clean.strip():
                continue

            for m_macro in MACRO_RE.finditer(clean):
                macro_lines.append(lineno)
                if len(macro_names) < 12 and m_macro.group(1) not in macro_names:
                    macro_names.append(m_macro.group(1))

            if APPENDIX_RE.search(clean):
                if open_sections:
                    open_sections[-1]["end_line"] = max(open_sections[-1]["start_line"], lineno - 1)
                open_sections.append(
                    {"level": "appendix", "title": "Appendix", "file": rel, "start_line": lineno, "end_line": len(lines)}
                )

            sec_m = SECTION_RE.search(clean)
            if sec_m:
                if open_sections:
                    open_sections[-1]["end_line"] = max(open_sections[-1]["start_line"], lineno - 1)
                open_sections.append(
                    {
                        "level": sec_m.group(1),
                        "title": " ".join(sec_m.group(2).split()),
                        "file": rel,
                        "start_line": lineno,
                        "end_line": len(lines),
                    }
                )

            if active_env is None:
                env_m = ENV_BEGIN_RE.search(clean)
                if env_m:
                    active_env = {"env": env_m.group(1), "file": rel, "start_line": lineno, "text": [clean]}
            else:
                active_env["text"].append(clean)
                if f"\\end{{{active_env['env']}}}" in clean:
                    blob = " ".join(active_env["text"])
                    cap_m = CAPTION_RE.search(blob)
                    lbl_m = LABEL_RE.search(blob)
                    entry = {
                        "env": active_env["env"],
                        "file": rel,
                        "start_line": active_env["start_line"],
                        "end_line": lineno,
                        "caption": " ".join(cap_m.group(1).split())[:160] if cap_m else "",
                        "label": lbl_m.group(1).strip() if lbl_m else "",
                    }
                    if active_env["env"].startswith(("table", "wraptable")):
                        tables.append(entry)
                    elif entry["label"] or not active_env["env"].startswith(("equation", "align", "gather")):
                        blocks.append(entry)
                    active_env = None

        if macro_lines:
            macros.append(
                {
                    "file": rel,
                    "start_line": min(macro_lines),
                    "end_line": max(macro_lines),
                    "count": len(macro_lines),
                    "sample": macro_names,
                }
            )
        sections.extend(open_sections)

    bib_files = [p.relative_to(paper_dir).as_posix() for p in sorted(source_dir.rglob("*.bib"))]
    return {
        "mode": "latex",
        "root_tex": root_tex.relative_to(paper_dir).as_posix(),
        "files": [p.relative_to(paper_dir).as_posix() for p in ordered_files],
        "bib_files": bib_files,
        "macros": macros,
        "sections": sections,
        "tables": tables,
        "blocks": blocks,
    }


def build_pdf_index(pdf_path: Path, source_dir: Path, paper_dir: Path) -> dict[str, Any]:
    """Extract page-marked text from PDF (when PyMuPDF is installed) and index headings."""
    try:
        import pymupdf  # type: ignore[import-not-found]
    except ImportError:
        return {"mode": "pdf_unindexed", "warning": "Install pymupdf (`pip install pymupdf`) to index PDF-only papers."}

    source_dir.mkdir(parents=True, exist_ok=True)
    out_txt = source_dir / "pdf_extracted.txt"
    all_lines: list[str] = []
    with pymupdf.open(str(pdf_path)) as doc:
        page_count = doc.page_count
        for pno in range(page_count):
            all_lines.append(f"=== Page {pno + 1} ===")
            all_lines.extend(doc[pno].get_text().splitlines())

    out_txt.write_text("\n".join(all_lines) + "\n", encoding="utf-8")
    rel = out_txt.relative_to(paper_dir).as_posix()
    heading_re = re.compile(r"^(?:(?:\d+(?:\.\d+)*)|Abstract|Introduction|Related Work|Method\w*|Experiment\w*|Conclusion\w*|Appendix)\b.{0,80}$", re.I)
    sections: list[dict[str, Any]] = []
    for idx, line in enumerate(all_lines, 1):
        stripped = line.strip()
        if 3 <= len(stripped) <= 85 and heading_re.match(stripped):
            if sections:
                sections[-1]["end_line"] = max(sections[-1]["start_line"], idx - 1)
            sections.append({"level": "heading", "title": stripped, "file": rel, "start_line": idx, "end_line": len(all_lines)})
    return {"mode": "pdf_text", "files": [rel], "page_count": page_count, "sections": sections, "macros": [], "tables": [], "blocks": []}


def clone_official_repo(repo_url: str, repo_dir: Path) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(repo_url.strip())
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"github.com", "gitlab.com"}:
        raise ValueError(f"Repository URL must be HTTPS on github.com or gitlab.com: {repo_url!r}")
    if not (repo_dir / ".git").exists():
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        subprocess.run(["git", "clone", "--depth", "1", repo_url.strip(), str(repo_dir)], check=True, capture_output=True, text=True)
    commit = subprocess.run(["git", "-C", str(repo_dir), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    code_exts = {".py", ".yaml", ".yml", ".json", ".sh", ".toml", ".md", ".cu", ".cpp", ".h"}
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv"}
    tree: list[str] = []
    for path in sorted(repo_dir.rglob("*")):
        if not path.is_file() or any(part in skip_dirs for part in path.parts):
            continue
        if path.suffix.lower() in code_exts and len(tree) < 120:
            rel = path.relative_to(repo_dir.parent).as_posix()
            try:
                lc = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
                tree.append(f"{rel} ({lc} lines)")
            except OSError:
                tree.append(rel)
    return {"url": repo_url.strip(), "commit": commit, "files": tree}


def render_index_markdown(meta: dict[str, Any], idx_data: dict[str, Any], repo_info: dict[str, Any] | None) -> str:
    lines = [
        f"# Source Index — {meta.get('title', meta.get('slug', 'Paper'))}",
        "",
        f"- **Slug**: `{meta.get('slug', '')}`",
        f"- **arXiv / Year**: `{meta.get('arxiv_id') or 'n/a'}` ({meta.get('year') or '?'})",
        f"- **Source Mode**: `{idx_data.get('mode')}` (ground-truth files under `source/` are unmodified)",
    ]
    if idx_data.get("root_tex"):
        lines.append(f"- **Root TeX**: `{idx_data['root_tex']}`")
    if idx_data.get("bib_files"):
        lines.append(f"- **BibTeX Files**: {', '.join(f'`{b}`' for b in idx_data['bib_files'])}")
    if idx_data.get("warning"):
        lines.append(f"- **Warning**: {idx_data['warning']}")
    lines.append("")

    if idx_data.get("macros"):
        lines.extend(["## 1. Custom Macros & Notation Definitions (Read Before Interpreting Equations)", ""])
        for m in idx_data["macros"]:
            samples = ", ".join(f"`\\{s}`" for s in m["sample"])
            lines.append(f"- `{m['file']}:L{m['start_line']}-L{m['end_line']}` ({m['count']} definitions, e.g. {samples})")
        lines.append("")

    lines.extend(["## 2. Section & Appendix Line Index (Use Line Ranges for JIT Reading)", ""])
    for s in idx_data.get("sections") or []:
        indent = "  " * {"section": 0, "appendix": 0, "heading": 0, "subsection": 1, "subsubsection": 2}.get(s["level"], 0)
        lines.append(f"{indent}- **{s['title']}** — `{s['file']}:L{s['start_line']}-L{s['end_line']}`")
    if not idx_data.get("sections"):
        for f in idx_data.get("files") or []:
            lines.append(f"- `{f}`")
    lines.append("")

    if idx_data.get("tables"):
        lines.extend(["## 3. Experimental & Summary Tables", ""])
        for t in idx_data["tables"]:
            lbl = f" (`{t['label']}`)" if t.get("label") else ""
            cap = f": {t['caption']}" if t.get("caption") else ""
            lines.append(f"- `{t['file']}:L{t['start_line']}-L{t['end_line']}`{lbl}{cap}")
        lines.append("")

    if idx_data.get("blocks"):
        lines.extend(["## 4. Theorems, Algorithms & Labeled Equations", ""])
        for b in idx_data["blocks"][:60]:
            lbl = f" `{b['label']}`" if b.get("label") else ""
            lines.append(f"- [{b['env']}{lbl}] `{b['file']}:L{b['start_line']}-L{b['end_line']}`")
        lines.append("")

    if repo_info:
        lines.extend([
            "## 5. Official Code Repository (`repo/`)",
            "",
            f"- **URL**: {repo_info['url']}",
            f"- **Pinned Commit**: `{repo_info['commit']}`",
            "",
        ])
        for entry in repo_info["files"]:
            lines.append(f"- `{entry}`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _init_notes_if_missing(paper_dir: Path, meta: dict[str, Any], role: str, repo_info: dict[str, Any] | None) -> None:
    notes_path = paper_dir / "notes.md"
    if notes_path.exists():
        return
    repo_str = f"{repo_info['url']} (commit: `{repo_info['commit']}`)" if repo_info else "None"
    authors = ", ".join((meta.get("authors") or [])[:5]) or "Unknown"
    content = (
        f"# Paper Note: {meta.get('title', meta.get('slug', ''))}\n\n"
        f"- **Slug**: `{meta.get('slug', '')}`\n"
        f"- **Authors / Year**: {authors} ({meta.get('year') or '?'})\n"
        f"- **Identifier**: arXiv:`{meta.get('arxiv_id') or 'n/a'}` | DOI:`{meta.get('doi') or 'n/a'}`\n"
        f"- **Official Repo**: {repo_str}\n"
        f"- **Role**: `{role}`\n"
        f"- **Reading Depth**: `L0 (Downloaded — Pending Reader Subagent)`\n\n"
        "## 1. Research Question & Lineage Position\n待核实\n\n"
        "## 2. Core Mechanism\n待核实（须附 `source/...:Lxx-Lyy` 原始行号坐标）\n\n"
        "## 3. Explicit & Implicit Assumptions\n待核实\n\n"
        "## 4. Author Claims vs. Actual Experimental Evidence\n"
        "- **`[作者声称]`**：待核实\n- **`[实验实证]`**：待核实\n- **未控制的混杂因素**：待核实\n\n"
        "## 5. Unverified Claims & Limitations\n待核实\n\n"
        "## 6. Code Mapping\n当前未升至 L3 代码审计\n\n"
        "## 7. Potential Research Questions Triggered\n待核实\n"
    )
    notes_path.write_text(content, encoding="utf-8")


def fetch_and_index_paper(
    *,
    workspace: Path,
    arxiv: str = "",
    pdf_url: str = "",
    local_pdf: str = "",
    slug: str = "",
    repo_url: str = "",
    with_pdf: bool = False,
    role: str = "Recent Frontier",
    downloader: BytesDownloader | None = None,
) -> Path:
    if downloader is None:
        downloader = default_download
    if not any((arxiv, pdf_url, local_pdf)):
        raise ValueError("Specify one of --arxiv, --pdf-url, or --local-pdf")

    meta: dict[str, Any] = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if arxiv:
        aid = normalize_arxiv_id(arxiv)
        meta.update(fetch_arxiv_metadata(aid, downloader=downloader))
        paper_slug = slug or slugify(f"{meta.get('year') or ''}_{aid.replace('/', '_')}")
    elif local_pdf:
        src_pdf = Path(local_pdf).resolve()
        if not src_pdf.is_file():
            raise FileNotFoundError(f"Local PDF not found: {src_pdf}")
        paper_slug = slug or slugify(src_pdf.stem)
        meta.update({"title": src_pdf.stem, "arxiv_id": "", "year": 0})
    else:
        paper_slug = slug or slugify(Path(urllib.parse.urlparse(pdf_url).path).stem or "paper")
        meta.update({"title": paper_slug, "arxiv_id": "", "year": 0, "pdf_url": pdf_url})

    meta["slug"] = paper_slug
    paper_dir = (workspace / "papers" / paper_slug).resolve()
    source_dir = paper_dir / "source"
    pdf_path = paper_dir / "paper.pdf"
    paper_dir.mkdir(parents=True, exist_ok=True)

    if arxiv:
        aid = meta["arxiv_id"]
        eprint_bytes = downloader(f"https://arxiv.org/e-print/{urllib.parse.quote(aid, safe='/')}")
        meta["eprint_sha256"] = hashlib.sha256(eprint_bytes).hexdigest()
        payload_kind = unpack_eprint_payload(eprint_bytes, source_dir, pdf_path)
        meta["payload_kind"] = payload_kind
        if with_pdf and not pdf_path.exists():
            pdf_bytes = downloader(f"https://arxiv.org/pdf/{urllib.parse.quote(aid, safe='/')}.pdf")
            pdf_path.write_bytes(pdf_bytes)
            meta["pdf_sha256"] = hashlib.sha256(pdf_bytes).hexdigest()
    elif local_pdf:
        shutil.copy2(local_pdf, pdf_path)
        meta["payload_kind"] = "local_pdf"
        meta["pdf_sha256"] = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    else:
        pdf_bytes = downloader(pdf_url)
        if not pdf_bytes.startswith(b"%PDF-"):
            raise ValueError(f"URL did not return PDF bytes: {pdf_url}")
        pdf_path.write_bytes(pdf_bytes)
        meta["payload_kind"] = "remote_pdf"
        meta["pdf_sha256"] = hashlib.sha256(pdf_bytes).hexdigest()

    idx_data = build_latex_index(source_dir, paper_dir) if meta["payload_kind"].startswith("latex") else build_pdf_index(pdf_path, source_dir, paper_dir)
    repo_info = clone_official_repo(repo_url, paper_dir / "repo") if repo_url.strip() else None
    if repo_info:
        meta["repo"] = {"url": repo_info["url"], "commit": repo_info["commit"]}

    (paper_dir / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (paper_dir / "index.md").write_text(render_index_markdown(meta, idx_data, repo_info), encoding="utf-8")
    _init_notes_if_missing(paper_dir, meta, role, repo_info)
    return paper_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download paper source/PDF, generate line index, and clone official repo.")
    parser.add_argument("--arxiv", default="", help="arXiv ID or URL (e.g. 2310.06762)")
    parser.add_argument("--pdf-url", default="", help="Direct HTTPS URL to a PDF paper")
    parser.add_argument("--local-pdf", default="", help="Path to a local PDF file")
    parser.add_argument("--workspace", required=True, help="Target workspace folder (e.g. workspaces/cl_peft)")
    parser.add_argument("--slug", default="", help="Folder slug under <workspace>/papers/<slug>")
    parser.add_argument("--repo", default="", help="Official GitHub/GitLab HTTPS repo URL to shallow-clone")
    parser.add_argument("--with-pdf", action="store_true", help="Also download paper.pdf alongside LaTeX source")
    parser.add_argument("--role", default="Recent Frontier", help="Initial role label in notes.md")
    args = parser.parse_args(argv)

    paper_dir = fetch_and_index_paper(
        workspace=Path(args.workspace),
        arxiv=args.arxiv,
        pdf_url=args.pdf_url,
        local_pdf=args.local_pdf,
        slug=args.slug,
        repo_url=args.repo,
        with_pdf=args.with_pdf,
        role=args.role,
    )
    print(f"Prepared paper at: {paper_dir}")
    print(f"  Index: {paper_dir / 'index.md'}")
    print(f"  Notes: {paper_dir / 'notes.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
