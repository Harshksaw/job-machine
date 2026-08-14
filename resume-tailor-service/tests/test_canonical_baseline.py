"""Guards the canonical resume baseline.

The tailoring verifier described in
docs/superpowers/specs/2026-08-03-canonical-resume-tailoring-verifier-design.md
compares every tailored candidate against this baseline. If the baseline drifts
without review, every downstream comparison is silently wrong, so these tests
fail loudly on any change to the canonical trio or to what it compiles into.

Hash tests always run. Compile tests need pdflatex and skip without it, matching
tests/test_render.py; CI's deploy-check job installs TeX so they execute there.
"""
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pypdf
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST_PATH = Path(__file__).resolve().parent.parent / "content" / "canonical_baseline.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

needs_tex = pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not on PATH")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract(pdf_path: Path) -> str:
    reader = pypdf.PdfReader(str(pdf_path))
    return _normalize("\n".join(page.extract_text() or "" for page in reader.pages))


def _fonts(pdf_path: Path) -> list[str]:
    page = pypdf.PdfReader(str(pdf_path)).pages[0]
    resources = page.get("/Resources", {}) or {}
    fonts = set()
    for _name, font in (resources.get("/Font", {}) or {}).items():
        base_font = font.get_object().get("/BaseFont")
        if base_font:
            fonts.add(str(base_font))
    return sorted(fonts)


def _compile_twice(tmp_path: Path) -> Path:
    shutil.copy(REPO_ROOT / "harshsaw.tex", tmp_path / "harshsaw.tex")
    shutil.copy(REPO_ROOT / "resume.cls", tmp_path / "resume.cls")
    for _ in range(2):  # twice so hyperref cross-references settle
        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "harshsaw.tex"],
            cwd=tmp_path, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, (
            (tmp_path / "harshsaw.log").read_text(errors="replace")[-2000:]
        )
    return tmp_path / "harshsaw.pdf"


@pytest.mark.parametrize("filename", sorted(MANIFEST["artifacts"]))
def test_canonical_artifact_matches_pinned_hash(filename):
    """The canonical trio must be byte-identical to what the manifest pins."""
    path = REPO_ROOT / filename
    expected = MANIFEST["artifacts"][filename]
    assert path.is_file(), f"{filename} is missing from the repository root"
    data = path.read_bytes()
    assert len(data) == expected["bytes"], f"{filename} size drifted"
    assert hashlib.sha256(data).hexdigest() == expected["sha256"], (
        f"{filename} content drifted from the pinned baseline. If this change was "
        f"intentional, regenerate {MANIFEST_PATH.name} and review the diff."
    )


def test_canonical_source_is_not_a_placeholder():
    """Regression: harshsaw.tex was a 1-byte '/' placeholder before 2026-08-07."""
    source = (REPO_ROOT / "harshsaw.tex").read_text(encoding="utf-8")
    assert len(source) > 1000
    assert "\\documentclass" in source


def test_base_pdf_matches_pinned_text_and_geometry():
    """The published base PDF is what the manifest says it is. No TeX needed."""
    base = REPO_ROOT / "resume.pdf"
    reader = pypdf.PdfReader(str(base))
    invariants = MANIFEST["rebuild_invariants"]

    assert len(reader.pages) == invariants["pages"]
    page = reader.pages[0]
    assert [
        round(float(page.mediabox.width), 1),
        round(float(page.mediabox.height), 1),
    ] == invariants["page_size_pt"]
    assert _fonts(base) == invariants["fonts"]

    text = _extract(base)
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == \
        invariants["normalized_text_sha256"]
    assert len(text.split()) == invariants["normalized_text_tokens"]


@needs_tex
def test_canonical_source_rebuilds_to_the_base_pdf(tmp_path):
    """Compiling the canonical trio reproduces the published base PDF.

    This is the load-bearing check: it proves the baseline is reproducible, which
    is what lets the verifier treat a base-vs-tailored diff as meaningful. PDF
    bytes are deliberately not compared, since build metadata and compression
    legitimately differ between compiles.
    """
    rebuilt = _compile_twice(tmp_path)
    invariants = MANIFEST["rebuild_invariants"]
    page = pypdf.PdfReader(str(rebuilt)).pages[0]

    assert len(pypdf.PdfReader(str(rebuilt)).pages) == invariants["pages"]
    assert [
        round(float(page.mediabox.width), 1),
        round(float(page.mediabox.height), 1),
    ] == invariants["page_size_pt"]
    assert _fonts(rebuilt) == _fonts(REPO_ROOT / "resume.pdf")
    assert _extract(rebuilt) == _extract(REPO_ROOT / "resume.pdf")


@needs_tex
def test_canonical_compile_emits_only_the_allowed_warning(tmp_path):
    """A new or changed LaTeX warning means the layout moved. Fail closed."""
    _compile_twice(tmp_path)
    log = (tmp_path / "harshsaw.log").read_text(errors="replace")
    seen = sorted({
        line.strip()
        for line in log.splitlines()
        if "Overfull" in line or "Underfull" in line or "LaTeX Warning" in line
    })
    assert seen == sorted(MANIFEST["allowed_warnings"]), (
        f"LaTeX warnings changed.\nexpected: {MANIFEST['allowed_warnings']}\ngot: {seen}"
    )
