"""Generate private local secrets; never overwrite existing configuration."""
import base64
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / '.env'
if path.exists():
    raise SystemExit('.env already exists; preserved.')
template = (root / '.env.example').read_text()
template = template.replace('JWT_SECRET=GENERATE_WITH_scripts_init_env', 'JWT_SECRET=' + secrets.token_urlsafe(48))
template = template.replace('AES_MASTER_KEY=GENERATE_WITH_scripts_init_env', 'AES_MASTER_KEY=' + base64.b64encode(secrets.token_bytes(32)).decode())
template = template.replace('POSTGRES_PASSWORD=GENERATE_WITH_scripts_init_env', 'POSTGRES_PASSWORD=' + secrets.token_hex(24))
path.write_text(template)
print('Created private .env. Keep it outside source control.')
