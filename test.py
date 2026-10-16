import socket
s=socket.create_connection(('127.0.0.1', 8888))
s.sendall(b'{\"type\":\"HELLO\",\"request_id\":1}\n')
print('Réponse du serveur :', s.recv(1024))
s.close()