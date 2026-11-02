# Verification record

Verified on the local Windows host during implementation, 18 September 2026.

## Software checks completed

- `python -m pytest tests -q`: **14 passed** (15.19 seconds on the initial full run).
- Python syntax compilation for backend, ML, blockchain, camera and utility modules.
- Vite production build using `vite.portable.config.js`: **passed**, 2,579 modules transformed.
- Real dataset training: 20 epochs; 838 thermal files discovered; seven exact duplicates and six unreadable files excluded; 825 usable unique images.
- Train/validation/test counts: 495/165/165. Held-out test accuracy: **0.3575757576**. Macro F1: approximately **0.283**. Metrics are actual measured outputs.
- Matplotlib exports of loss, accuracy and confusion matrix in SVG and PNG formats.
- After plot integration, a separate one-epoch training smoke run completed and exported checkpoint, metrics, split manifest, training history and all six plot files. The delivered 20-epoch model was preserved.
- Browser sign-in, protected dashboard, image file chooser, preprocessing preview, real model inference, encrypted result retrieval, Verify Integrity success, hash explorer and safe tamper demonstration.
- Browser checks for history, settings, camera selection page, system analytics, user management, model metrics and audit log: distinct routes rendered.
- Browser warnings/errors during the authenticated flow: none observed.
- Mobile viewport check: dashboard and audit page render at 390px override; content width equals viewport width; sidebar navigation opens/closes and closed links are inert; tables scroll within their card.

The standard esbuild subprocess path was restricted by the execution environment. Dependencies were installed from npm with install scripts skipped, and a separate portable Vite configuration uses Babel and in-process Rollup for a successful production build. The conventional Vite configuration remains available for development and optimized builds on unrestricted machines. The included compiled frontend can be served directly with the full Python API via `python -m scripts.serve_preview`.

## What the tests prove

Auth tests enforce normal signup roles, protected API access, invalid passwords, rotation of refresh tokens, stale refresh rejection, logout revocation, password-change revocation, origin rejection, settings persistence and rate limits.

Record tests submit an image through actual model inference, inspect encrypted DB bytes, retrieve authorized evidence, verify commitments and reject other users. Ciphertext alteration and chain-hash alteration are detected. New writes stop if the chain is invalid. Upload decoding/MIME validation rejects malformed inputs.

Admin tests exercise analytics, measured metrics, safe tamper demo, role changes, account disablement and security logs.

Camera tests create a local MJPEG video and acquire it through the real OpenCV VideoCapture driver. A session-ticket authenticated WebSocket returns real encoded frames; capture passes the server frame through inference, encryption and chain verification. Serial tests decode the actual ETH1 frame format from a byte-stream test double and reject bad dimensions. Browser PNG inputs tagged uvc use the same pipeline. These do not prove physical device or SDK compatibility.

## Still dependent on your environment

- **Physical thermal cameras:** none was specified or connected for testing. UVC acquisition, sensor drivers, serial firmware, radiometric properties and disconnect behavior need testing with the chosen device.
- **Vendor SDK adapter:** interface and bridge are implemented; a specific adapter requires the model and its SDK documentation. ETH1 is an explicit supported serial format, not a universal vendor protocol.
- **Docker/PostgreSQL:** Docker CLI was unavailable on the host, so the Compose deployment was not run. Backend tests used SQLite. Container builds, database driver and device passthrough need verification on a Docker-enabled host.
- **HTTPS:** configuration and localhost certificate generator are included; browser certificate trust and physical camera access over HTTPS were not exercised.
- **Subject-independent evaluation:** source subject IDs were not available; image-level metrics can overestimate performance on unseen people. Use documented subject grouping before making stronger academic accuracy claims.
- **Public hosting:** not performed. The app and dataset integration are local, preserving the requested Python/hardware architecture.
