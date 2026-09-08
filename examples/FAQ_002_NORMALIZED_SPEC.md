# Public-command FAQ example

This is an authoring example, not a universal importer or automatic layout engine.
Run from a source checkout with hwpctl dependencies installed:

```powershell
python examples/rebuild_faq_002_from_normalized_spec.py --spec examples/specs/faq.synthetic.json --output output/faq-synthetic.hwp --dry-run
```

Remove `--dry-run` only on Windows with Han/글 installed and after reviewing the
specification. The driver opens a **new** document via `Engine.dispatch`, saves to
a new output, and leaves it open for inspection. It does not open a reference,
use private COM authoring, import rendered pages, or overwrite an existing output.
The filename preserves the prototype's provenance; no private FAQ is distributed.

## Specification boundary

[faq.synthetic.json](specs/faq.synthetic.json) is a complete runnable synthetic
example: three body paragraphs and one native 3×2 table with a merged header.
Its zero hash is an explicit synthetic sentinel, **not** a reference capture hash.
For actual analysis, supply the actual reference hash; `reference` accepts only
`label` and `source_sha256`, never an input-document path.

- `page` maps to `set_pagedef`; optional `page_number` to `set_page_number`.
- Operations are `paragraph`, `table`, or `text_box`. Rich runs stay rich runs.
- Tables require dimensions, widths, heights, default cell margins, properties,
  and cell paragraphs. Grid sizing precedes merges. Final logical `exit_cell`
  must be represented in `cells`, including when blank. `move_to_cell` replaces
  the old margin-reapplication navigation workaround.
- Flat table position records are validated and translated to the existing
  `set_table_position` payload. Inline-only irrelevant coordinates are discarded;
  floating positioning remains explicit. This is not a schema unification.
- `page_controls_after` retains ordered page visibility and numbering restart.
- Optional images reference explicit `assets` keys with paths relative to the
  spec (or user-supplied absolute paths) and optional SHA-256 checks. Public fixture
  contains no assets. A whole-page image is not an editable reconstruction.
- Generic shapes, floating images, and text-box inner-margin workarounds are
  rejected. Preflight compiles commands without constructing Engine/COM and
  checks tool availability, assets, hashes, and output collisions. It does not
  guarantee all Engine argument validations or native layout will succeed.

## Safety and evidence

Build/progress logs include command arguments and can contain document text and
local paths: keep them private. Counts describe requested authoring operations,
not an independent inspection of the saved document. Partial COM failures can
leave a dirty document; inspect it instead of blindly rerunning. The legacy
`--resume-from-operation` is expert-only: it does not verify document identity or
completion of earlier operations; it is not part of the validated synthetic path.
Do not use resume against a different active document.

Tests: `tests/test_rebuild_faq_002_from_normalized_spec.py` (no COM), and opt-in
`tests/test_hangul_live_integration.py` (isolated synthetic document). Structural
success is not evidence of visual equivalence. Full source fidelity, private
source-specific exporters, pagination fitting, and visual comparisons remain
separate follow-up work. See [integration inventory](../docs/INTEGRATION_STATUS.md).
