# Set up new games

**English** · [Русский](README.ru.md)

For the Steam Deck. Add a non-Steam game to Steam (a repack, a GOG game, anything with an `.exe`), and within a few
seconds its shortcut gets everything the Steam original would have:

1. **Name** — a shortcut named after its exe (`VRising.exe`) becomes `V Rising`.
2. **Artwork** from the Steam store: capsule, hero, logo with its original position, and wide capsule.
   Artwork you set yourself is left alone.
3. **Proton** — forced to the version the game works with most often according to positive ProtonDB reports.
4. **Controller layout** — the same as the Steam original.
5. **Layout choice** — the shortcut's controller menu lists the original's official and community layouts, so you
   can pick any of them, just like for a game you own. Steam Deck layouts come first, by number of installs.
6. **Libraries** — Visual C++, DirectX and OpenAL, which Steam installs for the original before its first launch,
   plus legacy PhysX. Without them a game says "Microsoft Visual C++ 2015–2022 Redistributable required" or
   crashes with "General protection fault" (Batman: Arkham Asylum without PhysX).
7. **Launch target** — a shortcut that points to the graphics configurator instead of the game is switched to the
   game's exe.

The «Оформить новые игры» ("Set up new games") button in Steam does the same on demand and shows a report: what
was found, what was set and why. When there are no new games, it shows the last report, including the automatic
one.

The program's windows and reports are in Russian for now. The installer speaks English or Russian, following the
system or Steam language; to force one, run `… | NONSTEAM_LANG=en bash` (or `ru`).

## Install

In Desktop Mode, open Konsole and paste:

```bash
curl -fsSL https://raw.githubusercontent.com/toytronic22/steamdeck-nonsteam-setup/main/get.sh | bash
```

The installer:

- puts the program in `~/.local/share/nonsteam-setup/app` — no root, no system changes;
- adds the «Оформить новые игры» button to Steam (among non-Steam shortcuts, with its own artwork) and to the
  desktop;
- turns on automatic mode — systemd user services;
- asks whether to enable Steam's debugging port ([below](#steam-debugging-port-and-security)); the program does
  not work without it. After enabling it, restart Steam or the Deck, and the button appears on its own.

Without the question: `… | bash -s -- --enable-port` or `… | bash -s -- --no-port`. From a clone of the repo:
`bash install.sh`.

Requirements: SteamOS or another Linux with non-Flatpak Steam, systemd user services, Python 3.9 or newer; `zenity`
for windows (SteamOS has it). Network access: the Steam store, GitHub (the ProtonDB dump and the update check) and,
as a fallback, `api.steamcmd.net`. No API keys.

## Steam debugging port and security

The program talks to Steam itself through its debugging port `127.0.0.1:8080` — the same way Decky Loader plugins
do. That is why everything applies instantly, without restarting Steam, and exactly as if you had set it by hand
in the game's properties.

**Risk.** While the port is open, any program on this device, including a non-Steam game, can connect to Steam and
act on behalf of your Steam account. The port is not reachable from the network. Enable it only if you trust what
you run. If you have Decky Loader installed, the port is already open.
If you uninstall Decky, its uninstaller turns the port off: run the installer again and it will offer to turn it back on.

You can also switch the port in Steam itself: Settings → System → «Enable Developer Mode», then Settings →
Developer → «CEF Remote Debugging». The installer does the same thing: it creates the file
`~/.local/share/Steam/.cef-enable-remote-debugging`, which Steam reads at startup.

## Update

Run the install command again. Settings, reports and already set-up games are kept.

The last line of the button's report shows the version and whether a newer one exists. The program checks the
`VERSION` file on GitHub at most once every six hours. It never updates itself.

## Uninstall

```bash
bash ~/.local/share/nonsteam-setup/app/uninstall.sh
```

Removes the services, the button in Steam and on the desktop, and the program itself. It turns the debugging port
off only if our installer turned it on, and asks first. Data (reports, logs, the ProtonDB cache, backups of Steam
files) is removed after a question too; `--purge` removes it without asking, `--keep-data` keeps it.

Artwork, Proton, layouts and libraries the program set for your games stay. The original's layouts disappear from
the controller menu after Steam restarts.

## PhysX: download once by hand

Old PhysX games (Batman: Arkham Asylum and the like) need NVIDIA's PhysX installer. The program never downloads
anything itself, so put it in place once (28 MB, same checksum as winetricks):

