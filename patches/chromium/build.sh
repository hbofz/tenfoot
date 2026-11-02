#!/bin/bash
# Cross-builds the kiosk's Chromium on an x86-64 Linux machine (a Colab v5e runtime works: 24
# cores, 47 GB): Raspberry Pi OS's Chromium for arm64, with the Pi's own patches that matter
# on a Pi 4 (V4L2 hardware decoding on Linux, its V4L2 fixes, decoder devices in the GPU sandbox,
# Widevine on arm64, the GLES fallback) and ours (0001: Wayland may put page video on its own
# buffer, so the compositor can show it without the GPU redrawing it; 0002: decoder NV12 frames
# imported through GBM, so they can go on that buffer).
# Not like Raspberry Pi's build, to be quick: Chromium's own toolchain and sysroot instead of
# Debian's, no ThinLTO/PGO, no symbols. Output: $WORK/chromium-tenfoot.tar.zst: unpack it in the repo on the
# Pi (tar -I zstd -xf ... -C ~/tenfoot) and system/kiosk.sh runs chromium/chrome; the system Chromium stays.
#   build.sh            everything, in order (each step skips itself when already done)
set -ex
V=155.0.8059.79
RPT=1~deb13u1+rpt1
# sha256s: RPT_SHA from Raspberry Pi's signed index (see "New Chromium version" in docs/1080p60-project.md),
# UAPI_SHA from Debian's package list; a new V needs a new RPT_SHA
RPT_SHA=ae03c326475d94a84815eff2be831067b13ec6d2b3350313f2e708a296f5f6fe
UAPI_SHA=6183985d8fa4b97d277e8b55b10ad247bd98bc23aa8b531c1f79f05bfbf50997
WORK=${WORK:-/content}
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$WORK/chromium-$V
JOBS=${JOBS:-$(nproc)}

# 1. Source: Google's release tarball ("lite": no test data).
if [ ! -f "$SRC/chrome/VERSION" ]; then
  cd "$WORK"
  wget -q -O src.tar.xz "https://commondatastorage.googleapis.com/chromium-browser-official/chromium-$V-lite.tar.xz"
  tar -I "xz -T0" -xf src.tar.xz && rm src.tar.xz
fi
cd "$SRC"

# 2. Patches: Raspberry Pi's (from their Debian source package), then ours. A stamp file per patch.
if [ ! -d "$WORK/rpt/debian" ]; then
  wget -q -O "$WORK/rpt.tar.xz" "https://archive.raspberrypi.com/debian/pool/main/c/chromium/chromium_$V-$RPT.debian.tar.xz"
  echo "$RPT_SHA  $WORK/rpt.tar.xz" | sha256sum -c --quiet
  mkdir -p "$WORK/rpt" && tar -xf "$WORK/rpt.tar.xz" -C "$WORK/rpt"
fi
for p in rpi/0007-Widevide-Add rpi/enable-AcceleratedVideoDecodeLinux rpi/0019-gl-Disable-FallbackToSWIfGLES3NotSupported \
         rpi/v4l2-stateful-limit-instances rpi/v4l2-do-not-advertise-stateless-codecs rpi/v4l2-sandbox-allow-decoder-devices \
         rpi/v4l2-stateful-count-instances-once rpi/v4l2-stateful-rearm-poll-after-pollerr fixes/arm-logging; do
  echo "$WORK/rpt/debian/patches/$p.patch"
done > "$WORK/patches.list"
ls "$HERE"/rpi-*.patch "$HERE"/0*.patch >> "$WORK/patches.list"  # the Pi's, re-based onto this source; then ours
while read -r p; do
  stamp=".tenfoot-$(basename "$p").applied"
  if [ ! -f "$stamp" ]; then patch -p1 --forward < "$p"; touch "$stamp"; fi
done < "$WORK/patches.list"

# 3. Toolchain: the clang, rust and Debian sysroots this exact source wants (Google's prebuilts).
[ -x third_party/llvm-build/Release+Asserts/bin/clang ] || python3 tools/clang/scripts/update.py
[ -d third_party/rust-toolchain/bin ] || python3 tools/rust/update_rust.py
for arch in arm64 amd64; do python3 build/linux/sysroot_scripts/install-sysroot.py --arch=$arch; done
# The sysroots are Debian bullseye, with kernel 5.10 headers; the V4L2 code wants newer ones (AV1 controls),
# in the arm64 build and in the x64 one that makes V8's snapshot tools. Raspberry Pi builds against trixie,
# so put trixie's kernel headers (linux-libc-dev) into both, before anything is compiled against them.
[ -f "$WORK/uapi.deb" ] || wget -q -O "$WORK/uapi.deb" https://deb.debian.org/debian/pool/main/l/linux/linux-libc-dev_6.12.94-1_all.deb
echo "$UAPI_SHA  $WORK/uapi.deb" | sha256sum -c --quiet
for ROOT in build/linux/debian_bullseye_arm64-sysroot build/linux/debian_bullseye_amd64-sysroot; do
  if [ ! -f $ROOT/.tenfoot-trixie-uapi ]; then
    rm -rf "$WORK/uapi" && dpkg-deb -x "$WORK/uapi.deb" "$WORK/uapi"
    cp -a "$WORK/uapi/usr/include/." $ROOT/usr/include/
    cp -a "$WORK/uapi/usr/lib/linux" $ROOT/usr/lib/  # trixie's <triplet>/asm headers are links into here
    touch $ROOT/.tenfoot-trixie-uapi
  fi
