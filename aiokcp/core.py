import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from .kcp import KCP
from .utils import conv_bytes_to_id, random_id

__all__ = ['create_connection', 'create_server', 'KCPStreamTransport', 'KCPServer']

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

@dataclass
class KCPStreamTransport(asyncio.Transport):
    kcp: KCP
    address: tuple[str, int]
    transport: asyncio.DatagramTransport   # UDP transport
    _extra: dict = None
    protocol: asyncio.Protocol = None

    timeout: float = default_timeout
    is_server: bool = False
    crypto: Any = None

    # def __init__(self, kcp: KCP, address: tuple[str, int], transport: asyncio.DatagramTransport):
    #     self.kcp = kcp
    #     self.address = address
    #     self.transport = transport

    def __post_init__(self):
        if self._extra is None:
            self._extra = {}
        self.last_active = time.perf_counter()
        self.kcp.set_output_handler(self._send_to)
        self.__is_closing: bool = False
        self._closed = None
        self._is_reading: bool = True
        self._loop = asyncio.get_running_loop()

    @property
    def update_interval(self):
        return self._extra.get('update_interval', default_update_interval)

    def set_nodelay(self, no_delay: bool, update_interval: int, resend_count: int, no_congestion_control: bool):
        self.kcp.set_nodelay(no_delay, update_interval, resend_count, no_congestion_control)
        self._extra.update(no_delay=no_delay,
                                update_interval=update_interval,
                                resend_count=resend_count,
                                no_congestion_control=no_congestion_control)
        return self

    def set_wndsize(self, send: int, receive: int):
        self.kcp.set_wndsize(send, receive)
        self._extra.update(send_window_size=send, receive_window_size=receive)
        return self

    def set_mtu(self, max_transmission: int):
        self.kcp.set_mtu(max_transmission)
        self._extra.update(max_transmission=max_transmission)
        return self

    def set_stream(self, stream):
        stream = int(bool(stream))
        self.kcp.set_stream(stream)
        self._extra.update(stream=stream)
        return self

    def _send_to(self, _, data):
        if self.crypto is not None:
            try:
                data = self.crypto.encrypt(data)
            except:
                pass
        self.transport.sendto(data, self.address)

    def __update_activity(self):
        self.last_active = time.perf_counter()

    def update(self, ts_ms: Optional[int] = None) -> None:
        if self.kcp:
            return self.kcp.update(ts_ms)

    def set_protocol(self, protocol: asyncio.BaseProtocol) -> None:
        assert self.protocol is None
        self.protocol = protocol

    def get_protocol(self) -> asyncio.BaseProtocol:
        return self.protocol

    def is_reading(self) -> bool:
        return self._is_reading

    def pause_reading(self) -> None:
        self._is_reading = False

    def resume_reading(self) -> None:
        self._is_reading = True
        if self.protocol is not None:
            for data in self.kcp.get_all_received():
                self.protocol.data_received(data)

    def write(self, data: bytes | bytearray | memoryview) -> None:
        if not data or self.is_closing():
            return
        data = bytes(data)
        self.kcp.enqueue(data)
        self.kcp.update(int(time.perf_counter() * 1000))
        self.__update_activity()

    def write_eof(self) -> None:
        self.kcp.enqueue(b'')
        self.__update_activity()

    def can_write_eof(self) -> bool:
        return False

    def abort(self) -> None:
        self.transport.abort()
        if self.protocol is not None:
            self.protocol.connection_lost(ConnectionAbortedError("abort"))

    def close(self) -> None:
        if self.__is_closing:
            return
        self.__is_closing = True
        self._closed = asyncio.Future()
        self.update()
        self.kcp.flush()
        async def wait_flush():
            cnt = 5000 / self.update_interval
            while self.kcp.get_waitsnd() > 0 and (cnt := cnt -1) > 0:
                await asyncio.sleep(self.update_interval / 1000)
                self.update()
            await asyncio.sleep(0.1) # wait for last ack to send
            self.kcp = None

        def close_transport(_):
            if not self.is_server:
                self.transport.close()
            self._closed.set_result(None)

        task = asyncio.create_task(wait_flush())
        task.add_done_callback(close_transport)

        if self.protocol is not None:
            self.protocol.connection_lost(None)


    def is_closing(self) -> bool:
        return self.__is_closing

    async def wait_closed(self):
        await self._closed
        self._closed = None

    def _feed_data(self, data):
        if self.kcp is None:
            return
        conv_id = conv_bytes_to_id(data[:4])
        if conv_id != self.kcp.get_conv_id():
            return
        try:
            self.kcp.receive(data)
        except Exception as e:
            self._loop.call_exception_handler({
                'message': 'KCP receive error',
                'exception': e,
                'transport': self
            })
        self.__update_activity()
        if self.protocol is not None and self._is_reading:
            for data in self.kcp.get_all_received():
                self.protocol.data_received(data)

    def get_extra_info(self, name, default=None):
        if name in self._extra:
            return self._extra[name]
        return self.transport.get_extra_info(name, default)

    async def _update_loop(self):
        while not self.is_closing():
            current = time.perf_counter()
            current_ts = int(current * 1000)
            await asyncio.sleep(self.update_interval / 1000)
            self.update(current_ts)
            if current - self.last_active > self.timeout:
                self.close()
                break

