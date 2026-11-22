"""Developer task runner for ansible-workstation.

Every check that CI performs is a task in this file, so CI and a local machine
run byte-identical commands.  Invoke with ``uv run invoke <task>``.
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from invoke import Context, Exit, task

ROOT = Path(__file__).parent.resolve()
PLAYBOOKS = [
    "playbooks/site.yml",
    "playbooks/windows.yml",
    "playbooks/maintenance.yml",
]
# The first entry is the default target: `invoke converge` with no
# `--ubuntu` uses it.
UBUNTU_TARGETS = ["26.04", "24.04"]

# requirements.txt is this command's output, never edited by hand.
EXPORT = "uv export --no-dev --no-hashes --format requirements-txt"

# Pins that carry a SHA-256 next to their version.  Renovate raises the
# version; `invoke checksums` rewrites the checksums to match it.
CHEZMOI_DEFAULTS = ROOT / "roles" / "chezmoi" / "defaults" / "main.yml"
CHEZMOI_RELEASES = "https://github.com/twpayne/chezmoi/releases/download"
FONTS_DEFAULTS = ROOT / "roles" / "fonts" / "defaults" / "main.yml"
FONTS_RELEASES = "https://github.com/ryanoasis/nerd-fonts/releases/download"

ANTORA_PLAYBOOK = "antora-playbook.yml"
NODE_MODULES = ROOT / "node_modules"
SITE_DIR = ROOT / "build" / "site"


@task
def setup(c: Context) -> None:
    """Create the virtual environment and install Galaxy requirements."""
    c.run("uv sync", pty=True)
    c.run("uv run ansible-galaxy install -r requirements.yml", pty=True)


@task
def lock(c: Context) -> None:
    """Refresh uv.lock and the exported requirements.txt."""
    c.run("uv lock", pty=True)
    c.run(f"{EXPORT} -o requirements.txt", pty=True)


def requirement_lines(text: str) -> list[str]:
    """Return the requirement lines of an exported file, comments dropped."""
    return [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


@task(name="lock-check")
def lock_check(c: Context) -> None:
    """Fail when uv.lock or requirements.txt no longer match pyproject.toml.

    Renovate updates ``uv.lock`` but cannot regenerate the exported
    ``requirements.txt``; this is what catches the two drifting apart.
    """
    c.run("uv lock --check", pty=True)
    exported = c.run(f"{EXPORT} --frozen", hide=True).stdout
    committed = (ROOT / "requirements.txt").read_text()
    if requirement_lines(exported) != requirement_lines(committed):
        raise Exit(
            "requirements.txt does not match uv.lock. Run "
            "`uv run invoke lock` and commit both files.",
            code=1,
        )


@task
def fmt(c: Context) -> None:
    """Format the Python sources."""
    c.run("ruff format .", pty=True)


def tracked(c: Context, *patterns: str) -> list[str]:
    """Return the files git tracks, optionally narrowed by pathspecs.

    Linting only tracked files keeps ``.venv``, ``node_modules`` and build
    output out of every check without a separate exclude list per tool.
    """
    out = c.run(
        shlex.join(["git", "ls-files", "-z", "--", *patterns]),
        hide=True,
    ).stdout
    return [name for name in out.split("\0") if name]


@task
def leaks(c: Context) -> None:
    """Scan the whole git history for committed secrets with gitleaks.

    gitleaks is not on PyPI, so it is the one lint tool outside uv.lock:
    the devcontainer and CI install it from the Ubuntu archive.  Findings
    are redacted, so a real secret is not printed a second time.
    """
    if shutil.which("gitleaks") is None:
        raise Exit(
            "gitleaks is required to scan for secrets "
            "(`sudo apt install gitleaks`; preinstalled in the devcontainer)",
            code=2,
        )
    c.run("gitleaks detect --redact --no-banner --source .", pty=True)


@task
def lint(c: Context) -> None:
    """Check the lock files and secrets, then lint every kind of source."""
    lock_check(c)
    leaks(c)
    c.run("yamllint .", pty=True)
    c.run("ansible-lint", pty=True)
    c.run("ruff check .", pty=True)
    c.run("ruff format --check .", pty=True)
    c.run(shlex.join(["shellcheck", *tracked(c, "*.sh")]), pty=True)
    # actionlint also runs shellcheck over every `run:` block.
    c.run("actionlint", pty=True)
    c.run("zizmor --offline .", pty=True)
    c.run(shlex.join(["ec", *tracked(c)]), pty=True)


@task
def syntax(c: Context) -> None:
    """Parse every playbook without executing it."""
    for playbook in PLAYBOOKS:
        c.run(f"ansible-playbook {playbook} --syntax-check", pty=True)


def site_playbook(*args: str, tags: str = "") -> None:
    """Run the site playbook attached to this terminal, asking for sudo.

    Not through ``c.run``: Invoke relays the terminal through a pty of its
    own, and Ansible's password prompt behind that relay loses the first
    keystroke, echoes the rest and never sees Enter.  Started directly, the
    playbook talks to the terminal itself, as it would from a shell.
    """
    cmd = ["ansible-playbook", "playbooks/site.yml", "--ask-become-pass"]
    cmd += [*args, *(["--tags", tags] if tags else [])]
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    if result.returncode != 0:
        raise Exit(code=result.returncode)


@task(help={"tags": "Comma separated list of tags to limit the run to."})
def check(c: Context, tags: str = "") -> None:
    """Dry-run the site playbook against this machine.

    Asks for the sudo password like ``apply``: tasks that need root
    escalate in check mode too.
    """
    site_playbook("--check", "--diff", tags=tags)


@task(help={"tags": "Comma separated list of tags to limit the run to."})
def apply(c: Context, tags: str = "") -> None:
    """Provision this machine for real.

    Run it as the login account, not with sudo: the playbook asks for the
    sudo password and uses it per task, and the docker and kvm roles add
    the account that runs it to their groups.
    """
    site_playbook(tags=tags)


@task(
    help={
        "ubuntu": "Ubuntu release to converge against "
        f"({' or '.join(UBUNTU_TARGETS)}; default {UBUNTU_TARGETS[0]})."
    }
)
def converge(c: Context, ubuntu: str = UBUNTU_TARGETS[0]) -> None:
    """Converge twice in a throwaway container; the second run must be a no-op.

    The container runs the playbook as root, so root is the account the
    docker and kvm roles add to their groups there.
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


