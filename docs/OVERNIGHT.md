# Overnight work log

Autonomous run started 2026-11-03, on the `overnight` branch. Each feature: research how it's usually built, build it, test it (unit tests, and on the SD-card test Pi when it needs real hardware), then a reviewer pass repeated until it's clean. One commit per feature. `main` is untouched; no GitHub releases were published.

## Ranked plan

| # | Feature | Status |
|---|---------|--------|
| 1 | Timezone and clock (the update window was in UTC) | done |
| 2 | Whole-box watchdog and memory guard | done |
| 3 | Health warnings: undervoltage, heat, disk, no internet | done |
| 4 | Offline and error screens | done |
| 5 | YouTube ad blocking | done (a real pre-roll not seen yet) |
| 6 | OS security updates (Widevine included) | done (kernel not yet) |
| 7 | Phone Settings page | done |
| 8 | Fewer SD card writes, power-cut survival | done |
| 9 | Idle handling inside apps (screensaver, TV standby) | done |
| 10 | "Send logs" bundle | done |
| 11 | Factory reset and sign-out | done |
| 12 | Display adaptivity (720p and 4K TVs) | done |
| 13 | Recently used apps first | decided against; a fix instead |

Needs Hamzah: Chromium rebuild pipeline (CI money/owner), signed-in testing per site, Bluetooth pairing, home screen design and icons, a smart plug for real power-cut tests.

## Log

### 1. Timezone and clock: done
- The first phone to connect sets the box's timezone (sent by the Wi-Fi setup page and the remote). Later phones (guests, trips) are ignored. `UTC`-style guesses from privacy browsers don't count. `tenfoot timezone ZONE` changes it on purpose.
- Old names browsers still send (`Asia/Calcutta`) map to current ones. Only names tzdata lists are accepted (the reviewer caught that `localtime` would have looped the clock for good).
- The home screen hides the clock until it has synced (no clock battery on a Pi). The updater's 3-6 am window waits for a synced clock too.
- On the test Pi: set through polkit as the TV's user, Chromium switched zone live with no restart, the clock shows and hides correctly.
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

### 4. Offline and error screens: done
- When a site can't load (no internet, a name that doesn't exist, a host that refuses), the TV shows its own page instead of Chromium's, which a remote can't work: what's wrong in plain words, and Try again / Go back / Home, driven by the arrows and OK. It keeps retrying by itself (5 s, 10 s, ... up to a minute, one try at a time) and loads the site once it answers.
- It's served at the site's own address, so the remote's Back works normally.
- On the test Pi: a non-existent domain showed it with Try again focused; real remote presses moved between the buttons, went Home, and went Back; a site blocked then unblocked came back by itself within 5 s.
- Not covered: a dead server whose connection times out, and certificate errors, still get Chromium's page (Chromium lumps those together; noted in the code).
- Review: RED three times (a swallowed Back key that I found on the Pi myself; overlapping retries; a reload loop that could keep a slow site from ever loading), fixed, then GREEN.

