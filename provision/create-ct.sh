#!/bin/bash
# Run on the Proxmox host. Creates a minimal Debian LXC, pushes this repo's
# provision/ directory plus the whole fleetbroker source tree into it, then
# hands off to install-node.sh for the in-container setup (including the
# interactive login step - this script does not attempt to skip that).
#
# Usage: create-ct.sh <VMID> <IP/CIDR> <FleetName> [ProfileName]
# Example: create-ct.sh 120 192.168.1.96/24 MySecondFleetNode github-triage
#   ProfileName, if given, must match a directory under provision/profiles/
#   (pushed into the CT along with the rest of the source tree) - see
#   provision/profiles/README.md.
#   Optionally export PCT_PASSWORD to set the container's root password
#   (useful for a throwaway/test CT); omit it to leave password login
#   disabled, which is the recommended default for a real fleet node.
set -euo pipefail

VMID="${1:?Usage: create-ct.sh <VMID> <IP/CIDR> <FleetName> [ProfileName]}"
IP="${2:?Usage: create-ct.sh <VMID> <IP/CIDR> <FleetName> [ProfileName]}"
FLEET_NAME="${3:?Usage: create-ct.sh <VMID> <IP/CIDR> <FleetName> [ProfileName]}"
PROFILE_NAME="${4:-}"
GATEWAY="${GATEWAY:-$(echo "$IP" | cut -d. -f1-3).1}"

# Auto-discover the latest available Debian 13 template rather than pinning
# an exact version string, which inevitably goes stale as new point releases
# replace old ones in the catalog.
TEMPLATE="$(pveam list local 2>/dev/null | grep -o 'debian-13-standard_[^ ]*_amd64\.tar\.zst' | sort -V | tail -1)"
if [[ -z "$TEMPLATE" ]]; then
    echo "No local debian-13 template found, checking catalog..."
    pveam update >/dev/null
    TEMPLATE="$(pveam available --section system 2>/dev/null | grep -o 'debian-13-standard_[^ ]*_amd64\.tar\.zst' | sort -V | tail -1)"
    : "${TEMPLATE:?No debian-13-standard template found in the pveam catalog}"
    echo "Downloading $TEMPLATE..."
    pveam download local "$TEMPLATE"
fi

CREATE_ARGS=(
    --hostname "$(echo "$FLEET_NAME" | tr '[:upper:]' '[:lower:]')"
    --cores 2 --memory 2048 --swap 512
    --rootfs "local-lvm:16"
    --net0 "name=eth0,bridge=vmbr0,gw=${GATEWAY},ip=${IP},type=veth"
    --unprivileged 1
    --features nesting=1
    --onboot 1
)
if [[ -n "${PCT_PASSWORD:-}" ]]; then
    CREATE_ARGS+=(--password "$PCT_PASSWORD")
fi

echo "Creating CT $VMID ($FLEET_NAME) at $IP..."
pct create "$VMID" "local:vztmpl/$TEMPLATE" "${CREATE_ARGS[@]}"

pct start "$VMID"
sleep 3

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "Pushing fleetbroker source into CT $VMID..."
pct exec "$VMID" -- mkdir -p /opt/fleetbroker-src
tar -C "$REPO_ROOT" -cf - --exclude .venv --exclude .git . | pct exec "$VMID" -- tar -C /opt/fleetbroker-src -xf -

INSTALL_CMD="/opt/fleetbroker-src/provision/install-node.sh $FLEET_NAME"
if [[ -n "$PROFILE_NAME" ]]; then
    INSTALL_CMD="$INSTALL_CMD --profile /opt/fleetbroker-src/provision/profiles/$PROFILE_NAME"
fi

echo
echo "CT $VMID created and source pushed. Now run interactively:"
echo "    pct enter $VMID"
if [[ -n "$PROFILE_NAME" ]]; then
    echo "    export <any secrets the '$PROFILE_NAME' profile's mcp.json needs>"
fi
echo "    $INSTALL_CMD"
echo
echo "(Left as a separate manual step, not chained automatically here, because"
echo " install-node.sh needs your interactive input for 'claude auth login'.)"
