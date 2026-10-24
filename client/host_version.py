"""Local version discovery is a suggestion, not a protocol compatibility whitelist."""
from pathlib import Path
import re


def host_version(value):
    number = int(value)
    if not 0 < number <= 0xffffffff:
        raise ValueError('host-version-boundary')
    return number


def discover_host(path):
    path = Path(path)
    if path.stat().st_size > 65536:
        raise ValueError('steam-info-budget')
    match = re.search(r'^PatchVersion=(\d+(?:\.\d+){1,4})\s*$', path.read_text(encoding='utf-8'), re.M)
    if not match:
        raise ValueError('steam-info-version-missing')
    return host_version(match.group(1).replace('.', ''))
