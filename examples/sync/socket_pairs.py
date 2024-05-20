import threading

from aiokcp.sync import KCPSocket

sock1, sock2 = KCPSocket.socket_pair()
sock1.send(b'123')
print(sock2.recv(100))
sock2.send(b'234')
print(sock1.recv(100))