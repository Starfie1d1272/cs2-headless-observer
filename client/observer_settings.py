"""Explicit observer settings only. Never query host environment/files/credentials."""
from handshake import blob, number
from wire import fields, scalar, ProbeError


class ObserverSettings:
    def __init__(self):
        # This program is an ordinary viewer, not a GOTV relay or game renderer.
        self.values = {b'name': b'Mizar observer', b'tv_relay': b'0'}

    def userinfo(self):
        entries = b''.join(blob(1, blob(1, name) + blob(2, value))
                           for name, value in self.values.items())
        return blob(1, entries)

    def query(self, payload):
        values = fields(payload, limit=4096)
        cookie = (scalar(values, 1) or 0) & 0xffffffff
        name = scalar(values, 2, 2) or b''
        if len(name) > 256 or b'\0' in name:
            raise ProbeError('observer-cvar-query-name')
        value = self.values.get(name)
        # Native status1 is NotFound. Never fabricate an engine cvar value.
        return number(1, cookie) + number(2, 1 if value is None else 0) + blob(3, name) + blob(4, value or b'')
