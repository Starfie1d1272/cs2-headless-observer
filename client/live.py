"""Source 2 net-message consumer. No Demo wrapper, auth bytes, sockets or init ACKs.

The historical Source1Legacy names below are messages in CS2's gameevents.proto;
this does not import Source 1 transport. Player identity/entity state stay unknown.
"""
import hashlib
import math
import struct
from handshake import number, uint
from wire import fields, scalar, varint, ProbeError
from resource_manifest import decode_resource_manifest

EVENTS = {'weapon_fire', 'player_death', 'round_start', 'round_end'}


def repeated(f, tag, wire=2):
    values = f.get(tag, [])
    if any(kind != wire for kind, _ in values):
        raise ProbeError('live-repeated-wire')
    return [value for _, value in values]


def text(value, maximum=256):
    if not isinstance(value, bytes) or not value or len(value) > maximum or b'\0' in value:
        raise ProbeError('live-text-boundary')
    try:
        return value.decode('utf8')
    except UnicodeError:
        raise ProbeError('live-text-encoding') from None


def int32(value):
    if value is None:
        return None
    value &= 0xffffffff
    return value - 0x100000000 if value & 0x80000000 else value


def client_info(*, server_count, account_id, send_table_crc=0):
    """Ordinary-client info. Zero CRC requests the complete send-table path.

    engine2 05ff20 sends the cached CRC or zero; 120fa0 takes the full-table
    branch for zero. Nonzero values require a matching real cached schema.
    is_hltv=false retains ordinary-client identity. See INITIALIZATION-EVIDENCE.
    """
    return b'\x0d' + uint(send_table_crc).to_bytes(4, 'little') + number(2, server_count) + number(3, 0) + number(5, account_id)


