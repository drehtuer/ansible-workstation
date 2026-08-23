"""Developer task runner for ansible-workstation.

Every check that CI performs is a task in this file, so CI and a local machine
run byte-identical commands.  Invoke with ``uv run invoke <task>``.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from invoke import Context, Exit, task

ROOT = Path(__file__).parent.resolve()
PLAYBOOKS = ["playbooks/site.yml", "playbooks/windows.yml"]
UBUNTU_TARGETS = ["24.04", "26.04"]

VAULT_PASSWORD_FILE = Path.home() / ".config" / "ansible" / "vault_pass"
VAULT_FILE = ROOT / "inventory" / "group_vars" / "all" / "vault.yml"


def vault_args() -> str:
    """Return the vault flag, but only when a password file actually exists.

    An absent password file is silently ignored so that lint, syntax checks and
    CI work on a machine that holds no secrets.  The password itself is never
    read here -- only the path is handed to ansible.
    """
    return f"--vault-password-file {VAULT_PASSWORD_FILE}" if VAULT_PASSWORD_FILE.is_file() else ""


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
    c.run("uv export --no-dev --no-hashes --format requirements-txt -o requirements.txt", pty=True)


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
    c.run(ansible(f"ansible-playbook playbooks/site.yml --check --diff{limit}"), pty=True)


@task(help={"tags": "Comma separated list of tags to limit the run to."})
def apply(c: Context, tags: str = "") -> None:
    """Provision this machine for real."""
    limit = f" --tags {tags}" if tags else ""
    c.run(ansible(f"ansible-playbook playbooks/site.yml --ask-become-pass{limit}"), pty=True)


@task(help={"ubuntu": f"Ubuntu release to converge against ({' or '.join(UBUNTU_TARGETS)})."})
def converge(c: Context, ubuntu: str = UBUNTU_TARGETS[0]) -> None:
    """Converge twice in a throwaway container; the second run must be a no-op.

    No vault password is used.  Secret-consuming tasks carry the ``secrets``
    tag and are skipped; ``tests/vars.ci.yml`` supplies obviously-fake values
    so the same code paths still execute.
    """
    if ubuntu not in UBUNTU_TARGETS:
        raise Exit(f"unsupported target {ubuntu!r}, expected one of {UBUNTU_TARGETS}", code=2)
    if shutil.which("docker") is None:
        raise Exit("docker is required for converge tests", code=2)

    script = (
        "set -eu\n"
        "export DEBIAN_FRONTEND=noninteractive\n"
        "apt-get update -qq\n"
        "apt-get install -y -qq python3 python3-venv sudo git >/dev/null\n"
        "python3 -m venv /venv\n"
        "/venv/bin/pip install --quiet --upgrade pip\n"
        "/venv/bin/pip install --quiet -r requirements.txt\n"
        "/venv/bin/ansible-galaxy install -r requirements.yml\n"
        "run() { /venv/bin/ansible-playbook playbooks/site.yml"
        ' --skip-tags secrets -e @tests/vars.ci.yml "$@"; }\n'
        'echo "=== converge 1 ==="\n'
        "run\n"
        'echo "=== converge 2 (must report changed=0) ==="\n'
        "run | tee /tmp/second.log\n"
        'grep -q "changed=0" /tmp/second.log || { echo "NOT IDEMPOTENT"; exit 1; }\n'
    )
    c.run(
        f"docker run --rm -v {ROOT}:/repo -w /repo ubuntu:{ubuntu} bash -c {script!r}",
        pty=True,
    )


@task
def docs(c: Context) -> None:
    """Render every AsciiDoc file to HTML."""
    if shutil.which("asciidoctor") is None:
        raise Exit("asciidoctor is not installed (available in the devcontainer)", code=2)
    outdir = ROOT / "build" / "docs"
    outdir.mkdir(parents=True, exist_ok=True)
    for adoc in sorted(ROOT.glob("*.adoc")) + sorted((ROOT / "docs").glob("*.adoc")):
        c.run(f"asciidoctor -D {outdir} {adoc}", pty=True)


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


@task
def vault_edit(c: Context) -> None:
    """Edit the vault in place; it is never decrypted to disk."""
    password_file = require_password_file()
    if not VAULT_FILE.exists():
        raise Exit(f"{VAULT_FILE} does not exist -- run `invoke vault-init` first", code=2)
    c.run(f"ansible-vault edit --vault-password-file {password_file} {VAULT_FILE}", pty=True)


@task
def vault_init(c: Context) -> None:
    """Create the encrypted vault from its example template.

    The password file must already exist and must live outside this repository.
    """
    password_file = require_password_file()
    if VAULT_FILE.exists():
        raise Exit(f"{VAULT_FILE} already exists", code=2)
    VAULT_FILE.write_text(VAULT_FILE.with_suffix(".yml.example").read_text())
    c.run(f"ansible-vault encrypt --vault-password-file {password_file} {VAULT_FILE}", pty=True)


@task(name="all", pre=[lint, syntax])
def run_all(c: Context) -> None:
    """Run everything CI runs, for every Ubuntu target."""
    for ubuntu in UBUNTU_TARGETS:
        print(f"\n=== converge {ubuntu} ===", file=sys.stderr)
        converge(c, ubuntu=ubuntu)