```bash
mkdir -p ~/.local/share/nonsteam-setup/redist/PhysX && cd ~/.local/share/nonsteam-setup/redist/PhysX && curl -fLO https://us.download.nvidia.com/Windows/9.23.1019/PhysX_9.23.1019_SystemSoftware.exe && echo "9b42b84e881769d681e09f62a1b51532616b2e6a2d5d99d0ccae6eb5fbbc208c  PhysX_9.23.1019_SystemSoftware.exe" | sha256sum -c
```

Without the file, the report says PhysX is missing on the Deck and shows this hint.

## How Proton is chosen

The program takes "works" reports from ProtonDB for the last two years (all time if there are fewer than three)
and counts which Proton appears in them most often.

| Winner in ProtonDB | What is set |
|---|---|
| "official" — stable Proton | the newest installed stable Proton |
| "experimental" | Proton Experimental |
| GE-Proton | the same GE version if installed; otherwise the newest GE; no GE at all — the next option |
| old Proton (5.13, 7.0…) | that version if Steam has it; otherwise the next option |
| fewer than three reports, or a tie | Proton Experimental |

The ProtonDB database (the `bdefore/protondb-data` dump, about 70 MB) is downloaded on the first run and refreshed
once a month. Offline, the old copy is used.

## How the layout is chosen

1. The developer's official layout from Steam, if there is one.
2. Full controller support — the «Gamepad» template.
3. Otherwise — the most popular community layout for the original (Steam downloads it itself).
4. No community layouts: partial support — «Gamepad», none — the gamepad template with high-precision joystick.

If a shortcut with this name already has a layout (you set one yourself), it is left alone.

## Libraries: Visual C++, DirectX, OpenAL and PhysX

Before the first launch of a game you own, Steam installs the libraries declared by the developer into its Proton
prefix. It never does that for a shortcut, which is why repacks fail with "Visual C++ … required" errors. The
program does what Steam does:

- **what** — it looks up which Steam redistributables the original requires (the list in the game's appinfo, asked from
  Steam itself); Visual C++ 2015–2022 is always installed: almost every modern game needs it and it does no
  harm;
