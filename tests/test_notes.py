"""SPEC-v10 §5. Notes: Ian's, agent-readable, agent-unwritable."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db          # noqa: E402
from core import notes as note_visibility  # noqa: E402
from api import main         # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.connect().close()
    return TestClient(main.app)


# ------------------------------------------------------------------- the title

def test_the_first_line_becomes_the_title():
    """iPhone Notes behaviour, and the reason there is no title field to fill in."""
    assert db.note_title_from("Dorm packing\nCommand strips") == "Dorm packing"
    assert db.note_title_from("\n\n  Leading blanks  \nrest") == "Leading blanks"
    assert db.note_title_from("# Markdown heading") == "Markdown heading"
    assert db.note_title_from("") == ""
    assert db.note_title_from("   \n  ") == ""
    assert len(db.note_title_from("x" * 500)) == db.NOTE_TITLE_MAX


def test_the_title_is_stored_not_recomputed(conn):
    """Rendering a list must never parse a body."""
    n = db.create_note(conn, "First line\nsecond")
    assert n["title"] == "First line"
    row = conn.execute("SELECT title FROM notes WHERE id = ?", (n["id"],)).fetchone()
    assert row["title"] == "First line"
    n = db.update_note(conn, n["id"], body="Renamed\nsecond")
    assert n["title"] == "Renamed"


# ------------------------------------------------------------- partial updates

def test_pinning_does_not_clobber_the_body(client):
    """Autosave PATCHes the body alone and a pin PATCHes the pin alone; if the
    endpoint filled in the blanks, one would erase the other."""
    n = client.post("/api/notes", json={"body": "keep me\nplease"}).json()
    pinned = client.patch(f"/api/notes/{n['id']}", json={"pinned": True}).json()
    assert pinned["pinned"] == 1
    assert pinned["body"] == "keep me\nplease"
    assert pinned["title"] == "keep me"

    edited = client.patch(f"/api/notes/{n['id']}", json={"body": "new text"}).json()
    assert edited["pinned"] == 1, "editing the body dropped the pin"


# --------------------------------------------------------------- delete + undo

def test_delete_is_soft_so_undo_restores_the_same_note(client):
    n = client.post("/api/notes", json={"body": "oops"}).json()
    client.delete(f"/api/notes/{n['id']}")
    assert client.get("/api/notes").json()["notes"] == []
    assert [x["id"] for x in client.get("/api/notes?deleted=true").json()["notes"]] == [n["id"]]

    restored = client.post(f"/api/notes/{n['id']}/restore").json()
    assert restored["id"] == n["id"], "undo re-created a note instead of restoring it"
    assert restored["body"] == "oops"


def test_search_covers_title_and_body(client):
    client.post("/api/notes", json={"body": "Pricing\nraise to 450"})
    client.post("/api/notes", json={"body": "Packing\nHDMI cable"})
    assert len(client.get("/api/notes?q=450").json()["notes"]) == 1
    assert len(client.get("/api/notes?q=Packing").json()["notes"]) == 1
    assert client.get("/api/notes?q=nothinghere").json()["notes"] == []


def test_pinned_sort_first(client):
    a = client.post("/api/notes", json={"body": "older"}).json()
    client.post("/api/notes", json={"body": "newer"})
    client.patch(f"/api/notes/{a['id']}", json={"pinned": True})
    assert client.get("/api/notes").json()["notes"][0]["id"] == a["id"]


def test_missing_note_is_404(client):
    assert client.patch("/api/notes/9999", json={"body": "x"}).status_code == 404
    assert client.delete("/api/notes/9999").status_code == 404
    assert client.post("/api/notes/9999/restore").status_code == 404


# ------------------------------------------------------- the closed grammar (v31)

def test_sanitize_note_body_keeps_the_six_closed_node_kinds(conn):
    """Bold, italic, lists, checklists, and a well-formed note-image: embed
    all pass through untouched -- the closed grammar SPEC-v31 names."""
    body = (
        "**bold** and *italic*\n"
        "- a list item\n"
        "1. an ordered item\n"
        "- [ ] unchecked\n"
        "- [x] checked\n"
        "![a caption](note-image:abcd1234)"
    )
    assert db.sanitize_note_body(body) == body


def test_sanitize_note_body_strips_a_raw_script_tag(conn):
    n = db.create_note(conn, "Reminder\n<script>alert('x')</script> call mom")
    assert "<script" not in n["body"]
    assert "</script>" not in n["body"]
    assert "alert('x')" in n["body"], "the inert text survives, only the tag is stripped"


def test_sanitize_note_body_strips_a_markdown_table(conn):
    body = "Budget\n| a | b |\n| --- | --- |\n| 1 | 2 |"
    n = db.create_note(conn, body)
    assert "---" not in n["body"]
    assert "| --- | --- |" not in n["body"]


def test_sanitize_note_body_strips_footnotes(conn):
    n = db.create_note(conn, "Lease terms[^1] apply\n[^1]: see the PDF")
    assert "[^1]" not in n["body"]
    assert "see the PDF" not in n["body"], "the footnote definition line is dropped whole"
    assert "Lease terms" in n["body"] and "apply" in n["body"]


def test_sanitize_note_body_drops_a_foreign_image_target(conn):
    """Only note-image: may embed an image -- an external URL is dropped
    whole rather than stored, so a note can never carry an outbound fetch."""
    n = db.create_note(conn, "![tracker](https://evil.example/pixel.png) text")
    assert "evil.example" not in n["body"]
    assert "text" in n["body"]


def test_sanitize_note_body_strips_a_plain_link_but_keeps_the_words(conn):
    n = db.create_note(conn, "call [the landlord](tel:5551234) today")
    assert "tel:5551234" not in n["body"]
    assert "the landlord" in n["body"]


def test_sanitize_note_body_runs_on_update_too(conn):
    n = db.create_note(conn, "clean")
    edited = db.update_note(conn, n["id"], body="<b>bold html</b> stays as text minus the tag")
    assert "<b>" not in edited["body"] and "</b>" not in edited["body"]
    assert "bold html" in edited["body"]


def test_sanitize_note_body_is_idempotent(conn):
    once = db.sanitize_note_body("<i>x</i> | --- | --- | [^1]: y [t](u)")
    twice = db.sanitize_note_body(once)
    assert once == twice


# --------------------------------------------- agent-visibility resolve (v31)

def test_resolve_note_body_replaces_a_captioned_image_with_its_caption():
    body = "Before ![the lease signature page](note-image:ab12cd34) after"
    resolved = note_visibility.resolve_note_body_for_agents(body)
    assert "note-image:" not in resolved
    assert "ab12cd34" not in resolved
    assert "[image: the lease signature page]" in resolved
    assert "Before" in resolved and "after" in resolved


def test_resolve_note_body_replaces_an_uncaptioned_image_with_a_bare_placeholder():
    resolved = note_visibility.resolve_note_body_for_agents("![](note-image:ffff0000)")
    assert resolved == "[image]"


def test_resolve_note_body_never_leaks_the_raw_token_regardless_of_input():
    """Belt-and-braces: even text that bypassed sanitize_note_body (e.g. a
    row written before this pass shipped) must never let a token through."""
    resolved = note_visibility.resolve_note_body_for_agents(
        "![caption](note-image:deadbeef) and ![](note-image:00000001)"
    )
    assert "note-image:" not in resolved
    assert "deadbeef" not in resolved and "00000001" not in resolved


def test_read_notes_ships_the_resolved_body_never_the_raw_token(conn):
    """End-to-end through the actual tool: create a note with a captioned and
    an uncaptioned embed, then confirm read_notes' payload shape stays
    exactly {title, body, updated_at} and body carries no image-write."""
    from agents import runner

    db.create_note(
        conn,
        "Lease\n![the signature page](note-image:ab12cd34) and ![](note-image:ffff0000)",
    )
    token = runner._RUN_CONTEXT.set({
        "role": "chief",
        "conn": conn,
        "interactive_read_sources": set(),
        "role_domains": ["all"],
    })
    try:
        payload = asyncio.run(runner.read_notes.handler({}))
    finally:
        runner._RUN_CONTEXT.reset(token)
    data = json.loads(payload["content"][0]["text"])
    assert data["notes"], "the note should be readable by chief"
    row = data["notes"][0]
    assert set(row.keys()) == {"title", "body", "updated_at"}
    assert "note-image:" not in row["body"]
    assert "ab12cd34" not in row["body"] and "ffff0000" not in row["body"]
    assert "[image: the signature page]" in row["body"]
    assert "[image]" in row["body"]
    assert "folder_id" not in row and "folder" not in row


def test_read_notes_resolves_the_title_too_not_only_the_body(conn):
    """note_title_from stores the note's FIRST LINE verbatim, so an
    image-first note's title IS the raw embed. Shipping title untouched
    leaked the attachment token and the caption past the same wall the body
    already passes through."""
    from agents import runner

    db.create_note(conn, "![my passport photo](note-image:deadbeef)\nsome text")
    token = runner._RUN_CONTEXT.set({
        "role": "chief",
        "conn": conn,
        "interactive_read_sources": set(),
        "role_domains": ["all"],
    })
    try:
        payload = asyncio.run(runner.read_notes.handler({}))
    finally:
        runner._RUN_CONTEXT.reset(token)
    row = json.loads(payload["content"][0]["text"])["notes"][0]
    assert "note-image:" not in row["title"]
    assert "deadbeef" not in row["title"]
    assert row["title"] == "[image: my passport photo]"


def test_read_notes_leaks_no_token_in_any_field(conn):
    """Belt across the whole payload, not one field at a time: whatever
    read_notes ships, no attachment token is in it."""
    from agents import runner

    db.create_note(conn, "![](note-image:beefcafe)\nbody ![x](note-image:0badf00d)")
    token = runner._RUN_CONTEXT.set({
        "role": "archivist",
        "conn": conn,
        "interactive_read_sources": set(),
        "role_domains": ["all"],
    })
    try:
        payload = asyncio.run(runner.read_notes.handler({}))
    finally:
        runner._RUN_CONTEXT.reset(token)
    raw = payload["content"][0]["text"]
    assert "note-image:" not in raw
    assert "beefcafe" not in raw and "0badf00d" not in raw


# ---------------------------------------------------- attachments (v31, fixed)

def test_removing_an_embed_soft_deletes_its_attachment_on_the_next_save(conn):
    """SPEC-v31: 'deleting an attachment from the body soft-deletes the row
    lazily on next autosave.' delete_note_attachment had zero callers, so
    every uploaded image stayed live and servable forever."""
    note = db.create_note(conn, "Lease")
    att = db.create_note_attachment(conn, note["id"], path="data/notes/2026/08/1-x.png")
    db.update_note(conn, note["id"], body=f"Lease\n![scan](note-image:{att['token']})")

    assert db.note_attachment_by_token(conn, att["token"]) is not None

    db.update_note(conn, note["id"], body="Lease")
    assert db.note_attachment(conn, att["id"])["deleted_at"] is not None
    assert db.note_attachment_by_token(conn, att["token"]) is None, "the bytes stop resolving"


def test_an_embed_that_comes_back_revives_its_attachment(conn):
    """Editor undo (and the sanitize round trip) can put a removed embed
    straight back. A one-way reap would leave that image permanently broken,
    which is the same 'undo restores the SAME row' law delete_note follows."""
    note = db.create_note(conn, "Lease")
    att = db.create_note_attachment(conn, note["id"], path="data/notes/2026/08/1-y.png")
    embed = f"Lease\n![scan](note-image:{att['token']})"

    db.update_note(conn, note["id"], body=embed)
    db.update_note(conn, note["id"], body="Lease")
    assert db.note_attachment_by_token(conn, att["token"]) is None

    db.update_note(conn, note["id"], body=embed)
    assert db.note_attachment(conn, att["id"])["deleted_at"] is None
    assert db.note_attachment_by_token(conn, att["token"]) is not None


def test_the_reap_never_touches_another_notes_attachments(conn):
    a = db.create_note(conn, "A")
    b = db.create_note(conn, "B")
    att_a = db.create_note_attachment(conn, a["id"], path="data/notes/2026/08/a.png")
    att_b = db.create_note_attachment(conn, b["id"], path="data/notes/2026/08/b.png")
    db.update_note(conn, a["id"], body=f"A\n![](note-image:{att_a['token']})")
    db.update_note(conn, b["id"], body=f"B\n![](note-image:{att_b['token']})")

    db.update_note(conn, a["id"], body="A")
    assert db.note_attachment(conn, att_a["id"])["deleted_at"] is not None
    assert db.note_attachment(conn, att_b["id"])["deleted_at"] is None


def test_a_pin_only_patch_does_not_reap_anything(conn):
    """The reap keys off the body, and a pin PATCH carries no body. Reading
    'no body' as 'no embeds' would delete every image on a pin tap."""
    note = db.create_note(conn, "Lease")
    att = db.create_note_attachment(conn, note["id"], path="data/notes/2026/08/1-z.png")
    db.update_note(conn, note["id"], body=f"Lease\n![](note-image:{att['token']})")

    db.update_note(conn, note["id"], pinned=1)
    assert db.note_attachment(conn, att["id"])["deleted_at"] is None


def test_attachment_tokens_are_unique_even_when_the_mint_repeats(conn, monkeypatch):
    """32 bits in a UNIQUE column: a repeat used to surface as an uncaught
    IntegrityError and a 500 on an upload whose file was already on disk."""
    note = db.create_note(conn, "N")
    minted = iter(["cafe0001", "cafe0001", "cafe0002"])
    monkeypatch.setattr(db.secrets, "token_hex", lambda n: next(minted))

    first = db.create_note_attachment(conn, note["id"], path="data/notes/2026/08/1.png")
    second = db.create_note_attachment(conn, note["id"], path="data/notes/2026/08/2.png")
    assert first["token"] == "cafe0001"
    assert second["token"] == "cafe0002"


def test_a_delete_batch_id_is_never_reused(conn, monkeypatch):
    """deleted_batch_id has no UNIQUE constraint (many rows share one), so a
    repeat would not raise: it would MERGE two unrelated deletes and one Undo
    would resurrect the other batch's rows."""
    a = db.create_note_folder(conn, "A")
    b = db.create_note_folder(conn, "B")
    minted = iter(["b0000001", "b0000001", "b0000002"])
    monkeypatch.setattr(db.secrets, "token_hex", lambda n: next(minted))

    first = db.delete_note_folder_cascade(conn, a["id"])
    second = db.delete_note_folder_cascade(conn, b["id"])
    assert first["deleted_batch_id"] != second["deleted_batch_id"]

    restored = db.restore_note_folder_cascade(conn, first["deleted_batch_id"])
    assert restored["folder_ids"] == [a["id"]], "undo must restore only its own batch"


