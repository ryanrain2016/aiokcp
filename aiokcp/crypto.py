import base64
import os

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers import Cipher
    from cryptography.hazmat.primitives.ciphers.algorithms import AES
    from cryptography.hazmat.primitives.ciphers.modes import CBC
    from cryptography.hazmat.primitives.hmac import HMAC
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.padding import PKCS7

    class InvalidToken(Exception):
        pass

    class AES_CBC:
        def __init__(self, key: bytes, salt: bytes, key_size: int = 256):
            key_sizes = frozenset([128, 192, 256])
            if key_size not in key_sizes:
                raise ValueError('block_size must be one of {}'.format(key_sizes))
            key_length = key_size // 8
            key = PBKDF2HMAC(algorithm=hashes.SHA256(),
                                length=key_length * 2,
                                salt=salt,
                                iterations=480000).derive(key)
            self._signing_key = key[:key_length]
            self._encryption_key = key[key_length:]

        def encrypt(self, data):
            padder = PKCS7(AES.block_size).padder()
            padded = padder.update(data) + padder.finalize()
            iv = os.urandom(AES.block_size // 8)
            cipher = Cipher(AES(self._encryption_key), CBC(iv)).encryptor()
            ciphered = cipher.update(padded) + cipher.finalize()
            h = HMAC(self._signing_key, hashes.SHA256())
            h.update(iv + ciphered)
            return iv + ciphered + h.finalize()

        def _verify_token(self, token):
            if len(token) < 32:
                raise InvalidToken
            iv = token[:AES.block_size // 8]
            ciphered = token[AES.block_size // 8:-32]
            h = HMAC(self._signing_key, hashes.SHA256())
            h.update(iv + ciphered)
            try:
                h.verify(token[-32:])
            except InvalidToken:
                raise InvalidToken
            return iv, ciphered

        def decrypt(self, data):
            iv, ciphered = self._verify_token(data)
            cipher = Cipher(AES(self._encryption_key), CBC(iv)).decryptor()
            padded = cipher.update(ciphered) + cipher.finalize()
            unpadder = PKCS7(AES.block_size).unpadder()
            return unpadder.update(padded) + unpadder.finalize()

    def get_crypto(key, salt):
        return AES_CBC(key, salt)

except ImportError:
    def get_crypto(key, salt):
        raise ImportError('cryptography is not installed')

if __name__ == "__main__":
    key = b'1234567890123456789012345611789012'
    salt = b'123456789011123456'
    crypto = get_crypto(key, salt)
    print()
    s = os.urandom(1000)
    print(ss := crypto.encrypt(s))
    print(len(sss:=base64.urlsafe_b64decode(ss)))
    print(crypto.decrypt(ss) == s)