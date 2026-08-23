"""Pre-commit guard: refuse plaintext vaults and stray password files.

Run over staged files.  Exits non-zero with an explanation when a file that is
supposed to be an encrypted vault is not, or when something that looks like a
vault password file is about to be committed.
"""

from __future__ import annotations

import sys
from pathlib import Path

VAULT_HEADER = "$ANSIBLE_VAULT"
PASSWORD_NAME_HINTS = ("vault_pass", "vault-pass", ".vault_password")


VAULT_DIRS = ("group_vars", "host_vars")


def is_vault_file(path: Path) -> bool:
    """True for files this repository requires to be encrypted.

    Both the shared vault under ``group_vars/`` and a machine's own vault
    under ``host_vars/<hostname>/`` are covered; the ``.example`` templates
    beside them are not vaults and are left alone.
    """
    return path.name == "vault.yml" and any(
        part in VAULT_DIRS for part in path.parts
    )


def looks_like_password_file(path: Path) -> bool:
    """True for paths whose name suggests they hold a vault password."""
    return any(hint in path.name for hint in PASSWORD_NAME_HINTS)


def main(argv: list[str]) -> int:
    problems: list[str] = []

    for name in argv:
        path = Path(name)
        if not path.is_file():
            continue

        if looks_like_password_file(path):
            problems.append(
                f"{path}: looks like a vault password file and must "
                "never be committed"
            )
            continue

        if is_vault_file(path):
            first_line = path.read_text(errors="replace").partition("\n")[0]
            if not first_line.startswith(VAULT_HEADER):
                problems.append(
                    f"{path}: is not encrypted "
                    f"(expected a {VAULT_HEADER} header)"
                )

    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
