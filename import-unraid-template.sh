#!/bin/bash
set -euo pipefail

TEMPLATE_NAME="${TEMPLATE_NAME:-my-homelab-hub.xml}"
TEMPLATE_DIR="${TEMPLATE_DIR:-/boot/config/plugins/dockerMan/templates-user}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "${SCRIPT_DIR}/homelab-hub/unraid/${TEMPLATE_NAME}" ]]; then
  TEMPLATE_SOURCE="${SCRIPT_DIR}/homelab-hub/unraid/${TEMPLATE_NAME}"
elif [[ -f "${SCRIPT_DIR}/${TEMPLATE_NAME}" ]]; then
  TEMPLATE_SOURCE="${SCRIPT_DIR}/${TEMPLATE_NAME}"
else
  echo "ERROR: Could not find ${TEMPLATE_NAME} next to this script or in homelab-hub/unraid." >&2
  exit 1
fi

if [[ ! -d /boot/config/plugins/dockerMan ]]; then
  echo "ERROR: Unraid dockerMan configuration directory was not found." >&2
  echo "Run this script directly on the Unraid server." >&2
  exit 1
fi

TEMPLATE_DEST="${TEMPLATE_DIR}/${TEMPLATE_NAME}"
mkdir -p "${TEMPLATE_DIR}"
install -m 0644 "${TEMPLATE_SOURCE}" "${TEMPLATE_DEST}"

echo "Imported Homelab Hub template:"
echo "  ${TEMPLATE_DEST}"
echo
echo "Next:"
echo "  Unraid WebUI -> Docker -> Add Container -> Template -> Homelab-Hub"
