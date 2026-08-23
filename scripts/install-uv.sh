#!/usr/bin/env bash
#
# Install uv and its system prerequisites on a clean Ubuntu.
#
# Deliberately standalone: it makes no assumption about this repository, so the
# same script serves three callers --
#   * a fresh WSL distribution, run by hand
#   * scripts/bootstrap.sh, which continues with the project virtualenv
#   * the devcontainer image build, which runs it as root
#
# Idempotent: re-running it when uv is already present does nothing.
#
# Environment:
#   UV_INSTALL_DIR   where the uv binary lands
#                    (default: /usr/local/bin as root, ~/.local/bin otherwise)
#   UV_VERSION       pin a specific release (default: latest)
set -euo pipefail

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }

# Run privileged commands directly when root, otherwise via sudo.
if [[ "$(id -u)" -eq 0 ]]; then
    SUDO=""
    : "${UV_INSTALL_DIR:=/usr/local/bin}"
else
    if ! command -v sudo >/dev/null 2>&1; then
        warn "not root and sudo is unavailable; system packages cannot be installed"
    fi
    SUDO="sudo"
    : "${UV_INSTALL_DIR:=$HOME/.local/bin}"
fi

# Everything uv needs to build a working environment, plus the tools the
# playbooks assume exist before ansible takes over.
APT_PACKAGES=(
    ca-certificates
    curl
    git
    python3
    python3-venv
)

install_prerequisites() {
    local missing=()
    for pkg in "${APT_PACKAGES[@]}"; do
        dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "^install ok installed$" \
            || missing+=("$pkg")
    done

    if [[ ${#missing[@]} -eq 0 ]]; then
        log "System prerequisites already present"
        return
    fi

    log "Installing system prerequisites: ${missing[*]}"
    DEBIAN_FRONTEND=noninteractive $SUDO apt-get update -qq
    DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y --no-install-recommends "${missing[@]}"
}

install_uv() {
    if command -v uv >/dev/null 2>&1; then
        log "uv already installed: $(uv --version)"
        return
    fi

    log "Installing uv into ${UV_INSTALL_DIR}"
    mkdir -p "$UV_INSTALL_DIR"

    # The installer writes only into UV_INSTALL_DIR and does not edit shell
    # profiles when UV_NO_MODIFY_PATH is set -- PATH stays under our control.
    local installer="https://astral.sh/uv/install.sh"
    [[ -n "${UV_VERSION:-}" ]] && installer="https://astral.sh/uv/${UV_VERSION}/install.sh"

    curl -LsSf "$installer" \
        | env UV_INSTALL_DIR="$UV_INSTALL_DIR" UV_NO_MODIFY_PATH=1 sh
}

ensure_on_path() {
    if command -v uv >/dev/null 2>&1; then
        return
    fi

    export PATH="$UV_INSTALL_DIR:$PATH"
    if ! command -v uv >/dev/null 2>&1; then
        warn "uv is not on PATH after installation; expected it in ${UV_INSTALL_DIR}"
        return 1
    fi

    # Only worth suggesting for a per-user install; /usr/local/bin is already
    # on every sane PATH.
    if [[ "$UV_INSTALL_DIR" == "$HOME"/* ]]; then
        cat <<EOF

uv is installed but not yet on your PATH.  Add this to your shell profile:

    export PATH="${UV_INSTALL_DIR}:\$PATH"

EOF
    fi
}

main() {
    install_prerequisites
    install_uv
    ensure_on_path
    log "Ready: $(uv --version 2>/dev/null || echo 'uv (restart your shell)')"
}

main "$@"
