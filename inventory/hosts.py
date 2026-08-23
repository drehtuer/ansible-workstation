#!/usr/bin/env python3
"""Inventory of exactly one host: this machine, under its own name.

Ansible resolves ``host_vars`` by *inventory* hostname.  A static inventory
has to write that name down, and the only name that is true on every machine
is ``localhost`` -- at which point every workstation sharing this repository
reads the same ``host_vars`` file, which defeats the point of having one.

Reporting the machine's real name instead makes
``inventory/host_vars/<hostname>/`` mean what it says, and keeps the names
themselves out of the repository: they are discovered, never committed.

Connection stays local.  There is no SSH here; the machine provisions itself.
"""

from __future__ import annotations

import json
import socket
import sys


def hostname() -> str:
    """Return the short hostname, the same value as ``ansible_hostname``."""
    return socket.gethostname().split(".", 1)[0]


def inventory() -> dict[str, object]:
    """Return the one-host inventory that ``--list`` has to produce."""
    host = hostname()
    return {
        "all": {"hosts": [host]},
        "_meta": {"hostvars": {host: {"ansible_connection": "local"}}},
    }


def main(argv: list[str]) -> int:
    """Answer ``--list``; ``--host`` carries no variables of its own."""
    print(json.dumps({} if "--host" in argv else inventory(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
