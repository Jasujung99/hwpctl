# Authoring completion gate — still open

PR #24 is an integration branch, not a completed authoring release. The fixed
acceptance scope remains HWPML/HWPX/reference conversion, ordered v2 native
authoring, synthetic HWP/HWPX save/reopen/edit/Undo, and full PR review. Do not
merge #24, safe #17, or bridge #12 on the basis of the partial evidence below.

The frozen source set for this increment remains: hwpctl #24
`b1118bfa8527f93e1d0354fbc1d694911d17b45b`, hwpctl main
`09fe92884ccf03bfdf3c9bbef18251382e861c99`, safe #17
`c805c928191aa606cbb73e84eed0e6bf6b009ebd`, bridge #12
`9e9f5e39fc1ba44573b24aec377572966b8383fe`, old native
`fbdc2dc2e89000e3c481c0abb95da2e31d039522` and old research clone
`40c061a`. Private prototype hashes remain in the earlier PR history; they
identify local snapshots, not permission to publish those files.

## Current implementation

- `hwpctl.authoring.model` upgrades v1 and recursively validates ordered v2
  sections, paragraphs, runs, cell content, nested/merged tables, pictures,
  editable shapes/text boxes, charts and page controls before COM is opened.
  `compiler.py` emits existing public `Engine.dispatch` commands with v2 and
  source locations. Omitted table properties remain distinct from explicit
  values. A synthetic v2 example is at `examples/specs/authoring-v2.synthetic.json`.
- `reference_to_spec` accepts HWPML, HWPX and read-only bundles. It reports
  source-to-target provenance, exact raw-HU grid constraints, embedded assets,
  conversion and losses; a report with losses does not publish an executable
  spec. Supported primitive drawing, placement, borders and fills are covered
  by synthetic converter tests. ChartML is reported as loss, not silently
  replaced with a different chart.
- `build_document` preflights the entire spec and input hashes, keeps dry-run
  COM-free, uses a writer transaction and only publishes a fresh output after
  successful native save and owned-session cleanup. It proves a new Hwp PID,
  window, one blank document and COM document identity before writing or
  closing. Any changed/uncertain owner is left untouched and returned as a
  failure. The user foreground window and global pin/Undo state are not used.
- Engine, CLI, MCP schema and tool catalog expose the two commands and the
  required native primitives without replacing existing entry points.

## Verification completed on this working branch

- Local default suite: **439 passed, 21 skipped**. Opt-in native cases are
  skipped, not counted as passes. Synthetic v2 dry-run and public-file checks
  passed; Python 3.10 syntax was parsed for 59 Python source/test/example files;
  a no-isolation wheel/sdist build passed. The isolated build could not
  download build dependencies in the restricted local network environment.
- The implementation head passed Windows and Linux CI on Python 3.10 and 3.12,
  including the isolated package build. CI must be rerun after each new head;
  this does not substitute for Han/글 native verification.
- The earlier PR head had 15 passing native Hancom tests, including repeated
  COM diagnostics. Those results do **not** validate this branch's new builder.
- Safe PR #17 head `359cc938f81fdbbbd487da052576ac6795a224ea` separately
  passed its Windows 3.11/3.12 CI, fake tests and two synthetic COM contracts.
  It remains unmerged; manual screen verification was not run.

## Blocking acceptance items

1. On this host, independent Python `DispatchEx`, direct `CoCreateInstance`,
   and 32-bit PowerShell COM activation all stalled before the first command.
   The user restarted Han/글, and a retry with separate execution permission
   still stalled. An existing Hwp process recorded an `HwpAppModule.dll`
   access violation. No existing/uncertain user process was terminated. Native
   HWP/HWPX save, reopen, editable object order, page flow and Undo for the
   new builder are therefore **not verified**.
2. HWPX ChartML carries series, axes and styling through `chartIDRef` without
   a verified source-table/range relation. The public table-driven
   `insert_chart` cannot prove preservation of an arbitrary source chart.
   The converter fails closed. Also, its current table-selection route cannot
   prove that a chart stays at its ordered v2 body anchor. Do not treat a
   chart object merely appearing as a successful conversion.
3. The fixed independent synthetic FAQ, notice, complex-table and design
   round-trip corpus and whole-operation Undo have not passed for this
   increment. The final full diff review and review thread resolution must
   follow a verified head.
4. The converter now fails closed for unverified character border/fill, tab
   stops and special spacing controls. FAQ page-number controls still require
   an exact source mapping; a reported conversion loss is not completion.

The initial source snapshots and private prototypes were used only for
function-level understanding; no personal document or asset is published.
The agreed merge order remains #24 → safe #17 → bridge #12, with squash merges
only after the above blockers are actually resolved.
