# Security model and academic claims

## Boundaries

The deployment owns the master encryption key, JWT secret, encrypted RSA private key, database, and local chain. Unauthorized users cannot browse another user's scans. Admins may access any scan via the record endpoint for review and manage account roles; this privilege should be disclosed to research participants. Blockchain explorer exposes hashes and timestamps, not raw evidence, user identity or plaintext predictions.

AES-GCM protects confidentiality and ciphertext authenticity. RSA-OAEP wraps unique data keys. SHA-256 chain links expose changes to previously committed data. Two leading zeroes are demonstration proof of work and provide no meaningful adversarial consensus guarantee. An attacker controlling the entire database and secrets can decrypt evidence or rewrite and re-mine the whole chain. External trusted anchoring or independent validator nodes are necessary to defend against that attacker.

Raw uploads live only in request memory; encrypted image bytes and encrypted prediction bytes are persisted in separate tables. API responses may include decrypted evidence for an authorized user. Names/emails, audit events and timestamps are not encrypted in the current schema. Back up the DB, .env and encrypted RSA key securely together; never copy private secrets into reports or public repositories.

Refresh token rotation is persisted; access JWTs reference a revocable DB session. Tokens are held in frontend memory, and refresh cookies are HttpOnly. Logout revokes the session; password changes revoke all of a user's sessions. Account disablement prevents token reuse. Public signup cannot choose its role. Cookie refresh/login/signup verify Origin when provided; SameSite=Strict cookies constrain cross-site browser requests. Bearer-protected mutations do not use ambient cookie authentication.

The local rate limiter is per process, suitable for a single-worker demo. Behind the provided Nginx, request IP records the proxy address unless trusted proxy settings are configured. Configure Uvicorn's proxy trust only for the actual proxy network before claiming real client-IP audit fidelity. Do not trust arbitrary forwarded headers from the Internet.

SQLite uses local file storage for ease of setup; Compose uses PostgreSQL. Production schema upgrades need Alembic migrations rather than create_all. The audit table is useful for review but not independently append-only against database administrators. No fake distributed immutability claims should appear in a project report.

## Report language

“The system demonstrates encrypted thermal emotion inference with tamper-evident, hash-linked provenance in a simulated private chain.”

Explain evaluation split assumptions, measured accuracy, radiometric limitations of palette images, dataset imbalance, uncertain subject identities, and lack of hardware validation. Predictions from facial temperature alone are not established ground truth for an individual's emotional state.
