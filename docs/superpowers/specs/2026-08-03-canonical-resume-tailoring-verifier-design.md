# Canonical Resume Word-Level Tailoring and Verification — Design

Date: 2026-08-03
Status: Draft for written-spec approval
Supersedes: The selection/reordering and auto-trimming design in
`2026-07-21-resume-tailor-service-design.md`

## Goal

Tailor the user's real Overleaf resume to a job description by changing only a
small number of evidence-backed words or short keyword phrases. The service
must preserve the supplied `resume.cls`, LaTeX structure, section and item
order, formatting commands, whitespace outside edited text, and one-page
layout.

Every final result must include a fail-closed verification report comparing the
canonical base resume with the proposed tailored resume. A tailored PDF is
eligible for use only when every verification check passes.

## Why the Existing Pipeline Must Change

The current implementation does not edit the canonical resume. It asks a model
to select, reorder, and remove content-bank entries, writes a new document from
a Jinja template, and deletes complete projects, achievements, skills, or job
bullets when the PDF is too long. That behavior can produce a one-page PDF, but
it does not preserve the user's source, wording, spacing, or visual structure.

The replacement pipeline treats the original Overleaf project as the artifact
being edited. The model proposes a constrained patch; application code applies
and verifies it. The model never controls LaTeX.

## Confirmed Canonical Baseline

The canonical baseline is recoverable and reproducible:

- `harshsaw.tex` is restored byte-for-byte from commit `8be286f` rather than
  from the current one-byte `/` placeholder.
- `resume.cls` is the complete class supplied by the user on 2026-08-03,
  including its original copyright header and ATS bullet fix.
- The existing root `resume.pdf` remains the published base/fallback PDF.
- Compiling the recovered source twice with the supplied class succeeds and
  produces one US-letter page (`612 x 792` points).
- The normalized extracted text is exactly equal to the existing base PDF,
  with 766 extracted tokens and the same font resources.
  **Correction, 2026-08-07:** the token count is 742, not 766, under pypdf
  6.14.2; the base PDF and a fresh rebuild agree exactly at that figure and no
  tokenization reproduces 766, so it was specific to the 2026-08-03 extraction
  environment. Treat token count as environment-qualified provenance, pinned in
  `resume-tailor-service/content/canonical_baseline.json`. The load-bearing
  invariant is rebuild-equals-base, which holds.
- A Quick Look render of the compiled PDF is pixel-identical to the current
  base PDF. Both preview images had SHA-256
  `30a6eb556cb094797a6d7a67813a0490726f1ad0b2b0da940e4ae47cdb81c245`.

Provenance values to pin in the baseline manifest:

| Artifact | SHA-256 |
| --- | --- |
| Supplied `resume.cls` | `addfa2d77cf079ef06515f9266c7847bfbaddcbf61723c654caf80c2dd543049` |
| Recovered `harshsaw.tex` | `ca35f93320d7e8c4aef2b80cc93b1758593cb72a38734d24aa6578a6d3998eb8` |

PDF byte hashes are provenance only, not rebuild invariants, because valid PDF
build metadata and compression may differ. Text, page geometry, font resources,
and same-renderer pixels are the rebuild invariants.

The base compile currently has one known warning:
`Overfull \hbox (30.0pt too wide)` at the contact header. This design does not
silently change the class or header to fix it. The warning is recorded as the
only allowed baseline warning; a new or changed warning fails verification.

## Scope

This change includes:

- restoring and pinning the canonical Overleaf source and class;
- replacing selection/reordering manifests with word-level patch manifests;
- deterministic fact and patch validation;
- compilation with strict process-result checks;
- source, text, page, font, warning, anchor, and visual comparisons;
- a human-readable base-vs-tailored report and dashboard result summary;
- fail-closed fallback to the canonical PDF.

This change does not include:

- redesigning `resume.cls` or changing margins, font sizes, line spacing, or
  section spacing;
- deleting, adding, selecting, or reordering sections, jobs, projects,
  achievements, skill rows, or bullets;
- freeform summary or bullet rewrites;
- adding a claim merely because the job description mentions it;
- auto-trimming content to force one page;
- a general dashboard redesign unrelated to explaining tailoring results.

## Source of Truth and File Layout

The repository-root trio is canonical because it is also the user's portable
Overleaf project and the existing workflow's fallback:

```text
harshsaw.tex              canonical editable source
resume.cls                canonical class, exact user-supplied bytes
resume.pdf                canonical compiled base and fallback
resume-tailor-service/
  content/
    resume_bank.yaml      factual evidence catalog; no longer a render source
    canonical_map.json    pinned source map, hashes, slots, anchors, warnings
  app/
    canonical.py          canonical artifact loading and integrity checks
    patch.py              patch schema, validation, and safe application
    verify.py             source/PDF comparison and report generation
    tailor.py             model request for constrained edits
    render.py             strict compiler wrapper; no trimming
```

