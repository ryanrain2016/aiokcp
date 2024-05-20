import asyncio
import time

from aiokcp import open_connection, start_server


async def handle_echo(reader, writer):
    n = 21000
    while n:
        data = await reader.read(100)
        n -= len(data)
        message = data.decode()
        addr = writer.get_extra_info('peername')

        print(f"server: At {time.time()} Received {message!r} from {addr!r}")

        print(f"server: At {time.time()} Send: {message!r}")
        writer.write(data)
        await writer.drain()
    print(f"server: At {time.time()} Close the connection")
    await asyncio.sleep(10)
    writer.close()
    await writer.wait_closed()
    print(f'server: At {time.time()} Done')

async def kcp_echo_client(message):
    reader, writer = await open_connection(
        '127.0.0.1', 8888, kcp_kwargs={
            # ...
        })

    print(f'client: At {time.time()} Send: {message!r}', len(message))
    writer.write(message.encode())
    await writer.drain()
    n = len(message)
    while n > 0:
        data = await reader.read(1000)
        print(f'client: At {time.time()} Received: {data.decode()!r}', len(data), n)
        n -= len(data)

    print(f'client: At {time.time()} Close the connection', '#' * 20)
    writer.close()
    await writer.wait_closed()

async def server():
    server = await start_server(
        handle_echo, '127.0.0.1', 8888, kcp_kwargs={
            # ...
        })
    async with server:
        await server.serve_forever()
    print('server done')

async def main():
    await asyncio.gather(server(), kcp_echo_client('Hello World!'))

if __name__ == '__main__':
    asyncio.run(main())