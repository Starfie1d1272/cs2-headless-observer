"""Historical synthetic ticket fixture; not part of the SDK runtime."""
import struct
from typing import Callable
from handshake import uint
from wire import ProbeError

class TicketLease:
    """SDK callback/lifetime gate. Neither creates nor validates a Steam ticket.

    Handle and bytes come from GetAuthSessionTicket for the actual remote identity.
    Only a matching successful GetAuthSessionTicketResponse_t releases bytes.
    cancel is the host adapter's CancelAuthTicket; a host must close on timeout,
    disconnect and shutdown. No SDK adapter is implemented by this module.
    """
    def __init__(self, handle: int, sdk_ticket: bytes, cancel: Callable[[int], None]):
        uint(handle)
        if not handle or not 0 < len(sdk_ticket) <= 2040:
            raise ProbeError('invalid-ticket-result')
        self._handle = handle
        self._bytes = bytearray(sdk_ticket)
        self._cancel = cancel
        self._state = 'pending'

    def callback(self, handle: int, result: int):
        if self._state != 'pending' or handle != self._handle:
            return False
        if result != 1:  # k_EResultOK, not a server-side authorization decision.
            self.close()
            return False
        self._state = 'ready'
        return True

    def auth_steam(self, own_steam_id: int):
        if self._state != 'ready':
            raise ProbeError('ticket-not-ready')
        # Observed helper writes GetSteamID() as uint64 then the SDK ticket bytes.
        uint(own_steam_id, 64)
        if not own_steam_id:
            raise ProbeError('missing-user-identity')
        return struct.pack('<Q', own_steam_id) + bytes(self._bytes)

    def close(self):
        if self._state != 'closed':
            self._state = 'closed'
            self._bytes[:] = bytes(len(self._bytes))
            self._cancel(self._handle)
        # Python/SDK/caller copies are not guaranteed erased by this operation.

