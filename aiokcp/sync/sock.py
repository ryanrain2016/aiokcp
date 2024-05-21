import enum
import socket
import threading
import time
from queue import PriorityQueue, Queue
from typing import Optional, Union

from ..core import default_kcp_kwargs, default_timeout
from ..kcp import KCP
from ..utils import conv_bytes_to_id, random_id

__all__ = ['KCPSocket', 'KCPSocketType']

class KCPSocketType(enum.Enum):
    SERVER = 1
    SERVER_SIDE = 2
    CLIENT_SIDE = 3

class _UpdateLoop:
    def __init__(self):
        self._queue = PriorityQueue()
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run)
        self._thread.setDaemon(True)
        self._thread.start()

    def _run(self):
        while self._running or not self._queue.empty():
            sock: 'KCPSocket'
            next_time, sock = self._queue.get()
            if sock._is_closing:
                self._queue.task_done()
                continue
            current = time.perf_counter()
            sleep_time = next_time - current
            if sleep_time > 0:
                time.sleep(sleep_time)
                current = time.perf_counter()
            current_ts = int(current*1000)
            sock.update(current_ts)
            next_time = current + sock._kcp_kwargs.get('update_interval') / 1000
            if current - sock._last_active > sock._timeout:
                sock.close()
            elif not sock._is_closing and self._running:
                self._queue.put((next_time, sock))
            self._queue.task_done()

    def add(self, sock: 'KCPSocket'):
        if sock.tp == KCPSocketType.SERVER:
            return
        next_time = time.perf_counter() + sock._kcp_kwargs.get('update_interval') / 1000
        self._queue.put((next_time, sock))

    def stop(self):
        if not self._running:
            return
        self._running = False
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        self._queue.join()

_ul = _UpdateLoop()
_ul.start()

def stop_update_loop():
    _ul.stop()