# ------------------------------------------------------------ the agent seam

def test_only_chief_and_archivist_can_read_notes():
    """The read_pipeline precedent: enforced in the allowlist AND in the tool."""
    from agents import runner

    assert runner.NOTE_READERS == {"chief", "archivist"}
    for role, tools in runner.ALLOWLISTS.items():
        if "read_notes" in tools:
            assert role in runner.NOTE_READERS, f"{role} is allowlisted but not a reader"
    for role in runner.NOTE_READERS:
        assert "read_notes" in runner.ALLOWLISTS[role], f"{role} cannot reach the tool"


def test_no_agent_can_write_a_note():
    """Read-only, with no writing counterpart anywhere, the same shape as
    read_pipeline in v9. An agent may never put words in Ian's notes."""
    src = (Path(__file__).resolve().parent.parent / "agents" / "runner.py").read_text()
    for forbidden in ('@tool("write_note', '@tool("create_note',
                      '@tool("delete_note', '@tool("update_note'):
        assert forbidden not in src, f"a note-writing tool exists: {forbidden}"

    from agents import runner
    for tools in runner.ALLOWLISTS.values():
        assert not any(t.endswith("_note") or t.endswith("_notes")
                       for t in tools if t.startswith("write") or t.startswith("create"))


def test_chat_write_note_schema_is_frozen_at_body_and_domain():
    """SPEC-v31 'Agent visibility'. chat_write_note (SPEC-v29 Phase 6) is the
    real, narrow, human-triggered exception test_no_agent_can_write_a_note
    above doesn't catch (it lives in INSTANT_WRITE_TOOLS, never ALLOWLISTS).
    That's fine -- it's the deliberate exception, not a hole -- but its
    schema must stay exactly {body, domain} forever: no folder_id, ever. A
    chat-created note always lands unfiled, never a folder chosen as a side
    effect of writing text."""
    from agents import runner

    assert runner.chat_write_note.input_schema == {"body": str, "domain": str}
    assert "chat_write_note" in runner.INSTANT_WRITE_TOOLS
    for role, tools in runner.ALLOWLISTS.items():
        assert "chat_write_note" not in tools, \
            f"chat_write_note must never enter a nightly allowlist ({role})"


