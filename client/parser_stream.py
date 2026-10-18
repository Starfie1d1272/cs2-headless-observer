"""Frame decoded network messages for the existing public DemoReader stream API.

This is a local parser adapter, not a recording made by CS2 or online evidence.
Only the wrapper and ClassInfo field mapping are generated; network payloads
remain unchanged. No Steam transport, authentication, or rendering lives here.
"""
from channel import encode_message, join_messages, messages
from handshake import blob, encode_varint, uint
from wire import fields, scalar, ProbeError
from live import repeated, text

MAGIC = b'PBDEMS2\0' + bytes(8)
MAX_BODY = 4 * 1024**2


def frame(command, tick, payload):
    return encode_varint(command) + encode_varint(tick & 0xffffffff) + encode_varint(len(payload)) + payload


class ParserStream:
    def __init__(self, write):
        self.write = write
        self.tick = -1
        self.have_serializers = False
        self.have_classes = False
        self.sequence = 0
        self.write(MAGIC)

    def _observe(self, message_id, body):
        uint(message_id)
        if not isinstance(body, bytes) or len(body) > MAX_BODY:
            raise ProbeError('parser-stream-body-limit')
        if message_id == 4:
            tick = scalar(fields(body), 1)
            if tick is None or not 0 <= tick <= 0x7fffffff or tick < self.tick:
                raise ProbeError('parser-stream-tick-regressed-or-missing')
            self.tick = tick
        if message_id == 55 and not self.have_classes:
            raise ProbeError('parser-stream-entities-before-schema')

    def consume(self, message_id, body):
        self._observe(message_id, body)
        if message_id == 41:
            # CDemoSendTables.data contains a length-prefixed FlattenedSerializer.
            if self.have_classes:
                raise ProbeError('parser-stream-schema-changed-new-instance-required')
            self.write(frame(4, self.tick, blob(1, encode_varint(len(body)) + body)))
            self.have_serializers = True
            return
        if message_id == 42:
            f = fields(body, limit=MAX_BODY)
            if scalar(f, 1) not in (None, 0):
                if self.have_classes:
                    return  # Existing supplied full schema; no invented cached classes.
                raise ProbeError('parser-stream-cached-classes-unavailable')
            if not self.have_serializers or self.have_classes:
                raise ProbeError('parser-stream-class-info-order')
            classes, seen = [], set()
            for raw in repeated(f, 2):
                row = fields(raw)
                class_id = scalar(row, 1)
                name = scalar(row, 3, 2)
                if class_id is None or not 0 <= class_id <= 65535 or class_id in seen:
                    raise ProbeError('parser-stream-class-id')
                text(name, 1024)
                seen.add(class_id)
                # CSVC ClassInfo class_name=3 -> CDemoClassInfo network_name=2.
                classes.append(blob(1, b'\x08' + encode_varint(class_id) + blob(2, name)))
            if not classes:
                raise ProbeError('parser-stream-empty-classes')
            self.write(frame(5, self.tick, b''.join(classes)))
            self.have_classes = True
            return
        packet, _ = encode_message(message_id, body)
        self.write(frame(7, self.tick, blob(3, packet)))

    def consume_packet(self, packet):
        decoded, _ = messages(packet)
        if not any(m.message_id in (41, 42) for m in decoded):
            for m in decoded:
                self._observe(m.message_id, m.body)
            # Preserve the original packet's event flush boundary.
            self.write(frame(7, self.tick, blob(3, packet)))
            return
        pending = []
        def flush():
            if pending:
                body, _ = join_messages(pending)
                self.write(frame(7, self.tick, blob(3, body)))
                pending.clear()
        for m in decoded:
            if m.message_id in (41, 42):
                flush()
                self.consume(m.message_id, m.body)
            else:
                self._observe(m.message_id, m.body)
                pending.append(encode_message(m.message_id, m.body))
        flush()

    def checkpoint(self):
        """Local-only marker acknowledged after prior frames are parsed in order."""
        self.sequence += 1
        if self.sequence > 0x7fffffff:
            raise ProbeError('parser-checkpoint-limit')
        self.write(frame(10, self.tick, b'\x08' + encode_varint(self.sequence)))
        return self.sequence
