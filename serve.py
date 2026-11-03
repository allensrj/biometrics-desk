from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import socket
import webbrowser

class LocalServer(ThreadingHTTPServer):
    def server_bind(self):
        socket.socket.bind(self.socket, self.server_address)
        self.server_address = self.socket.getsockname()
        self.server_name, self.server_port = self.server_address

os.chdir(Path(__file__).resolve().parent)
try:
    server = LocalServer(('127.0.0.1', 8765), SimpleHTTPRequestHandler)
except OSError:
    server = LocalServer(('127.0.0.1', 0), SimpleHTTPRequestHandler)
url = f'http://127.0.0.1:{server.server_port}/'
print(f'临床研究雷达  {url}  ·  Ctrl+C 停止', flush=True)
webbrowser.open(url)
server.serve_forever()
