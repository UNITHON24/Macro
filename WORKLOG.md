# Work log

## 2026-07-18 — Profile-specific read-only acceptance gate

- Objective: turn the UNITHON kiosk profile into a reproducible acceptance contract without
  pretending that a macOS run is physical Windows kiosk evidence.
- Changes: added a versioned acceptance spec for required profile states, aliases, viewport,
  observation providers, default microphone capability, and representative order semantics; added a read-only CLI that reports
  `profile_ready`, `passed`, or `failed` and keeps physical observation explicitly `not_run` unless
  `--observe` is requested; added fail-closed tests for profile drift, mismatched providers and
  viewports, and unknown states.
- Validation: `python3 -m compileall -q macro_pkg tests`, all 76 standard-library tests, and the
  offline acceptance CLI completed locally. The generated offline report was `profile_ready` with
  two matching order cases and `live_observation.status=not_run`.
- Delivery: prepared on a dedicated feature branch for pull-request review; no pointer action,
  real kiosk operation, or physical-device acceptance was performed.
- Remaining work: run `acceptance_kiosk.py --observe` on the intended isolated Windows kiosk and
  retain that machine-specific report before enabling live input. Real microphone/OCR/UIA E2E and
  a short hardware demonstration remain unverified here.

## 2026-07-15 — Black-box semantic automation completion

- Objective: replace the demonstration-time absolute-coordinate path with a reusable, fail-closed
  client for Windows kiosks whose source code and DOM are unavailable.
- Architecture: bound UI Automation and OCR to one native window handle, made UIA the primary
  semantic provider, added OCR and explicit scaled-coordinate fallbacks, introduced a reviewed
  kiosk profile and transition graph, and required stable postconditions and semantic cart deltas.
- Order semantics: preserved the backend's visible `displayName`, temperature, size, and quantity;
  rejected ambiguous menu and control matches before input; and stopped at the verified payment
  method modal without selecting a method or submitting payment.
- Reliability: replaced the volatile handoff with a SQLite queue, idempotency keys, global
  single-claim transactions, result ACKs, and distinct `awaiting_handoff` and `uncertain` states.
  Any verified live cart mutation now blocks the next order until an operator confirms customer
  handoff or cancellation and restores the kiosk. The queue now also closes every SQLite
  connection explicitly so transaction completion releases its database handle on Windows.
- Security: required an installation-specific token for every durable order-hub request, used
  constant-time comparison, authenticated every local API endpoint, filtered offscreen and disabled
  UIA controls, and kept dry-run, payment navigation, OCR downloads, and coordinate fallback as
  separate safe defaults.
- Documentation: kept Korean as the canonical README with a linked English document, recorded the
  architecture decision and real demonstration workaround, and separated the project's legal and
  accessibility motivation from certification or compliance claims.
- Validation: syntax compilation and all 69 standard-library tests passed locally. The suite covers
  the backend payload contract, actual nested controls in the team demo fixture, grounding,
  postconditions, cart evidence, window binding, order-hub authentication, idempotency, handoff
  blocking, recovery, and result acknowledgements. The first cross-platform CI run exposed Windows
  file-handle, console-encoding, and path-separator assumptions; their causes and fixes are recorded
  in the troubleshooting log and are covered by the Linux/Windows quality matrix.
- Delivery: merged pull request #3 into `main` after its Ubuntu and Windows quality jobs passed;
  the post-merge quality run passed on both operating systems as well. Backend pull request #2
  delivered the matching authenticated `X-Macro-Token` contract.

## 2026-07-15 — Public repository renovation and safe order execution

- Objective: make the UNITHON client repository reviewable without rewriting teammate-owned
  history or presenting a hackathon prototype as a production service.
- Structure: designated `macro_pkg/` as the canonical client path, documented the earlier team
  snapshot as legacy, retained its structure with only dry-run and pointer-failsafe hardening, and
  recorded the preserve-versus-rewrite decision in ADR-0001.
- Runtime: corrected launcher paths to the actual `macro_pkg` tree, prevented undrained background
  process pipes, removed shell-based setup commands, corrected the capture path, and completed the
  declared TTS dependencies.
- Safety at that stage: changed pointer automation to dry-run by default, restored the PyAutoGUI corner failsafe,
  separated live OCR calibration behind `KIOSK_RUN_CALIBRATION=1`, made invalid boolean values
  preserve safe defaults, prevented pointer movement during order dry runs, validated the full
  bounded order before any click, serialized order execution, restricted execution to the HTTP
  order-hub path, propagated and latched the pointer failsafe across the whole order until restart,
  and kept live checkout manual. At that stage, `KIOSK_ALLOW_CHECKOUT=1` added only a dry-run
  checkout trace; ADR-0002 and the newer entry above supersede that execution boundary.
- Repository hygiene: removed tracked IDE metadata and an empty root entry point, and added ignore
  rules for IDE files.
- Validation at that stage: added standard-library tests for launcher paths, calibration opt-in and failure
  propagation, configuration evaluation, menu indexing, malformed and unmatched orders, partial
  failure, full-payload rejection, order limits, overlapping execution, emergency stop, simulated
  checkout, manual live checkout, and full success. All 22 tests and syntax compilation passed
  locally and in GitHub Actions.
- Delivery: merged pull request #1 into `main`; pull-request and post-merge `quality` runs passed.
  The public README, architecture note, and work log returned HTTP 200, and repository description,
  homepage, and topics now identify the project as an accessibility hackathon prototype.