Local execution resolves the canonical trio from the repository root. The
container build copies those exact root artifacts into a read-only canonical
directory and sets an explicit `CANONICAL_RESUME_DIR`; it does not maintain a
second editable template. The Docker build context and documentation are
updated accordingly.

The old `templates/resume_template.tex.jinja` regeneration path and its altered
class are removed from the active code path. `resume_bank.yaml` remains useful
only as evidence. No Jinja rendering is used for a resume candidate.

## Canonical Source Map

`canonical_map.json` is generated once from the pinned source and reviewed into
version control. It contains:

- expected SHA-256 values for the source and class;
- expected base page size, page count, normalized text hash, font resource set,
  and allowed warning signatures;
- immutable text anchors such as the name, contact details, section headings,
  education, job/project headers, dates, links, and skill labels;
- mutable prose slots for the summary, each bullet, and each skill-value row;
- each slot's byte range and source hash against the exact canonical source;
- fact IDs allowed to support changes in that slot;
- per-slot edit and length budgets.

The source itself does not need marker comments or new LaTeX commands. Byte
ranges are safe because they are valid only while the complete canonical source
hash matches. Any intentional future base-resume change requires an explicit
baseline regeneration and review.

Mutable slots permit text-node edits only. LaTeX commands, braces,
environments, list boundaries, links, comments, and whitespace are immutable,
including commands located inside a mutable slot. The patcher maps plain-text
tokens back to a single LaTeX text node and rejects edits crossing a command or
formatting boundary.

## Patch Contract

The model receives the job description, role/company metadata, the current
plain text of mutable slots, and the evidence/approved-keyword records that each
slot is allowed to use. It returns JSON only:

```json
{
  "schema_version": 1,
  "edits": [
    {
      "slot_id": "experience.ommuse.1",
      "before": "semantic search",
      "after": "semantic vector search",
      "jd_keywords": ["vector search"],
      "evidence_ids": ["ommuse.semantic-search"],
      "reason": "Uses the JD's supported term for the existing vector-search work."
    }
  ]
}
```

The server, not the model, applies the edits. Every edit must satisfy all of the
following:

1. `slot_id` exists in the pinned source map.
2. `before` occurs exactly once in that slot's extracted plain text and maps to
   one text node without crossing a LaTeX command.
3. `after` is non-empty, single-line, source-safe plain text. LaTeX-reserved
   characters (`\\`, `{`, `}`, `%`, `$`, `#`, `&`, `_`, `~`, and `^`) are
   rejected rather than escaped, so applying an edit cannot add a control
   sequence or formatting command. A keyword requiring one of these characters
   needs a separately reviewed source-map entry; the model cannot invent it.
4. Leading/trailing whitespace, source newlines, and surrounding punctuation
   remain canonical. The replacement cannot introduce duplicate spaces.
5. Edits do not overlap and are always applied to a fresh canonical source,
   never on top of another candidate.
6. The normalized numeric-token sequence in `before` and `after` is identical;
   no number can be added, removed, reordered, or changed. Dates, URLs, company
   names, product names, and proper nouns also remain unchanged unless the
   source map explicitly permits one exact reviewed replacement. The initial
   map permits no numeric replacements.
7. Every newly introduced non-stopword token is covered by an approved term or
   alias for at least one referenced evidence ID that is allowed for the slot.
   The stopword list is fixed in code and checked into tests. Presence in the JD
   alone is never evidence.
8. Each edit declares at least one `jd_keywords` phrase. Every declared phrase
   appears in the normalized JD and in `after`, and every newly introduced
   approved term is accounted for by a declared JD keyword.
9. An edit changes a short phrase, not a sentence or complete bullet.

Initial conservative budgets are configuration constants covered by tests:

- at most 12 edits per resume;
- at most 5 replaced source words per edit;
- at most 2 net new words per edit;
- at most 40 changed words in total and no more than 6% of all mutable words;
- no slot may have 20% or more of its words changed;
- no empty replacement, item deletion, or whole-sentence replacement.

The exact lexical diff is computed server-side with one checked-in tokenizer.
For budgets, an edit's changed-word count is the larger of its removed-word and
added-word counts; total changed words is the sum across edits, and the 6%
denominator is the canonical mutable-word count. Model explanations do not
affect acceptance. An empty edit list is valid and produces an `unchanged`
result when the JD has no safe, useful keyword substitutions.

