# SPEC v36: School Study Workbench

**Status:** QUEUED. No implementation is authorized by this document alone.

> **Superseded in one place (Ian, 2026-09-09).** §8 "Course policies win" and
> the `prohibited` rejection in §551 no longer describe the build: a course's
> AI policy does not gate study tools, and `_school_course_blocks_study` is
> deleted. Study-mode consent (`school_ai_settings`) is the only wall, and it
> is unchanged. Read CLAUDE.md's School section for current behaviour.

**Date:** 2026-08-30  
**Owner:** Ian  
**Audience:** Ian and the implementing agent  
**Decision:** Evolve the existing private, note-only study aids into a
course-scoped, source-grounded study workspace. It should make answers and
review material traceable to the sources Ian selected, while preserving the
current hard boundary against Canvas actions and assessment completion.

## 0. Executive decision

ianOS already has a good safety-first nucleus:

- a saved note can explicitly request a summary, flashcards, practice prompts,
  or a study plan;
- the request is revision-bound, opt-in, course-policy-gated, and sent to a
  zero-tool worker;
- course files live in a separate private shelf and are intentionally absent
  from AI context;
- a course that prohibits AI is blocked by the server, not merely hidden in
  the UI.

That is not yet a useful NotebookLM-style study experience. It is a one-note
artifact generator. The missing product is a **source-grounded workbench**:

1. Ian chooses the course notes and materials relevant to a question.
2. ianOS retrieves only useful excerpts from those selected sources.
3. The model answers from those excerpts only.
4. Every answer block links to a specific note or file excerpt.
5. Ian can turn the cited material into review aids and revisit difficult
   material without reopening a generic chat.

