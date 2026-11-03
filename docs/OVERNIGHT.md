# Overnight work log

Autonomous run started 2026-11-03, on the `overnight` branch. Each feature: research how it's usually built, build it, test it (unit tests, and on the SD-card test Pi when it needs real hardware), then a reviewer pass repeated until it's clean. One commit per feature. `main` is untouched; no GitHub releases were published.

## Ranked plan

| # | Feature | Status |
|---|---------|--------|
| 1 | Timezone and clock (the update window was in UTC) | done |
| 2 | Whole-box watchdog and memory guard | in progress |
| 3 | Health warnings: undervoltage, heat, disk, no internet | |
| 4 | Offline and error screens | |
| 5 | YouTube ad blocking | |
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