# ------------------------------------------------------- folders (v31, fixed)

def test_move_folder_to_a_nonexistent_parent_is_a_clean_422_not_a_500(client):
    """move_note_folder used to skip straight to the UPDATE, so a bogus
    parent_id hit the FOREIGN KEY constraint as a raw, uncaught
    sqlite3.IntegrityError instead of failing cleanly."""
    a = client.post("/api/notes/folders", json={"name": "A"}).json()
    resp = client.patch(f"/api/notes/folders/{a['id']}", json={"parent_id": 999999})
    assert resp.status_code == 422
    assert client.get("/api/notes/folders").json()["folders"][0]["parent_id"] is None


def test_folder_cannot_be_reparented_under_a_soft_deleted_folder(client):
    victim = client.post("/api/notes/folders", json={"name": "Victim"}).json()
    live = client.post("/api/notes/folders", json={"name": "Live"}).json()
    client.delete(f"/api/notes/folders/{victim['id']}")

    resp = client.patch(f"/api/notes/folders/{live['id']}", json={"parent_id": victim["id"]})
    assert resp.status_code == 422
    top_level_ids = {f["id"] for f in client.get("/api/notes/folders").json()["folders"]}
    assert live["id"] in top_level_ids, "the live folder must not vanish under a dead parent"


