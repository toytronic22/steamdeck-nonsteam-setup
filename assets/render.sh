#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
render() {
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
    --default-background-color=00000000 --window-size="$2" --screenshot="$PWD/$1.png" \
    "file://$PWD/art.html#$1" >/dev/null 2>&1
}
render poster 600,900
render hero 1920,620
render wide 920,430
render logo 1080,360
render icon 256,256
for name in poster hero wide; do
  sips -s format jpeg -s formatOptions 92 "$name.png" --out "$name.jpg" >/dev/null
  rm "$name.png"
done
