#!/bin/sh
# Builds a ready-to-flash Tenfoot image from the current Raspberry Pi OS Lite. Run as a sudo-capable user on a 64-bit
# Raspberry Pi (it runs the image's own programs directly). Needs about 12 GB free.
#   tools/build-image.sh OUTPUT_DIR [WALLPAPERS_DIR] [VIDEO_DIR]
# WALLPAPERS_DIR: a finished web/home/wallpapers folder to put in the image, so the photos are there from the first boot.
# VIDEO_DIR: the 1080p60 builds from docs/1080p60.md, chromium-tenfoot.tar.zst (or chromium-*.tar.zst) and libwlroots-0.20.so.
set -eu
SRC=$(cd "$(dirname "$0")/.." && pwd)
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
WALLS=${2:-}
VIDEO=${3:-}
GROW=4G
[ "$(dpkg --print-architecture)" = arm64 ] || { echo "Run this on a 64-bit Raspberry Pi" >&2; exit 1; }
for tool in xz parted resize2fs e2fsck losetup curl; do command -v "$tool" >/dev/null || PATH=$PATH:/usr/sbin:/sbin; done

URL=$(curl -fsSLI -o /dev/null -w '%{url_effective}' https://downloads.raspberrypi.com/raspios_lite_arm64_latest)
BASE=$(basename "$URL")
cd "$OUT"
[ -f "$BASE" ] || curl -fsSL -o "$BASE" "$URL"
curl -fsSL -o "$BASE.sha256" "$URL.sha256"
sha256sum -c "$BASE.sha256"
IMG=$OUT/tenfoot-$(date +%Y-%m-%d)-arm64.img
xz -dc "$BASE" > "$IMG"
truncate -s +$GROW "$IMG"

LOOP=$(sudo losetup --find --show --partscan "$IMG")
M=$(mktemp -d)
cleanup() {
  for d in dev/pts dev proc sys boot/firmware ""; do sudo umount "$M/$d" 2>/dev/null || true; done
  sudo losetup -d "$LOOP" 2>/dev/null || true
  rmdir "$M" 2>/dev/null || true
}
trap cleanup EXIT
sudo parted -s "$LOOP" resizepart 2 100%
sudo partprobe "$LOOP" 2>/dev/null || true
sleep 1
sudo e2fsck -pf "${LOOP}p2" >/dev/null || [ $? -le 1 ]
sudo resize2fs "${LOOP}p2" >/dev/null
sudo mount "${LOOP}p2" "$M"
sudo mount "${LOOP}p1" "$M/boot/firmware"
sudo mount --bind /dev "$M/dev"
sudo mount --bind /dev/pts "$M/dev/pts"
sudo mount -t proc proc "$M/proc"
sudo mount -t sysfs sys "$M/sys"
sudo cp --remove-destination /etc/resolv.conf "$M/etc/resolv.conf"

# Tenfoot itself, installed the normal way, inside the image.
sudo mkdir -p "$M/tmp/tenfoot-src"
tar -C "$SRC" --exclude=.git --exclude=__pycache__ --exclude=web/home/run --exclude=web/home/wallpapers -cf - . | sudo tar -xf - -C "$M/tmp/tenfoot-src"
if [ -n "$WALLS" ]; then
  sudo mkdir -p "$M/tmp/tenfoot-src/web/home/wallpapers"
  sudo cp "$WALLS"/* "$M/tmp/tenfoot-src/web/home/wallpapers/"
fi
# (sudo inside: the image's sudo, as root; the policy-rc.d stops packages starting services in here.)
printf '#!/bin/sh\nexit 101\n' | sudo tee "$M/usr/sbin/policy-rc.d" >/dev/null
sudo chmod 755 "$M/usr/sbin/policy-rc.d"
sudo chroot "$M" sh -c 'apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-upgrade sudo >/dev/null && chown -R root:root /tmp/tenfoot-src && chmod 755 /tmp/tenfoot-src && /tmp/tenfoot-src/install.sh --image'
sudo rm -f "$M/usr/sbin/policy-rc.d"
sudo rm -rf "$M/tmp/tenfoot-src"

# The 1080p60 browser and compositor library: system/kiosk.sh and the kiosk loop use them when they're there.
if [ -n "$VIDEO" ]; then
  APP=$M/home/tenfoot/tenfoot
  OWNER=$(sudo chroot "$M" id -u tenfoot)
  zstd -dc "$VIDEO"/chromium-*.tar.zst | sudo tar -xf - -C "$APP"
  sudo mkdir -p "$APP/wlroots-build"
  sudo cp "$VIDEO/libwlroots-0.20.so" "$APP/wlroots-build/"
  sudo chown -R "$OWNER:$OWNER" "$APP/chromium" "$APP/wlroots-build"
  [ -x "$APP/chromium/chrome" ] && [ -s "$APP/wlroots-build/libwlroots-0.20.so" ]
fi

# An appliance: no first-user questions on the TV, a radio that's on before anyone has chosen a Wi-Fi country.
sudo chroot "$M" systemctl disable userconfig 2>/dev/null || true
sudo rm -f "$M/etc/modprobe.d/rfkill_default.conf"
sudo sed -i 's/$/ rfkill.default_state=1/' "$M/boot/firmware/cmdline.txt"
sudo mkdir -p "$M/var/lib/NetworkManager" "$M/var/lib/systemd/rfkill"
printf '[main]\nNetworkingEnabled=true\nWirelessEnabled=true\nWWANEnabled=true\n' | sudo tee "$M/var/lib/NetworkManager/NetworkManager.state" >/dev/null
echo 0 | sudo tee "$M/var/lib/systemd/rfkill/platform-fe300000.mmcnr:wlan" >/dev/null
echo tenfoot | sudo tee "$M/etc/hostname" >/dev/null
sudo sed -i 's/raspberrypi/tenfoot/g' "$M/etc/hosts"
sudo chroot "$M" sh -c 'apt-get clean'
sudo rm -rf "$M/var/lib/apt/lists/"* "$M/etc/resolv.conf"
sudo ln -s ../run/NetworkManager/resolv.conf "$M/etc/resolv.conf" 2>/dev/null || true
sudo fstrim "$M" 2>/dev/null || true
cleanup
trap - EXIT
if [ "${COMPRESS:-1}" = 1 ]; then
  xz -T0 -3 -f "$IMG"
  sha256sum "$IMG.xz" > "$IMG.xz.sha256"
  ls -la "$IMG.xz"
else
  ls -la "$IMG"
fi
echo BUILD_DONE
