#!/bin/sh
# Installs Tenfoot on Raspberry Pi OS (Trixie or later, 64-bit, Pi 4) for the user running it, from
# a clone of this repo. Safe to re-run. Options: --airplay  also install the AirPlay receiver
#                                                --no-wallpapers  skip the photo download
set -eu
ROOT=$(cd "$(dirname "$0")" && pwd)
AIRPLAY=0 WALLPAPERS=1
for a in "$@"; do
  case "$a" in
    --airplay) AIRPLAY=1 ;;
    --no-wallpapers) WALLPAPERS=0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done
[ "$(dpkg --print-architecture)" = arm64 ] || { echo "Tenfoot needs a 64-bit Raspberry Pi OS" >&2; exit 1; }
CONF=$HOME/.config/tenfoot
UNITS=$HOME/.config/systemd/user
mkdir -p "$CONF" "$UNITS"
chmod 700 "$CONF"
[ -e "$CONF/config.toml" ] || cp "$ROOT/config.example.toml" "$CONF/config.toml"
NAME=$(cd "$ROOT" && python3 -c 'from tenfoot import config; print(config.load().name)' 2>/dev/null || echo Tenfoot)
fill() { sed -e "s|@ROOT@|$ROOT|g" -e "s|@NAME@|$NAME|g" "$1"; }

# Chromium and the kiosk's compositor, Widevine from Raspberry Pi's own repo (never bundled), sound, CEC, input.
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-upgrade curl chromium cage wlr-randr libwidevinecdm0 \
  pipewire-pulse wireplumber pulseaudio-utils v4l-utils coreutils procps \
  python3-evdev python3-websocket python3-qrcode python3-cryptography python3-numpy python3-pil >/dev/null

# Widevine: the Pi package ships it in Firefox's layout; give Chromium the Chrome layout plus the
# hint file its component loader reads.
W=$CONF/chromium/WidevineCdm
mkdir -p "$W/pi/_platform_specific/linux_arm64"
ln -sf /opt/WidevineCdm/manifest.json "$W/pi/manifest.json"
ln -sf /opt/WidevineCdm/gmp-widevinecdm/latest/libwidevinecdm.so "$W/pi/_platform_specific/linux_arm64/"
echo "{\"Path\":\"$W/pi\"}" > "$W/latest-component-updated-widevine-cdm"

# Browser policy: ad-blocking DNS, and sites can't reach this box's own services or other files.
fill "$ROOT/system/chromium-policy.json" > "$CONF/policy.json"
sudo install -D -m 644 "$CONF/policy.json" /etc/chromium/policies/managed/tenfoot.json
rm "$CONF/policy.json"

# The virtual keyboard and mouse the remote drives.
sudo usermod -aG input,video,render "$(id -un)"  # uinput; CEC and the GPU
echo uinput | sudo tee /etc/modules-load.d/tenfoot.conf >/dev/null
echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' | sudo tee /etc/udev/rules.d/60-tenfoot-uinput.rules >/dev/null
sudo modprobe uinput
sudo udevadm control --reload
sudo udevadm trigger /dev/uinput

# Keep logs across reboots, capped, so an unexpected restart can be explained.
sudo mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=persistent\nSystemMaxUse=200M\n' | sudo tee /etc/systemd/journald.conf.d/tenfoot.conf >/dev/null
sudo systemctl restart systemd-journald

# Log in on tty1 at boot; the block in ~/.profile then starts the kiosk, only on that console.
# cage runs without -s, so a keyboard can't switch to another console; the optional zero-copy
# compositor (patches/wlroots) is used once it's built.
sudo raspi-config nonint do_boot_behaviour B2
touch "$HOME/.profile"
sed -i '/^# tenfoot kiosk/,/^fi$/d' "$HOME/.profile"
cat >> "$HOME/.profile" <<PROFILE
# tenfoot kiosk: only on the physical console, never over SSH. Ctrl+C can't break the loop.
if [ "\$(tty)" = /dev/tty1 ] && [ -z "\${WAYLAND_DISPLAY:-}" ]; then
  trap '' INT QUIT TSTP
  while :; do WLR_DRM_FORCE_LIBLIFTOFF=1 LD_LIBRARY_PATH="$ROOT/wlroots-build" cage -- "$ROOT/system/kiosk.sh"; sleep 3; done
fi
PROFILE

# Services.
fill "$ROOT/system/tenfoot.service" > "$UNITS/tenfoot.service"
SPOTIFY=$(cd "$ROOT" && python3 -c 'from tenfoot import config; print(int(config.load().spotify))' 2>/dev/null || echo 1)
if [ "$SPOTIFY" = 1 ]; then
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
fi
if [ "$AIRPLAY" = 1 ]; then
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-upgrade --no-install-recommends uxplay gstreamer1.0-plugins-bad avahi-daemon >/dev/null
  sudo systemctl enable --now avahi-daemon
  install -d -m 700 "$HOME/.config/uxplay"
  fill "$ROOT/system/tenfoot-airplay.service" > "$UNITS/tenfoot-airplay.service"
fi

# Sound: default output = the TV over HDMI, full volume, so the remote's volume is what you hear.
XDG_RUNTIME_DIR="/run/user/$(id -u)"
export XDG_RUNTIME_DIR
loginctl enable-linger "$(id -un)" 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user start pipewire.socket pipewire-pulse.socket pipewire wireplumber pipewire-pulse
sleep 2
HDMI=$(wpctl status | sed -n "/Sinks:/,/Sources:/p" | grep HDMI | grep -o "[0-9]\+\." | head -1 | tr -d .)
if [ -n "$HDMI" ]; then wpctl set-default "$HDMI"; wpctl set-volume "$HDMI" 1.0; wpctl set-mute "$HDMI" 0; fi

(cd "$ROOT" && python3 -m tenfoot render)
for s in tenfoot tenfoot-spotify tenfoot-airplay; do
  [ -e "$UNITS/$s.service" ] && { systemctl --user enable "$s" 2>/dev/null; systemctl --user restart "$s"; }
done
if [ "$WALLPAPERS" = 1 ]; then
  # One now, so the first boot has a picture (a rate-limited download mustn't hold up the install). The rest in
  # the background, resuming after a reboot until it has them all; the home screen uses what's there so far.
  timeout 180 python3 "$ROOT/tools/wallpapers.py" 1 >/dev/null 2>&1 || echo "No wallpaper yet; they'll keep downloading in the background."
  fill "$ROOT/system/tenfoot-wallpapers.service" > "$UNITS/tenfoot-wallpapers.service"
  systemctl --user daemon-reload
  systemctl --user enable tenfoot-wallpapers 2>/dev/null
  systemctl --user start --no-block tenfoot-wallpapers
fi
echo "Installed. Reboot to start the kiosk: sudo reboot"
