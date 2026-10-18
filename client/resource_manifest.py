"""Decode the resource-name manifest carried by ordinary SpawnGroup messages.

Names remain data: this module never opens paths, loads assets or acknowledges
world readiness. Format observations are recorded in INITIALIZATION-EVIDENCE.
"""
from channel import Bits, MAX_BYTES
from wire import ProbeError


def expand_lzss(data):
    if len(data) <= 8 or data[:4] != b'LZSS':
        raise ProbeError('manifest-compression-header')
    expected = int.from_bytes(data[4:8], 'little')
    if not 0 < expected <= MAX_BYTES:
        raise ProbeError('manifest-expanded-budget')
    output = bytearray()
    cursor = 8
    while cursor < len(data):
        commands = data[cursor]
        cursor += 1
        for bit in range(8):
            width = 2 if commands & (1 << bit) else 1
            if cursor + width > len(data):
                raise ProbeError('manifest-compression-truncated')
            token = data[cursor:cursor + width]
            cursor += width
            if width == 1:
                if len(output) >= expected:
                    raise ProbeError('manifest-expanded-overflow')
                output.append(token[0])
                continue
            count = (token[1] & 15) + 1
            if count == 1:
                if len(output) != expected or cursor != len(data):
                    raise ProbeError('manifest-compression-end')
                return bytes(output)
            distance = (token[0] << 4 | token[1] >> 4) + 1
            if distance > len(output) or len(output) + count > expected:
                raise ProbeError('manifest-compression-reference')
            for _ in range(count):
                output.append(output[-distance])
    raise ProbeError('manifest-compression-missing-end')


def _string(reader):
    value = bytearray()
    for _ in range(4096):
        char = reader.read(8)
        if not char:
            try:
                return value.decode('utf8')
            except UnicodeError:
                raise ProbeError('manifest-string-encoding') from None
        value.append(char)
    raise ProbeError('manifest-string-budget')


def decode_resource_manifest(data):
    if not isinstance(data, bytes) or len(data) > 128 * 1024:
        raise ProbeError('manifest-wire-budget')
    if not data:
        return []
    envelope = Bits(data)
    compressed, size = envelope.read(1), envelope.read(24)
    payload = envelope.bytes(size)
    if envelope.end - envelope.pos >= 8:
        raise ProbeError('manifest-trailing-bytes')
    if compressed:
        payload = expand_lzss(payload)
    reader = Bits(payload)
    extension_count, directory_count, resource_count = [reader.read(16) for _ in range(3)]
    if resource_count > 16384:
        raise ProbeError('manifest-resource-count-budget')
    extensions = [_string(reader) for _ in range(extension_count)]
    directories = [_string(reader) for _ in range(directory_count)]
    directory_bits = max(1, (directory_count - 1).bit_length())
    extension_bits = max(1, (extension_count - 1).bit_length())
    resources = []
    for _ in range(resource_count):
        directory = reader.read(directory_bits)
        name = _string(reader)
        extension = reader.read(extension_bits)
        if directory >= directory_count or extension >= extension_count:
            raise ProbeError('manifest-symbol-index')
        resources.append({'directory': directories[directory], 'name': name,
                          'extension': extensions[extension]})
    if reader.end - reader.pos >= 8:
        raise ProbeError('manifest-payload-trailing-bytes')
    return resources
