import ctypes
import os
import time

_LOG_PATH = os.environ.get("RENDERDOC_MCP_BRIDGE_LOG")
if not _LOG_PATH:
    _LOG_PATH = os.path.join(os.environ.get("TEMP", os.environ.get("TMP", ".")), "renderdoc_mcp_bridge_default.log")


def _log(message):
    if not _LOG_PATH:
        return
    try:
        with open(_LOG_PATH, "a") as handle:
            handle.write("[{}] {}\n".format(time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except Exception:
        pass


class _WSADATA(ctypes.Structure):
    _fields_ = [
        ("wVersion", ctypes.c_ushort),
        ("wHighVersion", ctypes.c_ushort),
        ("szDescription", ctypes.c_char * 257),
        ("szSystemStatus", ctypes.c_char * 129),
        ("iMaxSockets", ctypes.c_ushort),
        ("iMaxUdpDg", ctypes.c_ushort),
        ("lpVendorInfo", ctypes.c_void_p),
    ]


class _SockAddrIn(ctypes.Structure):
    _fields_ = [
        ("sin_family", ctypes.c_short),
        ("sin_port", ctypes.c_ushort),
        ("sin_addr", ctypes.c_uint32),
        ("sin_zero", ctypes.c_char * 8),
    ]


class _WinSockClient(object):
    AF_INET = 2
    SOCK_STREAM = 1
    IPPROTO_TCP = 6
    SOL_SOCKET = 0xFFFF
    SO_RCVTIMEO = 0x1006
    SO_SNDTIMEO = 0x1005
    INVALID_SOCKET = ctypes.c_size_t(-1).value
    SOCKET_ERROR = -1
    WSAETIMEDOUT = 10060
    WSAEWOULDBLOCK = 10035

    _started = False
    _ws2_32 = ctypes.WinDLL("Ws2_32.dll")

    @classmethod
    def _startup(cls):
        if cls._started:
            return
        data = _WSADATA()
        result = cls._ws2_32.WSAStartup(0x0202, ctypes.byref(data))
        if result != 0:
            raise RuntimeError("WSAStartup failed: {}".format(result))
        cls._started = True

    @classmethod
    def _last_error(cls):
        return int(cls._ws2_32.WSAGetLastError())

    def __init__(self):
        self._startup()
        self.sock = ctypes.c_size_t(self.INVALID_SOCKET)
        self._buffer = b""

    def connect(self, host, port):
        self.sock = ctypes.c_size_t(self._ws2_32.socket(self.AF_INET, self.SOCK_STREAM, self.IPPROTO_TCP))
        if self.sock.value == self.INVALID_SOCKET:
            raise RuntimeError("socket() failed: {}".format(self._last_error()))

        timeout_ms = ctypes.c_int(250)
        timeout_size = ctypes.c_int(ctypes.sizeof(timeout_ms))
        self._ws2_32.setsockopt(self.sock, self.SOL_SOCKET, self.SO_RCVTIMEO, ctypes.byref(timeout_ms), timeout_size)
        self._ws2_32.setsockopt(self.sock, self.SOL_SOCKET, self.SO_SNDTIMEO, ctypes.byref(timeout_ms), timeout_size)

        addr = _SockAddrIn()
        addr.sin_family = self.AF_INET
        addr.sin_port = ((int(port) & 0xFF) << 8) | ((int(port) >> 8) & 0xFF)
        addr.sin_addr = self._ws2_32.inet_addr(host.encode("ascii"))
        addr.sin_zero = b"\0" * 8

        result = self._ws2_32.connect(self.sock, ctypes.byref(addr), ctypes.sizeof(addr))
        if result == self.SOCKET_ERROR:
            error = self._last_error()
            self.close()
            raise RuntimeError("connect() failed: {}".format(error))

    def send_text(self, text):
        payload = text.encode("utf-8")
        total = 0
        while total < len(payload):
            chunk = payload[total:]
            result = self._ws2_32.send(self.sock, chunk, len(chunk), 0)
            if result == self.SOCKET_ERROR:
                error = self._last_error()
                if error in (self.WSAETIMEDOUT, self.WSAEWOULDBLOCK):
                    raise TimeoutError("send() timed out")
                raise RuntimeError("send() failed: {}".format(error))
            total += int(result)

    def recv_line(self):
        while True:
            newline_index = self._buffer.find(b"\n")
            if newline_index >= 0:
                line = self._buffer[:newline_index]
                self._buffer = self._buffer[newline_index + 1 :]
                return line.decode("utf-8")

            chunk = ctypes.create_string_buffer(4096)
            result = self._ws2_32.recv(self.sock, chunk, len(chunk), 0)
            if result == 0:
                raise RuntimeError("recv() returned EOF")
            if result == self.SOCKET_ERROR:
                error = self._last_error()
                if error in (self.WSAETIMEDOUT, self.WSAEWOULDBLOCK):
                    raise TimeoutError("recv() timed out")
                raise RuntimeError("recv() failed: {}".format(error))
            self._buffer += chunk.raw[: int(result)]

    def close(self):
        if self.sock.value != self.INVALID_SOCKET:
            self._ws2_32.closesocket(self.sock)
            self.sock = ctypes.c_size_t(self.INVALID_SOCKET)
