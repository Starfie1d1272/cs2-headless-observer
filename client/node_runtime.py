"""Minimum Node capabilities, independent of the application providing it."""
import json
from pathlib import Path
import re
import shutil
import subprocess

MINIMUM_MAJOR = 24
PROBE = """console.log(JSON.stringify({version:process.versions.node,platform:process.platform,arch:process.arch,
features:[typeof WebAssembly,typeof ReadableStream,typeof structuredClone]}))"""


def validate_info(info):
    if not isinstance(info, dict):
        raise ValueError('node-runtime-probe-invalid')
    version = info.get('version')
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('node-runtime-version-invalid')
    if int(version.split('.')[0]) < MINIMUM_MAJOR:
        raise ValueError('node-runtime-requires-24-or-newer')
    if not isinstance(info.get('platform'), str) or not isinstance(info.get('arch'), str):
        raise ValueError('node-runtime-probe-invalid')
    if info.get('features') != ['object', 'function', 'function']:
        raise ValueError('node-runtime-capabilities-missing')
    return info


def inspect_node(executable='node'):
    resolved = shutil.which(str(executable))
    if resolved is None:
        candidate = Path(executable)
        if candidate.is_file():
            resolved = str(candidate.resolve())
    if resolved is None:
        raise ValueError('node-runtime-not-found')
    try:
        result = subprocess.run([resolved, '-e', PROBE], capture_output=True, timeout=10, check=True)
        if len(result.stdout) > 4096:
            raise ValueError('node-runtime-probe-invalid')
        return validate_info(json.loads(result.stdout))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, UnicodeError):
        raise ValueError('node-runtime-probe-failed') from None
