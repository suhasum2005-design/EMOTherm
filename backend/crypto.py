import os
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes


class Vault:
    def __init__(self, master_key, directory):
        self.master = AESGCM(master_key)
        directory.mkdir(parents=True, exist_ok=True)
        keyfile = directory / 'rsa-private.pem.enc'
        if keyfile.exists():
            pem = self.open(keyfile.read_bytes(), b'rsa-key')
            self.private = serialization.load_pem_private_key(pem, password=None)
        else:
            self.private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
            pem = self.private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
            keyfile.write_bytes(self.seal(pem, b'rsa-key'))

    def seal(self, raw, aad):
        nonce = os.urandom(12)
        return nonce + self.master.encrypt(nonce, raw, aad)

    def open(self, raw, aad):
        return self.master.decrypt(raw[:12], raw[12:], aad)

    def encrypt_record(self, image, result, aad):
        # A unique AES-256 data key per prediction is wrapped with RSA-OAEP.
        # GCM authenticates the owner's record ID, preventing ciphertext substitution.
        key = os.urandom(32)
        aes = AESGCM(key)
        def encrypt(raw):
            nonce = os.urandom(12)
            return nonce + aes.encrypt(nonce, raw, aad)
        wrapped = self.private.public_key().encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        return encrypt(image), encrypt(result), wrapped

    def decrypt_record(self, raw, wrapped, aad):
        key = self.private.decrypt(wrapped, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        return AESGCM(key).decrypt(raw[:12], raw[12:], aad)

    def sign(self, payload):
        return self.private.sign(
            payload,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256())

    def verify_signature(self, payload, signature):
        try:
            self.private.public_key().verify(
                signature, payload,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
                hashes.SHA256())
            return True
        except Exception:
            return False

    def public_key_pem(self):
        return self.private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)

    def public_key_fingerprint(self):
        der = self.private.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        return hashlib.sha256(der).hexdigest()