class KCPSocket:
    def __init__(self, tp: KCPSocketType=KCPSocketType.CLIENT_SIDE, udp_sock=None, kcp_kwargs = None, **kw):
        self.sock = udp_sock or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.tp = tp # 1. server 2. server_side 3. client_side
        if tp == KCPSocketType.SERVER:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._clients: dict[tuple[str, int], 'KCPSocket'] = {}
            self._client_queue = None
        self._recv_lock = threading.Lock()
        if tp != KCPSocketType.SERVER_SIDE:
            self._recv_thread = None
        self._is_closing = False
        self._kcp_kwargs = default_kcp_kwargs.copy()
        self._kcp_kwargs.update(kcp_kwargs or {})
        self._addr = None
        self._last_active = time.perf_counter()
        self._timeout = kw.get('timeout', default_timeout)
        if tp != KCPSocketType.SERVER:
            if 'conv_id' not in self._kcp_kwargs:
                self._kcp_kwargs.update(conv_id=random_id())
            self.kcp: KCP = KCP(**self._kcp_kwargs)
            self.kcp.set_output_handler(self._send_to)
            self._buffer = bytearray()
            self._recv_condition = threading.Condition(self._recv_lock)
        if tp == KCPSocketType.SERVER_SIDE:
            self._attached: 'KCPSocket' = None
        self._io_refs = 0
        self._blocking = True
        self._crypto = kw.get('crypto', None)
        self._kw = kw
        self._kcp_lock = threading.Lock()

    def set_nodelay(self, no_delay: bool, update_interval: int, resend_count: int, no_congestion_control: bool):
        if self.tp != KCPSocketType.SERVER:
            self.kcp.set_nodelay(no_delay, update_interval, resend_count, no_congestion_control)
        self._kcp_kwargs.update(no_delay=no_delay,
                                update_interval=update_interval,
                                resend_count=resend_count,
                                no_congestion_control=no_congestion_control)
        return self

    def set_wndsize(self, send: int, receive: int):
        if self.tp != KCPSocketType.SERVER:
            self.kcp.set_wndsize(send, receive)
        self._kcp_kwargs.update(send_window_size=send, receive_window_size=receive)
        return self

    def set_mtu(self, max_transmission: int):
        if self.tp != KCPSocketType.SERVER:
            self.kcp.set_mtu(max_transmission)
        self._kcp_kwargs.update(max_transmission=max_transmission)
        return self

    def set_stream(self, stream):
        stream = int(bool(stream))
        self._kcp_kwargs.update(stream=stream)
        if self.tp != KCPSocketType.SERVER:
            self.kcp.set_stream(stream)
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _decref_socketios(self):
        if self._io_refs > 0:
            self._io_refs -= 1

    def _send_to(self, _, data):
        if self._crypto is not None:
            try:
                data = self._crypto.encrypt(data)
            except:
                pass
        try:
            n = self.sock.sendto(data, self._addr)
        except:
            return 0
        return n


    def _attach(self, sock: 'KCPSocket'):
        if self.tp != KCPSocketType.SERVER_SIDE:
            return
        self._attached = sock

    def _detach(self):
        if self.tp != KCPSocketType.SERVER_SIDE:
            return
        self._attached._clients.pop(self._addr, None)
        self._attached = None

    def close(self):
        if self._is_closing:
            return
        self._is_closing = True
        if self.tp != KCPSocketType.SERVER:
            with self._recv_condition:
                self._recv_condition.notify_all()
            update_interval = self._kcp_kwargs.get('update_interval')
            cnt = 5000 / update_interval
            while self.kcp.get_waitsnd() > 0 and (cnt := cnt -1) > 0:
                time.sleep(update_interval / 1000)
                self.update()
            time.sleep(0.1) # wait for last ack to send
            if self.tp == KCPSocketType.CLIENT_SIDE:
                self.sock.close()
        else:
            for client in tuple(self._clients.values()):
                client.close()
            self.sock.close()
        if self.tp == KCPSocketType.SERVER_SIDE:
            self._detach()
        elif self._recv_thread is not None:
            self._recv_thread.join()
            self._recv_thread = None

    def bind(self, addr):
        self.sock.bind(addr)

    def update(self, ts_ms: Optional[int] = None) -> None:
        if self.kcp:
            with self._kcp_lock:
                return self.kcp.update(ts_ms)

    def listen(self, backlog):
        if self.tp != KCPSocketType.SERVER:
            raise Exception('Not a server socket')
        self._client_queue = Queue(backlog)
        self._recv_thread = threading.Thread(target=self._server_recv)
        self._recv_thread.setDaemon(True)
        self._recv_thread.start()

    def _server_recv(self):
        while not self._is_closing or self._clients:
            try:
                data, addr = self.sock.recvfrom(2048)
                if len(data) < 24:
                    continue
                if self._crypto is not None:
                    try:
                        data = self._crypto.decrypt(data)
                    except:
                        continue
            except:
                break
            if addr not in self._clients:
                conv_id = conv_bytes_to_id(data[:4])
                kcp_kwargs = self._kcp_kwargs.copy()
                kcp_kwargs.update(conv_id=conv_id)
                sock = KCPSocket(KCPSocketType.SERVER_SIDE, self.sock, kcp_kwargs, **self._kw)
                sock._addr = addr
                sock._attach(self)
                _ul.add(sock)  # global update loop
                self._clients[addr] = sock
                self._client_queue.put(sock)
            else:
                sock = self._clients[addr]
            sock._feed_data(data)
            sock.__update_activity()

    def _feed_data(self, data):
        conv_id = conv_bytes_to_id(data[:4])
        if conv_id != self.kcp.get_conv_id():
            return
        try:
            with self._kcp_lock:
                self.kcp.receive(data)
        except:
            print('kcp receive error')
            return
        self.__update_activity()
        notify = False
        for data in self.kcp.get_all_received():
            self._buffer.extend(data)
            notify = True
        if (notify or self._buffer) and self._recv_condition is not None:
            with self._recv_condition:
                self._recv_condition.notify()

    def __update_activity(self):
        self._last_active = time.perf_counter()

    def accept(self) -> tuple['KCPSocket', tuple[str, int]]:
        if self.tp != KCPSocketType.SERVER:
            raise Exception('Not a server socket')
        sock: KCPSocket = self._client_queue.get()
        if self._kcp_kwargs.get('stream', False):
            sock.set_stream(True)
        return sock, sock._addr

    def connect(self, addr):
        if self.tp != KCPSocketType.CLIENT_SIDE:
            raise Exception('Not a client socket')
        self._addr = addr
        _ul.add(self)
        self._recv_thread = threading.Thread(target=self._recv)
        self._recv_thread.setDaemon(True)
        self._recv_thread.start()

    def _recv(self):
        while not self._is_closing or self.kcp.get_waitsnd() > 0 or self.kcp.packet_available:
            try:
                data, addr = self.sock.recvfrom(2048)
                if len(data) < 24:
                    continue
                if self._crypto is not None:
                    try:
                        data = self._crypto.decrypt(data)
                    except:
                        continue
            except:
                # udp socket is closed
                break
            if addr == self._addr:
                self._feed_data(data)

    def recv(self, bufsize=0, flags=0):
        with self._recv_condition:
            if self._buffer:
                if bufsize <= 0:
                    bufsize = len(self._buffer)
                data = self._buffer[:bufsize]
                if not (flags & socket.MSG_PEEK):
                    self._buffer = self._buffer[bufsize:]
                return data
            if self._is_closing:
                return b''
            if not self.getblocking():
                return b''
            self._recv_condition.wait_for(lambda: self._buffer or self._is_closing, 10)
        if not self._buffer:
            return b''
        return self.recv(bufsize, flags)

    def recv_into(self, buffer, nbytes=0, flags=0):
        with self._recv_condition:
            if self._buffer:
                view = memoryview(buffer)
                if nbytes <= 0:
                    nbytes = min(len(buffer), len(self._buffer))
                nbytes = min(len(buffer), len(self._buffer), nbytes)
                view[:nbytes] = self._buffer[:nbytes]
                if not (flags & socket.MSG_PEEK):
                    self._buffer = self._buffer[nbytes:]
                return nbytes
            self._recv_condition.wait_for(lambda: self._buffer or self._is_closing, 10)
        return self.recv_into(buffer, nbytes, flags)

    def sendall(self, data: Union[bytes, bytearray, memoryview], flags=0):
        while data:
            sent = self.send(data, flags)
            data = data[sent:]
        return

    def send(self, data: Union[bytes, bytearray, memoryview], flags=0):
        if self._is_closing:
            return 0
        data = bytes(data)
        with self._kcp_lock:
            n = self.kcp.enqueue(data)
            self.kcp.update(int(time.perf_counter() * 1000))
            return n

    def sendfile(self, file, offset=0, count=None):
        # file.seek(offset, 0)
        # count = -1 if count is None else count
        # return self.kcp.enqueue(file.read(count))
        return socket.socket._sendfile_use_send(self, file, offset, count)

    def setblocking(self, flag):
        self._blocking = flag

    def getblocking(self):
        return self._blocking

    def settimeout(self, timeout):
        timeout = timeout or default_timeout
        self._timeout = timeout
        self.sock.settimeout(timeout)

    def gettimeout(self):
        return self._timeout

    def ioctl(self, cmd, arg):
        return self.sock.ioctl(cmd, arg)

    def setsockopt(self, level, optname, value):
        return self.sock.setsockopt(level, optname, value)

    def getsockopt(self, level, optname):
        return self.sock.getsockopt(level, optname)

    def getpeername(self):
        if self.tp == KCPSocketType.SERVER:
            raise Exception('Not a client socket')
        return self._addr

    def getsockname(self):
        return self.sock.getsockname()

    def fileno(self):
        return self.sock.fileno()

    def makefile(self, mode='r', buffering=None, *, encoding=None, errors=None, newline=None):
        return socket.socket.makefile(self, mode, buffering, encoding=None, errors=errors, newline=newline)

    def shutdown(self, how):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @staticmethod
    def socket_pair(**kw):
        sock1 = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        sock2 = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        sock1.bind(('', 0))
        addr1 = ('127.0.0.1', sock1.getsockname()[1])
        sock2.bind(('', 0))
        addr2 = ('127.0.0.1', sock2.getsockname()[1])
        conv_id = random_id()
        kcp_kwargs = kw.pop('kcp_kwargs', default_kcp_kwargs.copy()) or {}
        kcp_sock1 = KCPSocket(udp_sock=sock1, kcp_kwargs={'conv_id': conv_id, **kcp_kwargs}, **kw)
        kcp_sock2 = KCPSocket(udp_sock=sock2, kcp_kwargs={'conv_id': conv_id, **kcp_kwargs}, **kw)
        kcp_sock1.connect(addr2)
        kcp_sock2.connect(addr1)
        return kcp_sock1, kcp_sock2

    @staticmethod
    def fromfd(fd, family=socket.AF_INET, type=socket.SOCK_DGRAM, proto=0, **kw):
        sock = socket.fromfd(fd, family, type, proto)
        return KCPSocket(udp_sock=sock, **kw)

    @staticmethod
    def create_connection(addr, timeout=None, source_address=None, **kw):
        sock = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        if source_address:
            sock.bind(source_address)
        else:
            sock.bind(('', 0))
        kcp_sock = KCPSocket(udp_sock=sock, timeout=timeout or default_timeout, **kw)
        kcp_sock.connect(addr)
        kcp_sock.send(b'')
        return kcp_sock

    @staticmethod
    def create_server(addr, *, backlog=128, **kw):
        sock = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        kcp_sock = KCPSocket(tp=KCPSocketType.SERVER, udp_sock=sock, **kw)
        kcp_sock.bind(addr)
        kcp_sock.listen(backlog)
        return kcp_sock

