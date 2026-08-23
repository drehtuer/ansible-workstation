"""Developer task runner for ansible-workstation.

Every check that CI performs is a task in this file, so CI and a local machine
run byte-identical commands.  Invoke with ``uv run invoke <task>``.
"""

from __future__ import annotations

import shutil
import socket
import sys
from pathlib import Path

from invoke import Context, Exit, task

ROOT = Path(__file__).parent.resolve()
PLAYBOOKS = ["playbooks/site.yml", "playbooks/windows.yml"]
UBUNTU_TARGETS = ["24.04", "26.04"]

VAULT_PASSWORD_FILE = Path.home() / ".config" / "ansible" / "vault_pass"
VAULT_FILE = ROOT / "inventory" / "group_vars" / "all" / "vault.yml"
HOST_VARS = ROOT / "inventory" / "host_vars"

HOST_HELP = (
    "Work on this machine's own vault under inventory/host_vars/, "
    "instead of the one shared by every machine."
)

ANTORA_PLAYBOOK = "antora-playbook.yml"
NODE_MODULES = ROOT / "node_modules"
SITE_DIR = ROOT / "build" / "site"


def vault_args() -> str:
    """Return the vault flag, but only when a password file actually exists.

    An absent password file is silently ignored so that lint, syntax checks and
    CI work on a machine that holds no secrets.  The password itself is never
    read here -- only the path is handed to ansible.
    """
    return (
        f"--vault-password-file {VAULT_PASSWORD_FILE}"
        if VAULT_PASSWORD_FILE.is_file()
        else ""
    )


def ansible(cmd: str) -> str:
    """Prefix an ansible command with the vault flag, when one applies."""
    args = vault_args()
    return f"{cmd} {args}" if args else cmd


@task
def setup(c: Context) -> None:
    """Create the virtual environment and install Galaxy requirements."""
    c.run("uv sync", pty=True)
    c.run("uv run ansible-galaxy install -r requirements.yml", pty=True)


@task
def lock(c: Context) -> None:
    """Refresh uv.lock and the exported requirements.txt."""
    c.run("uv lock", pty=True)
    c.run(
        "uv export --no-dev --no-hashes --format requirements-txt "
        "-o requirements.txt",
        pty=True,
    )


@task
def fmt(c: Context) -> None:
    """Format the Python sources."""
    c.run("ruff format .", pty=True)


@task
def lint(c: Context) -> None:
    """Lint YAML, Ansible content and Python sources."""
    c.run("yamllint .", pty=True)
    c.run("ansible-lint", pty=True)
    c.run("ruff check .", pty=True)
    c.run("ruff format --check .", pty=True)


@task
def syntax(c: Context) -> None:
    """Parse every playbook without executing it."""
    for playbook in PLAYBOOKS:
        c.run(ansible(f"ansible-playbook {playbook} --syntax-check"), pty=True)


@task(help={"tags": "Comma separated list of tags to limit the run to."})
def check(c: Context, tags: str = "") -> None:
    """Dry-run the site playbook against this machine."""
    limit = f" --tags {tags}" if tags else ""
    c.run(
        ansible(f"ansible-playbook playbooks/site.yml --check --diff{limit}"),
        pty=True,
    )


@task(help={"tags": "Comma separated list of tags to limit the run to."})
def apply(c: Context, tags: str = "") -> None:
    """Provision this machine for real."""
    limit = f" --tags {tags}" if tags else ""
    c.run(
        ansible(
            f"ansible-playbook playbooks/site.yml --ask-become-pass{limit}"
        ),
        pty=True,
    )


