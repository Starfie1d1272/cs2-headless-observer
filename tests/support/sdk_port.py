"""Synthetic SDK port: no Steam, tickets or sockets."""
import struct

class Port:
    def __init__(self):
        self.state, self.incoming, self.sent, self.closed = 3, [], [], 0
        self.ticket_requested = False
    def remote_id(self): return 456
    def local_id(self): return 76561198000000123
    def accept_server_auth2(self):
        assert self.state == 3
        self.state = 7
    def pump(self, now): pass
    def receive(self): return self.incoming.pop(0) if self.incoming else None
    def send(self, data, flags): self.sent.append((data, flags))
    def request_ticket(self): self.ticket_requested = True; self.state = 4
    def with_auth(self, consume): return consume(struct.pack('<Q', 76561198000000123) + b'SYNTHETIC-NOT-A-TICKET')
    def close(self): self.closed += 1; self.state = 6
