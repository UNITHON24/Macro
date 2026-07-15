# Voice Kiosk Macro

[한국어](README.ko.md)

Voice Kiosk Macro is a UNITHON 2024 accessibility prototype that turns a spoken order into
structured menu items and operates a fixed-layout kiosk UI. The repository is a hackathon
archive, not a deployed service; it documents the integration boundary, safety controls, and
known limitations so the work can be reviewed without overstating its maturity.

## What it demonstrates

- 16 kHz microphone streaming and VAD over WebSocket
- HTTP handoff of structured order items through a local order hub
- OCR-assisted indexing of menu categories, pages, and screen coordinates
- Deterministic navigation from a validated menu item to kiosk pointer actions
- Safe-by-default dry runs, bounded orders, and operator-confirmed manual checkout

```mermaid
flowchart LR
    A[Microphone] -->|PCM / WebSocket| B[Speech backend]
    B -->|Structured order| C[Local order hub]
    C --> D[Order validation]
    D --> E[Menu index]
    E --> F[Kiosk navigator]
    F -->|Dry run by default| G[Pointer actions]
```

The speech backend and kiosk web application are external team components and are not included
in this repository.

## Repository map

| Path | Purpose | Status |
| --- | --- | --- |
| `macro_pkg/` | Launcher, setup pipeline, voice client, order hub, and kiosk integration | Canonical client path |
| `tests/` | Dependency-free tests for configuration, menu indexing, and order safety | Runs in CI |
| `kioskMacro/` | Earlier team client snapshot retained for provenance | Legacy reference |
| `settingPack/`, root utilities | Original OCR captures and experiments | Legacy reference |

The two client trees are intentionally not merged in place. See
[the architecture note](docs/ARCHITECTURE.md) and
[ADR-0001](docs/adr/0001-preserve-hackathon-snapshot.md) for the boundary and trade-off.

## Verify the safe core

The quality gate uses only the Python standard library and does not move the pointer, open a
microphone, or contact a server.

```bash
python -m compileall -q macro_pkg tests
python -m unittest discover -s tests -v
```

CI runs the same checks on Python 3.11.

## Local runtime

The client targets a Windows kiosk environment and requires Python 3.10 or newer. Native audio,
OCR, and desktop-automation packages may require OS-level setup.

```powershell
py -m venv .venv
.venv\Scripts\activate
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
```

The full launcher expects the team's backend checkout outside this repository. Set
`KIOSK_BACKEND_DIR` to that directory, then run:

```powershell
py macro_pkg\launcher.py
```

If the backend is already running on port 8080, use:

```powershell
py macro_pkg\launcherNonback.py
```

Both launchers use the checked-in calibration data and do not start OCR calibration by default.
To regenerate coordinates and the menu index against a non-production kiosk, explicitly opt in:

```powershell
set KIOSK_RUN_CALIBRATION=1
py macro_pkg\launcherNonback.py
```

Calibration opens the configured kiosk and performs live pointer actions even when the order
client remains in dry-run mode. Keep PyAutoGUI's corner failsafe available throughout calibration.

## Safety controls

Pointer actions are simulated unless live clicks are explicitly enabled:

```powershell
set KIOSK_DRY_RUN=0
```

The client validates the complete order before the first pointer action, limits orders to 10 menu
lines and 10 units per line by default, and serializes execution. The HTTP order hub is the only
execution source; WebSocket `macro.trigger` events are informational so the same order cannot race
through two client paths.

Checkout automation is simulation-only. It can be included in a dry-run trace with:

```powershell
set KIOSK_ALLOW_CHECKOUT=1
```

In live mode, the client stops after adding validated items and requires an operator to verify the
cart, quantity, price, and current UI before manually continuing. PyAutoGUI's corner failsafe
remains enabled and aborts the rest of the order when activated. Coordinates, limits, and
endpoints can be overridden with the environment variables listed in
[the architecture note](docs/ARCHITECTURE.md).
After an emergency stop, the client rejects later orders until it is restarted and the operator
has checked the kiosk state.

## Contribution boundary

This was a team hackathon project. The `macro_pkg/` launcher, configuration, packaging, and
integration are the scope represented here; the speech backend, frontend, and earlier team client
are not presented as individual work.

## Limitations

- Coordinates depend on a particular resolution and kiosk layout.
- OCR assists calibration but does not remove layout drift at runtime.
- Desktop permissions, audio devices, and native libraries make the runtime platform-specific.
- The local order hub is an in-memory single-process handoff, not a durable queue.
- The launcher starts external child processes but does not yet supervise or restart them.
- Native runtime dependencies are declared but are not audited by the dependency-free CI gate.
- There is no production deployment, user study, or long-term maintenance claim.

For a production accessibility feature, an application-level accessibility API or explicit kiosk
command contract would be more reliable than coordinate automation.
