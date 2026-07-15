# Work log

## 2026-07-15 — Public repository renovation and safe order execution

- Objective: make the UNITHON client repository reviewable without rewriting teammate-owned
  history or presenting a hackathon prototype as a production service.
- Structure: designated `macro_pkg/` as the canonical client path, documented the earlier team
  snapshot as legacy, retained its structure with only dry-run and pointer-failsafe hardening, and
  recorded the preserve-versus-rewrite decision in ADR-0001.
- Runtime: corrected launcher paths to the actual `macro_pkg` tree, prevented undrained background
  process pipes, removed shell-based setup commands, corrected the capture path, and completed the
  declared TTS dependencies.
- Safety: changed pointer automation to dry-run by default, restored the PyAutoGUI corner failsafe,
  separated live OCR calibration behind `KIOSK_RUN_CALIBRATION=1`, made invalid boolean values
  preserve safe defaults, prevented pointer movement during order dry runs, validated the full
  bounded order before any click, serialized order execution, restricted execution to the HTTP
  order-hub path, propagated and latched the pointer failsafe across the whole order until restart,
  and kept live checkout manual. `KIOSK_ALLOW_CHECKOUT=1` now adds only a dry-run checkout trace.
- Repository hygiene: removed tracked IDE metadata and an empty root entry point, and added ignore
  rules for IDE files.
- Validation: added standard-library tests for launcher paths, calibration opt-in and failure
  propagation, configuration evaluation, menu indexing, malformed and unmatched orders, partial
  failure, full-payload rejection, order limits, overlapping execution, emergency stop, simulated
  checkout, manual live checkout, and full success. All 22 tests and syntax compilation passed
  locally and in GitHub Actions.
- Delivery: merged pull request #1 into `main`; pull-request and post-merge `quality` runs passed.
  The public README, architecture note, and work log returned HTTP 200, and repository description,
  homepage, and topics now identify the project as an accessibility hackathon prototype.
