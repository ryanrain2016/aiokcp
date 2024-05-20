import asyncio
import time

from aiokcp import create_connection, create_server


# copy from document from asyncio.Protocol
class EchoServerProtocol(asyncio.Protocol):
    def connection_made(self, transport):
        peername = transport.get_extra_info('peername')
        print('Connection from {}'.format(peername))
        self.transport = transport

    def data_received(self, data):
        message = data.decode()
        print('server: At {} Data received: {!r}'.format(time.time(), message))

        print('server: At {} Send: {!r}'.format(time.time(), message))
        self.transport.write(data)

        print('server: Close the client socket')
        self.transport.close()

# copy from document from asyncio.Protocol
class EchoClientProtocol(asyncio.Protocol):
    def __init__(self, message, on_con_lost):
        self.message = message
        self.on_con_lost = on_con_lost

    def connection_made(self, transport):
        transport.write(self.message.encode())
        print('client: At {} Data sent: {!r}'.format(time.time(), self.message))

    def data_received(self, data):
        print('client: At {} Data received: {!r}'.format(time.time(), data.decode()))

    def connection_lost(self, exc):
        print('client: The server closed the connection at {}'.format(time.time()))
        self.on_con_lost.set_result(True)

async def server():
    server = await create_server(EchoServerProtocol, '127.0.0.1', 8888, kcp_kwargs={
        # ...
    })
    async with server:
        await server.serve_forever()
    print('server done')

async def client():
    on_con_lost = asyncio.Future()
    transport, protocol = await create_connection(
        lambda: EchoClientProtocol('Hello World!', on_con_lost),
        '127.0.0.1', 8888, kcp_kwargs={
            # ...
        }
    )
    try:
        await on_con_lost
    finally:
        transport.close()

async def delay_client(delay = 1):
    await asyncio.sleep(delay)
    await client()

if __name__ == '__main__':
    async def main():
        await asyncio.gather(server(), client(), delay_client(1))

    asyncio.run(main())