## Evidence Model

The current content bank is migrated from a menu of renderable alternatives to
a factual evidence catalog with stable IDs. Evidence records may define a small
reviewed set of approved terms and aliases, for example that an existing
MongoDB Vector Store implementation supports the term `vector search`.

Evidence is slot-scoped. A technology mentioned in one job cannot be inserted
into a different job's bullet simply because the user has used it elsewhere.
Skill-value slots may reference the union of reviewed evidence, but experience
and project slots may reference only their mapped facts.

If a useful JD keyword lacks reviewed evidence, the correct result is no edit.
The system does not ask another model to decide whether a new claim is true.

## Candidate Construction

Candidate construction is deterministic:

1. Verify canonical source and class hashes before contacting the model.
2. Validate the patch manifest and compute a lexical diff.
3. Apply valid replacements from the highest source offset to the lowest so
   earlier byte ranges cannot move.
4. Preserve every source byte outside approved text-node replacement spans.
5. Copy the exact canonical `resume.cls` into an isolated build directory.
6. Write the candidate source and compile it twice.

There is no template regeneration and no trim loop. If a candidate causes
reflow or a second page, it is rejected. The service may make one bounded retry
from the untouched canonical source using verifier feedback such as the
offending slot and maximum allowed text width. A retry remains subject to every
patch rule. If it still fails, the base PDF is used.

## Strict Compilation

Both canonical and candidate builds run `pdflatex` twice with
`-halt-on-error`, `-file-line-error`, and a non-interactive mode in separate
temporary directories. Each invocation must return exit code 0. Merely finding
a PDF file is not success.

The compiler wrapper records command, executable/version, exit codes, log
hashes, normalized warnings, output hashes, and elapsed time. It rejects a
missing/stale PDF, zero-byte output, a page-count parsing failure, or any
non-zero compile pass.

## Verification Pipeline

Verification is independent of model output and runs against a freshly loaded
canonical base. Checks execute in this order and stop the candidate from being
published on any failure.

### 1. Canonical integrity

- Canonical `harshsaw.tex` and `resume.cls` match pinned hashes.
- The committed base PDF is exactly one US-letter page.
- A fresh canonical compile matches expected normalized text, fonts, page
  geometry, and visual baseline.
- The class copied into both build directories matches the supplied class hash.

### 2. Source structure

- Replaying the manifest from canonical source reproduces the candidate source
  exactly.
- All changed byte spans fall inside mapped plain-text nodes.
- Outside those spans, the source is byte-for-byte equal to canonical source.
- The LaTeX control-sequence stream, brace balance, environments, commands,
  comments, URLs, and whitespace outside replacement payloads are identical.
- Section, job, project, bullet, achievement, and skill-row counts and order are
  identical.

### 3. Content and evidence

- The manifest passes schema, uniqueness, overlap, lexical-budget, numeric, and
  evidence checks.
- Extracted immutable text is exactly equal to the base.
- Every text difference is explained by one accepted patch entry.
- ATS extraction contains no U+0088 or replacement glyph and retains expected
  headings, contact details, and real U+2022 bullets.

### 4. PDF and one-page layout

- Candidate compilation succeeds twice and yields exactly one `612 x 792`
  point page.
- Font resource names/types match the fresh base compile.
- The warning multiset adds no warning beyond the one pinned header warning.
- Each mutable slot occupies the same number of rendered lines as the base.
- Immutable anchors retain the same page and bounding boxes within a 0.5-point
  tolerance; later sections therefore cannot drift vertically.
- No text bounding box crosses the page/media box or canonical bottom limit.

### 5. Visual comparison

Base and candidate are rasterized by the same renderer at the same resolution.
The verifier creates masks from the rendered bounding boxes of accepted mutable
slots. Pixels outside the padded masks must match the base; differences inside
the masks are retained for review. This catches changed rules, spacing, headers,
or unrelated layout while allowing the intended words to differ.

The visual check emits a base image, tailored image, highlighted diff image,
and a side-by-side HTML comparison. It supplements, rather than replaces, the
source and text checks.

## Verification Report and Output Artifacts

Each request gets an isolated output directory containing:

```text
patch_manifest.json
verification.json
candidate.tex
base.png
tailored.png          only for a passing candidate
diff.png              only for a passing candidate
comparison.html       only for a passing candidate
final.pdf             only for a passing candidate
```

`verification.json` includes:

- overall status and fallback reason;
- canonical/candidate hashes and compiler metadata;
- every requested, accepted, or rejected word edit;
- before/after text, JD keyword, evidence IDs, and lexical counts;
- page count, page size, fonts, warning diff, slot line counts, and anchor
  deltas;
