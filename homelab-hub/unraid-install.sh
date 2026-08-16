#!/bin/bash
set -euo pipefail

IMAGE_NAME="homelab-hub:local"
TEMPLATE_NAME="my-homelab-hub.xml"
TEMPLATE_DIR="/boot/config/plugins/dockerMan/templates-user"
APPDATA_DIR="/mnt/user/appdata/homelab-hub"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_SOURCE="${SCRIPT_DIR}/unraid/${TEMPLATE_NAME}"
TEMPLATE_DEST="${TEMPLATE_DIR}/${TEMPLATE_NAME}"

if [[ ! -f "${SCRIPT_DIR}/Dockerfile" ]]; then
  echo "ERROR: Dockerfile not found in ${SCRIPT_DIR}" >&2
  exit 1
fi

if [[ ! -f "${TEMPLATE_SOURCE}" ]]; then
  echo "ERROR: Unraid template not found: ${TEMPLATE_SOURCE}" >&2
  exit 1
fi

if [[ ! -S /var/run/docker.sock ]]; then
  echo "ERROR: Docker does not appear to be running on this Unraid host." >&2
  exit 1
fi

if [[ ! -d /boot/config/plugins/dockerMan ]]; then
  echo "ERROR: Unraid dockerMan configuration directory was not found." >&2
  echo "Run this script directly on the Unraid server." >&2
  exit 1
fi

echo "[1/3] Building local Docker image: ${IMAGE_NAME}"
docker build -t "${IMAGE_NAME}" "${SCRIPT_DIR}"

echo "[2/3] Preparing persistent appdata directory"
mkdir -p "${APPDATA_DIR}"

echo "[3/3] Installing Unraid user template"
mkdir -p "${TEMPLATE_DIR}"
cp -f "${TEMPLATE_SOURCE}" "${TEMPLATE_DEST}"
chmod 0644 "${TEMPLATE_DEST}"

echo
echo "Installed successfully."
echo "Image:    ${IMAGE_NAME}"
echo "Template: ${TEMPLATE_DEST}"
echo "Appdata:  ${APPDATA_DIR}"
echo
echo "Next in the Unraid WebUI:"
echo "  Docker -> Add Container -> Template -> Homelab-Hub"
echo "Then set Admin Password and Session Secret and click Apply."
echo
echo "Generate a Session Secret with: openssl rand -hex 32"
