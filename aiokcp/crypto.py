import base64
import os

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    def _get_crypto(key, salt):
        key = PBKDF2HMAC(algorithm=hashes.SHA256(),
                                length=32,
                                salt=salt,
                                iterations=100000).derive(key)
        return Fernet(base64.urlsafe_b64encode(key))

    class CryptoWrapper:
        def __init__(self, key: bytes, salt: bytes):
            self._crypto = _get_crypto(key, salt)

        def encrypt(self, data):
            data = self._crypto.encrypt(data)
            return base64.urlsafe_b64decode(data)

        def decrypt(self, data):
            data = base64.urlsafe_b64encode(data)
            return self._crypto.decrypt(data)

    def get_crypto(key, salt):
        return CryptoWrapper(key, salt)

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