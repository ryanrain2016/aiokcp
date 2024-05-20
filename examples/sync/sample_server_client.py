from aiokcp.sync import KCPSocket

sock1 = KCPSocket.create_server(('127.0.0.1', 18586))
sock2 = KCPSocket.create_connection(('127.0.0.1', 18586))
server_sock, _ = sock1.accept()
server_sock.send(b'123')
print(sock2.recv(100))
sock2.send(b'234')
print(server_sock.recv(100))