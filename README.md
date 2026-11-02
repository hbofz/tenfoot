# Tenfoot

Turn a Raspberry Pi 4 into a TV box you can use from the couch. It boots straight into a full-screen home screen, and your streaming sites work with arrow keys instead of a mouse.

> **Status: early.** Developed on one Pi on one TV. The installer hasn't been run on a clean Pi OS yet.

- **Streaming sites, remote-friendly.** YouTube's TV app, Netflix, Disney+, HBO Max, Crunchyroll, Paramount+ and Shahid. Arrows move a highlight, OK picks, Back goes back, and an on-screen keyboard handles sign-in. Any other website works too, with a cursor for what the highlight can't reach.
- **Your phone is the remote.** Scan the QR code on the TV to get a touchpad, keys, typing and volume, with no app to install.
- **Your TV's remote works too,** if your TV forwards it over HDMI-CEC. Bluetooth and USB remotes work as well.
- **Spotify Connect,** with a Now Playing screen and synced lyrics (a Spotify Premium account is needed).
- **AirPlay,** optional, through UxPlay.
- **Optional 1080p60** with the GPU idle, with [five small patches](docs/1080p60.md) to Chromium and wlroots.

You need your own subscriptions: Tenfoot plays what your accounts already can, through the sites' own web players. It doesn't bypass DRM, and Widevine comes from Raspberry Pi's own package.

## Install

On a Raspberry Pi 4 running 64-bit Raspberry Pi OS Trixie:

    git clone https://github.com/hbofz/tenfoot ~/tenfoot
    ~/tenfoot/install.sh          # add --airplay for the AirPlay receiver
    sudo reboot

Undo it with `~/tenfoot/uninstall.sh`.

## Settings

Edit `~/.config/tenfoot/config.toml`, then `systemctl --user restart tenfoot` (after changing `name` or `spotify`, run `install.sh` again). Every setting is explained in [config.example.toml](config.example.toml). To change the apps, copy `apps.json` to `~/.config/tenfoot/apps.json` and edit it.

## The phone remote

By default phones connect over your home network, using a secret link. The link, and the key that unlocks a saved Spotify account, travel as plain HTTP, so anyone already on your network could read them. On a network you don't trust, use `remote_mode = "tailscale"`.

    python3 -m tenfoot links          # list links (run from ~/tenfoot)
    python3 -m tenfoot link sam       # make a personal link
    python3 -m tenfoot revoke sam     # it stops working at once
    python3 -m tenfoot revoke house   # new shared secret: the shared link and the TV's QR code both change

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
| `patches/` | The optional Chromium and wlroots builds |

## Tests

    pip install websocket-client qrcode cryptography numpy evdev playwright && playwright install chromium
    python3 -m unittest discover -s tests -p 'test_*.py'
    node tests/nav.test.js && node tests/youtube.test.js
    python3 tests/browser/test_sites.py
    python3 tests/browser/test_keyboard.py
    python3 tests/browser/test_service.py   # the real service against a real Chromium; visits YouTube and Shahid

## Credits and licence

MIT, see [LICENSE](LICENSE). Inter is under the OFL (`web/home/fonts/OFL-Inter.txt`). Wallpapers are downloaded from Wikimedia Commons at install, not stored here; each photographer and licence ends up in `web/home/wallpapers/CREDITS.txt`, and the screen credits the photographer. Lyrics come from [LRCLIB](https://lrclib.net), weather from [Open-Meteo](https://open-meteo.com), sponsor segments from [SponsorBlock](https://sponsor.ajay.app), and Spotify Connect from [go-librespot](https://github.com/devgianlu/go-librespot). Tenfoot isn't affiliated with any of the services it opens; their names are trademarks of their owners.