class LiveDecoder:
    def __init__(self, emit):
        self.emit = emit
        self.tick = None
        self.server = None
        self.descriptors = {}
        self.serializers = set()
        self.classes = {}
        self.tables = []
        self.entity_packets = 0
        self.counts = {}
        self.unresolved_events = 0
        self.spawn_groups = {}
        self.manifest_name_bytes = 0
        self.manifest_resources = 0
        self.session_manifest = None
        self.ready_spawn_groups = set()
        self.max_creation_sequence = 0
        self.retired_spawn_groups = {}

    def reset_world(self):
        # Explicit application/world boundary; transport counters live elsewhere.
        counts = self.counts
        self.__init__(self.emit)
        self.counts = counts

    def _manifest_fragment(self, payload):
        items = decode_resource_manifest(payload)
        names = sum(len(value.encode('utf8')) for item in items for value in item.values())
        if self.manifest_name_bytes + names > 4 * 1024**2 or self.manifest_resources + len(items) > 16384:
            raise ProbeError('spawn-group-session-manifest-budget')
        self.manifest_name_bytes += names
        self.manifest_resources += len(items)
        return items

    def ready_world_groups(self):
        """Allocate headless network-world identities in parent-first order.

        Rendering/client-only scene objects are outside this event receiver.
        Save-game worlds require an additional state source and stay unsupported.
        """
        if self.session_manifest is None:
            return []
        ready = []
        pending = set(self.spawn_groups) - self.ready_spawn_groups
        while pending:
            advanced = False
            for handle in sorted(pending):
                group = self.spawn_groups[handle]
                if group['manifest_incomplete']:
                    continue
                if group['flags'] & 1 or group['savegame']:
                    raise ProbeError('savegame-world-not-supported')
                dependencies = {group['owner'], group['parent']} - {0}
                if not dependencies.issubset(self.ready_spawn_groups):
                    continue
                self.ready_spawn_groups.add(handle)
                ready.append(handle)
                pending.remove(handle)
                advanced = True
            if not advanced:
                break
        return ready

    def blockers(self):
        # Presence is not initialization. This API offers no caller-controlled ready flag.
        return ['serializer-field-decoders',
                'string-table-callbacks-and-baselines', 'session-manifest-and-spawn-groups',
                'entity-full-snapshot']

    def consume(self, message_id, body):
        self.counts[message_id] = self.counts.get(message_id, 0) + 1
        if message_id not in (4, 8, 9, 11, 12, 40, 41, 42, 44, 45, 51, 55, 205, 207):
            return
        f = fields(body, limit=4 * 1024**2)
        if message_id == 4:
            tick = scalar(f, 1)
            if tick is None or tick > 0x7fffffff:
                raise ProbeError('live-tick-invalid-or-missing')
            self.tick = tick
        elif message_id == 8:
            handle = scalar(f, 4)
            if handle is None or not 0 < handle <= 0xffffffff:
                raise ProbeError('spawn-group-handle')
            if handle in self.spawn_groups:
                return  # Fixed080b60 ignores already loaded/loading duplicates.
            if len(self.spawn_groups) >= 1024:
                raise ProbeError('spawn-group-count-budget')
            self.spawn_groups[handle] = {
                'world': text(scalar(f, 1, 2), 4096),
                'payload_sha256': hashlib.sha256(body).hexdigest(),
                'flags': uint(scalar(f, 9) or 0),
                'owner': uint(scalar(f, 5) or 0),
                'parent': uint(scalar(f, 18) or 0),
                'savegame': bool(scalar(f, 17, 2)),
                'creation_tick': int32(scalar(f, 10)),
                'creation_sequence': scalar(f, 16),
                'manifest_incomplete': bool(scalar(f, 11)),
                'manifest_fragments': [self._manifest_fragment(scalar(f, 8, 2) or b'')],
            }
        elif message_id == 9:
            group = self.spawn_groups.get(scalar(f, 1))
            if group is None or not group['manifest_incomplete']:
                return
            if len(group['manifest_fragments']) >= 1024:
                raise ProbeError('spawn-group-fragment-budget')
            fragment = self._manifest_fragment(scalar(f, 2, 2) or b'')
            group['manifest_fragments'].append(fragment)
            group['manifest_incomplete'] = bool(scalar(f, 3))
        elif message_id == 11:
            group = self.spawn_groups.get(scalar(f, 1))
            sequence = scalar(f, 3) or 0
            uint(sequence)
            self.max_creation_sequence = max(self.max_creation_sequence, sequence)
            if group is None:
                return  # Native083a30 advances the global watermark even here.
            group['creation_sequence'] = sequence
            group['creation_tick'] = int32(scalar(f, 2))
        elif message_id == 12:
            handle = scalar(f, 1)
            group = self.spawn_groups.pop(handle, None)
            if group is None:
                return
            group['destruction_tick'] = int32(scalar(f, 3))
            group['cancelled'] = True
            self.retired_spawn_groups[handle] = group
            while len(self.retired_spawn_groups) > 1024:
                self.retired_spawn_groups.pop(next(iter(self.retired_spawn_groups)))
            self.ready_spawn_groups.discard(handle)
        elif message_id == 40:
            count, protocol = scalar(f, 2), scalar(f, 1)
            interval = scalar(f, 13, 5)
            if count is None or protocol is None or interval is None:
                raise ProbeError('live-serverinfo-required-field')
            interval = struct.unpack('<f', interval)[0]
            info = {'server_count': uint(count), 'protocol': uint(protocol),
                    'map': text(scalar(f, 15, 2)), 'tick_interval': interval,
                    'player_slot': int32(scalar(f, 12)) if scalar(f, 12) is not None else -1}
            if not math.isfinite(interval) or not 0 < interval <= 1:
                raise ProbeError('live-tick-interval')
            if self.server is not None and self.server != info:
                raise ProbeError('live-serverinfo-changed-new-instance-required')
            if self.server is None:
                self.session_manifest = self._manifest_fragment(scalar(f, 20, 2) or b'')
            self.server = info
        elif message_id == 41:
            # Empty symbols are valid placeholders in recorded flattened schemas.
            symbols = [text(value, 1024) if value else '' for value in repeated(f, 2)]
            definitions = repeated(f, 3)
            serializers = set()
            for raw in repeated(f, 1):
                s = fields(raw)
                index, version = scalar(s, 1), scalar(s, 2)
                if index is None or index >= len(symbols) or version is None:
                    raise ProbeError('serializer-symbol-boundary')
                key = (symbols[index], int32(version))
                if key in serializers:
                    raise ProbeError('serializer-duplicate')
                serializers.add(key)
                for wire, value in s.get(3, []):
                    indices = []
                    if wire == 0:
                        indices.append(value)
                    elif wire == 2:
                        pos = 0
                        while pos < len(value):
                            item, pos = varint(value, pos)
                            indices.append(item)
                    else:
                        raise ProbeError('serializer-index-wire')
                    if any(item >= len(definitions) for item in indices):
                        raise ProbeError('serializer-field-boundary')
            self.serializers = serializers  # Valid references, NOT executable entity decoders.
        elif message_id == 42:
            classes = {}
            for raw in repeated(f, 2):
                c = fields(raw)
                index = scalar(c, 1)
                if index is None or index > 65535 or index in classes:
                    raise ProbeError('class-index-boundary')
                classes[index] = text(scalar(c, 3, 2))
            self.classes = classes
        elif message_id == 44:
            if len(self.tables) >= 1024:
                raise ProbeError('string-table-count-budget')
            self.tables.append({'name': text(scalar(f, 1, 2)), 'decoded': False})
        elif message_id == 45:
            index = scalar(f, 1)
            if index is None or index >= len(self.tables):
                raise ProbeError('string-table-update-before-create')
        elif message_id == 51:
            self.reset_world()
        elif message_id == 55:
            self.entity_packets += 1  # Opaque; receiving this does not establish a baseline.
        elif message_id == 205:
            descriptors = {}
            for raw in repeated(f, 1):
                d = fields(raw)
                event_id = scalar(d, 1)
                if event_id is None or event_id > 65535 or event_id in descriptors:
                    raise ProbeError('event-descriptor-id')
                keys = []
                for key in repeated(d, 3):
                    k = fields(key)
                    kind, name = scalar(k, 1), text(scalar(k, 2, 2))
                    if kind is None or kind > 0x7fffffff or name in [name for _, name in keys]:
                        raise ProbeError('event-descriptor-key')
                    keys.append((kind, name))
                descriptors[event_id] = (text(scalar(d, 2, 2)), keys)
            self.descriptors = descriptors
        elif message_id == 207:
            self.event(f)

    def event(self, f):
        descriptor = self.descriptors.get(scalar(f, 2))
        if descriptor is None:
            self.unresolved_events += 1
            return  # No bundled/hard-coded event IDs or speculative name-only decode.
        name, keys = descriptor
        if name not in EVENTS:
            return
        supplied_name = scalar(f, 1, 2)
        if supplied_name is not None and text(supplied_name) != name:
            raise ProbeError('event-name-mismatch')
        values = repeated(f, 3)
        if len(values) != len(keys):
            raise ProbeError('event-key-count')
        weapon = None
        for (kind, key), raw in zip(keys, values):
            value = fields(raw)
            if scalar(value, 1) != kind:
                raise ProbeError('event-key-type')
            # Only the intended output scalar is retained; no arbitrary strings/IDs.
            if key == 'weapon':
                if kind != 1:
                    raise ProbeError('event-weapon-type')
                weapon = text(scalar(value, 2, 2), 128)
        event_tick = int32(scalar(f, 4))
        if event_tick is not None and event_tick < 0:
            event_tick = None
        tick = event_tick if event_tick is not None else self.tick
        self.emit({'kind': name, 'tick': tick,
                   'tick_source': 'event.server_tick' if event_tick is not None else 'net_Tick' if tick is not None else None,
                   'net_tick': self.tick, 'event_server_tick': event_tick,
                   'weapon': weapon, 'map': self.server['map'] if self.server else None,
                   'tick_interval': self.server['tick_interval'] if self.server else None,
                   'actor': None, 'target': None, 'warmup': None, 'round': None,
                   'online_success': 'INCONCLUSIVE'})
