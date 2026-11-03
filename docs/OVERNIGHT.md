# Overnight work log

Autonomous run started 2026-11-03, on the `overnight` branch. Each feature: research how it's usually built, build it, test it (unit tests, and on the SD-card test Pi when it needs real hardware), then a reviewer pass repeated until it's clean. One commit per feature. `main` is untouched; no GitHub releases were published.

## Ranked plan

| # | Feature | Status |
|---|---------|--------|
| 1 | Timezone and clock (the update window was in UTC) | done |
| 2 | Whole-box watchdog and memory guard | done |
| 3 | Health warnings: undervoltage, heat, disk, no internet | done |
| 4 | Offline and error screens | in progress |
| 5 | YouTube ad blocking | done (a real pre-roll not seen yet) |
| 6 | OS security updates (Widevine included) | |
| 7 | Phone Settings page | |
| 8 | Fewer SD card writes, power-cut survival | |
| 9 | Idle handling inside apps (screensaver, TV standby) | |
| 10 | "Send logs" bundle | |
| 11 | Factory reset and sign-out | |
| 12 | Display adaptivity (720p and 4K TVs) | |
| 13 | Recently used apps first | |

Needs Hamzah: Chromium rebuild pipeline (CI money/owner), signed-in testing per site, Bluetooth pairing, home screen design and icons, a smart plug for real power-cut tests.

## Log

### 1. Timezone and clock: done
- The first phone to connect sets the box's timezone (sent by the Wi-Fi setup page and the remote). Later phones (guests, trips) are ignored. `UTC`-style guesses from privacy browsers don't count. `tenfoot timezone ZONE` changes it on purpose.
- Old names browsers still send (`Asia/Calcutta`) map to current ones. Only names tzdata lists are accepted (the reviewer caught that `localtime` would have looped the clock for good).
- The home screen hides the clock until it has synced (no clock battery on a Pi). The updater's 3-6 am window waits for a synced clock too.
- On the test Pi: set through polkit as the TV's user, Chromium switched zone live with no restart, the clock shows and hides correctly. The test Pi is now on America/Chicago.
- Review: RED (6 findings), fixed, then GREEN.

### 2. Whole-box watchdog and memory guard: done
- The service tells systemd it's alive every 20 s, only while its local API answers and the kiosk watchdog keeps going; silent for 2 minutes and systemd restarts it, printing every thread's stack first. Tested on the Pi by freezing it: restarted after 2 min with the stack dump.
- A dead TV page now escalates: restart Chromium, then the compositor, then ask root to reboot. Root says no within an hour of starting (so it can never loop), during an update, or while anyone is logged in (an admin mid-upgrade). The TV user can no longer reboot by itself at all, only ask. Tested on the Pi by freezing the compositor, browser and kiosk loop together: each step fired on time and the box came back.
- earlyoom kills a browser tab before memory runs out (tuned for the Pi's compressed zram swap, where "swap still free" means nothing). A kernel panic now reboots in 10 s. The TV user's service manager restarts if the kernel's own out-of-memory killer takes it (it did, in a test: sound, Spotify and the service were gone until a reboot).
- The hardware watchdog was already on (Raspberry Pi OS arms it), and caught one of my too-harsh memory tests by rebooting the box.
- Review: RED (3 must-fix: a declined reboot was never retried, a failing step reset everything, and the reboot rights reached past logged-in admins), fixed with a root-decided reboot, then GREEN.
- Later verified end to end: with the box up over an hour and nobody logged in, the TV user asked and root rebooted it ("the kiosk is stuck: rebooting"); earlier it correctly said no (too soon after boot, and while I was logged in).

### 3. Health warnings: done
- A background check every minute: weak power supply (the Pi's own under-voltage flag), overheating, storage under 1 GB, a storage card gone read-only (failing), no internet, a network that blocks the browser's secure DNS, and weak Wi-Fi. Brief blips don't count (the internet must fail twice a minute apart, weak Wi-Fi three times running; never on Ethernet or during Wi-Fi setup).
- Each problem is a short card on the TV home screen under the QR code (the worst two), saying what to do, and the full list is in Settings on the phone. It goes away by itself once fixed.
- Low on storage: rebuildable browser caches are cleared before the browser starts (never sign-ins).
- On the test Pi: all good reads as no cards; blocking the secure DNS host showed "Websites won't load on this network" after about 100 s.
- Review: RED (weak Wi-Fi card wouldn't clear after plugging in Ethernet, as it tells you to), fixed, then GREEN.

### Test cards with access built in (your request)
- `tools/test-access.sh RELEASE.img TEST.img` makes a *copy* of a finished image with a way in for testing: the `couch` admin user with this laptop's SSH key, SSH on, and Tailscale with the test Pi's identity (saved privately in `~/.config/tenfoot-test/`, never in git), so a freshly flashed test card is reachable with nobody in the room. The copy says TEST IMAGE on its boot partition.
- Release images from `tools/build-image.sh` contain none of it. I built a fresh release image tonight and checked: only `root` and `tenfoot` (both locked), no keys, no Tailscale. The test copy booted in the Pi emulator with SSH and Tailscale starting.
- I can't reflash the card remotely (the Pi runs from it), so tonight's testing installed onto the running SD system instead. Next time you flash a test card, use a test copy.
- Review: RED twice (a failed run left a half-made copy with access but no label; then my fix could delete the input if given the same file twice), fixed, then GREEN.
- For your list: the release image has the SSH server enabled but nobody can log in (no keys, every password locked). Disabling it outright would be tidier.

### 5. YouTube ad blocking: done, one thing to confirm
- YouTube's TV app no longer gets its ads: the player's ad schedule (all three fields, or it waits for an ad) and the home screen's ad tiles, banner and promo rows are dropped as the app reads them, and video requests say "no ads" so YouTube doesn't hold back the first seconds of video. The same approach as TizenTube and youtube-webos. Never throws: if YouTube changes things, the app still works, just with ads.
- On the test Pi: a video played smoothly with it on; a fresh load of the app stripped 2 ad entries from what YouTube actually sent (on some loads, 0: YouTube varies what it sends, checked against the previous version).
- **Please check signed in:** the guest session never got a pre-roll ad, so I couldn't watch one being removed. Play a few videos signed in and see if any ad shows.
- Review: GREEN first time (optional test gaps filled in).
- Note: YouTube's guest mode asks "who's watching" on every fresh load of the TV app.
