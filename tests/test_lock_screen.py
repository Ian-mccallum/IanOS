"""SPEC-v12 lock screen gates (static checks)."""

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK_JS = (ROOT / "dashboard" / "src" / "lib" / "lock.js").read_text()
LOCK_UI = (ROOT / "dashboard" / "src" / "components" / "LockScreen.jsx").read_text()
APP = (ROOT / "dashboard" / "src" / "App.jsx").read_text()
CSS = (ROOT / "dashboard" / "src" / "styles.css").read_text()


def test_lock_modules_exist_and_gate_app():
    assert "LockScreen" in APP and "isUnlocked" in APP
    assert "attachRelockListeners" in APP
    assert "unlockWithBiometric" in LOCK_JS
    assert "unlockWithPassword" in LOCK_JS
    assert "navigator.credentials.create" in LOCK_JS
    assert "lock-screen" in LOCK_UI and "lock-clock" in LOCK_UI


def test_password_hash_matches_password_contract():
    """Manual unlock is SHA-256('ianos.lock.v1|ianos'), never plaintext compare."""
    expected = hashlib.sha256(b"ianos.lock.v1|ianos").hexdigest()
    m = re.search(r"PASS_HASH\s*=\s*\n?\s*'([0-9a-f]{64})'", LOCK_JS)
    assert m, "PASS_HASH missing from lock.js"
    assert m.group(1) == expected
    # Do not leave the literal password in the unlock library.
    assert "clockwork" not in LOCK_JS


def test_lock_css_uses_safe_area_and_dvh():
    assert "100dvh" in CSS
    assert "env(safe-area-inset-top" in CSS
    assert ".lock-screen" in CSS
    # Shame red stays off the lock surface.
    lock_block = CSS.split("/* ------------------------------------------------ lock screen")[1].split(
        "/* ------------------------------------------------"
    )[0]
    assert "--crit" not in lock_block