class _KCPClientUDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, kcp_kwargs, crypto=None):
        self._kcp_kwargs = kcp_kwargs
        self._kcp = KCP(**self._kcp_kwargs)
        self._transport:KCPStreamTransport | None = None
        self.crypto = crypto

    def datagram_received(self, data, addr):
        if len(data) < 24:
            return
        if self._transport is None:
            return
        if self.crypto is not None:
            try:
                data = self.crypto.decrypt(data)
            except:
                pass
        self._transport._feed_data(data)

    def error_received(self, exc):
        logger = logging.getLogger(__name__)
        logger.exception("KCP on UDP error: %s", exc)
        self._transport.abort()


async def create_connection(protocol_factory, host, port, *,
                                 loop=None, kcp_kwargs=None, timeout=default_timeout, crypto=None) -> KCPStreamTransport:
    _kcp_kwargs = default_kcp_kwargs.copy()
    _kcp_kwargs.update(kcp_kwargs or {})
    kcp_kwargs = _kcp_kwargs
    if 'conv_id' not in kcp_kwargs:
        conv_id = random_id()
        kcp_kwargs['conv_id'] = conv_id
    if loop is None:
        loop = asyncio.get_event_loop()

    proto = _KCPClientUDPProtocol(kcp_kwargs, crypto=crypto)

    transport, _ = await loop.create_datagram_endpoint(
        lambda: proto,
        remote_addr=(host, port))
    transport = KCPStreamTransport(proto._kcp,
                                             (host, port),
                                             transport,
                                             {**kcp_kwargs, 'peername': (host, port)},
                                             timeout=timeout, crypto=crypto)
    proto._transport = transport
    asyncio.create_task(transport._update_loop())
    kcp_proto = protocol_factory()
    transport.set_protocol(kcp_proto)
    kcp_proto.connection_made(transport)
    return transport, kcp_proto

class _KCPServerUDPProtocol(asyncio.DatagramProtocol):

    _transport_map: dict[tuple[str, int], KCPStreamTransport] = {}

    def __init__(self, kcp_kwargs, protocol_factory, timeout=default_timeout, crypto=None):
        self._kcp_kwargs = kcp_kwargs
        self._timeout = timeout
        self.protocol_factory = protocol_factory
        self.crypto = crypto

    def connection_made(self, transport):
        self._transport = transport

    def datagram_received(self, data, addr):
        if len(data) < 24:
            return
        if self.crypto is not None:
            try:
                data = self.crypto.decrypt(data)
            except:
                pass
        if addr in self._transport_map:
            transport = self._transport_map[addr]
        else:
            conv_id = conv_bytes_to_id(data[:4])
            kcp = KCP(**self._kcp_kwargs, conv_id=conv_id)
            transport = KCPStreamTransport(kcp,
                                           addr,
                                           self._transport,
                                           {**self._kcp_kwargs, 'peername': addr, 'conv_id': conv_id},
                                           is_server=True,
                                           timeout=self._timeout, crypto=self.crypto)
            proto = self.protocol_factory()
            transport.set_protocol(proto)
            proto.connection_made(transport)
            self._transport_map[addr] = transport
        transport._feed_data(data)

    def error_received(self, exc):
        logger = logging.getLogger(__name__)
        logger.exception("KCP on UDP error: %s", exc)

