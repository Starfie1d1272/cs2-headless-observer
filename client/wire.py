"""Bounded protobuf control wire helpers; no capture or diagnostic CLI."""
class ProbeError(ValueError):
    pass


def varint(data, pos):
    value = 0
    for shift in range(0, 70, 7):
        if pos >= len(data):
            raise ProbeError('truncated-varint')
        byte = data[pos]
        pos += 1
        if shift == 63 and byte > 1:
            raise ProbeError('overflow-varint')
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
    raise ProbeError('overflow-varint')


def fields(data, *, limit=65535):
    """Bounded protobuf wire inspection; bytes fields stay opaque and are never printed."""
    if type(limit) is not int or not 0 < limit <= 4 * 1024**2 or len(data) > limit:
        raise ProbeError('payload-limit')
    pos, result = 0, {}
    while pos < len(data):
        key, pos = varint(data, pos)
        number, wire = key >> 3, key & 7
        if not 0 < number < (1 << 29):
            raise ProbeError('invalid-field-number')
        if wire == 0:
            value, pos = varint(data, pos)
        elif wire in (1, 2, 5):
            if wire == 2:
                size, pos = varint(data, pos)
            else:
                size = 8 if wire == 1 else 4
            if size > len(data) - pos:
                raise ProbeError('truncated-field')
            value = data[pos:pos + size]
            pos += size
        else:
            raise ProbeError('unsupported-wire-type')
        result.setdefault(number, []).append((wire, value))
    return result


def scalar(f, number, wire=0):
    values = f.get(number, [])
    if not values:
        return None
    if len(values) != 1 or values[0][0] != wire:
        raise ProbeError('ambiguous-or-wrong-wire-field')
    return values[0][1]


