"""Servidor local para probar la API sin AWS.
Uso (desde la raíz del proyecto):  LOCAL=1 DATA_DIR=data python lambda/local_server.py
En Windows PowerShell:  $env:LOCAL="1"; $env:DATA_DIR="data"; python lambda/local_server.py
Queda en http://localhost:3001  → en front/.env.local poner VITE_API_URL=http://localhost:3001"""
import json, os, socket, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qsl
os.environ.setdefault("LOCAL", "1"); os.environ.setdefault("DATA_DIR", "data")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app

class H(BaseHTTPRequestHandler):
    def _go(self, method):
        u = urlparse(self.path)
        n = int(self.headers.get("content-length") or 0)
        ev = {"requestContext": {"http": {"method": method}}, "rawPath": u.path,
              "queryStringParameters": dict(parse_qsl(u.query)) or None,
              "body": self.rfile.read(n).decode() if n else None}
        r = app.handler(ev)
        self.send_response(r["statusCode"])
        for k, v in r["headers"].items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(r["body"].encode())
    def do_GET(self): self._go("GET")
    def do_POST(self): self._go("POST")
    def do_OPTIONS(self): self._go("OPTIONS")

class DualStack(ThreadingHTTPServer):
    """Escucha en IPv4 e IPv6: en Windows 'localhost' prueba primero ::1 y, si no responde, espera ~2 s."""
    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


print("API local en http://localhost:3001")
try:
    DualStack(("::", 3001), H).serve_forever()
except OSError:
    ThreadingHTTPServer(("0.0.0.0", 3001), H).serve_forever()