@task(name="all", pre=[lint, syntax, site])
def run_all(c: Context) -> None:
    """Run everything CI runs, for every Ubuntu target."""
    for ubuntu in UBUNTU_TARGETS:
        print(f"\n=== converge {ubuntu} ===", file=sys.stderr)
        converge(c, ubuntu=ubuntu)


def pinned(text: str, variable: str) -> str:
    """Return the value of a top-level ``variable: value`` line in YAML."""
    match = re.search(rf'^{variable}: "?([^"\n]+)"?$', text, re.MULTILINE)
    if match is None:
        raise Exit(f"{variable} not found", code=2)
    return match.group(1)


def release_checksums(c: Context, url: str) -> dict[str, str]:
    """Download a ``<sha256>  <file>`` listing and map file name to sum."""
    listing = c.run(f"curl -fsSL {url}", hide=True).stdout
    sums = {}
    for line in listing.splitlines():
        fields = line.split()
        if len(fields) == 2 and re.fullmatch(r"[0-9a-f]{64}", fields[0]):
            sums[fields[1].lstrip("*")] = fields[0]
    return sums


def rewrite(
    path: Path, pattern: str, sums: dict[str, str], key: str, check: bool
) -> bool:
    """Point every SHA-256 that ``pattern`` finds at its released value.

    ``pattern`` captures the text before the checksum as ``head``, the
    checksum as ``sha`` and the name it belongs to as ``name``; ``key`` turns
    that name into a file name of the release listing.  Returns whether a
    checksum was stale.
    """
    text = path.read_text()

    def replace(match: re.Match[str]) -> str:
        file = key.format(name=match["name"])
        if file not in sums:
            raise Exit(f"{file} is not in the release's checksums", code=1)
        state = "ok" if match["sha"] == sums[file] else "stale"
        print(f"{path.relative_to(ROOT)}: {file}: {state}")
        return match["head"] + sums[file]

    updated = re.sub(pattern, replace, text, flags=re.MULTILINE)
    if updated != text and not check:
        path.write_text(updated)
    return updated != text


@task(help={"check": "Only report stale checksums; write nothing."})
def checksums(c: Context, check: bool = False) -> None:
    """Rewrite the SHA-256 pins to match the pinned release versions.

    chezmoi and the Nerd Font are pinned to a version *and* a checksum.
    Renovate raises the version but cannot compute the checksum, so its pull
    request fails converge until this has been run on its branch.
    """
    chezmoi = pinned(CHEZMOI_DEFAULTS.read_text(), "chezmoi_version")
    fonts = pinned(FONTS_DEFAULTS.read_text(), "fonts_nerd_fonts_version")
    stale = rewrite(
        CHEZMOI_DEFAULTS,
        r"^(?P<head>  (?P<name>[a-z0-9]+): )(?P<sha>[0-9a-f]{64})$",
        release_checksums(
            c,
            f"{CHEZMOI_RELEASES}/v{chezmoi}/chezmoi_{chezmoi}_checksums.txt",
        ),
        f"chezmoi_{chezmoi}_linux_{{name}}.deb",
        check,
    )
    stale |= rewrite(
        FONTS_DEFAULTS,
        r"^(?P<head>\s+- name: (?P<name>\w+)\n\s+sha256: >-\n\s+)"
        r"(?P<sha>[0-9a-f]{64})$",
        release_checksums(c, f"{FONTS_RELEASES}/{fonts}/SHA-256.txt"),
        "{name}.zip",
        check,
    )
    if stale and check:
        raise Exit("checksums are stale; run `uv run invoke checksums`", 1)
