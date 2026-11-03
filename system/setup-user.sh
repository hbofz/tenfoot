#!/bin/sh
# The part of install.sh that runs as the TV's own user. Safe to re-run.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
CONF=$HOME/.config/tenfoot
UNITS=$HOME/.config/systemd/user
mkdir -p "$CONF" "$UNITS"
chmod 700 "$CONF"
[ -e "$CONF/config.toml" ] || cp "$ROOT/config.example.toml" "$CONF/config.toml"
# The first phone sets the timezone (tenfoot/clock.py), unless an admin already chose one: keep that.
# (Europe/London and UTC are what Raspberry Pi OS and Debian start with: nobody chose those.)
ZONE=$(readlink /etc/localtime 2>/dev/null | sed 's|.*zoneinfo/||')
if [ "${IMAGE:-0}" = 0 ] && [ -n "$ZONE" ] && [ "$ZONE" != Europe/London ] && [ "$ZONE" != Etc/UTC ] && [ "$ZONE" != UTC ] && [ ! -e "$CONF/timezone-set" ]; then
  echo "$ZONE" > "$CONF/timezone-set"
fi
setting() { (cd "$ROOT" && python3 -c "from tenfoot import config; print(config.load().$1)"); }
NAME=$(setting name)
fill() { sed -e "s|@ROOT@|$ROOT|g" -e "s|@NAME@|$NAME|g" "$1"; }

# Widevine: the Pi package ships it in Firefox's layout; give Chromium the Chrome layout plus the
# hint file its component loader reads.
W=$CONF/chromium/WidevineCdm
mkdir -p "$W/pi/_platform_specific/linux_arm64"
ln -sf /opt/WidevineCdm/manifest.json "$W/pi/manifest.json"
ln -sf /opt/WidevineCdm/gmp-widevinecdm/latest/libwidevinecdm.so "$W/pi/_platform_specific/linux_arm64/"
echo "{\"Path\":\"$W/pi\"}" > "$W/latest-component-updated-widevine-cdm"

# The kiosk: only on the physical console, never over SSH. Ctrl+C can't break the loop. cage runs without -s, so a
# keyboard can't switch to another console; the optional zero-copy compositor (patches/wlroots) is used once it's built.
touch "$HOME/.profile"
sed -i '/^# tenfoot kiosk/,/^fi$/d' "$HOME/.profile"
cat >> "$HOME/.profile" <<PROFILE
# tenfoot kiosk: only on the physical console, never over SSH. Ctrl+C can't break the loop.
if [ "\$(tty)" = /dev/tty1 ] && [ -z "\${WAYLAND_DISPLAY:-}" ]; then
  trap '' INT QUIT TSTP
  while :; do WLR_DRM_FORCE_LIBLIFTOFF=1 LD_LIBRARY_PATH="$ROOT/wlroots-build" cage -- "$ROOT/system/kiosk.sh"; sleep 3; done
fi
PROFILE

fill "$ROOT/system/tenfoot.service" > "$UNITS/tenfoot.service"
if [ "$(setting spotify)" = True ]; then
  # Spotify Connect (go-librespot, pinned release, checksum-verified).
  GLR=v0.10.2 GLR_SHA=800b174f066624edf37caec8266fd08e914e6fd837b2c92a4042aa21c0bafa4d
  mkdir -p "$ROOT/spotify"
  if [ "$(cat "$ROOT/spotify/.sha" 2>/dev/null)" != "$GLR_SHA" ]; then
    T=$(mktemp)
    curl -fsSL -o "$T" "https://github.com/devgianlu/go-librespot/releases/download/$GLR/go-librespot_linux_arm64.tar.gz"
    echo "$GLR_SHA  $T" | sha256sum -c --quiet
    tar -xzf "$T" -C "$ROOT/spotify" go-librespot
    rm "$T"
    echo "$GLR_SHA" > "$ROOT/spotify/.sha"
  fi
  mkdir -p "$HOME/.config/go-librespot"
  chmod 700 "$HOME/.config/go-librespot"
  fill "$ROOT/system/go-librespot.yml" > "$HOME/.config/go-librespot/config.yml"
  fill "$ROOT/system/tenfoot-spotify.service" > "$UNITS/tenfoot-spotify.service"
else
  rm -f "$UNITS/tenfoot-spotify.service"
fi
if [ "$AIRPLAY" = 1 ]; then
  install -d -m 700 "$HOME/.config/uxplay"
  fill "$ROOT/system/tenfoot-airplay.service" > "$UNITS/tenfoot-airplay.service"
fi

# Nothing's running inside a disk image: just mark the services as enabled. (Sound is set up by kiosk.sh at first boot.)
enable_unit() {
  if [ "${IMAGE:-0}" = 1 ]; then
    mkdir -p "$UNITS/default.target.wants"
    ln -sf "$UNITS/$1.service" "$UNITS/default.target.wants/$1.service"
  else
    systemctl --user daemon-reload
    systemctl --user enable "$1" 2>/dev/null
  fi
}

(cd "$ROOT" && python3 -m tenfoot render)
for s in tenfoot tenfoot-spotify tenfoot-airplay; do
  if [ -e "$UNITS/$s.service" ]; then
    enable_unit "$s"
    [ "${IMAGE:-0}" = 1 ] || systemctl --user restart "$s"
  fi
done
if [ "$WALLPAPERS" = 1 ]; then
  # One now, so the first boot has a picture (a rate-limited download mustn't hold up the install). The rest in
  # the background, resuming after a reboot until it has them all; the home screen uses what's there so far.
  # (An image is built with them already in place, so this finds nothing to do.)
  [ "${IMAGE:-0}" = 1 ] || timeout 180 python3 "$ROOT/tools/wallpapers.py" 1 >/dev/null 2>&1 || echo "No wallpaper yet; they'll keep downloading in the background."
  fill "$ROOT/system/tenfoot-wallpapers.service" > "$UNITS/tenfoot-wallpapers.service"
  enable_unit tenfoot-wallpapers
  [ "${IMAGE:-0}" = 1 ] || systemctl --user start --no-block tenfoot-wallpapers
fi