### 6. OS security updates: done (kernel and firmware not yet)
- Raspberry Pi OS Lite installs no updates by itself; nothing on these boxes was ever getting security fixes. Now, once a week (Sunday night, auto mode), the updater takes Debian's security and point-release updates of Debian's own packages, plus Widevine. Never Raspberry Pi's other builds: the 1080p60 browser and compositor need exactly the cage, wlroots and Mesa they were built against, and those are now held.
- The old packages are saved first; if the box isn't healthy after the reboot they go back. A download that fails (Wi-Fi down at 4 am) just waits a week; a version is only given up on after failing twice; a rollback cut short by a power cut finishes on the next boot.
- On the test Pi: the first real run updated 15 packages (libnss3, curl, expat, ca-certificates, tzdata and more); with the TV service stopped on purpose, all 15 went back to their exact old versions; run again normally, they were kept. The patched video path was untouched.
- Not yet: kernel and firmware (needs the Pi's tryboot so a bad kernel falls back by itself). A known risk it can't undo: a power cut at the exact moment a system update rebuilds the boot files.
- Review: RED (a 4 am Wi-Fi drop would have black-listed every pending security fix), fixed, then GREEN.

### 7. Phone Settings: done
- New "This TV" section in Settings on the phone: rename the TV (Spotify and AirPlay follow), pick the weather's town from a search (which sets the clock's timezone too), °C or °F, and updates automatic or ask first. Hidden from the guest QR link, which can't read or change any of it.
- Saved into config.toml without losing its comments, checked before it's written.
- On the test Pi, through the running service: everything landed (config, home screen, Spotify's name, the system clock); guest and bad names refused. Put back afterwards.
- Review: GREEN, with small fixes taken (a name starting with "-" would have crashed AirPlay).

### 8. SD card and power cuts: done
- Measured on the test Pi first: about 5 MB written to the card every 4 minutes with the browser open (mostly the browser's profile and the system log), so roughly 75 MB an hour. Even always-on, that's far below what an SD card tolerates for years: wear isn't the real risk, power cuts are.
- Raspberry Pi OS already does the important things (no access-time writes, a filesystem repair at boot, swap compressed in RAM); the image build now refuses a base image that stops doing them. Its swap does keep a file on the card (/var/swap) for pages idle for hours, written at most once a day: left as it is.
- Turned off browser history (written on every page visit, read by nothing), and the "restore pages?" bubble after a power cut (a remote can't close it).
- Power-cut test, without a smart plug: 5 forced instant resets (sysrq-b) during YouTube. Every time it came back by itself in under 1.5 minutes, 0 filesystem errors, browser and service up, no dialogs. (A forced reset keeps the card powered, so it's not quite a real cut: a smart plug would test that.)
- Not done on purpose: a read-only system (it would lose saved Wi-Fi, logins and updates), the browser profile in RAM (loses logins on a cut).
- Review: GREEN.

### 9. Idle: screensaver over apps, and TV standby: done
- Nobody at the remote for 10 minutes and nothing playing (a paused show, a menu): the picture dims, so an OLED doesn't burn in. The first press only wakes it. The home screen keeps its own photo screensaver (same setting).
- Nobody at the remote for 4 hours, even mid-show (YouTube autoplaying all night): a one-minute warning on screen, then it pauses, dims and turns the TV off over HDMI-CEC. Not while Spotify plays, and not if the TV is showing another input.
- "Playing" is the page's video or the browser's sound actually reaching the speakers (that sees players inside frames, like Crunchyroll's, and DRM video). A short gap between episodes doesn't count as quiet. The phone checking in every few seconds doesn't count as someone there.
- Settings: `screensaver_minutes` and `standby_hours` in config.toml (0 = never).
- On the test Pi with short timers: dimmed on a page after ~45 s, a phone press woke it without doing anything else; the warning, then pause and dim. **Your TV ignores the CEC "off" command** (many need "turn off with connected devices" switched on in their own settings), so it stays on but dark and still. Worth checking that TV setting.
- Bugs found on the way: the dim script had a syntax error the browser reported without raising, so the service thought it had dimmed (now every overlay script is compile-tested); a first standby version un-dimmed itself right away.
- Review: RED (4: dim state drifting after a page change, dimming in the gap between episodes, video in frames unseen, the cursor path not waking), fixed, then GREEN.

### 10. Diagnostic report: done
- "Get a diagnostic report" in the phone's Settings (not for the guest link) downloads one text file to send whoever helps with the TV: versions, health, updates, settings (an allowlist; never the name or location), screen modes, network type and signal, the TV over HDMI-CEC, and the service's recent log. Nothing is uploaded by the box.
- Everything personal is taken out of the whole file: link tokens, passwords, names, the hostname, addresses, emails, URL paths (searches), and what was listened to on Spotify (track and episode titles from its log). If the secrets can't be read, there's no report rather than an unredacted one; a section that fails says so and the rest still comes.
- On the test Pi: a 22 KB report with all 11 sections; the guest link gets nothing; no tokens or tailnet names inside.
- Review: RED (a hung section sank the whole report; Spotify listening history went into it), fixed, then GREEN.

### 11. Sign out of everything, and reset: done
- In the phone's Settings: "Sign out of everything" (every app's login in the browser, and Spotify's accounts; Wi-Fi and settings stay) and "Reset this TV" (that, plus new links so every phone's stops working, the TV's personal settings back to defaults, its timezone, and saved Wi-Fi forgotten so the setup screen comes up). `tenfoot reset [--signout] [--keep-wifi]` does it from SSH.
- Both need a 4-digit code shown on the TV and typed on the phone, so nobody can do it without seeing the screen. The code is only ever shown on the TV's own home screen (a website on screen could read it otherwise), and wrong codes add up across tries, restarts and asks: every third locks it out for longer (1, 2, 4... minutes), counted on disk before any guess is checked.
- A reset cut short by a power cut finishes on the next start.
- On the test Pi: sign-out through the phone cleared a 182 MB browser profile (Widevine kept, DRM still working); a reset (keeping Wi-Fi) changed the links and QR code and cleared the personal settings; the code showed on the home screen even when asked from a website; three wrong codes locked it.
- Review: RED five times, all about guessing the code without seeing the TV (asking again for a fresh 3 tries; a website reading the code; a rename restarting the service to forget the count; a full disk not counting). Each closed, then GREEN.

### 12. Any TV's display: done
- The box used to insist on exactly "1920x1080 at 60 Hz". Many screens list 59.94 Hz instead (which the tool prints as 59.939999 and only matches when spelled exactly), 720p TVs have no 1080p at all, and some European TVs only do 50 Hz: on those it failed every 30 seconds, and a 4K TV without a 60 Hz 1080p stayed at choppy 4K 30 Hz.
- Now `display_mode = "auto"` (the new default) picks from what the TV lists: 1080p at the best refresh up to 60, else the TV's own preferred mode, else the largest the Pi draws smoothly. An explicit mode is still honoured if the TV lists it.
- On the test Pi's 4K TV: 31 modes listed, auto picks 1080p60; switched to 720p by hand, it was put back within 30 seconds; the kiosk starting fresh came up in 1080p60.
- Review: GREEN (small fixes taken: a malformed setting is caught at load instead of leaving the TV asleep after every wake).
