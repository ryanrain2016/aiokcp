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