class KCPServer:

    def __init__(self,
                 inner_protocol:_KCPServerUDPProtocol,
                 transport: KCPStreamTransport,
                 loop: asyncio.AbstractEventLoop,
                 kcp_kwargs: dict) -> None:
        self._inner_protocol = inner_protocol
        self._transport = transport
        self._loop = loop
        self._kcp_kwargs = kcp_kwargs

        self._is_serving = False
        self._serve_forever_fut = None
        self._waiters = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.close()
        await self.wait_closed()

    def close(self):
        self._is_serving = False
        for transport in self._inner_protocol._transport_map.values():
            transport.close()

    async def wait_closed(self):
        for waiter in self._waiters:
            await waiter
        self._inner_protocol._transport.close()
        for transport in self._inner_protocol._transport_map.values():
            await transport.wait_closed()
        self._inner_protocol._transport_map.clear()
        self._inner_protocol._transport = None

    def set_nodelay(self, no_delay: bool, update_interval: int, resend_count: int, no_congestion_control: bool):
        self._kcp_kwargs.update(no_delay=no_delay,
                                update_interval=update_interval,
                                resend_count=resend_count,
                                no_congestion_control=no_congestion_control)
        self._inner_protocol._kcp_kwargs.update(no_delay=no_delay,
                                update_interval=update_interval,
                                resend_count=resend_count,
                                no_congestion_control=no_congestion_control)
        return self

    def set_wndsize(self, send: int, receive: int):
        self._kcp_kwargs.update(send_window_size=send, receive_window_size=receive)
        self._inner_protocol._kcp_kwargs.update(send_window_size=send, receive_window_size=receive)
        return self

    def set_mtu(self, max_transmission: int):
        self._kcp_kwargs.update(max_transmission=max_transmission)
        self._inner_protocol._kcp_kwargs.update(max_transmission=max_transmission)
        return self

    def set_stream(self, stream):
        stream = int(bool(stream))
        self._kcp_kwargs.update(stream=stream)
        self._inner_protocol._kcp_kwargs.update(stream=stream)
        return self

    async def start_serving(self):
        if self._is_serving:
            return

        task = asyncio.create_task(self._serve())
        self._waiters.append(task)

    def is_serving(self):
        return self._is_serving

    async def serve_forever(self):
        if self._serve_forever_fut is not None:
            raise RuntimeError(
                'server has already started, serve_forever can only be called once'
            )
        self._loop.create_task(self._serve_forever())
        self._serve_forever_fut = asyncio.Future()
        await self._serve_forever_fut

    async def _serve_forever(self):
        try:
            await self._serve()
            self._serve_forever_fut.set_result(None)
        except Exception as e:
            self._serve_forever_fut.set_exception(e)

    async def _serve(self):
        self._is_serving = True
        while self._is_serving:
            current_time = time.perf_counter()
            current_ts = int(current_time * 1000)
            update_interval = self._kcp_kwargs.get('update_interval', default_update_interval)
            await asyncio.sleep(update_interval / 1000)
            for transport in tuple(self._inner_protocol._transport_map.values()):
                transport.update(current_ts)
                if current_time - transport.last_active > transport.timeout:
                    transport.close()
            self._inner_protocol._transport_map = {
                addr: transport
                for addr, transport in self._inner_protocol._transport_map.items()
                if not transport.is_closing()
            }
        self._wakeup()

    def _wakeup(self):
        for waiter in self._waiters:
            if not waiter.done():
                waiter.set_result(None)

async def create_server(protocol_factory, host, port, *,
                             loop=None, kcp_kwargs=None, timeout=default_timeout, crypto=None) -> KCPStreamTransport:
    _kcp_kwargs = default_kcp_kwargs.copy()
    _kcp_kwargs.update(kcp_kwargs or {})
    kcp_kwargs = _kcp_kwargs
    if loop is None:
        loop = asyncio.get_running_loop()

    proto = _KCPServerUDPProtocol(kcp_kwargs, protocol_factory, timeout=timeout, crypto=crypto)

    transport, _ = await loop.create_datagram_endpoint(
        lambda: proto,
        local_addr=(host, port))

    return KCPServer(proto, transport, loop, kcp_kwargs)
