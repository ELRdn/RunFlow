#!/usr/bin/env bash
# Explicitly run as root in Ubuntu 24.04; never edits a user's .bashrc.
set -euo pipefail
source /etc/os-release
test "${ID}" = ubuntu && test "${VERSION_ID}" = 24.04
test "$(id -u)" = 0
list=/etc/apt/sources.list.d/runflow-openfoam.list
key=/usr/share/keyrings/runflow-openfoam.asc
if ! test -e "$list"; then
    curl -fsSL https://dl.openfoam.org/gpg.key -o "$key"
    echo 'deb [signed-by=/usr/share/keyrings/runflow-openfoam.asc] http://dl.openfoam.org/ubuntu noble main' > "$list"
fi
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends openfoam14=20260724
dpkg-query -W openfoam14
