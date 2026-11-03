#!/bin/sh
# Runs inside cage on tty1: one full-screen Chromium, its own profile, on the home screen. After a power cut, no
# "restore pages?" bubble (a remote can't close it), and no history kept (written on every visit, and nothing reads it).
# No back/forward cache: leaving an app really closes it (a Pi can't keep YouTube around).
# The disk cache lives in RAM (/tmp is tmpfs): faster, and no wear on the drive.
# Extra browser flags go in ~/.config/tenfoot/kiosk.env, one quoted argument each:
#   set -- '--host-resolver-rules=MAP media.lan 192.168.1.20'
ROOT=$(cd "$(dirname "$0")/.." && pwd)
[ -f "$HOME/.config/tenfoot/kiosk.env" ] && . "$HOME/.config/tenfoot/kiosk.env"
# TVs can advertise 4K: 4x the pixels at half the frames turns every animation choppy.
OUT=$(wlr-randr 2>/dev/null | awk '/^[A-Z]/ { print $1; exit }')
[ -n "$OUT" ] && wlr-randr --output "$OUT" --mode "$(cat "$ROOT/web/home/run/display-mode" 2>/dev/null || echo 1920x1080@60)" 2>/dev/null
# Sound, once: the TV over HDMI at full volume, so the remote's volume is what you hear. Tried each start until a TV is there.
AUDIO_DONE=$HOME/.config/tenfoot/audio-set
if [ ! -e "$AUDIO_DONE" ]; then
  HDMI=$(wpctl status 2>/dev/null | sed -n "/Sinks:/,/Sources:/p" | grep HDMI | grep -o "[0-9]\+\." | head -1 | tr -d .)
  if [ -n "$HDMI" ]; then wpctl set-default "$HDMI"; wpctl set-volume "$HDMI" 1.0; wpctl set-mute "$HDMI" 0; touch "$AUDIO_DONE"; fi
fi
# Low on space (under 1 GB: tenfoot/health.py warns at the same point): clear what Chromium rebuilds by itself, never
# sign-ins (Cookies, Local Storage, IndexedDB). Only here, before it starts: it holds these files open while it runs.
P=$HOME/.config/tenfoot/chromium
if [ "$(df --output=avail -k "$P" 2>/dev/null | tail -1)" -lt 1048576 ] 2>/dev/null; then
  rm -rf "$P/Default/Service Worker/CacheStorage" "$P/Default/Service Worker/ScriptCache" "$P/Default/Code Cache" \
    "$P/Default/GPUCache" "$P/GPUCache" "$P/GrShaderCache" "$P/GraphiteDawnCache" "$P/ShaderCache" "$P/component_crx_cache"
fi
# The 1080p60 build (docs/1080p60.md) when it's there; otherwise the system Chromium.
CHROMIUM=${TENFOOT_CHROMIUM:-$ROOT/chromium/chrome}
if [ -x "$CHROMIUM" ]; then
  export FONTCONFIG_FILE=/etc/fonts/fonts.conf  # its bundled fontconfig looks for this elsewhere
  # No GPU memory buffers for software-decoded video (VP9, and DRM video Widevine decodes): Chromium
  # copies those frames into buffers marked fit for an overlay, the Pi can't show them as one, and
  # the picture was black with sound. Hardware-decoded video doesn't use these buffers.
  EXTRA="--use-angle=gles --enable-gpu-rasterization --disable-dev-shm-usage --enable-features=WaylandOverlayDelegation --disable-gpu-memory-buffer-video-frames"
else
  CHROMIUM=chromium EXTRA=
fi
exec "$CHROMIUM" \
  --kiosk \
  --ozone-platform=wayland \
  --user-data-dir="$HOME/.config/tenfoot/chromium" \
  --no-first-run \
  --noerrdialogs \
  --disable-infobars \
  --hide-crash-restore-bubble \
  --password-store=basic \
  --check-for-update-interval=31536000 \
  --remote-debugging-port=9222 \
  --disable-features=BackForwardCache,Translate \
  --disk-cache-dir=/tmp/tenfoot-chromium-cache \
  --disk-cache-size=67108864 \
  $EXTRA \
  "$@" \
  "file://$ROOT/web/home/home.html"
