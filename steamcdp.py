import base64
import json
import os
import socket
import struct
import urllib.request


class SteamUnavailable(Exception):
    pass


class JsError(Exception):
    pass


class Cdp:
    def __init__(self, host="127.0.0.1", port=None, title="SharedJSContext", timeout=60):
        self.timeout = timeout
        port = port or int(os.environ.get("NONSTEAM_CDP_PORT") or 8080)
        try:
            with urllib.request.urlopen(f"http://{host}:{port}/json", timeout=5) as r:
                targets = json.load(r)
        except (OSError, ValueError) as e:
            raise SteamUnavailable(str(e))
        if not isinstance(targets, list):
            raise SteamUnavailable("unexpected /json answer")
        target = next((t for t in targets if t.get("title") == title), None)
        if not target:
            raise SteamUnavailable("SharedJSContext not found")
        url = target["webSocketDebuggerUrl"]
        path = url.split(f"{host}:{port}", 1)[1]
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise SteamUnavailable("websocket handshake failed")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise SteamUnavailable(head.split(b"\r\n", 1)[0].decode(errors="replace"))
        self.buf = head.split(b"\r\n\r\n", 1)[1]
        self.next_id = 0

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _send(self, text):
        data = text.encode()
        header = bytearray([0x81])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        key = (mask * (n // 4 + 1))[:n]
        masked = (int.from_bytes(data, "big") ^ int.from_bytes(key, "big")).to_bytes(n, "big")
        self.sock.sendall(bytes(header) + masked)

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise SteamUnavailable("connection closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _recv(self):
        message = b""
        while True:
            b1, b2 = self._read(2)
            opcode = b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            if b2 & 0x80:
                mask = self._read(4)
                payload = bytearray(self._read(n))
                for i in range(n):
                    payload[i] ^= mask[i & 3]
                payload = bytes(payload)
            else:
                payload = self._read(n)
            if opcode == 0x8:
                raise SteamUnavailable("connection closed by Steam")
            if opcode in (0x9, 0xA):
                continue
            message += payload
            if b1 & 0x80:
                return message.decode()

    def eval(self, expression):
        self.next_id += 1
        my_id = self.next_id
        self._send(json.dumps({
            "id": my_id,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "awaitPromise": True, "returnByValue": True},
        }))
        while True:
            msg = json.loads(self._recv())
            if msg.get("id") != my_id:
                continue
            if "error" in msg:
                raise JsError(msg["error"].get("message", str(msg["error"])))
            result = msg["result"]
            if "exceptionDetails" in result:
                details = result["exceptionDetails"]
                text = details.get("exception", {}).get("description") or details.get("text")
                raise JsError(text)
            return result["result"].get("value")

    def call(self, js_function, *args):
        return self.eval(f"({js_function})(...{json.dumps(list(args), ensure_ascii=False)})")
