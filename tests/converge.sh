#!/usr/bin/env bash
#
# Converge twice inside a throwaway container and assert the second run is a
# no-op.  Executed by `invoke converge`; not meant to be run on a real machine,
# since it provisions whatever host it runs on.
#
# No vault password is involved: tasks that consume secrets carry the 'secrets'
# tag and are skipped, while tests/vars.ci.yml supplies obviously-fake values so
# the same code paths still execute.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

# Work on a copy, without the vaults.  CI holds no vault password, and an
# encrypted file under group_vars/ or host_vars/ fails the run while
# variables are being loaded -- long before --skip-tags secrets could matter.
# tests/vars.ci.yml supplies obviously-fake values in their place.  The copy
# also guarantees the container cannot write to the repository it came from.
cp -a /repo /work
cd /work
find inventory -name vault.yml -delete

echo "=== preparing container ==="
apt-get update -qq
apt-get install -y -qq python3 python3-venv sudo git >/dev/null

python3 -m venv /venv
/venv/bin/pip install --quiet --upgrade pip
/venv/bin/pip install --quiet -r requirements.txt
/venv/bin/ansible-galaxy install -r requirements.yml

converge() {
    /venv/bin/ansible-playbook playbooks/site.yml \
        --skip-tags secrets \
        -e @tests/vars.ci.yml \
        "$@"
}

echo "=== converge 1 ==="
converge

echo "=== converge 2 (must report changed=0) ==="
converge | tee /tmp/second.log

if ! grep -q "changed=0" /tmp/second.log; then
    echo "NOT IDEMPOTENT: the second converge reported changes" >&2
    exit 1
fi

echo "=== idempotent ==="
