# Authoring completion work — not a release sign-off

This work extends PR #24. The full v2 conversion/build acceptance gate is **not
complete**. Passing tests below do not authorize merging #24, safe #17 or bridge
#12 as a completed authoring release. Existing integration documents describe the
previous phase, not completion of this expanded scope.

## Frozen starting points

| Repository / candidate | Starting commit or SHA-256 |
| --- | --- |
| hwpctl #24 | `b1118bfa8527f93e1d0354fbc1d694911d17b45b` |
| hwpctl main | `09fe92884ccf03bfdf3c9bbef18251382e861c99` |
| safe #17 | `c805c928191aa606cbb73e84eed0e6bf6b009ebd` |
| bridge #12 | `9e9f5e39fc1ba44573b24aec377572966b8383fe` |
| old native branch | `fbdc2dc2e89000e3c481c0abb95da2e31d039522` |
| old research clone | `40c061a` (local abbreviated object ID) |
| legacy FAQ converter file | `A7ED89D61A3D57AB71216A9B9682D1A3FDE1D8C1F1B83BF905820494A4E6A299` |
| legacy notice authoring file | `0F661186E2B66AC805BC5B673167DC2C1CBFDCB09C9CBF8DEB3F918CC5BA86F2` |
| private editable design prototype file | `5C748EAF49E548DCFBF00ADB30136609BA71E71DCA3D7834B878219893F89C4F` |

Hashes identify local source snapshots, not permission to publish their content.
No private document, image, asset alias or default user path is added here.
Function-level reconciliation of the old clone/native branch remains pending;
these branches have not been replayed on the basis of commit IDs alone.

## Implemented and locally verified in this increment

- The v1 FAQ model, validation and public-command driver now live in
  `hwpctl.authoring.legacy`. The old example imports the same classes/functions
  and remains a CLI entry point. It still has the v1 feature boundary; this move
  does not magically supply v2 conversion or owned-session safety.
- Existing text-box margins are accepted by the v1 driver. The native adapter
  now edits `ShapeListProperites` after creating the text list and commits the
  copied child parameter set back to its parent. The previous item-set name was
  invalid; a successful action alone was insufficient evidence of changed margins.
  Hancom explains Automation's copy semantics in
  [the developer forum](https://forum.developer.hancom.com/t/hwpctrl/2354).
- Text-box radial fill reuses the existing gradient implementation; it no longer
  fails the adapter's obsolete linear-only input gate.
- Nested-table parent exit crosses the child-table anchor after `MoveParentList`.
  It stays in the immediate parent cell rather than inserting the next sibling
  before the first. Failure restores the original cursor through the existing
  exit-table boundary.
- Internal `authoring.geometry` solves both axes from raw integer HU cell/span
  constraints and checks cell coverage/overlap. Missing or contradictory tracks
  stay unresolved; no outer size, first-row inference or proportional repair is
  used. This is geometry evidence, not native layout or conversion acceptance.
- Internal `authoring.paths` resolves recursive parent-cell/child-table paths in
  HWPML. Synthetic native siblings confirm XML order matches native table indexes
  in that case. This helper is not yet exposed as a CLI/MCP table selector.
- `authoring.model` is an internal v2 **envelope only**: copies ordered sections,
  keeps omitted/explicit fields distinct and wraps v1 operations without loss.
  It is not full recursive validation and must not be used as build preflight.

## Evidence

All new tests use independently written synthetic input. Local Windows results:

- Default regression suite: **376 passed, 18 skipped** (opt-in tests excluded).
- Native Hancom 2022 integration suite: **15 passed**. Includes the existing
  three-cycle read-only export/owned-window cleanup diagnostic test.
- New native cases: sibling nested-table order and native selection; radial
  text-box HWP/HWPX save/reopen, persisted margins `(283, 567, 850, 1134)` HU for
  `(1, 2, 3, 4)` mm, native text editing and Undo of that text edit.
- These checks do not claim visual equality, whole-build Undo coverage, or safe
  foreground/preview screen validation. No personal profile or existing user
  document was selected.

## Required before the agreed merge gate

Still implement and validate, not merely reclassify as unsupported:

1. Full recursive v2 body/cell model, v1 transformation and compiler.
2. HWPML/HWPX/bundle conversion, embedded assets and loss/provenance report.
3. Multi-section/page flow, inherited margins/headers, all fixed design objects,
   floating placement and charts through public Engine operations.
4. Owned build lifecycle, whole-spec preflight, failure location, output/source
   protection and cleanup; public `reference_to_spec` / `build_document` and
   Engine/CLI/MCP/catalog consistency.
5. The full fixed synthetic source/expected corpus, failure paths, whole-operation
   Undo, Windows/Linux CI, package/public-file checks and review of final heads.
6. After those pass: squash #24 → safe #17 → bridge #12 without bypassing checks;
   update bridge to the actual merged engine commit and verify main CI.

No unrelated newly discovered feature has been added to the fixed scope.