done
if [ ! -x third_party/node/linux/node-linux-x64/bin/node ]; then  # the tarball leaves Node.js out
  NODE=$(grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' third_party/node/update_node_binaries | head -1)
  mkdir -p third_party/node/linux
  wget -q -O- "https://nodejs.org/dist/$NODE/node-$NODE-linux-x64.tar.xz" | tar -xJ -C third_party/node/linux
  mv "third_party/node/linux/node-$NODE-linux-x64" third_party/node/linux/node-linux-x64
fi
GO=third_party/dawn/tools/golang/linux-amd64  # Dawn's code generators are Go (Debian uses its golang); left out too
if [ ! -x $GO/bin/go ]; then
  GOV=$(curl -s "https://go.dev/dl/?mode=json" | python3 -c "import json, sys; print(json.load(sys.stdin)[0]['version'])")
  mkdir -p $GO && wget -q -O- "https://go.dev/dl/$GOV.linux-amd64.tar.gz" | tar -xz -C $GO --strip-components=1
fi
command -v ninja || { apt-get -qq update && apt-get -qq install -y ninja-build; }
LLVM=$PWD/third_party/llvm-build/Release+Asserts/bin
if [ ! -x out/gn ]; then  # with Chromium's clang: the system g++ fails on a warning in gn's own source
  CC=$LLVM/clang CXX=$LLVM/clang++ AR=$LLVM/llvm-ar python3 tools/gn/bootstrap/bootstrap.py --skip-generate-buildfiles -j"$JOBS"
  cp out/Release/gn out/gn
fi

# 4. Configure: Raspberry Pi's GN args (debian/rules) where they matter, minus the slow extras.
mkdir -p out/pi
cat > out/pi/args.gn <<'EOF'
target_os = "linux"
target_cpu = "arm64"
use_siso = false
is_official_build = true
is_debug = false
chrome_pgo_phase = 0
use_thin_lto = false
symbol_level = 0
blink_symbol_level = 0
v8_symbol_level = 0
treat_warnings_as_errors = false
use_v4l2_codec = true
use_vaapi = false
use_av1_hw_decoder = true
proprietary_codecs = true
ffmpeg_branding = "Chrome"
enable_widevine = true
use_pulseaudio = true
rtc_use_pipewire = true
use_qt5 = false
use_qt6 = false
use_dawn = false
skia_use_dawn = false
enable_vr = false
enable_validating_command_decoder = true
enable_hangout_services_extension = true
disable_fieldtrial_testing_config = true
use_unofficial_version_number = false
# Skips building Blink a second time for the snapshot tool; pages start a few ms slower.
use_v8_context_snapshot = false
EOF
out/gn gen out/pi

# 5. Build (the long part), then pack what /usr/lib/chromium ships on the Pi.
# Scripts run straight from their #! line (protoc's Python plugins) get Chromium's bundled Python, not
# the machine's: Colab's own protobuf package otherwise leaks in and breaks them (FrozenInstanceError).
export PATH="$PWD/third_party/cpython3/host/bin:$PATH"
# DevTools' bundle can run before its generated AI "skill" files exist (a missing dependency in 154's
# BUILD.gn: the build fails, depending on timing, with "Cannot read file .../styling.skill.js"), so make them first.
ninja -C out/pi -j"$JOBS" third_party/devtools-frontend/src/front_end/models/ai_assistance/skills:generate_skills || true  # gone in a later version: fine
# -k 0: keep building everything else after a failure, so one pass shows every error there is.
ninja -C out/pi -k 0 -j"$JOBS" chrome chrome_crashpad_handler
# Pack a copy as chromium/ (see the top of this file), symbol tables
# stripped: 475 MB -> 276 MB.
command -v zstd || { apt-get -qq update && apt-get -qq install -y zstd; }
PKG=$WORK/pkg/chromium
rm -rf "$WORK/pkg" && mkdir -p "$PKG"
cd out/pi
FILES="chrome chrome_crashpad_handler *.pak locales icudtl.dat snapshot_blob.bin v8_context_snapshot.bin
       libEGL.so libGLESv2.so libvk_swiftshader.so vk_swiftshader_icd.json libvulkan.so.1"
cp -a $(ls -d $FILES 2>/dev/null) "$PKG"/  # whichever of the optional ones exist
"$LLVM/llvm-strip" --strip-all "$PKG"/chrome "$PKG"/chrome_crashpad_handler "$PKG"/*.so*
tar -C "$WORK/pkg" -I "zstd -T0 -12" -cf "$WORK/chromium-tenfoot.tar.zst" chromium
ls -la "$WORK/chromium-tenfoot.tar.zst"
echo BUILD-DONE
