# Verification scope

## Passage adaptation (0.4.0)

The Linux suite includes 23 tests covering the encrypted vault, persistence across
restart, local OCR on an actual rendered image, sessions, deletion, receipts,
privacy exclusions, opt-in capture and a window becoming private during OCR.
The gated suite exercises real X11 input and both browser interfaces. The Passage
browser test drives Recall, Timeline, Sessions, Access History, handoff, deletion
and responsive layouts, with zero console errors or external requests. A local
axe-core script checks WCAG 2.1 A/AA at the tested widths.

Windows verification is separate. The native OCR test runs the Windows WinRT
recognizer against a rendered image. An interactive-session test captures a real,
clearly labelled WinForms verification window, reads `ORCHID RIVER 4729` from the
saved screenshot, verifies encrypted image round-trip, and verifies disabled
capture does not add moments. These are real Windows API calls, not mocked
screens or invented OCR responses.

A separate on-device Chromium fixture verifies non-black image pixels and native
OCR of `ORCHID CHROME RIVER 5821`. Windows uses the visible foreground-window
rectangle because PrintWindow can return black GPU-composited browser frames.
Verification checks actual Windows foreground identity, not merely CDP tab focus.

The installed browser suite exercises all four views, real screenshot retrieval,
context handoff, pause/resume, responsive geometry and axe checks on Windows.
Receipt source previews are resolved from existing moments rather than stored as
extra text copies: deleting the moment also removes its preview from the receipt.

The verification images contain deliberately labelled test content, not personal
history. Application tests use disposable data directories. Do not run screenshot
fixtures against a user's unrelated documents.

Source/package and final installed-UI checks are recorded by the release runner.
A pass from Linux alone does not certify Windows desktop visibility. The Windows
recorder must run in the interactive session and return a fresh receipt; Session
0 process/window inspection and Task Scheduler return codes are insufficient.

## Context inference (0.4.0)

Inference is a separate opt-in layer, off by default. A local OpenAI-compatible
stub records exactly what each request contained, and the suite asserts:

- no request is made while inference is off, during search, or on any read path
- the request carries text, window titles, app names and timestamps only: no image
  bytes, no media path, no vault key and no window geometry
- the API key is sealed in the vault, absent from every API response and never logged
- the prompt is capped, keeps the newest moments, and sends the chosen moments plus
  same-app neighbours within fifteen minutes, never unrelated apps
- null content, fenced JSON, malformed JSON, a non-object reply and wrong field
  types are typed failures; one repair attempt is allowed, and a second failure is
  reported as a failure rather than replaced by an invented reading
- cited moment ids that were not sent are dropped, and such a reading is marked
  unverified; an unknown confidence value degrades to low
- an endpoint that rejects `response_format` is retried plainly, and a dead endpoint
  or rejected request reports a transport failure with no receipt
- every successful call commits a receipt carrying the endpoint, model and duration,
  and the inferred context is stored encrypted so Access History can re-read it

The gated browser suite drives the real UI end to end: the off state with its honest
message, enabling the layer through the Settings form, a real call to the stub, the
rendered reading with confidence, entities, open threads and source links, the
receipt naming the endpoint in Access History, viewport checks, axe checks, no
console errors and no browser request leaving the local origin.

## Boundaries

- The upstream macOS app was inspected as the design and feature reference. Its
  Swift, CoreML, SQLCipher and external-agent stack were not ported wholesale.
- The current search is lexical OCR search, not semantic or generative AI.
  Inference is a separate opt-in call to an endpoint you configure, not a bundled
  local model, and its reading is labelled as inference in the UI.
- Receipts document what this UI prepared or sent. They are not a kernel-level audit
  of every local read.
- Encrypted payloads are not a fully encrypted database: timestamps and sizes are
  visible, and legacy title history remains in its original plaintext SQLite DB.
- Private-window detection is best-effort. Pause before sensitive work.
- Linux screenshot capture is secondary; the primary deployment is Windows.
- Automated accessibility checks are not a complete manual accessibility audit.

The earlier collector's storage, CSV safety, DST clipping, launcher-lock handling,
pause persistence, aggregate input counts and Windows history preservation remain
covered by the same tests rather than being replaced by screenshot-only checks.
