import socket
from socket import socket as _socket
from socketserver import (BaseRequestHandler, BaseServer, StreamRequestHandler,
                          TCPServer, ThreadingMixIn)
from time import sleep, time

from .sock import KCPSocket, KCPSocketType


class KCPServer(TCPServer):

    request_queue_size = 10
    def __init__(self, server_address, RequestHandlerClass, bind_and_activate=True, kcp_kwargs=None, **kw):
        """Constructor.  May be extended, do not override."""
        BaseServer.__init__(self, server_address, RequestHandlerClass)
        udp_sock = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        self.socket: KCPSocket = KCPSocket(KCPSocketType.SERVER, udp_sock=udp_sock, kcp_kwargs=kcp_kwargs, **kw)
        if bind_and_activate:
            try:
                self.server_bind()
                self.server_activate()
            except:
                self.server_close()
                raise

    def set_nodelay(self, no_delay: bool, update_interval: int, resend_count: int, no_congestion_control: bool):
        self.socket.set_nodelay(no_delay, update_interval, resend_count, no_congestion_control)
        return self

    def set_wndsize(self, send: int, receive: int):
        self.socket.set_wndsize(send, receive)
        return self

    def set_mtu(self, max_transmission: int):
        self.socket.set_mtu(max_transmission)
        return self

    def set_stream(self, stream: bool):
        self.socket.set_stream(stream)
        return self

    def serve_forever(self, poll_interval=0.5):
        """Handle one request at a time until shutdown.

        Polls for shutdown every poll_interval seconds. Ignores
        self.timeout. If you need to do periodic tasks, do them in
        another thread.
        """
        self._BaseServer__is_shut_down.clear()
        try:
            while not self._BaseServer__shutdown_request:
                # bpo-35017: shutdown() called during select(), exit immediately.
                if self._BaseServer__shutdown_request:
                        break
                if not self.socket._client_queue.empty():
                    self._handle_request_noblock()
                else:
                    sleep(0.5)
                self.service_actions()
        finally:
            self._BaseServer__shutdown_request = False
            self._BaseServer__is_shut_down.set()

    def handle_request(self):
        """Handle one request, possibly blocking.

        Respects self.timeout.
        """
        # Support people who used socket.settimeout() to escape
        # handle_request before self.timeout was available.r

        timeout = self.socket.gettimeout()
        if timeout is None:
            timeout = self.timeout
        elif self.timeout is not None:
            timeout = min(timeout, self.timeout)
        if timeout is not None:
            deadline = time() + timeout

        # Wait until a request arrives or the timeout expires - the loop is
        # necessary to accommodate early wakeups due to EINTR.

        while True:
            if not self.socket._client_queue.empty():
                self._handle_request_noblock()
            else:
                if timeout is not None:
                    timeout = deadline - time()
                    if timeout < 0:
                        return self.handle_timeout()
            sleep(0.5)

    def get_request(self):
        request = super().get_request()
        return request

class KCPThreadingServer(ThreadingMixIn, KCPServer):
    pass