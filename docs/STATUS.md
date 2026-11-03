# Status and handoff

Where Tenfoot stands, what was tested and how, and what's left before a public release. Updated 2026-11-03.

## What works

On a real Raspberry Pi 4 (1.8 GB) connected to a 1080p TV, from a freshly flashed image:

| Step | Result |
| --- | --- |
| First boot | Logs the TV's user in by itself after about 30 s, with no keyboard and no account |
| Wi-Fi setup | No saved network: the box starts its own hotspot about 20 s later, and the TV shows a QR code |
| Phone setup | An iPhone scanned the code, the setup page opened, it picked an open network, and the box joined it about 40 s after the hotspot started |
| Phone remote | The remote's QR code appears on the home screen within seconds. Swipe, OK, Back, Home and volume all work |
| YouTube | The TV app plays 1080p at 60.2 frames a second, with the video on its own display plane (the 1080p60 browser at work). Sound goes over HDMI. 35°C, no throttling |

Also checked on the Pi with no TV, on a virtual screen, by `tests/box_check.py`:
- Real key presses move the focus on the home screen and the highlight on websites.
- Widevine reports as available.
- The phone link can't open the box's own services or `file://` pages, and websites can't reach them either.
- The browser comes back about 5 s after a crash and about 94 s after a freeze.
- The TV's user has no sudo.

## How it was tested

- **Unit tests:** `python3 -m unittest discover -s tests -p 'test_*.py'` (about 90 tests, no Pi needed).
- **Browser tests:** `tests/browser/test_sites.py`, `test_keyboard.py`, and `test_service.py`. The last one runs the real service against a real Chromium on a PC.
- **On an installed box:** `tests/box_check.py`, run as the `tenfoot` user.
- **Image first boot on a PC:** `tools/vm-boot.sh IMAGE.img.xz` boots a copy in QEMU's Raspberry Pi 4 model and reads the result from its disk. It's slow (a first boot needs about 8 minutes) and has no Wi-Fi, TV or network, but it proves boot, auto-login and the services without touching a real Pi.
- **On a real Pi:** flash the image to an SD card and boot it. The Pi tries the SD card before USB, so a Pi with a working system on USB boots the card when it's in, and goes back to USB when it's out.

To test on a real Pi you can reach remotely, flash a test copy instead of the release image: `tools/test-access.sh tenfoot-….img tenfoot-TEST.img` adds an admin user (`couch`, key-only, passwordless sudo) with your SSH key, switches SSH on, and, if `~/.config/tenfoot-test/tailscale.tar.gz` exists (a node's `tailscaled.state` and `certs/`; without the certificates Funnel hangs fetching new ones), installs Tailscale with that identity so the box joins your tailnet by itself. The copy is labelled `TEST-IMAGE.txt` on its boot partition. Never publish or hand out a test copy: whoever holds the key owns the box. Release images from `tools/build-image.sh` contain none of this. Build and boot-test images under a big disk (not a small `/tmp`): about 7 GB each.

## How to build

On any Linux PC with `qemu-user-static`, `parted`, `e2fsprogs`, `xz-utils` and `zstd` (about 10 minutes plus compression), or on a 64-bit Pi:

    tools/build-image.sh OUTPUT_DIR WALLPAPERS_DIR VIDEO_DIR

- `WALLPAPERS_DIR`: a finished `web/home/wallpapers` folder from `python3 tools/wallpapers.py`, which includes `CREDITS.txt`.
- `VIDEO_DIR`: the 1080p60 builds, `chromium-*.tar.zst` from `patches/chromium/build.sh` and `libwlroots-0.20.so` from `patches/wlroots/build.sh`. See [1080p60.md](1080p60.md).

## Updates

`system/tenfoot-update` (root, from `/usr/local/sbin`) checks GitHub Releases four times a day, installs a newer release signed by the key `tools/release.py` holds, reboots, and rolls back if the service (or the browser, if it was up) doesn't answer within 5 minutes. To release: bump `VERSION`, commit, `tools/release.py publish --notes "..."`. The signing key is `~/.config/tenfoot-release/signing.key` on Hamzah's PC; every box trusts only it, so it must be backed up.

The system's own packages: Raspberry Pi OS Lite installs no updates by itself, so once a week (Sunday, 3-6 am, `updates = "auto"`) the same updater takes Debian's security and point-release updates of Debian's own packages, plus Widevine, never Raspberry Pi's other builds (the 1080p60 browser and compositor depend on exactly the cage, wlroots and Mesa they were built against; `install.sh` holds those, so `apt-mark unhold` them before upgrading by hand, then rebuild). It saves the packages it replaces with `dpkg-repack` and puts them back if the box isn't healthy after the reboot. `sudo tenfoot-update os` runs it now. Tested on the real Pi: 15 security updates kept; the same 15 rolled back to the exact old versions when the health check was made to fail. Anything that fails before a package changes (no network at 4 am, a mirror mid-sync) just waits a week; a version is never tried again only after it failed twice; a rollback cut short by a power cut finishes on the next boot. Only in `auto` mode: `notify` boxes get no system updates. Not yet: the kernel and firmware (Raspberry Pi's; a bad one needs the Pi's tryboot to recover without a person). One risk it can't undo: Debian updates of udev, systemd or initramfs-tools rebuild the initramfs on the boot partition, and a power cut in that moment can leave the card unbootable.

Tested 2026-11-03 on the real Pi (SD-card image) from a local test feed: "Update now" through polkit as the TV's user, 0.1.0 to 0.1.1 (installed, rebooted, kept after 2 minutes), then a release whose service crashes (installed, rebooted, rolled back to 0.1.1 about 8 minutes later, never offered again). Unit tests in `tests/test_update.py`. Not yet tried against a real GitHub release, or with the Chromium build (updates replace Tenfoot's own files only; the patched Chromium stays as it is).