def test_folder_cannot_be_created_under_a_soft_deleted_folder(client):
    victim = client.post("/api/notes/folders", json={"name": "Victim2"}).json()
    client.delete(f"/api/notes/folders/{victim['id']}")

    resp = client.post("/api/notes/folders", json={"name": "Orphan", "parent_id": victim["id"]})
    assert resp.status_code == 404


def test_folder_cannot_be_reparented_under_its_own_descendant(client):
    """The other half of the cycle guard: not "into itself" but "into a child
    of itself", which would orphan the whole subtree from the root walk."""
    parent = client.post("/api/notes/folders", json={"name": "Parent"}).json()
    child = client.post(
        "/api/notes/folders", json={"name": "Child", "parent_id": parent["id"]}
    ).json()
    grandchild = client.post(
        "/api/notes/folders", json={"name": "Grandchild", "parent_id": child["id"]}
    ).json()

    resp = client.patch(
        f"/api/notes/folders/{parent['id']}", json={"parent_id": grandchild["id"]}
    )
    assert resp.status_code == 422
    top = client.get("/api/notes/folders").json()["folders"]
    assert [f["id"] for f in top] == [parent["id"]], "the tree must still hang off the root"


def test_folder_cannot_be_reparented_under_itself(client):
    f = client.post("/api/notes/folders", json={"name": "Self"}).json()
    assert client.patch(
        f"/api/notes/folders/{f['id']}", json={"parent_id": f["id"]}
    ).status_code == 422


