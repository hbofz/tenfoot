#!/bin/sh
# Builds the kiosk's wlroots on the Pi: Raspberry Pi OS's wlroots 0.20.2-1+rpt4 (the library cage uses)
# with its own patches plus ours: 0001 + 0002 let Chromium's video go straight to a display plane and
# keep it getting frame callbacks, 0003 gets video colours right on the planes (YCbCr range in the
# kernel's order, BT.709 for HD). Takes about a minute. Output: $OUT/libwlroots-0.20.so, loaded by cage
# through LD_LIBRARY_PATH (the system copy stays as it is).
# Needs wlroots' build dependencies (debian/control Build-Depends), once:
#   sudo apt-get install -y --no-install-recommends build-essential dpkg-dev glslang-tools hwdata libcairo2-dev libcap-dev libdisplay-info-dev libdrm-dev libegl-dev libegl1-mesa-dev libgbm-dev libgles2-mesa-dev libinput-dev liblcms2-dev libliftoff-dev libpixman-1-dev libpng-dev libseat-dev libvulkan-dev libwayland-dev libx11-xcb-dev libxcb-composite0-dev libxcb-dri3-dev libxcb-errors-dev libxcb-ewmh-dev libxcb-icccm4-dev libxcb-image0-dev libxcb-present-dev libxcb-render-util0-dev libxcb-render0-dev libxcb-res0-dev libxcb-shm0-dev libxcb-xfixes0-dev libxcb-xinput-dev libxcb1-dev libxkbcommon-dev meson pkgconf wayland-protocols xwayland
#   build.sh [OUT]      default OUT: wlroots-build/ in the repo (where the kiosk loop in ~/.profile looks)
set -ex
V=0.20.2
RPT=1+rpt4
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${1:-$(cd "$(dirname "$0")/../.." && pwd)/wlroots-build}
WORK=$HOME/build/wlroots
POOL=https://archive.raspberrypi.com/debian/pool/main/w/wlroots

rm -rf "$WORK" && mkdir -p "$WORK" && cd "$WORK"
wget -q "$POOL/wlroots_$V.orig.tar.bz2" "$POOL/wlroots_$V-$RPT.debian.tar.xz"
# sha256s from Raspberry Pi's signed .dsc; a new version needs new ones
echo "20c37b521dc3054b6e9627b79bdd45fc716db9ebc58bdf97e57e84d04b04610f  wlroots_$V.orig.tar.bz2
aeea5c71bbc9980ddebe0b03412b19f7423d7f212328bf1adb9719d77986c611  wlroots_$V-$RPT.debian.tar.xz" | sha256sum -c --quiet
tar -xjf "wlroots_$V.orig.tar.bz2" && tar -xJf "wlroots_$V-$RPT.debian.tar.xz"
cd "wlroots-$V"
grep -vE '^\s*(#|$)' ../debian/patches/series | while read -r p; do patch -p1 -s < "../debian/patches/$p"; done
for p in "$HERE"/0*.patch; do patch -p1 < "$p"; done
meson setup build -Dbackends=drm,libinput,x11 -Dbuildtype=release -Dexamples=false  # Debian's -Dbackends
nice ninja -C build
mkdir -p "$OUT" && cp build/libwlroots-0.20.so "$OUT/"
ls -la "$OUT/libwlroots-0.20.so"
