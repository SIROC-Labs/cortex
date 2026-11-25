#!/usr/bin/env python3
#
# notify.py — a banner from Conductor.app, whose click opens a page. The app is
# built here from Conductor.swift the first time, and again when the source
# changes, into ~/Applications. Without a Swift compiler, only the sound plays.
#
#   notify.py <title> <text> <url> <sound>

import fcntl
import hashlib
import os
import plistlib
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "Conductor.swift")
APP = os.path.expanduser("~/Applications/Conductor.app")
BUNDLE_ID = "com.siroc.conductor"
SOUNDS = ("Glass", "Basso", "Hero")


def source_hash():
    with open(SOURCE, "rb") as f:
        return hashlib.sha1(f.read() + " ".join(SOUNDS).encode()).hexdigest()


def stamp_path(app):
    return os.path.join(app, "Contents", "Resources", "source.sha1")


def current(app, digest):
    try:
        with open(stamp_path(app)) as f:
            return f.read().strip() == digest
    except OSError:
        return False


def build(app=APP):
    """Build and sign Conductor.app from its source, unless it is current. Returns
    whether the app is there."""
    digest = source_hash()
    if current(app, digest):
        return True
    swiftc = shutil.which("swiftc") or "/usr/bin/swiftc"
    os.makedirs(os.path.dirname(app), exist_ok=True)
    with open(app + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if current(app, digest):
            return True
        work = app + ".new"
        shutil.rmtree(work, ignore_errors=True)
        macos, resources = os.path.join(work, "Contents", "MacOS"), os.path.join(work, "Contents", "Resources")
        os.makedirs(macos)
        os.makedirs(resources)
        if subprocess.run([swiftc, "-O", "-o", os.path.join(macos, "Conductor"), SOURCE],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
            shutil.rmtree(work, ignore_errors=True)
            return False
        for sound in SOUNDS:
            shutil.copyfile("/System/Library/Sounds/%s.aiff" % sound, os.path.join(resources, sound + ".aiff"))
        with open(os.path.join(work, "Contents", "Info.plist"), "wb") as f:
            plistlib.dump({"CFBundleIdentifier": BUNDLE_ID, "CFBundleName": "Conductor",
                           "CFBundleDisplayName": "Conductor", "CFBundleExecutable": "Conductor",
                           "CFBundlePackageType": "APPL", "CFBundleShortVersionString": "1.0",
                           "CFBundleVersion": "1", "LSUIElement": True,
                           "LSMinimumSystemVersion": "13.0"}, f)
        with open(stamp_path(work), "w") as f:
            f.write(digest)
        subprocess.run(["codesign", "--force", "--sign", "-", work],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(app, ignore_errors=True)
        os.rename(work, app)
    return True


def main(argv):
    title, text, url, sound = (argv + ["", "", "", ""])[:4]
    if build():
        subprocess.run(["open", "-n", "-g", "-a", APP, "--args", "notify", title, text, url, sound])
    else:
        subprocess.run(["afplay", "/System/Library/Sounds/%s.aiff" % (sound or "Glass")])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
