#!/usr/bin/env bash
set -euo pipefail

# Standalone helper for Windows usbipd attach from WSL.
BUSID="${1:-1-1}"

if ! command -v usbipd.exe >/dev/null 2>&1; then
  echo "usbipd.exe not found in PATH. Install usbipd on Windows first." >&2
  exit 1
fi

echo "Attaching USB device to WSL via usbipd (busid=${BUSID}) ..."
usbipd.exe attach --wsl --busid "${BUSID}"
echo "Done. If needed, verify with: usbipd.exe list"