The reference is the useful behavior of Google NotebookLM, not its product
surface or branding: source selection, grounded answers with citations, and
study aids such as flashcards and quizzes. Google describes those capabilities
in its official [NotebookLM overview](https://support.google.com/notebooklm/answer/16164461?hl=en)
and [flashcards and quizzes help](https://support.google.com/notebooklm/answer/16958963?hl=en-GB).

ianOS must not copy Google data, depend on Google Drive, use NotebookLM APIs,
or present generated material as authoritative course answers.

## 1. Product outcome

Within a course, Ian can answer this in under ten seconds:

> Which source-backed concept should I understand next, and where did it come
> from?

The first useful workflow is:

1. Open **Study workspace** from a course note or the School page.
2. Keep the current note selected by default; add or remove course notes and
   indexed class files in a visible source shelf.
3. Ask a conceptual question such as “How does chain of custody differ from
   evidence admissibility in these notes?”
4. Receive an answer with compact, clickable source references such as
   `Lecture 4 · ¶3` or `Syllabus.pdf · p. 6`.
5. Open a citation to inspect the exact excerpt in place.
6. Create cited flashcards, a self-check set, or a session plan from the same
   selected sources.

The workbench is a study companion, not a tutoring substitute for graded work.
It should say **“Not enough evidence in the selected sources”** instead of
filling gaps from general model knowledge.

## 2. What exists now

| Existing capability | Location | v36 decision |
| --- | --- | --- |
| Four note-only study aid types | `core/school_study.py` | Keep the strict schema and assessment guardrails. |
| Revision-bound artifact storage | `core/school.py` `school_study_artifacts` | Preserve as the legacy/compact aid path; do not weaken its note revision semantics. |
| Zero-tool Claude worker | `api/main.py` `_school_study_model_reply` | Reuse its isolated execution model for all remote study requests. |
| Global study-mode consent | `school_ai_settings` | Keep; make each new request disclose the selected source excerpts it will send. |
| Course AI-policy enforcement | `school_courses.policy_json` | Preserve the server-side prohibition. Conditions remain visible in every study request. |
| Course file shelf | `SchoolFilesPanel.jsx`, `school_note_assets` | Reuse ownership, upload validation, deletion, and private download behavior. |
| Note-based study UI | `SchoolStudyPanel.jsx` | Reduce to a compact entry point and keep previously accepted aids accessible. |

### Current gap

The current panel explicitly says “Course files are not included.” That is
intentional and correct for its current contract, but it means the system
cannot answer from slides, readings, handouts, or earlier notes. It also has
no course-wide source picker, retrieval step, cited answers, answer review,
or study progress.

## 3. Binding product laws

1. **Selection is visible and reversible.** The UI always names the source
   set used for a run. A source is never silently included because it happens
   to belong to the course.
2. **Grounding precedes fluency.** A rendered answer contains one or more
   valid citations per answer block, or it is rendered as an insufficient-
   evidence result. A smooth uncited answer is a failure.
3. **No Canvas boundary change.** No source extractor, retrieval worker, or
   model request reads Canvas credentials, Canvas descriptions, hidden URLs,
   submissions, grades, or assessment content. No study endpoint writes to
   Canvas, Plans, notes, assignments, or agent memory.
4. **No assessment completion.** The existing prohibition on answers,
   solutions, completion, submission, or grading help stays in the prompt,
   pure validator, persistence layer, and UI. Practice material contains
   prompts and hints, never answer keys.
5. **Local extraction, explicit remote use.** File parsing and retrieval are
   local. A remote model receives only the selected, bounded excerpts and the
   explicit question or requested aid, never raw file bytes or the entire
   library by default.
6. **Source changes invalidate derived work.** A response or aid records a
   source-set snapshot. If a selected note revision or indexed file hash
   changes, affected derived work becomes stale rather than looking current.
7. **Errors stay closed.** Browser status and persisted errors use safe codes;
   they never contain provider messages, file paths, raw extracts, or question
   text.
8. **Course policies win.** `prohibited` blocks all remote study work
   server-side. `permitted_with_conditions` shows the condition before each
   request. Unknown policy is a visible caution, not a fabricated permission.
9. **One natural page scroll on phone.** Source selection and citations open
   in sheets; the mobile workspace must not create a chat scroll nested inside
   the page scroll.
10. **No background surprise.** Uploading a file may trigger local indexing
    only. It never triggers a model call, creates a study aid, sends a
    notification, or changes the Day Command.

## 4. Scope

### Phase-one scope

- Course-scoped source shelf.
- All saved note sessions for a course as eligible sources.
- Local extraction and indexing of supported file types.
- A cited conceptual Q&A mode.
- Cited summary, flashcards, self-check prompts, and study plans.
- Citation inspection, stale status, delete, and retry behavior.
- Local review state for generated flashcards and self-check prompts.

### Deliberately out of scope

- Canvas import expansion, scraping, browser automation, or Canvas actions.
- Answers to quiz, exam, homework, lab, or assignment questions.
- Autonomous course monitoring or auto-generated study plans.
- Provider file uploads, Google Drive integration, or external vector stores.
- Multi-user sharing, classroom collaboration, grading, or instructor-facing
  workflows.
- Voice cloning or an “Audio Overview” in the first release. That needs a
  separate cost, accessibility, transcript, and source-attribution decision.
- OCR as a prerequisite for all image-based PDFs. Unsupported material stays
  on the file shelf with an honest indexing status.

## 5. User experience

### 5.1 Entry points

- The current **Study from this note** action opens the workbench with that
  note preselected.
- The School course detail gains **Open study workspace**. It opens with no
  remote request and a compact source shelf.
- `SchoolStudyPanel` remains the small consent/status surface for an opened
  note, but its primary action becomes **Open study workspace**. Existing
  accepted note-only artifacts remain visible in a “Previous aids” disclosure.

### 5.2 Desktop composition

The workspace is a dedicated School surface, not another card inside the
Notebook editor:

```text
Course source rail        Study canvas                         Review rail
------------------        ----------------------------         -----------------
Selected sources          Question + grounded answer           Current aid / deck
Search / filter           Citation chips in every answer       Due to review
Index state               Ask / summary / cards / practice     Recent runs
```

- The source rail is the control surface, not a permanent large file browser.
- The study canvas is the reading path: question, answer, citations, then
  one next action.
- The review rail is supplementary and collapses below the canvas before the
  source rail disappears at intermediate desktop widths.
- A long answer remains in normal document flow. Only a large source list may
  use a contained desktop scroll pane.

### 5.3 Mobile composition

- The current question and its cited answer are first.
- **Sources** opens a sheet with selected count, search, source states, and
  checkboxes.
- Tapping a citation opens a bottom sheet to the precise note paragraph or
  extracted file excerpt.
- **Create study aid** opens a small action sheet; no four-card dashboard
  appears above the answer.
- The body has one vertical scroller, 44px targets, and no duplicated School
  title.

### 5.4 Source states

| State | UI copy | Meaning |
| --- | --- | --- |
| Ready | `Ready` | Local text and chunks are current. |
| Indexing | `Preparing for study` | Local extraction is queued/running; no remote call. |
| Unsupported | `Stored, not searchable yet` | The file remains private and downloadable, but is excluded from source selection. |
| Needs review | `Text could not be confirmed` | Extraction produced too little or invalid text; do not use it. |
| Stale | `Source changed` | The stored material changed. Existing runs may still render with a stale label, but this source cannot be selected again until it is re-indexed. |
| Deleted | `Source removed` | It cannot be selected; derived work retains a safe stale label. |

### 5.5 Cited answer contract in the UI

An answer is made of short blocks, never one opaque wall of model text:

```text
Answer block text… [1] [2]

[1] Lecture 4 · Aug 30 note · paragraph 3
[2] Chain of Custody.pdf · page 6
```

- Citation labels are meaningful without color.
- A citation opens the saved note or a read-only excerpt panel.
- If selected material is insufficient, the canvas renders the limitation and
  suggests source types to add; it does not answer from the model’s general
  knowledge.
- A citation is never a fake link. The backend resolves its source and chunk
  against the exact source snapshot recorded for the run.

## 6. Source pipeline

### 6.1 Source eligibility

| Source type | Phase-one eligibility | Canonical source |
| --- | --- | --- |
| Saved course note | Yes | `school_note_sessions.plain_text` at a named revision. |
| `.txt` / `.md` | Yes | Private asset bytes, parsed locally. |
| Text PDF | Yes | Private asset bytes, parsed locally with page labels. |
| `.docx` | Yes | Private asset bytes, parsed locally with document section labels when available. |
| `.pptx` | Yes | Private asset bytes, parsed locally with slide labels. |
| Images / scanned PDF | Later, only with a reviewed local OCR path. | Never silently remote-uploaded for OCR. |
| `.doc`, `.ppt`, `.xls`, `.xlsx` | Stored now; unsupported in v36 phase one. | File shelf only. |

The file shelf’s existing allowlist and size cap remain authoritative. An
extractor never uses the client filename as a path or trusts its MIME type
over the validated asset record.

### 6.2 Local indexing pipeline

1. A note save or eligible file upload creates or refreshes a local source
   record. Upload is still successful even when indexing later fails.
2. A local worker derives a bounded plain-text projection with location
   markers such as page, slide, or paragraph.
3. It normalizes control characters, enforces a source size cap, assigns a
   content hash, and chunks text into stable, location-aware excerpts. A
   changed note revision or asset hash transitions the source through `STALE`
   and `INDEXING`; it is not selectable until the new version is `READY`.
4. It writes only local source/chunk records. No model request happens here.
5. A local lexical index searches selected sources. Initial retrieval is
   deterministic SQLite FTS5 with a startup capability test; it does not need
   embeddings or an external vector database.
6. Before every remote request, retrieval creates an immutable source-set
   snapshot containing source IDs, versions, chunk IDs, display labels, and
   the bounded text excerpts actually sent.

Stable chunks must use a source-local ordinal plus version, not an array index
that can silently change when a previous paragraph is edited. A file hash or
note revision change retires old chunks and prevents them from being cited as
current.

### 6.3 Retrieval rules

- The user chooses one or more sources; the server rejects cross-course IDs.
- Retrieval searches only that selected source set.
- Start with at most 12 chunks and a strict combined text budget. The exact
  cap is chosen from an adversarial test corpus, not a token guess in UI code.
- Prefer diversity: do not return twelve adjacent chunks from one file when
  selected notes also match.
- Keep chunk label, source ID, version, ordinal, and excerpt text together in
  the worker-only context.
- If no relevant chunk scores above the tested threshold, return an
  `insufficient_evidence` result locally and make no provider request.
- The model receives no source outside that snapshot and no tool capability.

## 7. Data model

Do not mutate the proven `school_study_artifacts` contract in place. Add a
parallel workbench family; old note-only artifacts remain readable and safely
retire over time.

```sql
CREATE TABLE school_study_sources (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code           TEXT NOT NULL REFERENCES school_courses(code),
    source_type           TEXT NOT NULL CHECK (source_type IN ('note','asset')),
    school_note_session_id INTEGER REFERENCES school_note_sessions(id) ON DELETE SET NULL,
    school_note_revision  INTEGER,
    school_asset_id       INTEGER REFERENCES school_note_assets(id) ON DELETE SET NULL,
    source_version        TEXT NOT NULL,
    display_label         TEXT NOT NULL,
    state                 TEXT NOT NULL CHECK (state IN ('READY','INDEXING','UNSUPPORTED','NEEDS_REVIEW','STALE','DELETED')),
    extraction_error_code TEXT NOT NULL DEFAULT '',
    content_hash          TEXT NOT NULL DEFAULT '',
    created_at            TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at            TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE school_study_chunks (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    school_study_source_id INTEGER NOT NULL REFERENCES school_study_sources(id) ON DELETE CASCADE,
    source_version        TEXT NOT NULL,
    ordinal               INTEGER NOT NULL CHECK (ordinal >= 0),
    location_label        TEXT NOT NULL,
    plain_text            TEXT NOT NULL,
    text_hash             TEXT NOT NULL,
    created_at            TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(school_study_source_id, source_version, ordinal)
);

CREATE VIRTUAL TABLE school_study_chunks_fts USING fts5(
    plain_text, content='school_study_chunks', content_rowid='id'
);

-- External-content FTS does not synchronize itself. Keep these triggers in
-- the same migration as the table and test every source/chunk lifecycle.
CREATE TRIGGER school_study_chunks_ai AFTER INSERT ON school_study_chunks BEGIN
  INSERT INTO school_study_chunks_fts(rowid, plain_text) VALUES (new.id, new.plain_text);
END;
CREATE TRIGGER school_study_chunks_ad AFTER DELETE ON school_study_chunks BEGIN
  INSERT INTO school_study_chunks_fts(school_study_chunks_fts, rowid, plain_text)
  VALUES ('delete', old.id, old.plain_text);
END;
CREATE TRIGGER school_study_chunks_au AFTER UPDATE OF plain_text ON school_study_chunks BEGIN
  INSERT INTO school_study_chunks_fts(school_study_chunks_fts, rowid, plain_text)
  VALUES ('delete', old.id, old.plain_text);
  INSERT INTO school_study_chunks_fts(rowid, plain_text) VALUES (new.id, new.plain_text);
END;

CREATE TABLE school_study_runs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code           TEXT NOT NULL REFERENCES school_courses(code),
    request_id            TEXT NOT NULL,
    request_fingerprint   TEXT NOT NULL,
    mode                  TEXT NOT NULL CHECK (mode IN ('ask','summary','flashcards','practice','study_plan')),
    question              TEXT NOT NULL DEFAULT '',
    source_snapshot_json  TEXT NOT NULL,
    status                TEXT NOT NULL CHECK (status IN ('QUEUED','RUNNING','READY','STALE','FAILED','DISCARDED')),
    output_json           TEXT,
    error_code            TEXT NOT NULL DEFAULT '',
    created_at            TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at            TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(course_code, request_id)
);

CREATE TABLE school_study_review_items (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    school_study_run_id   INTEGER NOT NULL REFERENCES school_study_runs(id) ON DELETE CASCADE,
    item_key              TEXT NOT NULL,
    item_type             TEXT NOT NULL CHECK (item_type IN ('flashcard','practice')),
    state                 TEXT NOT NULL CHECK (state IN ('DUE','REVIEWED','STALE','DISCARDED')),
    due_at                TEXT,
    last_reviewed_at      TEXT,
    last_response         TEXT CHECK (last_response IN ('again','unsure','got_it')),
    created_at            TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at            TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(school_study_run_id, item_key)
);
```

The run snapshot is not a second file store. It contains only the selected
source identity/version and cited chunk identity/label required to render and
validate the run. It must not contain raw file bytes, a provider transcript,
Canvas identifiers, URLs, or credentials.

The exact query/answer retention policy must be explicit before Phase 1:

- default: keep local runs until Ian deletes them;
- never send prior run history to a model unless it is visibly selected as
  context for a new request;
- deleting a source deletes chunks and FTS rows through the verified FTS
  triggers, marks related runs and review items stale, and
  does not delete Ian’s saved note or accepted legacy artifacts;
- deleting a run removes its output and local review state through the foreign
  key, never source data.

Source transitions are closed: `READY → STALE → INDEXING → READY` for changed
material; `INDEXING → NEEDS_REVIEW | UNSUPPORTED`; and any live state may move
to `DELETED` when its backing note or asset is removed. `STALE`,
`NEEDS_REVIEW`, `UNSUPPORTED`, and `DELETED` sources are never selectable.

## 8. Remote study contract

The workbench reuses the existing zero-tool worker architecture but receives a
different, strictly typed input:

```json
{
  "mode": "ask",
  "question": "How do these sources distinguish X from Y?",
  "sources": [
    {
      "citation_id": "c:581:rev-4:7",
      "label": "Lecture 4 · Aug 30 note · paragraph 3",
      "text": "..."
    }
  ]
}
```

The model output for `ask` uses this shape:

```json
{
  "kind": "ask",
  "status": "grounded",
  "answer_blocks": [
    {
      "text": "...",
      "citation_ids": ["c:581:rev-4:7"]
    }
  ],
  "next_study_step": "..."
}
```

`insufficient_evidence` is a separate exact shape with no invented answer.
The backend validates all citation IDs against the run snapshot, requires at
least one citation per grounded answer block, rejects unknown fields and
duplicate keys, bounds every string/list, and refuses any output that looks
like an answer key or completion instruction.

For generated aids, extend the existing schemas only after this cited output
contract is proven. Flashcards and practice prompts each carry citation IDs at
card/question granularity; study plans cite the source evidence behind each
step. Existing note-only artifact schemas remain stable.

## 9. API surface

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/school/courses/{course_code}/study-sources` | Safe source metadata, local state, and selected-note availability. |
| `POST` | `/api/school/courses/{course_code}/study-sources/reindex` | Explicitly retry local extraction for one eligible source. No model call. |
| `GET` | `/api/school/study-runs/{run_id}` | Safe run projection with validated output and citations. |
| `POST` | `/api/school/study-runs` | Queue one explicit source-set study request. |
| `POST` | `/api/school/study-runs/{run_id}/discard` | Delete output/review state without touching sources. |
| `GET` | `/api/school/study-runs/{run_id}/citations/{citation_id}` | Return one bounded, read-only cited excerpt. |
| `PATCH` | `/api/school/study-review/{item_id}` | Save local review state only. |

`POST /api/school/study-runs` accepts a client-generated opaque `request_id`,
`course_code`, `mode`, explicit `source_ids`, and a question only for `ask`.
The server validates the request ID, computes a canonical payload fingerprint,
and makes `(course_code, request_id)` unique. Repeating the same ID and
fingerprint returns the existing safe run projection; repeating an ID with a
different fingerprint fails closed. It must:

1. validate every source belongs to the named course and is `READY`;
2. enforce global study consent and course AI policy;
3. retrieve only selected-source excerpts locally;
4. create an immutable source snapshot and one idempotent queued run;
5. start the isolated worker only when retrieval found usable evidence.

No endpoint accepts browser-provided raw extracts, a model name, an arbitrary
file path, Canvas IDs, URLs, or a citation label as an authority.

`PATCH /api/school/study-review/{item_id}` accepts only one explicit response:
`again`, `unsure`, or `got_it`. It updates `last_response`,
`last_reviewed_at`, and the locally scheduled `due_at`; it never changes the
source, run output, or citation snapshot. A stale run or source moves its
review rows to `STALE`, which remains readable but cannot schedule a new
review until a current aid is generated.

## 10. Implementation phases

### Phase 0: contract and extraction spike

**Goal:** prove that source grounding is possible locally before exposing a
new AI surface.

- Add pure contracts for source metadata, chunk normalization, source-set
  snapshots, cited output, and safe error codes.
- Build deterministic fixtures for a note, text PDF, DOCX, and PPTX.
- Verify FTS5 availability in the actual ianOS SQLite runtime; stop if it is
  not available rather than quietly falling back to a poor search.
- Select and license the local parsers. They must run without network access.
- Define content/chunk caps with real course-material fixtures and failure
  cases.

**Exit gate:** a local test can retrieve a known excerpt, produce a stable
citation ID, reject a stale snapshot, and prove no network call occurred.

### Phase 1: cited course-note workspace

**Goal:** make study tools materially more useful before file extraction adds
format complexity.

- Index all saved notes for a course.
- Build the Study workspace route, source sheet/rail, cited Q&A, and citation
  inspector.
- Reuse global consent, policy gate, zero-tool worker, queue/recovery, and
  safe error conventions.
- Add cited summaries and flashcards from selected notes.
- Preserve the note-only panel as an entry point and migrate no old rows.

**Exit gate:** an answer from two selected notes can cite each note exactly;
unselected notes cannot influence the worker input; a note edit stales the
run; mobile stays single-scroll.

### Phase 2: indexed course files

**Goal:** safely add the sources that make the workbench feel like a real
course library.

- Index text PDF, TXT/MD, DOCX, and PPTX locally.
- Render page/slide-aware citations and failure states.
- Add source retry, unsupported-state copy, file delete cleanup, and source
  count filtering.
- Add cited practice prompts and plans using the same source snapshot.

**Exit gate:** a deleted asset is unretrievable and cannot appear in future
context; a PDF citation opens the right page-labelled excerpt; a malformed
file never reaches a model or exposes parser diagnostics.

### Phase 3: review loop

**Goal:** turn generated aids into real recall practice rather than static
details elements.

- Add card reveal, confidence rating, missed-card filter, and local due state.
- Keep all scoring descriptive, not gamified or shame-based.
- Let Ian regenerate a cited aid from a current source set; never silently
  overwrite an accepted legacy artifact.
- Make the review rail useful without blocking the source-grounded answer
  flow.

**Exit gate:** review state survives reload, stale cards are labelled, and a
user can delete review data independently of sources.

### Phase 4: evaluate audio and local OCR

Only begin after the written, cited workflow has passed a real semester use
test. Decide separately:

- whether local OCR has acceptable accuracy and device cost;
- whether an audio overview has a transcript, citations, accessibility
  controls, provider cost cap, and explicit per-run consent;
- whether a local embedding model materially improves retrieval beyond FTS5.

None of these are prerequisites for the workbench to be useful.

## 11. Verification matrix

### Safety and privacy

- The worker options contain no MCP servers, tools, Canvas access, agent
  tools, or file paths.
- A course policy of `prohibited` rejects runs server-side and creates no row.
- Disabling study mode prevents queued/running results from becoming visible.
- Browser/API/error/log projections contain no raw file bytes, source chunks,
  provider response, Canvas URL, or credentials.
- A file upload and local reindex make zero provider calls.
- A run contains only selected-source chunks; a sentinel unselected source
  cannot be surfaced in model input or output fixtures.

### Grounding

- Every grounded answer block has one or more snapshot-valid citations.
- Unknown citation IDs, duplicate JSON fields, empty citation arrays, and
  citations from a different course fail closed.
- A source edit/hash change marks previous runs stale.
- Insufficient evidence returns a truthful state without a provider call.
- Citation inspect resolves a bounded current/existing source excerpt or a
  safe stale/deleted state.

### Extraction and lifecycle

- Text PDF, DOCX, PPTX, TXT/MD fixtures retain their page/slide/paragraph
  labels.
- Unsupported and malformed files remain on the shelf but never index or
  enter context.
- Asset delete purges chunks/FTS rows and stales related runs.
- Note delete/soft-delete makes related sources ineligible without breaking
  historical safe projections.
- Queue recovery terminalizes interrupted local work and never replays source
  text at boot.
- Retrying a timed-out create request with the same request ID returns exactly
  one run and can never queue a second provider call; a reused ID with changed
  inputs fails safely.
- Insert, re-index, update, and delete fixtures prove the FTS table has the
  same searchable chunks as `school_study_chunks` after every transaction.
- Review actions are limited to `again`, `unsure`, and `got_it`; source/run
  staleness marks the review item `STALE`, and deleting a run removes only its
  review rows.

### Interface

- 375×667 and 390×844: one vertical page scroller, no clipped source label,
  44px controls, citation sheet reachable, answer visible before long source
  list.
- 901×800, 1200×800, 1440×900, and 1920×1200: source/canvas/review hierarchy
  remains clear with no stranded full-height cards.
- Keyboard sequence follows DOM order: source selection, question, answer,
  citations, review actions.
- Long course names, 0/1/20 source states, long PDF titles, empty source set,
  a failed index, and a 12-chunk result all remain readable.

## 12. Deferred decisions

These decisions are intentionally deferred until Phase 0 evidence exists:

| Decision | Default until decided |
| --- | --- |
| Local parser libraries and binary distribution | Use only parsers proven locally in the extraction spike. |
| OCR | Unsupported files show an honest local state. No cloud OCR. |
| Retrieval cap and diversity scoring | Freeze from the fixture and latency test results. |
| Query/answer retention length | Keep local until manual deletion; no provider history replay. |
| Audio overview | Not built. Requires a dedicated consent, cost, transcript, and citation spec. |
| Embeddings | Not built. FTS5 is the first retrieval engine. |

## 13. Implementation order

1. Add Phase 0 pure contracts and fixture tests.
2. Implement local note-source indexing and retrieval; validate against a
   copied development database only.
3. Add run storage, cited output validator, and zero-tool worker integration.
4. Build the note-only course workspace and visual/mobile tests.
5. Add file extraction one format at a time with delete and stale tests.
6. Add review state only after cited cards work.
7. Reassess audio/OCR/embeddings from actual semester use, not novelty.

This makes the next study build a focused extension of the current subsystem,
not a second chat product or a fragile course-file upload to an opaque model.
