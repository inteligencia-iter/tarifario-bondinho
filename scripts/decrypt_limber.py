"""
Decriptador para o padrao CryptoJS "Salted__" usado pela plataforma Limber Software
(confirmado em Paineiras-Corcovado, e provavelmente AquaRio e BioParque do Rio).

Algoritmo: OpenSSL/CryptoJS EVP_BytesToKey com MD5, 1 iteracao, AES-CBC.
"""
import base64
import hashlib
import json
import os
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad


def evp_bytes_to_key(password: bytes, salt: bytes, key_len: int = 32, iv_len: int = 16):
    """Replica CryptoJS/OpenSSL EVP_BytesToKey (MD5, 1 iteracao)."""
    d = b""
    prev = b""
    while len(d) < key_len + iv_len:
        prev = hashlib.md5(prev + password + salt).digest()
        d += prev
    return d[:key_len], d[key_len:key_len + iv_len]


def decrypt_cryptojs(ciphertext_b64: str, passphrase: str) -> str:
    """Decripta uma string no formato CryptoJS.AES.encrypt(text, passphrase).toString().

    Tolerante a respostas HTTP que vem com aspas JSON ao redor do valor
    (ex: '"U2FsdGVkX1..."'), que e o formato usual retornado pela API real."""
    if ciphertext_b64.startswith('"') and ciphertext_b64.endswith('"'):
        ciphertext_b64 = json.loads(ciphertext_b64)
    raw = base64.b64decode(ciphertext_b64)
    assert raw[:8] == b"Salted__", "Formato inesperado, nao comeca com 'Salted__'"
    salt = raw[8:16]
    ciphertext = raw[16:]
    key, iv = evp_bytes_to_key(passphrase.encode(), salt)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = unpad(cipher.decrypt(ciphertext), AES.block_size)
    return decrypted.decode("utf-8")


def encrypt_cryptojs(plaintext: str, passphrase: str) -> str:
    """Cifra uma string no formato CryptoJS.AES.encrypt(text, passphrase).toString()."""
    salt = os.urandom(8)
    key, iv = evp_bytes_to_key(passphrase.encode(), salt)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    ct = cipher.encrypt(pad(plaintext.encode(), AES.block_size))
    return base64.b64encode(b"Salted__" + salt + ct).decode()


def host_signature(hostname: str) -> str:
    """Formula descoberta via engenharia reversa: hostname com string invertida, depois base64.
    Usado no parametro/header 'xlh' da API da plataforma Limber Software."""
    return base64.b64encode(hostname[::-1].encode()).decode()


if __name__ == "__main__":
    import sys
    passphrase = sys.argv[1] if len(sys.argv) > 1 else "ecck-SV6QdGk1NCg1NaXzQ"
    data = sys.stdin.read().strip()
    # Remove aspas externas se vier de um JSON string ("...")
    if data.startswith('"') and data.endswith('"'):
        data = json.loads(data)
    result = decrypt_cryptojs(data, passphrase)
    print(result)
