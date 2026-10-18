#!/bin/bash
set -euo pipefail

main() {
  local repo="${NONSTEAM_REPO:-toytronic22/steamdeck-nonsteam-setup}"
  local ref="${NONSTEAM_REF:-main}"
  local url="${NONSTEAM_URL:-https://github.com/$repo/archive/refs/heads/$ref.tar.gz}"
  NONSTEAM_TMP="$(mktemp -d "${TMPDIR:-/tmp}/nonsteam-setup.XXXXXX")"
  trap 'rm -rf "$NONSTEAM_TMP"' EXIT
  echo "Downloading $url"
  curl -fsSL "$url" | tar -xz -C "$NONSTEAM_TMP" --strip-components=1
  bash "$NONSTEAM_TMP/install.sh" "$@"
}

main "$@"
