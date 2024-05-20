import asyncio
from asyncio import StreamReader, StreamReaderProtocol
from asyncio import StreamWriter as _StreamWriter

from .core import create_connection, create_server

_DEFAULT_LIMIT = 2 ** 16  # 64 KiB

class StreamWriter(_StreamWriter):
    async def wait_closed(self) -> None:
        await self.transport.wait_closed()
        return await super().wait_closed()

async def open_connection(host=None, port=None, *,
                          limit=_DEFAULT_LIMIT, **kwds):
    loop = asyncio.get_running_loop()
    reader = StreamReader(limit=limit, loop=loop)
    protocol = StreamReaderProtocol(reader, loop=loop)
    transport, _ = await create_connection(
        lambda: protocol, host, port, **kwds)
    writer = StreamWriter(transport, protocol, reader, loop)
    return reader, writer


async def start_server(client_connected_cb, host=None, port=None, *,
                       limit=_DEFAULT_LIMIT, **kwds):
    loop = asyncio.get_running_loop()

    def factory():
        reader = StreamReader(limit=limit, loop=loop)
        protocol = StreamReaderProtocol(reader, client_connected_cb,
                                        loop=loop)
        return protocol

    return await create_server(factory, host, port, **kwds)