- **from where** — from "Steamworks Shared" on the Deck itself: these are Microsoft installers downloaded by Steam.
  Whatever is missing there, the program asks Steam to download (below). PhysX comes from
  `~/.local/share/nonsteam-setup/redist/PhysX/` ([above](#physx-download-once-by-hand)). Installers from the game's
  or repack's folder are never run;
- **where to** — into the shortcut's prefix (`compatdata/<shortcut id>`) with the Proton chosen for the game. If the
  prefix does not exist yet, it is created right away, as on the first launch.

| Steam redistributable | What is installed |
|---|---|
| Visual C++ 2015, 2017, 2019, 2022 | Visual C++ 2015–2022 (the newest from Steamworks Shared, it covers older ones) |
| Visual C++ 2005, 2008, 2010, 2012, 2013 | the same year |
| DirectX Jun2010 | DirectX (`DXSETUP.exe /silent`) |
| .NET, XNA | nothing: Proton marks them installed in advance and ships its own Wine Mono — Steam does not install them either |
| PhysX | NVIDIA PhysX 9.23.1019 (`/s`): all engines 2.7.1–2.8.3 and newer, `PhysX\Common` added to the prefix PATH |
| OpenAL | Creative OpenAL (`oalinst.exe /s`) |

PhysX is needed not only by games Steam declares it for. Old games (Batman: Arkham Asylum, for example) install it
with their own installer, which Steam runs from the game folder — it is not in appinfo. So the program looks for a
sign in the game files: an exe or dll mentions `PhysXLoader.dll` and there is no `PhysXCore.dll` of its own next to
it — PhysX is needed. Modern games on PhysX 3–5 ship it themselves and do not need it. OpenAL is installed only for
games Steam declares it for: the same check on `OpenAL32.dll` gave false positives — Stardew Valley has its own copy
under another name (`soft_oal.dll`), and Batman mentions it but Steam does not install it for the original. The sign
is computed once per exe and stored in `state.json` (`local`; `checks` lists the signs looked for — when a new one
is added, every game is re-checked once).

The report's libraries line lists what was installed, what was already there and what is missing on the Deck.
Steam keeps in Steamworks Shared only the packages needed by installed games you own, so, for example, Visual C++
2010 may be missing. Then the program downloads it through Steam itself: it sends `download_depot 228980 <depot>` to
the Steam console through the debugging port and waits for Steam's «Depot download complete» or «Depot download
failed» line in `logs/console_log.txt`, one package at a time, up to 5 minutes each. Steam puts the files into
`~/.local/share/Steam/ubuntu12_32/steamapps/content/app_228980/`, and the program installs from there. The packages
are small (Visual C++ 2005 — 6 MB, OpenAL — 1 MB) and are the same files Steam downloads for games you own. If Steam
fails, the report gives its reason; the button tries again on every press, the automatic run gives up after three
failures.

| Package | Steamworks Shared depot |
|---|---|
| Visual C++ 2005 | 228981 |
| Visual C++ 2008 | 228982 |
| Visual C++ 2010 | 228983 |
| Visual C++ 2012 | 228984 |
| Visual C++ 2013 | 228985 |
| Visual C++ 2015–2022 | 228989 |
| DirectX | 228990 |
| OpenAL | 229020 |

Whether a package is installed is checked in the prefix registry (the "Microsoft Visual C++ … Minimum Runtime"
entry and similar) and by files: `d3dx9_43.dll` for DirectX, real or a Wine stub; `OpenAL32.dll` for OpenAL;
`Program Files (x86)/NVIDIA Corporation/PhysX/Common/PhysXLoader.dll` for PhysX. This is also checked on every run:
if the prefix was recreated (deleted, or Proton switched with a cleanup), the libraries are installed again, and the
report has a section for already set-up games. A running game is never touched: the install waits until it exits.
If you start the game in the middle of an install, the program stops installing and leaves Wine alone (otherwise it
would close the game); the attempt does not count, the rest happens after you quit. A package that fails three
times in a row is not retried; the install log is `~/.local/share/nonsteam-setup/logs/redist-<shortcut id>.txt`.
Before installing, the prefix registry is copied to `~/.local/share/nonsteam-setup/prefix-backups/` (the last
three copies).

## The original's layouts in the controller menu

Steam looks up layouts by game id, and a shortcut has its own id, so for a shortcut Steam shows only your layouts
and templates. The program adds the original's official and community layouts to that list: «Controller Settings» →
«Current Button Layout» → the «Official Layouts» and «Community Layouts» tabs. A chosen layout is applied to the
shortcut like any other.

On the «Community Layouts» tab, layouts made for Steam Deck come first, most popular at the top: the start of the
title says how many people installed it, e.g. «6,332 installs on Steam Deck · V-Rising for steam deck». Layouts for
other controllers follow, in Steam's order. Steam's usual answer has no Steam Deck layouts, so the
program asks it for the original's layouts for all controllers and takes the Steam Deck ones. Steam loads the
install counts a second or two after the tab opens, and the list is reordered then. Steam does not return a full
list: for some games the answer has the most popular Steam Deck layouts, for others only little-known ones with
zero installs.

Sometimes the developer's official layout is a plain Steam template (Solarpunk uses the gamepad template with camera
controls). The shortcut already has that template among «Templates», so it is not added twice — it is just also
shown on the «Official Layouts» tab, as for a game you own.

This lives only in Steam's memory and writes nothing to files. After Steam restarts, the `nonsteam-layouts.service`
service restores it within a few seconds. A line in the button's report tells whether the original's layouts work
right now:

- connected, with the number of games — all good;
- failed to connect — Steam was updated and something inside changed; the program needs a fix;
- the service is not running — the original's layouts will disappear from the menu after Steam restarts;
  reinstalling helps;
- turned off by the safety switch — see below.

**Safety switch.** If Steam loses the connection three times in a row less than a minute after the service hooked up
the layouts, the service stops hooking them up, in case a new Steam version crashes because of it. Everything else
keeps working. To turn it back on, run the installer again.

Some games have no layouts even for the original (Graveyard Keeper 2, for example); then there is nothing to add.

To turn it off: `systemctl --user disable --now nonsteam-layouts.service`; the original's layouts disappear from the
menu after Steam restarts. Log: `journalctl --user -u nonsteam-layouts`.

## What gets processed

Shortcuts whose target is an `.exe`, `.bat` or `.cmd`, and only once: processed ones are recorded in
`~/.local/share/nonsteam-setup/state.json`. Chrome, VLC and other native programs are not touched. The Steam profile
is the one that logged in most recently.

The name is looked for in this order: the shortcut name (unless it is the exe name), the folders above the exe, the
exe name split into words (`GraveyardKeeper2` → `Graveyard Keeper 2`). Versions, `[v1.2]`, `RePack` and packer
signatures at the end are stripped: `Game by Someone`, `Game - Someone`, `Game-Someone`. Every name is tried both
whole and without such a tail, so real titles with dashes are not lost. In the store, an exact match is taken first
(`™` and `®` do not matter), then a match without the edition at the end ("Game of the Year Edition", "GOTY",
"Complete", "Definitive", "Special Edition", "Remastered" and the like: `Batman Arkham Asylum GOTY` → "Batman: Arkham
Asylum Game of the Year Edition", `The Witcher 3 Wild Hunt` → "The Witcher 3: Wild Hunt — Remastered"), then with the
part after a colon or dash (`Skyrim Special Edition` → "The Elder Scrolls V: Skyrim Special Edition") or before it —
only if exactly one game matches: `Batman` fits both Arkham Knight and Arkham City, so neither is taken. If the store
search returns nothing, the same search runs through the Steam community. Only games are taken: DLC, books and
soundtracks with a similar name are skipped (otherwise `Solarpunk` found "Solarpunk – Official Book"). Nothing
found — the game is left alone and the report lists the names tried: rename the shortcut to the exact game title and
it will be set up on its own.

**Shortcut to a configurator.** In Steam a game may have several launch options: the game itself and, for example,
a graphics configurator. If the shortcut points to an option Steam labels as settings ("Settings", "Config",
"Options", "Setup") and the main option is on disk nearby, the program switches the shortcut to the main exe and its
working folder, and says so in the report. A shortcut is never switched to a launcher.

**Shortcut to a launcher.** If the exe is a launcher (its name contains `launch`), it stays as is, and the report
gives a hint: if the launcher's buttons are invisible or do not respond (old launchers under Proton), point the
shortcut to the game's exe — with up to three suitable exes nearby. For Batman: Arkham Asylum that is
`Binaries/ShippingPC-BmGame.exe` instead of `Binaries/BmLauncher.exe`; graphics settings are then changed in the
game itself.

A shortcut pointing to something other than a program (a `.dll`, `.ini`, an image — this happens if you pick the
wrong file in «Add a Non-Steam Game») will not start in Steam. Such a shortcut is not set up; the report says what it
points to, which exes are nearby, and what to do — remove the shortcut and add the game's exe.

The weak spot is a meaningless short folder name that happens to match a real game (`xyz` → the game "XYZ"). Then
the shortcut gets someone else's artwork and Proton.

## Automatic mode

The installer turns on systemd user services:

- `nonsteam-setup.path` watches `shortcuts.vdf` of every Steam account on the device: Steam rewrites it when a
  shortcut is added or renamed, and 5 seconds later `run.sh --auto` runs;
- `nonsteam-setup.timer` — a fallback check every 10 minutes and 3 minutes after boot, in case Steam was not ready
  when the game was added;
- `nonsteam-layouts.service` — the original's layouts in the controller menu (see above), runs all the time. If the
  port was closed during install, this service also adds the button to Steam once the port opens.

The automatic run shows no windows. An empty run (no new games) does nothing and writes nothing. A game not found in
the store is not retried until the shortcut is renamed; on other errors it tries three times. The button always
tries.

To turn it off: `systemctl --user disable --now nonsteam-setup.path nonsteam-setup.timer`.
Log: `journalctl --user -u nonsteam-setup`.

Before every run, `shortcuts.vdf`, `config.vdf` and the layout files are copied to
`~/.local/share/nonsteam-setup/backups/` (the last ten).

## Running by hand

```bash
~/.local/share/nonsteam-setup/app/run.sh              # new games, with windows
~/.local/share/nonsteam-setup/app/run.sh --no-gui     # same, report to the terminal
~/.local/share/nonsteam-setup/app/run.sh --dry-run    # only show what was found
~/.local/share/nonsteam-setup/app/run.sh --all        # set up all shortcuts again
~/.local/share/nonsteam-setup/app/run.sh --appid 2286911949
~/.local/share/nonsteam-setup/app/run.sh --auto       # like the service: no windows, skips games it gave up on
```

The last report of the button or the service is in `~/.local/share/nonsteam-setup/last-report.txt` — the button
shows it when there are no new games. A dry run and `--appid` write separately, to `manual-report.txt`, and do not
overwrite it.

## Files

| File | What it does |
|---|---|
| `main.py` | picking shortcuts, name, artwork, Proton, layout, report |
| `launch.py` | Steam launch options: switching a shortcut from a configurator to the game, launcher hint |
| `steamcdp.py` | talking to Steam through the debugging port (Python standard library only) |
| `steamweb.py` | store search, artwork, logo, controller support |
| `protondb.py` | the ProtonDB database and choosing Proton |
| `vdf.py` | reading `shortcuts.vdf` and layout files |
| `layouts.py` | the original's layouts in the controller menu: injection, service, safety switch |
| `redist.py` | Visual C++, DirectX, OpenAL and PhysX in the shortcut's prefix: what is needed, install, check |
| `update.py` | version and update check |
| `add_to_steam.py` | the button in Steam and its artwork |
| `get.sh`, `install.sh`, `uninstall.sh`, `run.sh` | download, install and update, uninstall, run |
| `assets/` | button artwork; `art.html` is the source, `render.sh` re-renders it on a Mac with Chrome |
| `tests/` | tests: `python3 -m unittest discover -s tests -t .` |

## Why it works this way

- Registering your own handlers with `SteamClient.*.RegisterFor…` is not allowed: there is one slot, your handler
  kicks out Steam's own, and the layout menu stops receiving data. So layouts are taken through Steam's internal
  store that already uses them.
- A shortcut's layout in Steam is tied to its **name**, so the rename comes first, then the layout.
- The layout list in the menu cannot be supplied as a file: Steam requests it by game id every time. So two methods
  of that same layout store are replaced — on the store object only; Steam's code is not changed. Install counts
  come from the layout details Steam itself loads for the tab (the likes come from there too). The store is found
  among Steam's already loaded modules; no new modules are started. The service checks the replacement every 5
  seconds and restores it if Steam restarted or new games appeared in `state.json`.
- There is no pop-up notification in Game Mode: Steam does not show its notifications for outside programs. So the
  state is shown by the button — the last report.
- Windows (`zenity`) run with `LC_ALL=C.UTF-8`: started from Steam, the button runs without UTF-8, and zenity rejects
  a Russian title ("This option is not available"), so the window never appears.
- A button run and an automatic run never overlap: they share the `run.lock` lock, and the button waits.
- Appinfo (redistributables, launch options, the logo and its position) is asked from Steam itself with the console
  command `app_info_print`, and the answer is read from `logs/console_log.txt`. Steam keeps key case loosely
  (`BetaKey` and `betakey`), so keys are lowercased. If Steam stays silent for 15 s or knows nothing about the game,
  `api.steamcmd.net` is asked instead; if that does not answer either — a plain `logo.png` from the CDN (new games may
  not have one).
- Visual C++ installers need a display even in quiet mode (`/q`): without one they fail with "Failed to create
  window" and hang. The service has no display, so it borrows the one of the Steam process (`DISPLAY=:0`).
  Switching between Gaming and Desktop mode closes that Steam together with its display, and an installer started a
  second earlier hangs. So the program watches that Steam process: once it is gone, the installer is stopped, the
  program waits up to a minute for the new Steam and installs again on its display. No new Steam — the package is
  installed on the next run, and this does not count as a failed try. An installer that hangs anyway is stopped
  after 3 minutes (a good one takes 3–30 s).
- Wine only pretends to have Visual C++: it writes version 14.42 to the registry, which is not enough for UE5
  (Solarpunk) — its loader wants the real one. After the real 14.51 package from Steamworks Shared the error is gone.
- The Visual C++ installer under Proton does not replace `ucrtbase.dll`, the Wine one stays — and that is good: the
  real ucrtbase 14.4x reportedly crashes games under Proton.
- "Game is running" is detected by Steam's `reaper SteamLaunch AppId=<shortcut id>` process, by processes in this
  prefix, and by a live `wineserver` of the prefix. After installing, the program waits for the prefix's
  `wineserver` to finish so the registry gets written (up to a minute, then `wineserver -k`). If the game is started
  during that time, the wait ends without `-k`: the same `wineserver` is running the game.

## License and data

Code — [MIT](LICENSE).

Proton selection uses [ProtonDB](https://www.protondb.com) data from the
[bdefore/protondb-data](https://github.com/bdefore/protondb-data) dump under the
[ODbL](https://opendatacommons.org/licenses/odbl/1-0/). The program downloads it to the device and does not
redistribute it.

Not affiliated with Valve. Steam and Steam Deck are trademarks of Valve Corporation.
