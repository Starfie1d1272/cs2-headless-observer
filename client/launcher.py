"""Interactive entry point for the portable Windows observer."""
import os
from pathlib import Path
from host_version import discover_host, host_version
import sys
from datetime import datetime, timezone


def main():
    base = Path(__file__).resolve().parent
    if os.name != 'nt':
        raise SystemExit('This entry point requires Windows x64.')
    print('CS2 Headless Observer')
    print('Use your logged-in Steam account and an authorized spectator source.')
    game = Path(input('CS2 installation folder: ').strip().strip('"')).resolve(strict=True)
    api = game / 'game/bin/win64/steam_api64.dll'
    info = game / 'game/csgo/steam.inf'
    if not api.is_file() or not info.is_file():
        raise SystemExit('CS2 folder must contain game/bin/win64/steam_api64.dll and game/csgo/steam.inf.')
    suggested = discover_host(info)
    version = str(host_version(input(f'Actual source host version [{suggested}]: ').strip() or suggested))
    existing = os.environ.get('SteamAppId')
    if existing and existing != '730':
        raise SystemExit('Launch outside another Steam application context.')
    # Process-local application selection; Steam still validates the user's
    # legitimate account/context. No app-id file, login or ticket is persisted.
    os.environ['SteamAppId'] = '730'
    runs = base.parent / 'runs'
    runs.mkdir(exist_ok=True)
    output = runs / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-%fZ')
    sys.argv = [str(base / 'driver.py'), '--native', str(base / 'cs2_observer.dll'),
        '--steam-api', str(api), '--node', str(base.parent / 'runtime/node.exe'),
        '--host-version', version, '--output', str(output)]
    import driver
    try:
        return driver.main()
    finally:
        if existing is None:
            os.environ.pop('SteamAppId', None)
        print(f'Local report folder: {output}')


if __name__ == '__main__':
    raise SystemExit(main())