- source/text/visual invariant results;
- paths to review artifacts.

The HTML report leads with the outcome, then shows an exact changes table,
base and tailored pages side by side, the highlighted diff, and expandable
technical checks. It must be understandable without reading LaTeX logs.

## API and Dashboard Behavior

The existing response fields `pdf_path`, `manifest`, and `pages` remain for
caller compatibility. The response adds:

```json
{
  "status": "tailored | unchanged | fallback",
  "pdf_path": "...",
  "base_pdf_path": ".../resume.pdf",
  "pages": 1,
  "manifest": {"schema_version": 1, "edits": []},
  "verification_passed": true,
  "verification_report_path": ".../verification.json",
  "comparison_path": ".../comparison.html",
  "fallback_reason": null
}
```

Behavior by status:

- `tailored`: all checks pass and `pdf_path` points to `final.pdf`.
- `unchanged`: a valid empty patch; `pdf_path` points to the canonical
  `resume.pdf`, `verification_passed` is true, `comparison_path` is null, and
  verification records why no safe edit was made.
- `fallback`: a candidate or retry failed; no candidate is exposed as the
  upload path, `pdf_path` points to canonical `resume.pdf`,
  `verification_passed` is false, `comparison_path` is null, and
  `fallback_reason` is explicit.

A `fallback` is allowed only after the canonical base PDF passes its own
integrity checks. If canonical source, class, or base-PDF integrity fails, the
endpoint returns a non-success error with no `pdf_path`; it cannot claim that a
corrupt or unverified artifact is a safe fallback.

The dashboard result panel shows the status badge, final file actually in use,
exact changed words, evidence, page/format checks, and links to the side-by-side
comparison and machine-readable report. It does not imply a fallback PDF was
successfully tailored.

## Migration Strategy

Implementation proceeds behind tests in this order:

1. Restore the canonical source/class and create the baseline integrity test.
2. Add the canonical loader and checked-in source map.
3. Add patch models, deterministic validation, evidence aliases, and safe
   source application.
4. Replace the model selection prompt with the patch contract.
5. Replace template rendering and trimming with strict canonical compilation.
6. Add the complete verifier and comparison artifacts.
7. Update the API, dashboard result panel, Docker packaging, and workflow
   prompts.
8. Remove the old selector/trim code only after all new integration tests pass.

There is no runtime fallback to the old selector pipeline. During migration,
if the patch pipeline is not ready or fails verification, the only safe output
is the canonical base PDF.

## Testing and Acceptance Criteria

The implementation is accepted only when automated tests demonstrate all of
the following:

- the restored source plus supplied class recompiles to a one-page visual and
  textual match of the current base PDF;
- any source/class hash change fails canonical integrity;
- a valid short, evidenced word substitution passes and appears in the report;
- unsupported keywords, wrong-slot evidence, number changes, LaTeX injection,
  overlapping edits, whole-sentence edits, and edits outside slots fail;
- a changed command, environment, order, item count, whitespace outside an edit,
  link, heading, date, or contact field fails;
- a candidate that adds a page, changes slot line count, moves an immutable
  anchor, adds a compile warning, or changes fonts fails;
- a non-zero first or second `pdflatex` exit fails even if a PDF file exists;
- the known base header warning alone is accepted and any new warning is not;
- failed candidates return the canonical base path with an explicit `fallback`
  status and are never returned as the upload artifact;
- the comparison report identifies every and only accepted word change;
- all existing non-tailoring service tests continue to pass.

Before completion, the full service test suite, canonical golden test, at least
three representative JD integration cases, and a rendered side-by-side visual
inspection must pass.

## Operational Safety

- Canonical artifacts are opened read-only by request handlers.
- Each request builds in a unique temporary/output directory; no request edits
  root source or another request's candidate.
- Output paths remain within the configured output root.
- Logs and reports contain no API key or bearer token.
- Failed candidates are retained only as local diagnostic artifacts and are
  never selected for upload.
- Updating the base resume is a separate explicit maintenance operation that
  regenerates hashes/source maps and requires the golden comparison to pass.

## Design Decision

The chosen approach is canonical-source patching with deterministic,
word-level edits and an independent base-vs-tailored verifier.

Two alternatives were rejected:

1. Continue regenerating from the content bank and tighten the template. This
   still cannot prove that the original source, ordering, and spacing were
   preserved.
2. Let the model rewrite complete bullets and compare only the final PDF. This
   permits unreviewable semantic drift and makes source-level formatting
   changes difficult to detect reliably.

The selected approach is intentionally conservative: an unchanged truthful
one-page resume is preferable to an unverifiable tailored one.