## Left before a public release

1. **Design pass.** The home screen tiles are plain coloured placeholders. The plan: the installer downloads each app's icon onto the box from an open icon collection, so no logos live in this repo. The home screen look itself still needs a direction from the owner.
2. **Chromium updates.** The 1080p60 browser is Chromium 155 and doesn't update itself, while the system's Chromium is already at 156. Every release needs a rebuild (`V`, `RPT` and checksums at the top of `patches/chromium/build.sh`, about 3 hours on 24 cores) and a new image. Decide who does this and how often before people log their accounts into it. Automating it in CI would be the real fix.
3. **Publishing the image.** About 1.4 GB compressed. GitHub Releases can host it (files up to 2 GB).
4. **Send the patches upstream:** the two Chromium patches, and the three wlroots patches. The wlroots colour-range fix was still an upstream bug when this was written.
5. **Demo video and README screenshots.**
6. **Make the repo public.**

## Not tested yet

- Playback with a signed-in account (Netflix, Disney+, HBO Max, Shahid and the others) on this system, and Spotify sign-in and music.
- A wrong Wi-Fi password and a password-protected network in setup (only unit tests so far). An open network joined fine on the real Pi.
- Setup from an Android phone.
- HDMI-CEC with a TV that forwards its remote's buttons, and Bluetooth or USB remotes on this system.
- AirPlay (`install.sh --airplay`). It isn't in the image.
- The remote in the default `lan` mode on a normal home network. Testing so far used `tailscale` mode, because the test network keeps devices apart.
- `install.sh` on the full desktop Raspberry Pi OS. Only Lite was tried.

## Known issues

- **Dropped frames:** YouTube 1080p60 dropped about 2.4% of frames in the first minutes after boot. The patched build's own clip test showed none, so recheck after a few minutes of playback.
- **Wallpaper downloads:** `tools/wallpapers.py` is slow on some networks (Wikimedia rate limits); one test took about 20 minutes for 2 photos. The image includes all 53, so this only affects manual installs.
- **Wi-Fi driver:** the Pi 4's Wi-Fi driver rejects networks that pair an open name with OWE ("invalid akm suite"). Setup joins open networks as plain open networks to avoid it (`tenfoot/setup.py`).
- **Auto-login file name:** on a fresh image, something during the first boot removed a getty drop-in named `autologin.conf`. The cause wasn't found; installing it as `tenfoot-autologin.conf` avoids it, and a real first boot confirmed that.
- **Network control:** the TV's user may manage the network (polkit), because Wi-Fi setup needs that. A compromised browser still can't get sudo, but it could change the Wi-Fi.
- **Password on the command line:** a Wi-Fi password is briefly on `nmcli`'s command line while joining.

## Ideas parked

- **Phone over Bluetooth**, for setup and as the remote. Safari on iPhone appears to have no Web Bluetooth (no official Apple statement found), so iPhones would need a native app. It would work on networks that keep devices apart.
- **Wi-Fi country on the setup page.** Images use the world regulatory domain, which is fine for joining networks but limits some 5 GHz channels.
- **Settings on the setup page:** name, location for the weather, and Jellyfin, so nobody edits `config.toml`.
