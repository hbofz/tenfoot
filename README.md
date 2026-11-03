# Tenfoot

Turn a Raspberry Pi 4 into a TV box you can use from the couch. It boots straight into a full-screen home screen, and your streaming sites work with arrow keys instead of a mouse.

> **Status: early.** Developed on one Pi on one TV. A fresh image has been set up from a phone and run on a real TV, but streaming with a real account hasn't been tried on it yet.

- **Streaming sites, remote-friendly.** YouTube's TV app, Netflix, Disney+, HBO Max, Crunchyroll, Paramount+ and Shahid. Arrows move a highlight, OK picks, Back goes back, and an on-screen keyboard handles sign-in. Any other website works too, with a cursor for what the highlight can't reach.
- **Your phone is the remote.** Scan the QR code on the TV to get a touchpad, keys, typing and volume, with no app to install.
- **Your TV's remote works too,** if your TV forwards it over HDMI-CEC. Bluetooth and USB remotes work as well.
- **Spotify Connect,** with a Now Playing screen and synced lyrics (a Spotify Premium account is needed).
- **AirPlay,** optional, through UxPlay.
- **1080p60 with the GPU idle** in the ready-made image, using [five small patches](docs/1080p60.md) to Chromium and wlroots. A manual install adds them separately.

You need your own subscriptions: Tenfoot plays what your accounts already can, through the sites' own web players. It doesn't bypass DRM, and Widevine comes from Raspberry Pi's own package.

## Install

1. With [Raspberry Pi Imager](https://www.raspberrypi.com/software/), put 64-bit Raspberry Pi OS (Trixie; Lite is enough) on an SD card or USB drive for a Raspberry Pi 4. In its settings, set your Wi-Fi with its country, and turn on SSH.
2. Plug the Pi into the TV and power it on, then connect to it over SSH from a computer and run:

       sudo apt-get install -y git
       git clone https://github.com/hbofz/tenfoot ~/tenfoot
       ~/tenfoot/install.sh          # add --airplay for the AirPlay receiver
       sudo reboot

It boots into the home screen. One wallpaper comes with the install; the rest download in the background and can take hours, and the home screen uses what it has so far.

To update, `git pull` in your clone and run `install.sh` again. Undo it with `uninstall.sh`; add `--purge` to delete the TV's user, its logins and settings too.

## Settings

The TV runs as its own `tenfoot` user, which has no sudo. Edit its settings with `sudo -u tenfoot nano /home/tenfoot/.config/tenfoot/config.toml`, then run `tenfoot restart` (after changing `name` or `spotify`, run `install.sh` again). Every setting is explained in [config.example.toml](config.example.toml). To change the apps, put your own copy of `apps.json` in that same folder.

## The phone remote

By default phones connect over your home network, using a secret link. The link, and the key that unlocks a saved Spotify account, travel as plain HTTP, so anyone already on your network could read them. On a network you don't trust, use `remote_mode = "tailscale"`.

    tenfoot links          # list links
    tenfoot link sam       # make a personal link
    tenfoot revoke sam     # it stops working at once
    tenfoot revoke house   # new shared secret: the shared link and the TV's QR code both change

Anyone with a link can control the TV. They can't reach this box's own services or addresses on your network from the "open on TV" box.

## How it fits together

    cage (compositor) -> Chromium (kiosk, DevTools on localhost)
                            ^ DevTools: per-site identity and blocking, inject/*.js, navigation
    tenfoot service ------- +
        ^ HTTP + WebSocket under a secret link     -> uinput: virtual keyboard and mouse
    your phone                                     -> HDMI-CEC: TV power and remote keys
                                                   -> go-librespot: Spotify

| Path | What's there |
| --- | --- |
| `tenfoot/` | The service, Python standard library plus a few Debian packages |
| `inject/` | Scripts put into every page: the highlight, keyboard, per-site rules (`SITES` in `sites.js`) |
| `web/` | The home screen, Spotify screen and phone remote |
| `system/` | Kiosk launcher, browser policy, service files |
| `patches/` | The Chromium and wlroots builds for 1080p60 |

## Tests

    pip install websocket-client qrcode cryptography numpy evdev playwright && playwright install chromium
    python3 -m unittest discover -s tests -p 'test_*.py'
    node tests/nav.test.js && node tests/youtube.test.js
    python3 tests/browser/test_sites.py
    python3 tests/browser/test_keyboard.py
    python3 tests/browser/test_service.py   # the real service against a real Chromium; visits YouTube and Shahid
    sudo -u tenfoot -H sh -c 'cd ~/tenfoot && python3 tests/box_check.py'   # on an installed box: the running service, browser and input

## Credits and licence

MIT, see [LICENSE](LICENSE). Inter is under the OFL (`web/home/fonts/OFL-Inter.txt`). Wallpapers are downloaded from Wikimedia Commons at install, not stored here; each photographer and licence ends up in `web/home/wallpapers/CREDITS.txt`, and the screen credits the photographer. Lyrics come from [LRCLIB](https://lrclib.net), weather from [Open-Meteo](https://open-meteo.com), sponsor segments from [SponsorBlock](https://sponsor.ajay.app), and Spotify Connect from [go-librespot](https://github.com/devgianlu/go-librespot). Tenfoot isn't affiliated with any of the services it opens; their names are trademarks of their owners.
