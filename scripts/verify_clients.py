"""Read-only verification of setup's client entries; never print config secrets."""

import argparse
import sys
from pathlib import Path

import tomlkit

from chemcad_mcp.configure import CLIENTS, client_paths, read_config, server_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clients", choices=CLIENTS, nargs="+", default=list(CLIENTS))
    parser.add_argument("--config-root", type=Path)
    args = parser.parse_args()
    python = Path(sys.executable).resolve()
    targets = client_paths(args.config_root)
    failed = False
    for client in args.clients:
        section, expected = server_config(client, python)
        for path in targets[client]:
            try:
                config, _ = read_config(path)
                servers = config.get(section, {})
                valid = isinstance(servers, dict) and servers.get("chemcad") == expected
            except (OSError, ValueError, tomlkit.exceptions.ParseError):
                valid = False
            print(f"{client}: {'OK' if valid else 'MISSING/DIFFERENT'} ({path})")
            failed |= not valid
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
