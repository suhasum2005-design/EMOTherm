# Review panel walkthrough

1. Start Python and React, open the landing page and explain Acquire → Recognize → Protect → Verify.
2. Create a normal user with public signup. Show that administration is not visible to this role.
3. Upload a thermal image from a TI or thermal th folder. Inspect original and CLAHE-normalized model input, then Analyze & secure.
4. Read prediction and five-class distribution. Explain the measured baseline and why probabilities are not certainty.
5. Select Verify integrity. Show record commitment, chain reference, AES-GCM and RSA-OAEP.
6. Browse history and filter by class/source/date. Open the stored result; the image is decrypted only for an authorized viewer.
7. Switch camera modes on Live Capture. Use a UVC thermal device for browser capture, and a configured OpenCV/ETH1 serial device for Python bridge capture. If hardware is absent, demonstrate clear unavailable-device behavior rather than inventing a live feed.
8. Save a camera preference and light/dark theme. Sign out and back in to demonstrate persistence.
9. Sign in using an explicitly provisioned Admin. Review system analytics, class report, confusion matrix, actual loss/accuracy curves and training history.
10. Change a user's role, inspect the audit event, and demonstrate disabled account enforcement.
11. Browse blockchain blocks, search a hash, and use Demonstrate tampering. The in-memory altered copy fails while the persisted chain remains valid.
12. Explain that centralized private chain is tamper-evident; it is not distributed consensus or an unconditionally immutable database.

For screenshots in the report, avoid exposing emails, private dataset paths, secrets or identifiable participant images unless consent allows them.
