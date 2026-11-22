#!/usr/bin/env bash
#
# Prepare a machine to run these playbooks: install uv (via install-uv.sh),
# create the project virtualenv, and fetch Galaxy content.
#
# Never touches the system python -- Ubuntu 24.04+ refuses that under PEP 668.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

# Step 1: uv and its system prerequisites.  Standalone on purpose, so it can
# also be run by hand on a clean Ubuntu and during the devcontainer build.
# PATH as the calling shell has it, before this script extends its own.
caller_path="$PATH"
./scripts/install-uv.sh
export PATH="${UV_INSTALL_DIR:-$HOME/.local/bin}:$PATH"

# Step 2: pin the dependency tree if it has never been resolved.
if [[ ! -f uv.lock ]]; then
    log "No uv.lock yet - resolving dependencies"
    uv lock
    uv export --no-dev --no-hashes --format requirements-txt -o requirements.txt
    log "Commit uv.lock and requirements.txt so every machine" \
        "resolves identically"
fi

log "Creating the virtualenv from uv.lock"
uv sync

log "Installing Ansible Galaxy requirements"
uv run ansible-galaxy install -r requirements.yml

# The documentation toolchain.  Antora is installed from npm, which
# only the devcontainer has -- a bare WSL distro neither has node nor needs
# it, so this is skipped there instead of failing the bootstrap.
if command -v npm >/dev/null 2>&1; then
    log "Installing Antora from package-lock.json"
    npm ci
else
    log "npm not found - skipping Antora; 'invoke site' needs it"
fi

# On a fresh distro ~/.local/bin did not exist when the login shell started,
# so Ubuntu's ~/.profile left it off PATH; uv is there, but the calling
# shell cannot see it until it is started again.
if ! (PATH="$caller_path"; hash -r; command -v uv) >/dev/null 2>&1; then
    cat <<'EOF'

uv is installed, but not yet on this shell's PATH.  Start a new login shell
first, or reopen the distro:

  exec bash -l
EOF
fi

cat <<'EOF'

Done.  Next steps:

  uv run invoke apply             # provision this machine (asks for sudo)
  chezmoi init --apply <repo>     # then your personal settings: dotfiles,
                                  # git identity, keys

Later on:

  uv run invoke check             # dry run; zero changes on a converged host
  uv run invoke --list            # every available task
EOF
