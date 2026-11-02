"""Create a localhost-only self-signed certificate for an HTTPS demo."""
import datetime
import ipaddress
from pathlib import Path
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

folder=Path(__file__).resolve().parents[1]/'data/certs'
folder.mkdir(parents=True,exist_ok=True)
key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
stamp=datetime.datetime.now(datetime.timezone.utc)
cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(stamp).not_valid_after(stamp+datetime.timedelta(days=30)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).sign(key,hashes.SHA256()))
(folder/'localhost.key').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
(folder/'localhost.crt').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
print('Created data/certs/localhost.key and localhost.crt. Local demo only.')
