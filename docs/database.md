# Database schema

SQLAlchemy models in `backend/models.py` are the executable schema. The local demo uses SQLite; Compose overrides the connection URL with PostgreSQL. All record IDs use UUID strings. ISO 8601 UTC timestamps are stored in sortable string form for this demonstration.

```mermaid
erDiagram
    USERS ||--o{ UPLOADS : owns
    UPLOADS ||--|| PREDICTIONS : produces
    BLOCKCHAIN_BLOCKS ||--|| PREDICTIONS : commits
    USERS ||--o{ AUTH_SESSIONS : authenticates
    AUTH_SESSIONS ||--o{ CAMERA_TICKETS : authorizes
    USERS ||--o{ AUDIT_LOGS : acts
    USERS {
      string id PK
      string email UK
      string password_hash
      string role
      boolean active
      string camera_mode
      string theme
    }
    UPLOADS {
      string id PK
      string user_id FK
      string source
      string timestamp
      binary ciphertext
      binary wrapped_key
      string mime
    }
    PREDICTIONS {
      string id PK,FK
      binary ciphertext
      integer block_index UK
    }
    BLOCKCHAIN_BLOCKS {
      integer index PK
      string timestamp
      string data_hash
      string previous_hash
      integer nonce
      string hash
    }
    AUTH_SESSIONS {
      string id PK
      string user_id FK
      string refresh_hash
      integer expires
      boolean revoked
    }
    CAMERA_TICKETS {
      string hash PK
      string user_id FK
      string session_id FK
      integer expires
    }
    AUDIT_LOGS {
      integer id PK
      string user_id
      string action
      string timestamp
      string ip
      string detail
    }
```

The diagram expresses logical relationships; prediction-to-block and audit-to-user references are logical links rather than physical foreign-key constraints in the demo schema. The `chain_lock` table contains one sentinel row used to serialize append transactions in PostgreSQL. Plain emotion labels, probabilities and confidence are stored inside prediction ciphertext, not as unencrypted prediction columns. Lists decrypt results only after checking authorization.

Images are encrypted binary DB objects, so no raw uploaded image paths are persisted. `data/rsa-private.pem.enc` contains the master-key-encrypted RSA private key. Audit rows and account profile fields remain plaintext as documented in the security model.

No migration engine is included; create_all supports initial setup. Add Alembic before making schema changes to an existing deployment.
