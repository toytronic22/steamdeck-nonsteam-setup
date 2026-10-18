#!/bin/bash
set -euo pipefail

SRC="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
DATA="$HOME/.local/share/nonsteam-setup"
APP="$DATA/app"
UNITS="$HOME/.config/systemd/user"
STEAM="$HOME/.local/share/Steam"
FLAG="$STEAM/.cef-enable-remote-debugging"
FLAG_OURS="$DATA/port-flag-created"
NAME="Оформить новые игры"
PORT=ask

for arg in "$@"; do
  case "$arg" in
    --enable-port) PORT=yes ;;
    --no-port) PORT=no ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

is_ru() {
  case "${NONSTEAM_LANG:-}" in ru) return 0 ;; en) return 1 ;; esac
  case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in ru*) return 0 ;; esac
  grep -qiE '"language"[[:space:]]+"russian"' "$HOME/.steam/registry.vdf" 2>/dev/null
}
if is_ru; then RU=1; else RU=0; fi

say() { if [ "$RU" = 1 ]; then printf '%s\n' "$1"; else printf '%s\n' "$2"; fi; }
fail() { say "Ошибка: $1" "Error: $2" >&2; exit 1; }

has_tty() { { : </dev/tty; } 2>/dev/null; }

ask_yes() {
  local answer=""
  printf '%s ' "$(say "$1 [y/N]" "$2 [y/N]")" >/dev/tty
  read -r answer </dev/tty || answer=""
  case "$answer" in [yYдД]*) return 0 ;; *) return 1 ;; esac
}

port_open() {
  python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); from steamcdp import Cdp; Cdp(timeout=5).close()' \
    "$APP" >/dev/null 2>&1
}

command -v python3 >/dev/null || fail "нужен python3." "python3 is required."
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' ||
  fail "нужен python3 версии 3.9 или новее." "python3 3.9 or newer is required."
command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1 ||
  fail "нужен systemd пользователя (systemctl --user)." "a systemd user session (systemctl --user) is required."
[ -d "$STEAM" ] || fail "не нашёл Steam в $STEAM." "Steam was not found in $STEAM."
command -v zenity >/dev/null ||
  say "Внимание: нет zenity — окна отчёта не будет, отчёт останется в $DATA/last-report.txt." \
      "Warning: zenity is missing — no report window; the report stays in $DATA/last-report.txt."

UPDATE=0
[ -d "$APP" ] && UPDATE=1
mkdir -p "$DATA"
rm -rf "$APP.new" "$APP.old"
mkdir -p "$APP.new/assets"
cp "$SRC"/*.py "$SRC"/run.sh "$SRC"/uninstall.sh "$SRC"/VERSION "$APP.new"/
cp "$SRC"/assets/*.jpg "$SRC"/assets/*.png "$APP.new/assets"/
chmod +x "$APP.new/run.sh" "$APP.new/uninstall.sh"
if [ -d "$APP" ]; then mv "$APP" "$APP.old"; fi
mv "$APP.new" "$APP"
rm -rf "$APP.old"
rm -f "$DATA/layouts-off.json" "$DATA/layouts-fuse.json"
VERSION="$(cat "$APP/VERSION")"

DESKTOP_FILE="$HOME/.local/share/applications/nonsteam-setup.desktop"
mkdir -p "$(dirname "$DESKTOP_FILE")"
cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Type=Application
Name=$NAME
Comment=Картинки, Proton и раскладка от оригинала для игр не из Steam
Exec=$APP/run.sh
Icon=$APP/assets/icon.png
Terminal=false
Categories=Game;
DESKTOP
chmod +x "$DESKTOP_FILE"
if [ -d "$HOME/Desktop" ]; then
  cp "$DESKTOP_FILE" "$HOME/Desktop/"
fi

mkdir -p "$UNITS"
cat > "$UNITS/nonsteam-setup.service" <<UNIT
[Unit]
Description=$NAME (автоматически)

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 5
ExecStart=$APP/run.sh --auto
Nice=10
UNIT

cat > "$UNITS/nonsteam-setup.timer" <<UNIT
[Unit]
Description=$NAME: запасная проверка

[Timer]
OnBootSec=3min
OnUnitInactiveSec=10min

[Install]
WantedBy=timers.target
UNIT

cat > "$UNITS/nonsteam-layouts.service" <<UNIT
[Unit]
Description=$NAME: раскладки оригинала в меню контроллера

[Service]
ExecStart=/usr/bin/env python3 $APP/layouts.py
Restart=always
RestartSec=10
Nice=10

[Install]
WantedBy=default.target
UNIT

WATCH=""
for dir in "$STEAM"/userdata/*/; do
  id="$(basename "$dir")"
  case "$id" in ''|0|*[!0-9]*) continue ;; esac
  WATCH+="PathChanged=$STEAM/userdata/$id/config/shortcuts.vdf"$'\n'
