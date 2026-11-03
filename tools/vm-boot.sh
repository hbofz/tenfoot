#!/bin/sh
# First-boot test of an image on a PC, with no Pi: boots a throwaway copy in QEMU's Raspberry Pi 4 model, then reports
# what happened from the copy's own files. It has no Wi-Fi, TV or network, so those need the real thing.
#   tools/vm-boot.sh IMAGE.img.xz [SECONDS]      Needs qemu-system-arm, and sudo to read the result.
set -eu
IMG=$1; SECS=${2:-600}
W=$(mktemp -d "${TMPDIR:-/tmp}/tenfoot-vm.XXXXXX"); M=$W/mnt; mkdir -p "$M"
trap 'sudo umount "$M/boot/firmware" "$M" 2>/dev/null || true; [ -n "${L:-}" ] && sudo losetup -d "$L" 2>/dev/null; rm -rf "$W"' EXIT
xz -dc "$IMG" > "$W/sd.img"
qemu-img resize -q -f raw "$W/sd.img" 16G   # the emulated SD card must be a power of two
L=$(sudo losetup --find --show --partscan "$W/sd.img")
sudo mount -o ro "${L}p1" "$M"
cp "$M/kernel8.img" "$M/bcm2711-rpi-4-b.dtb" "$W/"
sudo umount "$M"; sudo losetup -d "$L"; L=
# Not the image's own initramfs or console settings: QEMU's Pi 4 model needs the serial console spelled out, and its
# watchdog resets a booting system (so it's left out). Root is mounted directly; the card isn't resized.
CMD="earlycon=pl011,mmio32,0xfe201000 console=ttyAMA0,115200 root=/dev/mmcblk1p2 rootfstype=ext4 rw rootwait panic=0 \
systemd.watchdog_sec=0 modprobe.blacklist=bcm2835_wdt initcall_blacklist=bcm2835_wdt_driver_init rfkill.default_state=1"
echo "booting for ${SECS}s (emulated: a first boot needs about 8 minutes)..."
timeout "$SECS" qemu-system-aarch64 -M raspi4b -kernel "$W/kernel8.img" -dtb "$W/bcm2711-rpi-4-b.dtb" -append "$CMD" \
  -drive "file=$W/sd.img,format=raw,if=sd" -display none -monitor none -serial "file:$W/serial.log" -serial null < /dev/null > /dev/null 2>&1 || true
L=$(sudo losetup --find --show --partscan "$W/sd.img")
sudo mount -o ro,noload "${L}p2" "$M"; sudo mount -o ro "${L}p1" "$M/boot/firmware"  # noload: it was switched off mid-run
echo "--- auto-login files"; sudo ls -la --time-style=long-iso "$M/etc/systemd/system/getty@tty1.service.d/" 2>&1 | tail -n +2 | cut -c30-90
J=$(sudo ls -d "$M"/var/log/journal/*/ 2>/dev/null | head -1)
if [ -n "$J" ]; then
  sudo journalctl -D "$J" --no-pager --list-boots 2>/dev/null | tail -3 | cut -c1-90
  echo "--- what happened"; sudo journalctl -D "$J" --no-pager -o short-monotonic 2>/dev/null | grep -E "Started getty@tty1|login.*session opened for user tenfoot|setup: |crashed|Started tenfoot.service" | head -12 | cut -c1-125
else echo "no journal; serial log:"; tail -25 "$W/serial.log" | cut -c1-120; fi
sudo grep -nE "autologin|getty" "$M/var/log/cloud-init.log" 2>/dev/null | tail -5 | cut -c1-120
cp "$W/serial.log" "${TMPDIR:-/tmp}/tenfoot-vm-serial.log" 2>/dev/null || true
