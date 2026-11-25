from __future__ import annotations

import gzip
import io
import json
from pathlib import Path
import tarfile
import pytest

from scripts.fetch_paper import (
    fetch_and_index_paper,
    normalize_arxiv_id,
    unpack_eprint_payload,
    validate_public_url,
)

SAMPLE_ATOM_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <title>Interference-Free Orthogonal Continual Learning</title>
    <summary>We study subspace interference in continual PEFT.</summary>
    <published>2025-02-14T00:00:00Z</published>
    <updated>2025-03-01T00:00:00Z</updated>
    <author><name>Jane Doe</name></author>
    <arxiv:doi>10.48550/arXiv.2502.12345</arxiv:doi>
  </entry>
</feed>
"""


def _make_multifile_tarball(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_normalize_arxiv_id() -> None:
    assert normalize_arxiv_id("2502.12345v2") == "2502.12345"
    assert normalize_arxiv_id("https://arxiv.org/abs/2502.12345v1") == "2502.12345"
    assert normalize_arxiv_id("https://arxiv.org/pdf/cs/0601001.pdf") == "cs/0601001"


def test_ssrf_guard_blocks_loopback_and_non_http() -> None:
    with pytest.raises(ValueError):
        validate_public_url("file:///etc/passwd")
    with pytest.raises(ValueError):
        validate_public_url("http://127.0.0.1:8080/secret")


def test_path_traversal_in_tarball_is_blocked(tmp_path: Path) -> None:
    evil_tar = _make_multifile_tarball({"../../escape.tex": b"pwned"})
    with pytest.raises(ValueError, match="Path traversal"):
        unpack_eprint_payload(evil_tar, tmp_path / "source", tmp_path / "paper.pdf")


def test_multifile_latex_preserved_unmodified_and_indexed(tmp_path: Path) -> None:
    raw_files = {
        "main.tex": (
            b"\\documentclass{article}\n"
            b"\\input{macros}\n"
            b"\\begin{document}\n"
            b"\\input{sections/intro}\n"
            b"\\input{sections/method}\n"
            b"\\input{tables/main_results}\n"
            b"\\appendix\n"
            b"\\section{Hyperparameter Details}\n"
            b"Learning rate is 1e-3.\n"
            b"\\end{document}\n"
        ),
        "macros.tex": (
            b"% Custom notation\n"
            b"\\newcommand{\\proj}{\\mathcal{P}_{\\perp}}\n"
            b"\\DeclareMathOperator{\\argmin}{arg\\,min}\n"
        ),
        "sections/intro.tex": b"\\section{Introduction}\nMotivation text.\n",
        "sections/method.tex": (
            b"\\section{Proposed Method}\n"
            b"\\subsection{Subspace Update}\n"
            b"\\begin{equation}\n"
            b"\\label{eq:update}\n"
            b"g' = \\proj g\n"
            b"\\end{equation}\n"
            b"\\begin{theorem}\n"
            b"\\label{thm:bound}\n"
            b"Interference is zero.\n"
            b"\\end{theorem}\n"
        ),
        "tables/main_results.tex": (
            b"\\begin{table*}[t]\n"
            b"\\caption{Main comparison on Split CIFAR-100 with 10 tasks.}\n"
            b"\\label{tab:main}\n"
            b"\\begin{tabular}{lcc} Method & ACC & BWT \\\\ \\end{tabular}\n"
            b"\\end{table*}\n"
        ),
        "refs.bib": b"@inproceedings{wang2023olora, title={O-LoRA}}\n",
    }
    tar_bytes = _make_multifile_tarball(raw_files)

    def fake_downloader(url: str) -> bytes:
        if "export.arxiv.org" in url:
            return SAMPLE_ATOM_XML
        if "arxiv.org/e-print/" in url:
            return tar_bytes
        raise AssertionError(f"Unexpected download URL: {url}")

    paper_dir = fetch_and_index_paper(
        workspace=tmp_path,
        arxiv="2502.12345",
        slug="2025_inflora_demo",
        role="Direct Baseline",
        downloader=fake_downloader,
    )

    # 1. Source files are 100% byte-identical (zero destructive cleaning)
    for rel_name, expected_bytes in raw_files.items():
        assert (paper_dir / "source" / rel_name).read_bytes() == expected_bytes

    # 2. Index contains macros, ordered sections across \input, tables, blocks, and appendix
    index_md = (paper_dir / "index.md").read_text(encoding="utf-8")
    assert "source/macros.tex:L2-L3" in index_md
    assert "`\\proj`" in index_md
    assert "**Introduction** — `source/sections/intro.tex:L1-L2`" in index_md
    assert "**Proposed Method** — `source/sections/method.tex:L1-L1" in index_md
    assert "`source/tables/main_results.tex:L1-L5` (`tab:main`): Main comparison on Split CIFAR-100" in index_md
    assert "[equation `eq:update`]" in index_md
    assert "[theorem `thm:bound`]" in index_md
    assert "**Hyperparameter Details**" in index_md

    # 3. Existing agent notes are never overwritten on re-fetch
    notes_path = paper_dir / "notes.md"
    notes_path.write_text("# Custom Agent Notes\nVerified fact.\n", encoding="utf-8")
    fetch_and_index_paper(
        workspace=tmp_path,
        arxiv="2502.12345",
        slug="2025_inflora_demo",
        downloader=fake_downloader,
    )
    assert notes_path.read_text(encoding="utf-8") == "# Custom Agent Notes\nVerified fact.\n"


def test_single_gzipped_tex_and_pdf_fallback(tmp_path: Path) -> None:
    single_gz = gzip.compress(b"\\documentclass{article}\n\\begin{document}\n\\section{Only Section}\nHi.\n\\end{document}\n")

    def gz_downloader(url: str) -> bytes:
        return SAMPLE_ATOM_XML if "export.arxiv.org" in url else single_gz

    pdir = fetch_and_index_paper(workspace=tmp_path, arxiv="2502.12345", slug="single_tex", downloader=gz_downloader)
    meta = json.loads((pdir / "metadata.json").read_text(encoding="utf-8"))
    assert meta["payload_kind"] == "latex_single"
    assert "**Only Section** — `source/main.tex:L3-L5`" in (pdir / "index.md").read_text(encoding="utf-8")

    # Local PDF indexing via PyMuPDF
    pymupdf = pytest.importorskip("pymupdf")
    pdf_file = tmp_path / "sample.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "1 Introduction\nThis is a PDF-only paper.\n2 Experiments\n benchmark table.")
    doc.save(str(pdf_file))
    doc.close()

    pdf_dir = fetch_and_index_paper(workspace=tmp_path, local_pdf=str(pdf_file), slug="pdf_paper")
    pdf_index = (pdf_dir / "index.md").read_text(encoding="utf-8")
    assert "source/pdf_extracted.txt" in pdf_index
    assert "1 Introduction" in pdf_index
