"""Note-body agent-visibility resolve pass (SPEC-v31). Pure, no network, no LLM.

Sibling to core/journal.py and core/plan.py: date/text math an agent tool
needs gets computed here in Python, never left to the model.

The privacy law this file exists to enforce: `read_notes` (agents/runner.py)
ships `title`/`body`/`updated_at` to chief/archivist as plain strings, and
notes.body's closed Markdown dialect (core.db.sanitize_note_body) embeds
inline images as `![caption](note-image:TOKEN)`. Shipping body untouched
would leak the raw attachment token -- and any caption -- as plain text.
`resolve_note_body_for_agents()` is the one rewrite that runs on body before
an agent ever sees it: every image embed becomes its caption text
("[image: caption]") or a bare "[image]" placeholder if Ian wrote no
caption. Never bytes, a path, dimensions, or the token itself reach an
agent. Mirrors `journal.agent_signal()`'s "a count, never the picture"
precedent and `read_pipeline`'s withheld run/heat data.
"""

from __future__ import annotations

import re

# Only a well-formed note-image: embed can reach this function -- anything
# pointing elsewhere was already stripped at write time by
# core.db.sanitize_note_body -- but the pattern is scoped to that one shape
# regardless, so this function stays correct even if called on unsanitized
# text.
_NOTE_IMAGE_RE = re.compile(r"!\[([^\]\n]*)\]\(note-image:[A-Za-z0-9_-]+\)")


def resolve_note_body_for_agents(body: str) -> str:
    """Replace every `![caption](note-image:TOKEN)` embed in `body` with a
    safe text placeholder. A captioned embed becomes "[image: caption]"; an
    uncaptioned one becomes a bare "[image]". Returns the rest of the text
    unchanged. Never returns bytes, a path, dimensions, or the raw token.
    """

    def _placeholder(match: re.Match) -> str:
        caption = match.group(1).strip()
        return f"[image: {caption}]" if caption else "[image]"

    return _NOTE_IMAGE_RE.sub(_placeholder, body or "")
