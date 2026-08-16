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
TMP_TEMPLATE="$(mktemp)"
cp -f "${TEMPLATE_SOURCE}" "${TMP_TEMPLATE}"

blank_config_value() {
  local target="$1"
  sed -i -E "s#(<Config Name=\"[^\"]*\" Target=\"${target}\"[^>]*>)[^<]*(</Config>)#\\1\\2#g" "${TMP_TEMPLATE}"
}

blank_config_value "HUB_JELLYFIN_URL"
blank_config_value "HUB_JELLYFIN_PUBLIC_URL"
blank_config_value "HUB_JELLYFIN_API_KEY"
blank_config_value "HUB_NEXTCLOUD_CALENDAR_URL"
blank_config_value "HUB_HOME_ASSISTANT_URL"
blank_config_value "HUB_HOME_ASSISTANT_TOKEN"
blank_config_value "HUB_HOME_ASSISTANT_ENTITIES"

mkdir -p "${TEMPLATE_DIR}"
install -m 0644 "${TMP_TEMPLATE}" "${TEMPLATE_DEST}"
rm -f "${TMP_TEMPLATE}"

echo "Imported Homelab Hub template:"
echo "  ${TEMPLATE_DEST}"
echo
echo "The live integration fields were installed blank:"
echo "  HUB_JELLYFIN_URL"
echo "  HUB_JELLYFIN_PUBLIC_URL"
echo "  HUB_JELLYFIN_API_KEY"
echo "  HUB_NEXTCLOUD_CALENDAR_URL"
echo "  HUB_HOME_ASSISTANT_URL"
echo "  HUB_HOME_ASSISTANT_TOKEN"
echo "  HUB_HOME_ASSISTANT_ENTITIES"
echo
echo "Next:"
echo "  Unraid WebUI -> Docker -> Add Container -> Template -> Homelab-Hub"