@task(
    help={
        "ubuntu": "Ubuntu release to converge against "
        f"({' or '.join(UBUNTU_TARGETS)})."
    }
)
def converge(c: Context, ubuntu: str = UBUNTU_TARGETS[0]) -> None:
    """Converge twice in a throwaway container; the second run must be a no-op.

    No vault password is used.  Secret-consuming tasks carry the ``secrets``
    tag and are skipped; ``tests/vars.ci.yml`` supplies obviously-fake values
    so the same code paths still execute.
    """
    if ubuntu not in UBUNTU_TARGETS:
        raise Exit(
            f"unsupported target {ubuntu!r}, expected one of {UBUNTU_TARGETS}",
            code=2,
        )
    if shutil.which("docker") is None:
        raise Exit("docker is required for converge tests", code=2)

    # The script lives in a file rather than inline: passing a multi-line
    # script through `bash -c` invites quoting bugs, and a real file can be
    # syntax-checked and read on its own.
    # Mounted read-only: the script copies the repository aside and works
    # there, so a converge can never write back into the checkout.
    c.run(
        f"docker run --rm -v {ROOT}:/repo:ro -w /repo ubuntu:{ubuntu} "
        "bash /repo/tests/converge.sh",
        pty=True,
    )


@task(help={"fetch": "Re-download the UI bundle instead of reusing the cache."})
def site(c: Context, fetch: bool = False) -> None:
    """Build the documentation site with Antora.

    Antora reads the *worktree*, so uncommitted documentation is part of the
    build.  A broken xref or an unresolved include fails the task, which is
    what makes this worth running in CI.
    """
    if shutil.which("npm") is None:
        raise Exit(
            "npm is required to build the site "
            "(Node.js; preinstalled in the devcontainer)",
            code=2,
        )
    if not NODE_MODULES.is_dir():
        c.run("npm ci", pty=True)
    c.run(
        f"npx antora{' --fetch' if fetch else ''} {ANTORA_PLAYBOOK}",
        pty=True,
    )
    print(f"site written to {SITE_DIR}", file=sys.stderr)


def vault_file(host: bool) -> tuple[Path, Path]:
    """Return the vault to work on and the example it is created from.

    With ``host``, that is this machine's own vault under
    ``inventory/host_vars/<hostname>/`` -- the same name the inventory
    reports.  Without it, the vault shared by every machine.
    """
    if not host:
        return VAULT_FILE, VAULT_FILE.with_suffix(".yml.example")
    name = socket.gethostname().split(".", 1)[0]
    return HOST_VARS / name / "vault.yml", HOST_VARS / "vault.yml.example"


def require_password_file() -> Path:
    """Return the vault password file, explaining how to create it if absent."""
    if VAULT_PASSWORD_FILE.is_file():
        return VAULT_PASSWORD_FILE
    raise Exit(
        f"password file {VAULT_PASSWORD_FILE} is missing -- create it with\n"
        f"  mkdir -p {VAULT_PASSWORD_FILE.parent}\n"
        f"  install -m 0600 /dev/null {VAULT_PASSWORD_FILE}\n"
        f"  $EDITOR {VAULT_PASSWORD_FILE}\n"
        "Do not use `echo`; the password would land in your shell history.",
        code=2,
    )


@task(help={"host": HOST_HELP})
def vault_edit(c: Context, host: bool = False) -> None:
    """Edit a vault in place; it is never decrypted to disk."""
    password_file = require_password_file()
    target, _ = vault_file(host)
    if not target.exists():
        raise Exit(
            f"{target} does not exist -- run `invoke vault-init"
            f"{' --host' if host else ''}` first",
            code=2,
        )
    c.run(
        f"ansible-vault edit --vault-password-file {password_file} {target}",
        pty=True,
    )


@task(help={"host": HOST_HELP})
def vault_init(c: Context, host: bool = False) -> None:
    """Create an encrypted vault from its example template.

    The password file must already exist and must live outside this
    repository.  One password covers every vault here, shared or per-host.
    """
    password_file = require_password_file()
    target, example = vault_file(host)
    if target.exists():
        raise Exit(f"{target} already exists", code=2)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(example.read_text())
    c.run(
        f"ansible-vault encrypt --vault-password-file {password_file} {target}",
        pty=True,
    )


@task(name="all", pre=[lint, syntax, site])
def run_all(c: Context) -> None:
    """Run everything CI runs, for every Ubuntu target."""
    for ubuntu in UBUNTU_TARGETS:
        print(f"\n=== converge {ubuntu} ===", file=sys.stderr)
        converge(c, ubuntu=ubuntu)
