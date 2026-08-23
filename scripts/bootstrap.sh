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

cat <<'EOF'

Done.  Next steps:

  uv run invoke --list            # every available task
  uv run invoke lint syntax       # the checks CI runs
  uv run invoke check             # dry run against this machine
  uv run invoke apply             # provision for real

If this machine needs secrets, create the vault password file OUTSIDE the
repository and then initialise the vault:

  mkdir -p ~/.config/ansible
  install -m 0600 /dev/null ~/.config/ansible/vault_pass
  $EDITOR ~/.config/ansible/vault_pass
  uv run invoke vault-init

Never write the password with `echo` - it would land in your shell history.
EOF
