#!/bin/sh
# Installs Tenfoot on Raspberry Pi OS (Trixie or later, 64-bit, Pi 4) from a clone of this repo. Run it as your
# normal admin user. The TV itself runs as its own "tenfoot" user with no sudo, so a hacked browser can't take
# over the box. Safe to re-run; re-run it to update. Options: --airplay  also install the AirPlay receiver
#                                                             --no-wallpapers  skip the photo download
# tools/build-image.sh runs it inside a disk image with --image: nothing is running there, so live steps are skipped.
set -eu
SRC=$(cd "$(dirname "$0")" && pwd)
TV=tenfoot
AIRPLAY=0 WALLPAPERS=1 IMAGE=0
for a in "$@"; do
  case "$a" in
    --airplay) AIRPLAY=1 ;;
    --no-wallpapers) WALLPAPERS=0 ;;
    --image) IMAGE=1 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done
[ "$(dpkg --print-architecture)" = arm64 ] || { echo "Tenfoot needs a 64-bit Raspberry Pi OS" >&2; exit 1; }
[ "$(id -un)" != "$TV" ] || { echo "Run this as your admin user, not $TV" >&2; exit 1; }

# Chromium and the kiosk's compositor, Widevine from Raspberry Pi's own repo (never bundled), sound, CEC, input.
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-upgrade curl chromium cage wlr-randr libwidevinecdm0 \
  pipewire-pulse wireplumber pulseaudio-utils v4l-utils coreutils procps network-manager dnsmasq-base polkitd \
  python3-evdev python3-websocket python3-qrcode python3-cryptography python3-numpy python3-pil earlyoom dpkg-repack >/dev/null
[ "$AIRPLAY" = 0 ] || {
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-upgrade --no-install-recommends uxplay gstreamer1.0-plugins-bad avahi-daemon >/dev/null
  if [ "$IMAGE" = 1 ]; then sudo systemctl enable avahi-daemon; else sudo systemctl enable --now avahi-daemon; fi
}

# The TV's user: no sudo and no password, only what it needs for sound, the GPU, CEC and the virtual remote.
id "$TV" >/dev/null 2>&1 || sudo useradd --create-home --shell /bin/bash "$TV"
sudo usermod -aG input,video,render,audio "$TV"
sudo passwd -l "$TV" >/dev/null
sudo chmod 750 "/home/$TV"
APP=/home/$TV/tenfoot
sudo -u "$TV" mkdir -p "$APP"
tar -C "$SRC" --exclude=.git --exclude=__pycache__ -cf - . | sudo -u "$TV" tar -xf - -C "$APP"
fill() { sed -e "s|@ROOT@|$APP|g" "$1"; }

# Browser policy: ad-blocking DNS, and sites can't reach this box's own services or other files.
fill "$SRC/system/chromium-policy.json" | sudo install -D -m 644 /dev/stdin /etc/chromium/policies/managed/tenfoot.json

# The virtual keyboard and mouse the remote drives.
echo uinput | sudo tee /etc/modules-load.d/tenfoot.conf >/dev/null
echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' | sudo tee /etc/udev/rules.d/60-tenfoot-uinput.rules >/dev/null
if [ "$IMAGE" = 0 ]; then
  sudo modprobe uinput
  sudo udevadm control --reload
  sudo udevadm trigger /dev/uinput
fi

# First-time Wi-Fi (tenfoot/setup.py): the TV's user may manage the network, every name on the setup hotspot leads to
# this box so phones open the setup page, and it may answer on port 80, where phones look for that.
sudo tee /etc/polkit-1/rules.d/50-tenfoot.rules >/dev/null <<POLKIT
polkit.addRule(function (action, subject) {
  if (subject.user == "$TV" && action.id.indexOf("org.freedesktop.NetworkManager.") == 0) return polkit.Result.YES;
  // The first phone to connect sets the timezone (tenfoot/clock.py).
  if (subject.user == "$TV" && action.id == "org.freedesktop.timedate1.set-timezone") return polkit.Result.YES;
  // Two root jobs it may start, nothing else: the phone's "Update now" (only ever a newer, signed release), and the kiosk
  // watchdog's last-resort reboot (which root refuses within an hour of starting, during updates, with anyone logged in).
  if (subject.user == "$TV" && action.id == "org.freedesktop.systemd1.manage-units" && action.lookup("verb") == "start" &&
      (action.lookup("unit") == "tenfoot-update-now.service" || action.lookup("unit") == "tenfoot-reboot-stuck.service"))
    return polkit.Result.YES;
});
POLKIT
sudo mkdir -p /etc/NetworkManager/dnsmasq-shared.d
echo 'address=/#/10.42.0.1' | sudo tee /etc/NetworkManager/dnsmasq-shared.d/tenfoot.conf >/dev/null
# A kernel panic reboots after 10 s instead of hanging (the hardware watchdog, which Raspberry Pi OS arms, covers freezes).
printf 'net.ipv4.ip_unprivileged_port_start=80\nkernel.panic=10\n' | sudo tee /etc/sysctl.d/60-tenfoot.conf >/dev/null
[ "$IMAGE" = 1 ] || sudo sysctl -q --system

