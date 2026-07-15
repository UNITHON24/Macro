# Architecture and runtime boundary

## Data flow

1. `macro_pkg/macro/voice/audio.py` captures 16 kHz PCM frames and VAD state.
2. `audio_ws.py` streams the frames to the external speech backend.
3. The backend sends structured order items to `ordersHub.py` over HTTP.
4. `orders_client.py` polls the hub and hands a list of items to `OrderMacro`.
5. `OrderMacro` validates the entire bounded order before navigation and serializes execution.
6. `MenuIndex` maps each menu to a category, page, and screen coordinate.
7. `Navigator` emits dry-run output or live PyAutoGUI actions.
8. Live execution stops after cart input; the operator verifies state and completes checkout.

The local order hub deliberately has a small contract: `POST /api/orders` stores one order and
`GET /api/orders` returns it once. It is suitable for the prototype boundary, not durability or
concurrent production traffic.

## Safety invariants

- `KIOSK_DRY_RUN` defaults to true.
- Dry-run code does not move the pointer.
- OCR calibration is skipped unless `KIOSK_RUN_CALIBRATION` is explicitly enabled; calibration is
  a separate live desktop operation.
- PyAutoGUI's corner failsafe remains enabled for live pointer actions.
- Missing names, unknown menus, invalid quantities, and partial failures block checkout.
- The complete payload is validated before the first item action; defaults cap an order at 10 menu
  lines and 10 units per line.
- One non-blocking execution lock rejects overlapping order attempts.
- HTTP polling is the only order execution source. WebSocket order events never invoke the macro.
- `KIOSK_ALLOW_CHECKOUT` only enables a dry-run checkout trace. Live checkout is always manual.
- Activating PyAutoGUI's corner failsafe stops the current and remaining items, then latches the
  client closed until restart.

The tests use a fake navigator, so these invariants can be checked on CI without desktop access.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `KIOSK_UI_COORDS` | `macro_pkg/settingPack/kiosk_ui_coords_easyocr.json` | Category and navigation coordinates |
| `KIOSK_MENU_CARDS` | `settingPack/menu_cards.json` | Menu-to-coordinate index |
| `KIOSK_AUDIO_WS_URL` | `ws://localhost:8080/chat` | External audio WebSocket |
| `KIOSK_ORDERS_URL` | `http://localhost:9999/api/orders` | Local order handoff |
| `KIOSK_DRY_RUN` | `1` | Simulate pointer actions; set `0` for live clicks |
| `KIOSK_ALLOW_CHECKOUT` | `0` | Include the checkout coordinate in dry-run output only |
| `KIOSK_CHECKOUT_X`, `KIOSK_CHECKOUT_Y` | `989`, `1880` | Checkout coordinate used only for simulation |
| `KIOSK_MAX_ORDER_ITEMS` | `10` | Maximum menu lines accepted before any action |
| `KIOSK_MAX_ITEM_QUANTITY` | `10` | Maximum units accepted for one menu line |
| `KIOSK_RUN_CALIBRATION` | unset | Explicitly run the live OCR and pointer calibration pipeline |
| `KIOSK_BACKEND_DIR` | `Backend-master` in the repository root | External backend checkout used by the full launcher |

Audio, timing, VAD, WebSocket size, and path settings are defined in
`macro_pkg/macro/voice/config.py` and can also be overridden through environment variables.

## Ownership boundary

The canonical `macro_pkg/` tree represents the launcher, packaging, setup, and client-integration
scope. `kioskMacro/` and root experiments predate that integration and remain available as team
history. The external frontend and backend are dependencies, not code claimed by this repository's
client integration scope.
