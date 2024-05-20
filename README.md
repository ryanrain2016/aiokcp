# aiokcp
[kcp](https://github.com/skywind3000/kcp)的python实践, 提供了类似python中TCP相关的标准库相同的编程接口(asyncio, socket, socketserver)，原tcp代码使用修改导入的方式可以轻松实现从tcp到kcp的平移替换。

## 什么是KCP？
KCP是一个致力于低延时的基于UDP自动重传的可靠传输协议。本身不包含任何网络传输的功能，使用回调的方式处理udp数据包的传输。详情见[kcp](https://github.com/skywind3000/kcp)

## 例子
例子详见`aiokcp/examples`目录
### asyncio 低级接口
这里实现了类似`loop.create_connection`和`loop.create_server`的功能
```py
import asyncio
import time

from aiokcp import create_connection, create_server


# copy from document of asyncio.Protocol
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

# copy from document of asyncio.Protocol
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
    server = await create_server(EchoServerProtocol, '127.0.0.1', 8888,
        kcp_kwargs={ # optional
            # ...
        })
    async with server:
        await server.serve_forever()
    print('server done')

async def client():
    on_con_lost = asyncio.Future()
    transport, protocol = await create_connection(
        lambda: EchoClientProtocol('Hello World!', on_con_lost),
        '127.0.0.1', 8888,
        kcp_kwargs={   # optional
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

```

### asyncio高级接口
```py
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
```

### 同步的kcp socketpair
```py
from aiokcp.sync import KCPSocket

sock1, sock2 = KCPSocket.socket_pair()
sock1.send(b'123')
print(sock2.recv(100))
sock2.send(b'234')
print(sock1.recv(100))
```
### 同步的kcp 简单服务器-客户端
```py
from aiokcp.sync import KCPSocket

sock1 = KCPSocket.create_server(('127.0.0.1', 18586))
sock2 = KCPSocket.create_connection(('127.0.0.1', 18586))
server_sock, _ = sock1.accept()
server_sock.send(b'123')
print(sock2.recv(100))
sock2.send(b'234')
print(server_sock.recv(100))
```

### 同步的kcp socketserver
```py
import os
import threading
import time

from aiokcp.sync import (BaseRequestHandler, KCPSocket, KCPThreadingServer,
                         StreamRequestHandler)


class Handler(BaseRequestHandler):
    def handle(self):
        nbytes = 0
        while True:
            # self.request is the KCP socket connected to the client
            data = self.request.recv(1024)
            print("Received from {}:{}".format(*self.client_address))
            # print("Data: {}".format(data))
            # just send back the same data
            # there is no mechanism to check if the connection is broken in kcp, but timeout.
            # when timeout occurs, the connection will be closed, recv will return empty bytes
            if not data:
                break
            nbytes += self.request.send(data)
            print('server recved: {} sent: {}'.format(nbytes, len(data)))
        print('server handle end ##################')

def server_thread(port):
    kw = {
        'kcp_kwargs': {
            # ...
        }
    }
    server = KCPThreadingServer(('127.0.0.1', port), Handler, **kw)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()

def client_thread(port):
    kw = {
        'kcp_kwargs': {
            # ...
        }
    }
    sock = KCPSocket.create_connection(('127.0.0.1', port), **kw)
    sent_buf = b'abc'
    sock.send(sent_buf)
    for _ in range(1):
        b = os.urandom(7 * 1000)
        sent_buf += b
        sock.send(b)
    print('###########', len(sent_buf), '###########')
    n = len(sent_buf)
    buf = b''
    while n > 0:
        data = sock.recv(1024)
        buf += data
        if data:
            n -= len(data)
        else:
            break
        print('client recv', len(buf), len(data)) # print(buf, len(data))
        if buf[:7003-n] != sent_buf[:7003-n]:
            # ensure sent in order
            print('error')
            print(buf[:7003-n])
            print(sent_buf[:7003-n])
            break
    print('client handle end', '###############')

    time.sleep(1)
    sock.close()


if __name__ == '__main__':
    def thread_test():
        from random import randint
        port = randint(10000, 20000)
        server_thread(port)
        client_thread(port)

    thread_test()
```
### 同步的kcp socketserver 流处理
```py
import os
import threading
import time

from aiokcp.sync import (BaseRequestHandler, KCPSocket, KCPThreadingServer,
                         StreamRequestHandler)


class StreamHandler(StreamRequestHandler):
    def handle(self):
        print('handling')
        n = 0
        while True:
            # self.rfile is a file-like object created by the handler;
            # we can now use e.g. readline() instead of raw recv() calls
            data = self.rfile.readline().strip()
            if not data or data == 'end':
                break
            n += len(data)
            print('server recved: {} sent: {}'.format(n, len(data)))
            # Likewise, self.wfile is a file-like object used to write back
            # to the client
            self.wfile.write(data)
            self.wfile.flush()
        print('server handle end ##################')
        time.sleep(1)
        self.wfile.close()
        self.request.close()

def server_thread(port):
    kw = {
        'kcp_kwargs': {
            # ...
        },
        'stream': 1
    }
    server = KCPThreadingServer(('127.0.0.1', port), StreamHandler, **kw)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()

def client_thread(port):
    kw = {
        'kcp_kwargs': {
            # ...
        },
        'stream': 1
    }
    sock = KCPSocket.create_connection(('127.0.0.1', port), **kw)
    sent_buf = b'abc\ndef\nghi\njkl\nmno\npqr\nstu\nvwx\nyza\nend\n'
    sock.send(sent_buf)
    buf = b''
    while len(buf) < 27:
        buf += sock.recv(27)
    print('client recv', buf)

if __name__ == '__main__':
    def thread_test():
        from random import randint
        port = randint(10000, 20000)
        server_thread(port)
        client_thread(port)

    thread_test()
```
### 可选的udp数据包加密
内置的加密方法需要安装`cryptography`, 默认采用的aes+cbc模式加密。也可以自定义加密对象, 只需要实现`encrypt`和`decrypt`方法即可
```py
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
    # need to implement encrypt and decrypt method
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
```

### 相关配置
kcp默认配置如下，可以通过传递`kcp_kwargs`参数到相应的方法，改变相关配置，`kcp_kwargs`不用每个参数都设置，没有设置的使用默认值
```py
default_update_interval = 100  # ms

default_kcp_kwargs = {
    'max_transmission': 1400,
    'no_delay'        : True,
    'update_interval' : default_update_interval,
    'resend_count'     : 2,
    'no_congestion_control': False,
    'send_window_size': 32,
    'receive_window_size': 128,
    'stream': 0
}

default_timeout = 600
```
#### 相关配置修改
`KCPServer`, `KCPSteamTransport`, `sync.KCPServer`, `sync.KCPSocket`均提供下面的方法修改相关的配置
```py
def set_nodelay(self, no_delay: bool, update_interval: int, resend_count: int, no_congestion_control: bool):
    pass

def set_wndsize(self, send: int, receive: int):
    pass

def set_mtu(self, max_transmission: int):
    pass

def set_stream(self, stream: bool):
    pass
```

# 功能
- [x] asyncio低级接口: Protocol
- [x] asyncio高级接口: Stream
- [x] 同步的kcp socket的实现
- [x] 同步的kcp socketserver的实现
- [x] 可选的udp数据包加密
- [ ] close时通知对方关闭socket
- [ ] 支持tls/ssl
