from aiokcp import (create_connection, create_server, open_connection,
                    start_server)
from aiokcp.crypto import get_crypto
from aiokcp.sync import KCPSocket

# need cryptography installed

key = b'12345678901234567890123456789012'
salt = b'1234567890123456'

crypto = get_crypto(key, salt)

# or

class Crypto:

    def encrypt(self, data):
        pass

    def decrypt(self, data):
        pass

crypto = Crypto()

create_connection(..., crypto=crypto)

create_server(..., crypto=crypto)

open_connection(..., crypto=crypto)

start_server(..., crypto=crypto)


KCPSocket(..., crypto=crypto)

KCPSocket.create_connection(..., crypto=crypto)

KCPSocket.create_server(..., crypto=crypto)

KCPSocket.socket_pair(crypto=crypto)

