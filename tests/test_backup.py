"""SPEC-v16: the backup. These test the laws, not restic.

Everything runs against a throwaway LOCAL restic repo and a fake IANOS_ROOT,
so no network, no B2, no creds. Skipped wholesale when restic is not installed
(CI or a fresh machine); the suite must not fail for a missing optional tool.
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RESTIC = shutil.which("restic") or (
    "/opt/homebrew/bin/restic" if Path("/opt/homebrew/bin/restic").exists() else None
)
pytestmark = pytest.mark.skipif(RESTIC is None, reason="restic not installed")

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKUP_SH = REPO_ROOT / "scripts" / "backup.sh"


@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    """A miniature ianOS tree: real-schema WAL DB, journal media, leads CSV,
    .env. The real schema matters: verify counts journal_entries/memos, and
    the failure-memo path runs core.db migrations against this file."""
    from core import db as core_db

    root = tmp_path / "ianos"
    (root / "data" / "journal" / "2026" / "08").mkdir(parents=True)
    (root / "leads").mkdir()
    (root / ".venv" / "bin").mkdir(parents=True)
    # The failure-memo path shells out to .venv/bin/python; point it at ours.
    os.symlink(sys.executable, root / ".venv" / "bin" / "python")

    monkeypatch.setattr(core_db, "DB_PATH", root / "data" / "ianos.db")
    conn = core_db.connect()
    conn.execute("INSERT INTO leads (business_name) VALUES ('Torres Plumbing')")
    conn.commit()
    conn.close()

    (root / "data" / "journal" / "2026" / "08" / "1-abcd.jpg").write_bytes(b"\xff\xd8fakejpeg")
    (root / "leads" / "enriched.csv").write_text("Business Name\nTorres Plumbing\n")
    (root / ".env").write_text("IANOS_API_TOKEN=secret123\n")
    return root


def run_backup(root, repo, password="test-password", args=(), extra_env=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("RESTIC_", "B2_"))}
    env.update({
        "IANOS_ROOT": str(root),
        "RESTIC_REPOSITORY": str(repo),
        "RESTIC_PASSWORD": password,
        "RESTIC_CACHE_DIR": str(root.parent / "restic-cache"),
    })
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(BACKUP_SH), *args],
        env=env, capture_output=True, text=True, timeout=120,
    )


def restic_env(repo, root, password="test-password"):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("RESTIC_", "B2_"))}
    env.update({"RESTIC_REPOSITORY": str(repo), "RESTIC_PASSWORD": password,
                "RESTIC_CACHE_DIR": str(root.parent / "restic-cache")})
    return env


def snapshots(repo, root, password="test-password"):
    r = subprocess.run([RESTIC, "snapshots", "--json"],
                       env=restic_env(repo, root, password),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ------------------------------------------------------------------ law 8

def test_unconfigured_is_exit_2_with_instructions(fake_root):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("RESTIC_", "B2_"))}
    env["IANOS_ROOT"] = str(fake_root)  # its .env has no RESTIC_* keys
    r = subprocess.run(["bash", str(BACKUP_SH)], env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 2
    assert "RESTIC_REPOSITORY" in r.stderr


# ------------------------------------------------------- laws 1 + idempotence

def test_two_runs_two_snapshots_staging_cleaned(fake_root, tmp_path):
    repo = tmp_path / "repo"
    assert run_backup(fake_root, repo).returncode == 0
    assert run_backup(fake_root, repo).returncode == 0
    snaps = snapshots(repo, fake_root)
    assert len(snaps) == 2
    # Staging must never linger: it holds an unencrypted DB copy.
    assert not (fake_root / "data" / "backup" / "staging").exists()
    assert (fake_root / "data" / "backup" / "last_success").exists()


def test_wal_row_survives_backup_and_restore(fake_root, tmp_path):
    """The reason VACUUM INTO is law: a row committed on a held-open WAL
    connection (nothing checkpointed into the main file yet) must still be in
    the restored DB. A raw file copy would lose it."""
    repo = tmp_path / "repo"
    conn = sqlite3.connect(fake_root / "data" / "ianos.db")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("INSERT INTO leads (business_name) VALUES ('Aurora Locksmith')")
    conn.commit()                      # committed, but connection stays open

    assert run_backup(fake_root, repo).returncode == 0
    conn.close()

    target = tmp_path / "out"
    r = subprocess.run([RESTIC, "restore", "latest", "--target", str(target)],
                       env=restic_env(repo, fake_root), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    restored_db = next(target.rglob("ianos.db"))
    rows = sqlite3.connect(restored_db).execute(
        "SELECT business_name FROM leads ORDER BY id").fetchall()
    assert [x[0] for x in rows] == ["Torres Plumbing", "Aurora Locksmith"]

    # Journal media and .env restore byte-identical.
    restored_jpg = next(target.rglob("1-abcd.jpg"))
    assert restored_jpg.read_bytes() == b"\xff\xd8fakejpeg"
    restored_env = next(target.rglob(".env"))
    assert restored_env.read_bytes() == (fake_root / ".env").read_bytes()
    # The WAL sidecar itself is never backed up (law 1).
    assert not list(target.rglob("ianos.db-wal"))


# ------------------------------------------------------------------ law 4

def test_failure_writes_system_memo(fake_root, tmp_path):
    repo = tmp_path / "repo"
    assert run_backup(fake_root, repo, password="right").returncode == 0
    r = run_backup(fake_root, repo, password="wrong")
    assert r.returncode != 0

    conn = sqlite3.connect(fake_root / "data" / "ianos.db")
    memos = conn.execute(
        "SELECT from_role, topic, body FROM memos").fetchall()
    conn.close()
    assert len(memos) == 1
    role, topic, body = memos[0]
    assert role == "system" and topic == "backup"
    assert "make backup" in body


# ------------------------------------------------------------------ verify

def test_verify_passes_on_good_repo(fake_root, tmp_path):
    repo = tmp_path / "repo"
    assert run_backup(fake_root, repo).returncode == 0
    r = run_backup(fake_root, repo, args=("verify",))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "integrity_check: ok" in r.stdout
