import os
import struct


def conv_bytes_to_id(data: bytes) -> int:
    if not data:
        return 0
    return struct.unpack('<I', data)[0]

def conv_id_to_bytes(id: int) -> bytes:
    return struct.pack('<I', id)

def random_id() -> int:
    return int.from_bytes(os.urandom(4), 'big')