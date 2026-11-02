"""Local private-chain demonstration. DB permissions remain part of the trust boundary."""
import hashlib
import json


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def record_hash(ciphertext, prediction_ciphertext, metadata):
    # Both AES-GCM ciphertexts and canonical provenance are covered by one commitment.
    return hashlib.sha256(ciphertext + prediction_ciphertext + canonical(metadata)).hexdigest()


def mine(index, timestamp, data_hash, previous_hash, difficulty=2):
    block = dict(index=index, timestamp=timestamp, data_hash=data_hash, previous_hash=previous_hash, nonce=0)
    while True:
        h = digest(block)
        if h.startswith('0' * difficulty):
            return {**block, 'hash': h}
        block['nonce'] += 1


def is_chain_valid(blocks, difficulty=2):
    previous = '0' * 64
    for index, block in enumerate(blocks):
        unsigned = {k: block[k] for k in ('index', 'timestamp', 'data_hash', 'previous_hash', 'nonce')}
        if block['index'] != index or block['previous_hash'] != previous:
            return False
        if digest(unsigned) != block['hash'] or not block['hash'].startswith('0' * difficulty):
            return False
        previous = block['hash']
    return True
