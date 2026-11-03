#!/bin/sh
# TEST CARDS ONLY. Copies a finished Tenfoot image and gives the copy a way in for a developer: an admin user with an
# SSH key and passwordless sudo, SSH switched on, and optionally a Tailscale identity so the box is reachable from
# anywhere without anyone in the room. Release images from tools/build-image.sh have none of this. Never publish this
# script's output, and never flash it for anyone else: whoever holds the key owns the box.
#   tools/test-access.sh IMAGE.img[.xz] OUT.img [PUBKEY_FILE]
# Settings, from the environment:
#   TEST_USER=couch                                       the admin user to add
#   TAILSCALE=~/.config/tenfoot-test/tailscale.tar.gz    an existing node's tailscaled.state and certs/ (from that
#                                                         node's /var/lib/tailscale; mode 600, never in git). Skipped
#                                                         when the file isn't there.
# Runs the image's own programs through qemu-user-static, like build-image.sh. Needs sudo. A run that fails part way
# deletes its output: a half-made copy would have the access without the TEST label.
set -eu
IN=$1 OUT=$2 KEY=${3:-$HOME/.ssh/id_ed25519.pub}
U=${TEST_USER:-couch}
TS=${TAILSCALE:-$HOME/.config/tenfoot-test/tailscale.tar.gz}
echo "$U" | grep -qE '^[a-z_][a-z0-9_-]*$' || { echo "bad user name $U" >&2; exit 1; }
ssh-keygen -l -f "$KEY" >/dev/null 2>&1 && ! grep -q PRIVATE "$KEY" || { echo "$KEY isn't an SSH public key" >&2; exit 1; }
[ "$(dpkg --print-architecture)" = arm64 ] || [ -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ] || { echo "Needs a 64-bit Raspberry Pi, or qemu-user-static" >&2; exit 1; }
for tool in losetup; do command -v "$tool" >/dev/null || PATH=$PATH:/usr/sbin:/sbin; done
LOOP= M=
cleanup() {
  if [ -n "$M" ]; then for d in dev/pts dev proc sys boot/firmware ""; do sudo umount "$M/$d" 2>/dev/null || true; done; fi
  [ -z "$LOOP" ] || sudo losetup -d "$LOOP" 2>/dev/null || true
  [ -z "$M" ] || rmdir "$M" 2>/dev/null || true
}
# Never over an existing file: it could be the input itself (and an old copy would keep its own file mode).
[ ! -e "$OUT" ] && [ ! -L "$OUT" ] || { echo "$OUT already exists: remove it first, or pick another name" >&2; exit 1; }
trap 'cleanup; rm -f "$OUT"' EXIT
trap 'exit 1' INT TERM HUP  # so an interrupted run cleans up too
(umask 077  # the copy holds the Tailscale node's private key: for this user's eyes only
 case "$IN" in *.xz) xz -dc "$IN" > "$OUT" ;; *) cp --sparse=always "$IN" "$OUT" ;; esac)

LOOP=$(sudo losetup --find --show --partscan "$OUT")
M=$(mktemp -d)
sleep 1
sudo mount "${LOOP}p2" "$M"
sudo mount "${LOOP}p1" "$M/boot/firmware"
sudo test -d "$M/home/tenfoot/tenfoot" || { echo "$IN isn't a Tenfoot image" >&2; exit 1; }
for d in dev dev/pts proc sys; do sudo mount --bind "/$d" "$M/$d"; done
# Never an existing user (the TV's own must keep having no sudo), unless this is a test copy being redone.
if sudo chroot "$M" id "$U" >/dev/null 2>&1 && ! sudo grep -q "user $U," "$M/etc/tenfoot-test-access" 2>/dev/null; then
  echo "$U already exists in $IN: pick another TEST_USER" >&2; exit 1
fi
# The label first: whatever happens next, this card says what it is.
printf 'TEST IMAGE with developer access (user %s, key %s). Not for release. Made %s by tools/test-access.sh.\n' \
  "$U" "$(cut -d' ' -f3 "$KEY")" "$(date -u +%Y-%m-%d)" | sudo tee "$M/etc/tenfoot-test-access" "$M/boot/firmware/TEST-IMAGE.txt" >/dev/null

# The admin user: key login only (no password at all), sudo without one.
sudo chroot "$M" sh -c "id $U >/dev/null 2>&1 || useradd --create-home --shell /bin/bash --groups sudo $U; passwd -l $U >/dev/null"
H=$M/home/$U
sudo install -d -m 700 "$H/.ssh"
sudo install -m 600 "$KEY" "$H/.ssh/authorized_keys"
sudo chroot "$M" chown -R "$U:$U" "/home/$U/.ssh"
echo "$U ALL=(ALL) NOPASSWD: ALL" | sudo install -m 440 /dev/stdin "$M/etc/sudoers.d/010-tenfoot-test"
sudo chroot "$M" systemctl enable ssh >/dev/null 2>&1

if [ -f "$TS" ]; then
  # Tailscale from its own Debian repo, with this node's identity, so the box joins the tailnet by itself.
  sudo mv "$M/etc/resolv.conf" "$M/etc/resolv.conf.test-access"  # build-image.sh leaves a link into /run: put it back after
  sudo cp /etc/resolv.conf "$M/etc/resolv.conf"
  printf '#!/bin/sh\nexit 101\n' | sudo install -m 755 /dev/stdin "$M/usr/sbin/policy-rc.d"
  CODENAME=$(. "$M/etc/os-release" && echo "$VERSION_CODENAME")
  GPG=$(mktemp)
  curl -fsSL -o "$GPG" "https://pkgs.tailscale.com/stable/debian/$CODENAME.noarmor.gpg"
  sudo install -D -m 644 "$GPG" "$M/usr/share/keyrings/tailscale-archive-keyring.gpg"
  rm -f "$GPG"
  echo "deb [signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg] https://pkgs.tailscale.com/stable/debian $CODENAME main" | sudo tee "$M/etc/apt/sources.list.d/tailscale.list" >/dev/null
  sudo chroot "$M" sh -c 'apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq tailscale >/dev/null && apt-get clean'
  sudo rm -rf "$M/var/lib/apt/lists/"*
  sudo install -d -m 700 "$M/var/lib/tailscale"
  sudo tar --no-same-owner -xzf "$TS" -C "$M/var/lib/tailscale"
  sudo chown -R 0:0 "$M/var/lib/tailscale"
  sudo chmod -R go-rwx "$M/var/lib/tailscale"
  sudo chroot "$M" systemctl enable tailscaled >/dev/null 2>&1
  sudo rm -f "$M/usr/sbin/policy-rc.d"
  sudo mv "$M/etc/resolv.conf.test-access" "$M/etc/resolv.conf"
  echo "Tailscale: in, with the identity from $TS"
else
  echo "Tailscale: skipped ($TS not found): reach it on the local network only"
fi

sudo fstrim "$M" 2>/dev/null || true
cleanup
trap - EXIT
echo "Wrote $OUT: a TEST card image (ssh $U@<box>). Don't publish it."