def test_folder_creation_with_a_truly_nonexistent_parent_is_still_404(client):
    """The old pre-check already caught this; confirms moving the validation
    into db.create_note_folder didn't regress it."""
    resp = client.post("/api/notes/folders", json={"name": "Orphan2", "parent_id": 999999})
    assert resp.status_code == 404


def test_notes_are_not_the_journal(client):
    """Journal is private from agents; notes are readable by chief+archivist.
    Separate tables so one boolean never stands between reflections and a model."""
    schema = (Path(__file__).resolve().parent.parent / "core" / "db.py").read_text()
    assert "CREATE TABLE IF NOT EXISTS notes" in schema
    assert "CREATE TABLE IF NOT EXISTS journal_entries" in schema


def test_the_phone_can_read_notes_and_journal_with_token(client, monkeypatch):
    """SPEC-v11: same valid token unlocks notes and journal. Agents still never
    see journal bodies, that wall is /api/state + no read_journal tool."""
    monkeypatch.setattr(main, "API_TOKEN", "tok123")
    remote = {"x-forwarded-for": "100.64.0.9", "authorization": "Bearer tok123"}

    n = client.post("/api/notes", json={"body": "reachable"}, headers=remote).json()
    got = client.get("/api/notes", headers=remote)
    assert got.status_code == 200
    assert n["id"] in [x["id"] for x in got.json()["notes"]]

    assert client.get("/api/journal", headers=remote).status_code == 200
    j = client.post("/api/journal", json={"body": "ZZPHONEPRIVATE"}, headers=remote).json()
    assert "ZZPHONEPRIVATE" not in client.get("/api/state", headers=remote).text
    assert j["entry"]["body"] == "ZZPHONEPRIVATE"