# Out of memory (1.8 GB and a browser): kill a browser tab early, never the compositor, the service, Spotify or SSH,
# instead of the whole box crawling for minutes first. Chromium marks its tabs as the first to go already. Swap here
# is zram, compressed RAM: "swap still free" doesn't mean memory is, so only available RAM counts (-s 100).
echo "EARLYOOM_ARGS=\"-m 8 -s 100,100 -r 0 --prefer '^(chrome|chromium)\$' --avoid '^(cage|python3|sshd|sshd-session|systemd|go-librespot|uxplay)\$'\"" | \
  sudo tee /etc/default/earlyoom >/dev/null
sudo systemctl enable earlyoom 2>/dev/null
[ "$IMAGE" = 1 ] || sudo systemctl restart earlyoom

# Keep logs across reboots, capped, so an unexpected restart can be explained.
sudo mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=persistent\nSystemMaxUse=200M\n' | sudo tee /etc/systemd/journald.conf.d/tenfoot.conf >/dev/null
[ "$IMAGE" = 1 ] || sudo systemctl restart systemd-journald

# The 1080p60 browser and compositor (patches/) were built against exactly these: held, so no upgrade (the updater's
# weekly system updates, or an admin's apt full-upgrade) swaps them underneath. Unhold with apt-mark unhold, rebuild.
HOLD=$(dpkg-query -W -f '${Package}\n' cage libwlroots-0.20 libgbm1 libegl-mesa0 mesa-libgallium libgl1-mesa-dri libglx-mesa0 \
  libdrm2 libdrm-common libliftoff0 2>/dev/null || true)
[ -z "$HOLD" ] || sudo apt-mark hold $HOLD >/dev/null

# Updates (system/tenfoot-update): root's own copy of the updater and its timer, and a copy of this release to go back
# to if the next one doesn't work. Run by the updater itself, this already is that copy.
U=/var/lib/tenfoot-update
V=$(cat "$SRC/VERSION")
sudo install -d -m 755 "$U" "$U/releases"
sudo install -m 755 "$SRC/system/tenfoot-update" /usr/local/sbin/tenfoot-update
for f in tenfoot-update.service tenfoot-update-now.service tenfoot-update.timer tenfoot-reboot-stuck.service; do sudo install -m 644 "$SRC/system/$f" /etc/systemd/system/; done
case "$SRC" in
  "$U/releases/"*) ;;
  *) sudo rm -rf "$U/releases/$V"
     sudo mkdir "$U/releases/$V"
     tar -C "$SRC" --exclude=.git --exclude=__pycache__ --exclude=web/home/run --exclude=web/home/wallpapers --exclude=chromium \
       --exclude=wlroots-build --exclude=spotify -cf - . | sudo tar -xf - --no-same-owner -C "$U/releases/$V" ;;
esac
echo "$V" | sudo tee "$U/version" >/dev/null
[ "$IMAGE" = 1 ] || sudo systemctl daemon-reload
sudo systemctl enable tenfoot-update.timer 2>/dev/null
[ "$IMAGE" = 1 ] || sudo systemctl start tenfoot-update.timer

# Boot to a console logged in as the TV's user on tty1; its ~/.profile starts the kiosk.
# Not named autologin.conf: on a fresh image something at first boot took that one away (see system tools' use of it).
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
printf '[Service]\nExecStart=\nExecStart=-/sbin/agetty --autologin %s --noclear %%I $TERM\n' "$TV" | sudo tee /etc/systemd/system/getty@tty1.service.d/tenfoot-autologin.conf >/dev/null
sudo systemctl set-default multi-user.target >/dev/null
# Raspberry Pi OS only switches the console login on at the end of its first-boot setup wizard, which an image skips
# (a TV has no keyboard for it): switch it on here, or a fresh card never logs in and the screen stays on boot text.
sudo systemctl enable getty@tty1.service >/dev/null 2>&1
[ "$IMAGE" = 1 ] || sudo systemctl daemon-reload

# If its service manager dies (the kernel's last-ditch out-of-memory killer can take it), start it again: it brings
# back everything under it (the service, Spotify, sound). Otherwise the TV limps on without them until a reboot.
sudo mkdir -p "/etc/systemd/system/user@$(id -u "$TV").service.d"
printf '[Service]\nRestart=always\nRestartSec=5\n' | sudo tee "/etc/systemd/system/user@$(id -u "$TV").service.d/tenfoot-restart.conf" >/dev/null
[ "$IMAGE" = 1 ] || sudo systemctl daemon-reload
# Keep its services running with nobody logged in, and wait for its service manager to be up.
RUN=/run/user/$(id -u "$TV")
if [ "$IMAGE" = 1 ]; then
  sudo mkdir -p /var/lib/systemd/linger
  sudo touch "/var/lib/systemd/linger/$TV"
else
  sudo loginctl enable-linger "$TV"
  for _ in 1 2 3 4 5 6 7 8 9 10; do [ -S "$RUN/bus" ] && break; sleep 1; done
fi

# Everything else runs as that user.
sudo -u "$TV" -H env XDG_RUNTIME_DIR="$RUN" AIRPLAY="$AIRPLAY" WALLPAPERS="$WALLPAPERS" IMAGE="$IMAGE" sh "$APP/system/setup-user.sh"

# `tenfoot` for your admin user: links, restart.
fill "$SRC/system/tenfoot-command" | sudo install -m 755 /dev/stdin /usr/local/bin/tenfoot
echo "Installed. Reboot to start the kiosk: sudo reboot"
