#!/usr/bin/env python3
"""Make a Tenfoot release that boxes update themselves to (system/tenfoot-update).

  tools/release.py keygen                       once: make the signing key, print the public half for tenfoot-update
  tools/release.py build OUT_DIR [--notes TEXT] [--base URL]
                                                the release for VERSION in OUT_DIR: tarball, update.json, its signature
  tools/release.py publish [--notes TEXT]       build, then put it on GitHub as release vVERSION (needs gh)

The private key lives in ~/.config/tenfoot-release/signing.key (mode 600), never in git. Back it up: without it, boxes
already out there can't be updated (they only trust this key). Bump VERSION and commit before releasing; the tarball is
the committed HEAD, so it has to be a clean tree.
"""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = Path.home() / ".config" / "tenfoot-release" / "signing.key"
REPO = "hbofz/tenfoot"


def key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(KEY.read_text()))


def public_b64(k):
    from cryptography.hazmat.primitives import serialization
    raw = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def keygen():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if KEY.exists():
        sys.exit(f"{KEY} already exists; it's the key every box trusts, so it's never replaced here")
    k = Ed25519PrivateKey.generate()
    raw = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    KEY.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(KEY, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(base64.b64encode(raw).decode() + "\n")
    print(f"Wrote {KEY}. Back it up somewhere safe. Public key, for PUBLIC_KEY in system/tenfoot-update:")
    print(public_b64(k))


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True).stdout


def build(out, notes, base=None):
    version = (ROOT / "VERSION").read_text().strip()
    if git("status", "--porcelain").strip():
        sys.exit("Commit everything first: the release is the committed HEAD")
    k = key()
    trusted = next(line.split('"')[1] for line in (ROOT / "system" / "tenfoot-update").read_text().splitlines()
                   if line.startswith("PUBLIC_KEY = "))
    if public_b64(k) != trusted:
        sys.exit("This signing key isn't the one system/tenfoot-update trusts")
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], cwd=ROOT, check=True)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    name = f"tenfoot-{version}.tar.gz"
    git("archive", "--format=tar.gz", "-o", str(out / name), "HEAD")
    base = base or f"https://github.com/{REPO}/releases/download/v{version}/"
    manifest = json.dumps({"version": version, "notes": notes, "url": base + name,
                           "sha256": hashlib.sha256((out / name).read_bytes()).hexdigest()}, indent=1).encode()
    (out / "update.json").write_bytes(manifest)
    (out / "update.json.sig").write_bytes(k.sign(manifest))
    print(f"Built {version} in {out}")
    return version, out


def publish(notes):
    with tempfile.TemporaryDirectory() as d:
        version, out = build(d, notes)
        files = [str(out / f) for f in (f"tenfoot-{version}.tar.gz", "update.json", "update.json.sig")]
        subprocess.run(["gh", "release", "create", f"v{version}", *files, "--repo", REPO, "--title", version,
                        "--notes", notes or version, "--target", git("rev-parse", "HEAD").strip()], check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen")
    b = sub.add_parser("build")
    b.add_argument("out")
    b.add_argument("--notes", default="")
    b.add_argument("--base", help="where the tarball will be served from (default: the GitHub release)")
    pub = sub.add_parser("publish")
    pub.add_argument("--notes", default="")
    a = p.parse_args()
    if a.cmd == "keygen":
        keygen()
    elif a.cmd == "build":
        build(a.out, a.notes, a.base)
    else:
        publish(a.notes)


if __name__ == "__main__":
    main()
