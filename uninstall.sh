#!/bin/bash
set -euo pipefail

main() {
  local DATA="$HOME/.local/share/nonsteam-setup"
  local APP="$DATA/app"
  local UNITS="$HOME/.config/systemd/user"
  local FLAG="$HOME/.local/share/Steam/.cef-enable-remote-debugging"
  local FLAG_OURS="$DATA/port-flag-created"
  local NAME="Оформить новые игры"
  local PURGE=ask RU=0 arg unit file

  for arg in "$@"; do
    case "$arg" in
      --purge) PURGE=yes ;;
      --keep-data) PURGE=no ;;
      *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
  done

  case "${NONSTEAM_LANG:-}" in
    ru) RU=1 ;;
    en) RU=0 ;;
    *) case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in
         ru*) RU=1 ;;
         *) grep -qiE '"language"[[:space:]]+"russian"' "$HOME/.steam/registry.vdf" 2>/dev/null && RU=1 ;;
       esac ;;
  esac

  say() { if [ "$RU" = 1 ]; then printf '%s\n' "$1"; else printf '%s\n' "$2"; fi; }
  has_tty() { { : </dev/tty; } 2>/dev/null; }
  ask() {
    local answer=""
    printf '%s ' "$(say "$1" "$2")" >/dev/tty
    read -r answer </dev/tty || answer=""
    printf '%s' "$answer"
  }

  if command -v systemctl >/dev/null; then
    for unit in nonsteam-setup.path nonsteam-setup.timer nonsteam-layouts.service nonsteam-setup.service; do
      systemctl --user disable --now "$unit" >/dev/null 2>&1 || true
    done
  fi
  for unit in nonsteam-setup.path nonsteam-setup.timer nonsteam-layouts.service nonsteam-setup.service; do
    rm -f "$UNITS/$unit"
  done
  if command -v systemctl >/dev/null; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    systemctl --user reset-failed nonsteam-setup.service nonsteam-layouts.service >/dev/null 2>&1 || true
  fi
  say "Службы остановлены и удалены." "Services stopped and removed."

  if [ -f "$APP/add_to_steam.py" ]; then
    python3 "$APP/add_to_steam.py" --remove || true
  fi

  for file in "$HOME/.local/share/applications/nonsteam-setup.desktop" "$HOME/Desktop/nonsteam-setup.desktop"; do
    if [ -f "$file" ] && grep -qF "$APP/run.sh" "$file"; then
      rm -f "$file"
    fi
  done

  if [ -f "$FLAG_OURS" ]; then
    if [ -e "$FLAG" ]; then
      local drop=y
      if has_tty; then
        case "$(ask "Порт отладки Steam включила эта программа. Выключить его? [Y/n]" \
                    "This tool enabled Steam's debugging port. Disable it? [Y/n]")" in
          [nNнН]*) drop=n ;;
        esac
      fi
      if [ "$drop" = y ]; then
        rm -f "$FLAG"
        say "Порт отладки выключится после перезапуска Steam. Если он нужен другой программе (например, Decky), включи снова: Настройки → Разработчикам → «Удалённая отладка CEF»." \
            "The debugging port closes after Steam restarts. If another tool needs it (e.g. Decky), turn it back on: Settings → Developer → “CEF Remote Debugging”."
      else
        say "Порт отладки оставил включённым." "Left the debugging port enabled."
      fi
    fi
    rm -f "$FLAG_OURS"
  fi

  rm -rf "$APP" "$APP.new" "$APP.old"

  if [ "$PURGE" = ask ]; then
    PURGE=no
    if [ -d "$DATA" ] && has_tty; then
      case "$(ask "Удалить и данные программы ($DATA: отчёты, журнал, кэш)? [y/N]" \
                  "Also delete the tool's data ($DATA: reports, log, cache)? [y/N]")" in
        [yYдД]*) PURGE=yes ;;
      esac
    fi
  fi
  if [ "$PURGE" = yes ]; then
    rm -rf "$DATA"
    say "Данные удалены." "Data deleted."
  elif [ -d "$DATA" ]; then
    say "Данные оставил в $DATA." "Kept the data in $DATA."
  fi

  say "Готово: программа удалена. Картинки, Proton и раскладки, которые она поставила играм, остаются. Раскладки оригинала в меню контроллера пропадут после перезапуска Steam." \
      "Done: the tool is removed. Artwork, Proton and layouts it set for your games stay. The original game's layouts in the controller menu disappear after Steam restarts."
}

main "$@"
