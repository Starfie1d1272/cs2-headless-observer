"""Interactive entry point for the portable Windows research client."""
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timezone


def main():
    base = Path(__file__).resolve().parent
    if os.name != 'nt':
        raise SystemExit('This entry point requires Windows x64.')
    print('Mizar ordinary GOTV viewer — connection research build')
    print('Use your logged-in Steam account and an authorized test match.')
    game = Path(input('CS2 installation folder: ').strip().strip('"')).resolve(strict=True)
    api = game / 'game/bin/win64/steam_api64.dll'
    info = game / 'game/csgo/steam.inf'
    if not api.is_file() or not info.is_file():
        raise SystemExit('CS2 folder must contain game/bin/win64/steam_api64.dll and game/csgo/steam.inf.')
    if info.stat().st_size > 65536:
        raise SystemExit('Unexpected steam.inf size.')
    match = re.search(r'^PatchVersion=(\d+(?:\.\d+){1,4})\s*$', info.read_text(encoding='utf8'), re.M)
    suggested = match.group(1).replace('.', '') if match else ''
    version = input(f'Host version from CS2 version output [{suggested}]: ').strip() or suggested
    if not re.fullmatch(r'\d{1,10}', version) or not 0 < int(version) <= 0xffffffff:
        raise SystemExit('Enter the numeric host version shown by the current CS2 client.')
    existing = os.environ.get('SteamAppId')
    if existing and existing != '730':
        raise SystemExit('Launch outside another Steam application context.')
    # Process-local application selection; Steam still validates the user's
    # legitimate account/context. No app-id file, login or ticket is persisted.
    os.environ['SteamAppId'] = '730'
    runs = base.parent / 'runs'
    runs.mkdir(exist_ok=True)
    output = runs / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-%fZ')
    sys.argv = [str(base / 'driver.py'), '--native', str(base / 'mizar_observer.dll'),
        '--steam-api', str(api), '--node', str(base.parent / 'runtime/node.exe'),
        '--host-version', version, '--output', str(output), '--seconds', '300']
    import driver
    try:
        return driver.main()
    finally:
        if existing is None:
            os.environ.pop('SteamAppId', None)
        print(f'Local report folder: {output}')


if __name__ == '__main__':
    raise SystemExit(main())
