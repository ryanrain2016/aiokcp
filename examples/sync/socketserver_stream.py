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