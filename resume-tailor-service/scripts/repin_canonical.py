"""Rebuild resume.pdf from the canonical source and regenerate its baseline.

`content/canonical_baseline.json` pins the SHA-256 of harshsaw.tex, resume.cls
and resume.pdf plus the invariants a rebuild has to reproduce. Its own
provenance note says an intentional change to the base resume "requires
regenerating this file and reviewing the diff, not editing a hash in place" --
this is that regeneration step.

    uv run python scripts/repin_canonical.py [--check]

--check reports drift and exits non-zero without writing anything, so it can
gate CI or a pre-commit hook.

Normalization here is deliberately identical to tests/test_canonical_baseline.py
(_normalize / _extract / _fonts). If that test changes, change this too, or the
pins it writes will not be the pins the test reads.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import pypdf

SERVICE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SERVICE_DIR.parent
MANIFEST_PATH = SERVICE_DIR / "content" / "canonical_baseline.json"
ARTIFACTS = ("harshsaw.tex", "resume.cls", "resume.pdf")
WARNING_RE = re.compile(r"Overfull|Underfull|LaTeX Warning")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _compile_twice(work_dir: Path) -> tuple[Path, list[str]]:
    """Compile harshsaw.tex twice (LaTeX needs two passes to settle refs)."""
    for name in ("harshsaw.tex", "resume.cls"):
        shutil.copy(REPO_ROOT / name, work_dir / name)
    for attempt in (1, 2):
        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "harshsaw.tex"],
            cwd=work_dir, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            log = work_dir / "harshsaw.log"
            tail = log.read_text(errors="ignore")[-2000:] if log.exists() else result.stdout[-2000:]
            raise SystemExit(f"pdflatex failed on pass {attempt}:\n{tail}")
    warnings = sorted({
        line.strip()
        for line in (work_dir / "harshsaw.log").read_text(errors="ignore").splitlines()
        if WARNING_RE.search(line)
    })
    return work_dir / "harshsaw.pdf", warnings


def build_manifest(pdf_path: Path, warnings: list[str], previous: dict) -> dict:
    reader = pypdf.PdfReader(str(pdf_path))
    box = reader.pages[0].mediabox
    pages = len(reader.pages)
    size = [round(float(box.width), 1), round(float(box.height), 1)]
    if pages != 1:
        raise SystemExit(f"refusing to pin a {pages}-page resume; it must fit one page")
    if size != [612.0, 792.0]:
        raise SystemExit(f"refusing to pin non-US-Letter geometry {size}")

    text = _extract(pdf_path)
    manifest = json.loads(json.dumps(previous))  # deep copy, keeps key order
    for name in ARTIFACTS:
        path = REPO_ROOT / name
        manifest["artifacts"][name]["sha256"] = _sha256(path)
        manifest["artifacts"][name]["bytes"] = path.stat().st_size

    invariants = manifest["rebuild_invariants"]
    invariants["pages"] = pages
    invariants["page_size_pt"] = size
    invariants["fonts"] = _fonts(pdf_path)
    invariants["normalized_text_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    invariants["normalized_text_tokens"] = len(text.split())
    manifest["allowed_warnings"] = warnings
    manifest["provenance"]["verified_on"] = date.today().isoformat()
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report drift and exit non-zero; write nothing")
    args = parser.parse_args()

    if shutil.which("pdflatex") is None:
        raise SystemExit("pdflatex not on PATH (try /Library/TeX/texbin)")

    previous = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory() as tmp:
        built_pdf, warnings = _compile_twice(Path(tmp))
        if args.check:
            pdf_for_pins = built_pdf
        else:
            shutil.copy(built_pdf, REPO_ROOT / "resume.pdf")
            pdf_for_pins = REPO_ROOT / "resume.pdf"
        manifest = build_manifest(pdf_for_pins, warnings, previous)

        changed = [
            name for name in ARTIFACTS
            if manifest["artifacts"][name]["sha256"] != previous["artifacts"][name]["sha256"]
        ]
        if args.check:
            if changed:
                print("DRIFT in: " + ", ".join(changed))
                return 1
            print("canonical baseline is current")
            return 0

        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    for name in ARTIFACTS:
        before = previous["artifacts"][name]["sha256"][:12]
        after = manifest["artifacts"][name]["sha256"][:12]
        mark = "changed" if before != after else "same"
        print(f"  {name:14} {before} -> {after}  ({mark}, "
              f"{manifest['artifacts'][name]['bytes']} bytes)")
    inv, old_inv = manifest["rebuild_invariants"], previous["rebuild_invariants"]
    print(f"  tokens         {old_inv['normalized_text_tokens']} -> "
          f"{inv['normalized_text_tokens']}")
    print(f"  pages/size     {inv['pages']} {inv['page_size_pt']}")
    print(f"  warnings       {manifest['allowed_warnings']}")
    print(f"\nwrote {MANIFEST_PATH.relative_to(REPO_ROOT)} -- review the diff before committing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