done
if [ -n "$WATCH" ]; then
  cat > "$UNITS/nonsteam-setup.path" <<UNIT
[Unit]
Description=$NAME: следит за ярлыками Steam

[Path]
${WATCH}
[Install]
WantedBy=default.target
UNIT
fi

systemctl --user daemon-reload
systemctl --user enable --now nonsteam-setup.timer
systemctl --user enable nonsteam-layouts.service
systemctl --user restart nonsteam-layouts.service
if [ -n "$WATCH" ]; then
  systemctl --user enable nonsteam-setup.path
  systemctl --user restart nonsteam-setup.path
else
  systemctl --user disable --now nonsteam-setup.path >/dev/null 2>&1 || true
  rm -f "$UNITS/nonsteam-setup.path"
  systemctl --user daemon-reload
  say "Steam ещё не входил ни в один аккаунт: новые игры будут оформляться раз в 10 минут. После входа запусти установку ещё раз — будет сразу." \
      "Steam has no signed-in account yet: new games will be set up every 10 minutes. Run the installer again after signing in to make it instant."
fi

echo
if port_open; then OPEN=1; else OPEN=0; fi
if [ -e "$FLAG" ] && [ "$OPEN" = 1 ]; then
  say "Связь со Steam есть." "Steam connection: OK."
elif [ -e "$FLAG" ]; then
  say "Порт отладки Steam включён, но откроется после перезапуска Steam. Перезапусти Steam или перезагрузи устройство." \
      "Steam's debugging port is enabled but opens only after Steam restarts. Restart Steam or reboot."
else
  if [ "$OPEN" = 1 ]; then
    say "Порт отладки Steam сейчас открыт, но не включён насовсем: после перезапуска Steam он закроется." \
        "Steam's debugging port is open now but not enabled permanently: it closes after Steam restarts."
  fi
  say "Программа работает через порт отладки Steam (127.0.0.1:8080): через него она ставит картинки, Proton и раскладки.
Пока порт открыт, к Steam может подключиться любая программа на этом устройстве, в том числе игра не из Steam,
и действовать от имени твоего аккаунта Steam. Включай, только если доверяешь тому, что запускаешь.
Порт включается и выключается и в самом Steam: Настройки → Система → «Включить режим разработчика»,
затем Настройки → Разработчикам → «Удалённая отладка CEF»." \
      "The tool works through Steam's debugging port (127.0.0.1:8080): it uses it to set artwork, Proton and layouts.
While the port is open, any program on this device, including a non-Steam game, can connect to Steam
and act on behalf of your Steam account. Enable it only if you trust what you run.
You can also turn the port on and off in Steam itself: Settings → System → “Enable Developer Mode”,
then Settings → Developer → “CEF Remote Debugging”."
  if [ "$PORT" = ask ]; then
    if has_tty && ask_yes "Включить порт сейчас?" "Enable the port now?"; then PORT=yes; else PORT=no; fi
  fi
  if [ "$PORT" = yes ]; then
    touch "$FLAG" "$FLAG_OURS"
    if [ "$OPEN" = 1 ]; then
      say "Порт включён насовсем." "Port enabled permanently."
    else
      say "Порт включён. Перезапусти Steam или перезагрузи устройство — кнопка «$NAME» появится в библиотеке сама." \
          "Port enabled. Restart Steam or reboot — the “$NAME” button will appear in your library by itself."
    fi
  else
    say "Порт не включён — без него программа не работает. Включить потом: запусти установку ещё раз или включи переключатель в Steam." \
        "Port not enabled — the tool cannot work without it. Later: run the installer again or use the Steam toggle."
  fi
fi

echo
python3 "$APP/add_to_steam.py" || true
echo
if [ "$UPDATE" = 1 ]; then
  say "Готово: обновлено до версии $VERSION." "Done: updated to version $VERSION."
else
  say "Готово: установлена версия $VERSION." "Done: version $VERSION installed."
fi
say "Удалить: bash $APP/uninstall.sh" "Uninstall: bash $APP/uninstall.sh"
