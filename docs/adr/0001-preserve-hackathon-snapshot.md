# ADR-0001: Preserve the team snapshot and define one canonical client path

- Status: accepted
- Date: 2026-07-15

## Context

The hackathon repository contains an earlier `kioskMacro/` client and a later `macro_pkg/`
integration tree. They overlap, but the later tree also contains launcher and setup assumptions
that are not present in the earlier snapshot. Replacing both with a new package would make the
tree look cleaner while obscuring team provenance and increasing regression risk in a
platform-specific application that cannot be exercised end to end on CI.

## Decision

`macro_pkg/` is the canonical client path. The earlier `kioskMacro/` tree and root experiments are
retained as a legacy reference. The public README labels this boundary. Maintenance focuses on
safe defaults, broken launcher paths, dependency declarations, and dependency-free tests around
configuration, menu indexing, whole-order validation, serialized execution, and manual checkout.
The legacy tree is preserved structurally, with only minimal safety hardening: its pointer default
is dry-run and PyAutoGUI's corner failsafe remains enabled.

## Alternatives considered

- Delete the earlier tree. Rejected because it erases useful team provenance and may remove the
  only copy of experiment code and captured assets.
- Merge the trees mechanically. Rejected because similarly named files have diverged and an
  automated merge would imply end-to-end validation that is not available.
- Rewrite the desktop client. Rejected because it would create new, unvalidated product scope for
  an archived hackathon prototype.

## Consequences

The repository remains larger than a greenfield package, but reviewers can identify the supported
path and contribution boundary immediately. CI validates the deterministic safety core, while
native audio, OCR, and live pointer integration remain explicitly manual and platform-specific.
The legacy client remains visibly labeled and defaults to dry-run; it is not a second supported
execution path.
