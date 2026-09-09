"""SPEC-v10 osUI: mobile gates that are invisible until they bite.

These check CSS text, not rendering, because the defects they guard against are
silent: the app builds, the tests pass, the desktop looks perfect, and the phone
is broken. Each one here shipped for real.
"""

import re
from pathlib import Path

import pytest

_RAW = (Path(__file__).resolve().parent.parent
        / "dashboard" / "src" / "styles.css").read_text()
# Strip comments but keep newlines, so reported line numbers still match the
# file. Without this the prose in a comment ("...Safari's 100vh is...") reads as
# a declaration and every check here fires on its own documentation.
CSS = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), _RAW, flags=re.S)


def _blocks(css: str):
    """(condition_or_None, body) for every top-level rule/@media block."""
    out, i, depth, start, cond = [], 0, 0, 0, None
    while i < len(css):
        if css[i] == "{":
            if depth == 0:
                cond = css[start:i].strip()
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                out.append((cond, css[start:i + 1]))
                start = i + 1
        i += 1
    return out


def test_every_css_variable_resolves_to_a_defined_token():
    """SPEC-v28/v29 Phase 5's own guardrail, finally a real test instead of a
    one-off grep repeated by hand in every pass since.

    `var(--s8)` with no fallback silently computed to `max-height: none` and
    shipped a P0 (a 1613px sheet in an 800px viewport) with zero build
    warnings, because nothing checked that a referenced custom property was
    ever declared. A var() WITH a fallback (`var(--x, default)`) degrades
    safely by the CSS spec itself, that's not the risk class; a var() with
    NO fallback and no declaration anywhere is.

    Building this test caught a second, live instance of exactly this bug:
    `var(--text)` (six call sites) was never declared anywhere, `--text` was
    never a real token (the text-color tokens are --ink/--dim/--muted), and
    it happened to render correctly only because color is inherited and
    every affected element's ancestor already set --ink.
    """
    declared = set(re.findall(r"--([a-zA-Z][\w-]*)\s*:", CSS))
    used_no_fallback = set(re.findall(r"var\(\s*--([a-zA-Z][\w-]*)\s*\)", CSS))
    # Set only via JS (lib/viewport.js, or an inline style={{'--agent': ...}}
    # per agent/thread, or {{'--swatch': ...}} per account color swatch in
    # AccountSheet.jsx), never declared in a CSS rule, and every real usage
    # of --app-height/--kb already carries its own fallback anyway.
    js_only = {"agent", "app-height", "kb", "swatch"}
    missing = used_no_fallback - declared - js_only
    assert not missing, (
        f"these CSS custom properties are referenced with no fallback and "
        f"never declared anywhere, an unresolved var() with no fallback "
        f"silently computes to nothing: {sorted(missing)}"
    )


def test_the_mobile_nav_is_only_ever_hidden_by_a_min_width_query():
    """The bug that gave the phone NO navigation at all.

    `.nav-mobile { display: none }` sat as a bare rule AFTER the
    `@media (max-width: 900px)` block that showed it. Equal specificity, so
    source order decided: and the bar was hidden at every width. Nothing about
    the build, the tests, or the desktop UI changed. Only the phone died.
    """
    for cond, body in _blocks(CSS):
        if not re.search(r"\.nav-mobile\s*\{[^}]*display:\s*none", body):
            continue
        assert cond and cond.startswith("@media"), (
            "a bare rule hides .nav-mobile, it will override the media query "
            "that shows it and the phone will have no navigation"
        )
        assert "min-width" in cond, (
            f"the mobile bar may only be hidden by a min-width query, got: {cond}"
        )


def test_no_bare_100vh_anywhere():
    """iOS Safari's 100vh is the viewport with the URL bar HIDDEN, taller than
    what you can see, so the bottom of the app lands under the toolbar.

    Shell height must go through --app-height (100dvh in Safari, 100vh only
    when the standalone bootstrap flips it). A bare `height: 100vh` without a
    following 100dvh / --app-height override is still banned for non-shell
    rules; shell uses var(--app-height) instead of chaining vh→dvh.
    """
    offenders = []
    for m in re.finditer(r"([\w-]+)\s*:\s*[^;]*\b100vh\b[^;]*;", CSS):
        prop, tail = m.group(1), CSS[m.end():m.end() + 160]
        if re.match(rf"\s*{re.escape(prop)}\s*:\s*[^;]*\b100dvh\b", tail):
            continue
        if re.match(rf"\s*{re.escape(prop)}\s*:\s*[^;]*--app-height", tail):
            continue
        line = CSS[:m.start()].count("\n") + 1
        offenders.append(f"line {line}: {m.group(0).strip()}")
    assert not offenders, "100vh without a 100dvh/--app-height fallback:\n  " + "\n  ".join(offenders)


def test_standalone_pwa_uses_vh_not_dvh_for_shell_height():
    """WebKit #254868: in an installed Home Screen app, 100dvh is short by
    ~safe-area-inset-top and leaves a black band under the tab bar. 100vh is
    the full screen. CSS defaults --app-height to 100dvh; index.html +
    viewport.js flip it to 100vh when navigator.standalone is true.
    """
    assert "--app-height" in CSS
    assert "height: var(--app-height" in CSS or "height:var(--app-height" in CSS.replace(" ", "")
    html = (Path(__file__).resolve().parent.parent / "dashboard" / "index.html").read_text()
    assert "navigator.standalone" in html and "--app-height" in html and "100vh" in html
    vp = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
          / "lib" / "viewport.js").read_text()
    assert "100vh" in vp and "navigator.standalone" in vp
    # The old "pull the bar with negative bottom" hack must stay gone.
    assert "--nav-shift" not in CSS


def test_mobile_tab_bar_paints_the_home_indicator_band():
    """Tab icons sit in --nav-h; env(safe-area-inset-bottom) pads under them so
    the bar background reaches the physical bottom (no black hole)."""
    mobile = "".join(b for c, b in _blocks(CSS)
                     if c and "max-width" in c and "900px" in c)
    # Pinned to the bottom. SPEC-v26 made that "0px, plus the keyboard inset
    # when one is up", which still resolves to 0 with no keyboard.
    assert re.search(
        r"\.nav-mobile\s*\{[^}]*bottom:\s*(0|var\(--kb,\s*0px\))", mobile,
    ), "nav not pinned to the bottom"
    assert "safe-area-inset-bottom" in mobile, "nav does not paint the home-indicator band"


@pytest.mark.parametrize("selector", [".btn", ".action-btn", ".nav-mobile .nav-link"])
def test_primary_controls_meet_the_44px_touch_minimum(selector):
    """Apple's HIG minimum. A 17px tall primary action is a miss, not a tap."""
    mobile = "".join(b for c, b in _blocks(CSS)
                     if c and "max-width" in c and "900px" in c)
    pattern = re.escape(selector).replace(r"\ ", r"\s+")
    rule = re.search(rf"[^{{}}]*{pattern}[^{{}}]*\{{[^}}]*min-height:\s*44px", mobile)
    assert rule, f"{selector} has no 44px minimum inside the mobile breakpoint"


def test_no_padding_shorthand_ever_drops_the_safe_area_insets():
    """The defect that broke the INSTALLED app while the website looked fine.

    A `.app-main { padding: a b c }` override inside the mobile breakpoint wiped
    all four `env(safe-area-inset-*)` values. In a Safari tab that costs nothing
   , the browser chrome owns the notch, so inset-top is 0. Installed
    standalone with viewport-fit=cover the web view runs under the status bar,
    and the first line of the page renders beneath the clock.

    Any rule that sets padding on a full-bleed container must keep the insets.
    """
    for cond, body in _blocks(CSS):
        rules = re.findall(r"([^{}]*)\{([^}]*)\}", body) or [(cond or "", body)]
        for selector, decls in rules:
            if not re.search(r"\.app-(main|shell)\b", selector):
                continue
            pad = re.search(r"(?<![\w-])padding\s*:\s*([^;]+);", decls)
            if pad and "safe-area-inset-top" not in pad.group(1):
                pytest.fail(
                    f"{selector.strip()} sets padding without safe-area insets "
                    f"({pad.group(1).strip()!r}), the installed app will render "
                    f"under the notch"
                )


def test_swipe_leaves_the_screen_edges_to_ios():
    """An installed PWA still gets iOS's back/forward edge gesture. If ianOS
    claimed the full width the two would fight, so a swipe starting in the outer
    band is ignored, we take the middle, iOS keeps the rails (SPEC-v10 §2.2)."""
    src = (Path(__file__).resolve().parent.parent
           / "dashboard" / "src" / "lib" / "swipe.js").read_text()
    assert re.search(r"EDGE\s*=\s*\d+", src), "no edge exclusion band"
    assert "window.innerWidth - EDGE" in src, "the right edge is not excluded"
    assert "startsInHorizontalScroller" in src, (
        "a swipe beginning inside a sideways scroller must belong to that scroller"
    )


def test_committed_modes_cannot_be_swiped_out_of():
    """call-mode and journal-mode are deliberate, committed surfaces. Leaving
    one by accident mid-call, or mid-exhale, is the worst thing the gesture
    could do, so it is disabled there."""
    app = (Path(__file__).resolve().parent.parent
           / "dashboard" / "src" / "App.jsx").read_text()
    at = app.find("pillarSwipeHandlers(")
    assert at != -1, "swipe handlers are not wired up"
    args = app[at:at + 260]
    assert "journalComposing" in args and "callMode" in args, (
        f"swipe must be disabled in committed modes, got: {args}"
    )


def test_the_day_command_is_not_pushed_below_the_action_rail():
    """`.command-rail { order: -1 }` hoisted the action list above the hero on a
    phone, which put the Day Command at y=1012 on a 667px screen, the one
    sentence the product exists to deliver, a thousand pixels down, under a
    strip that repeats the tab bar (SPEC-v10 §3, L4)."""
    for cond, body in _blocks(CSS):
        if not cond or "max-width" not in cond:
            continue
        m = re.search(r"\.command-rail\s*\{([^}]*)\}", body)
        if m and re.search(r"order:\s*-\d", m.group(1)):
            pytest.fail(
                f"{cond} hoists .command-rail above the hero, the Day Command "
                f"ends up below the fold"
            )


def test_command_uses_compiled_attention_and_caps_secondary_items():
    """Command renders the compiler result; React must not grow a second ranker."""
    page = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
            / "pages" / "CommandPage.jsx").read_text()
    stack = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
             / "components" / "ActionStack.jsx").read_text()
    app = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
           / "App.jsx").read_text()
    assert "state.attention" in page
    assert "SIGNAL_RANK" not in page
    assert "resolveExecute" not in page
    assert "/api/day" not in page
    assert "sessionKind" not in stack
    assert re.search(r"\.slice\(0,\s*3\)", stack), "secondary attention is not capped"
    assert "proposal_decision" in stack and "Review proposal" in stack
    assert "onNavigate(item.route)" in stack
    assert "onDecide" not in stack, "Command must not become a second decision surface"
    assert "/api/proposals/" not in stack, "Command must not fetch private proposal detail"
    assert "attachment" not in stack, "long draft bodies must stay out of Command"
    assert "attentionFresh={!stale}" in app, "cached attention is not identified"
    assert "ACTIVITY_FIELDS" in stack and "queueable: true" in stack


def test_proposal_drafts_are_private_inert_and_inbox_only():
    """State carries a chip; the Inbox explicitly fetches and renders plain text."""
    app = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
           / "App.jsx").read_text()
    draft = app[app.index("function ProposalDraft"):app.index("function Proposals")]
    assert "Draft attached" in draft
    assert "{ cache: 'no-store' }" in draft
    assert "navigator.clipboard.writeText" in draft and "Copy draft" in draft
    assert "Records approval. Does not send this draft." in draft
    for unsafe in ("dangerouslySetInnerHTML", "mailto:", "href=", "provider"):
        assert unsafe not in draft, f"draft UI exposes active content: {unsafe}"


def test_hard_to_reverse_approval_requires_the_second_control():
    """The `a` key opens confirmation and can never submit hard approval itself."""
    app = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
           / "App.jsx").read_text()
    proposals = app[app.index("function Proposals"):app.index("function ClampedText")]
    assert "proposal.reversibility === 'hard_to_reverse'" in proposals
    assert "setConfirmingId(proposal.id)" in proposals
    assert "if (p) requestApproval(p)" in proposals
    assert "confirmed_hard_to_reverse: true" in proposals
    assert "Confirm approval" in proposals and "ref={confirmRef}" in proposals
    assert "Evidence: {evidence.join(', ')}" in app
    assert "item.label.trim()" in app, "evidence objects may expose labels only"


def test_proposal_controls_have_real_44px_targets():
    for selector in (".prop-draft-toggle", ".prop-copy-draft", ".prop-hard-confirm .btn"):
        rule = re.search(rf"{re.escape(selector)}[^{{}}]*\{{[^}}]*(?:min-)?height:\s*44px", CSS)
        assert rule, f"{selector} has no real 44px hit target"


def test_partner_consumers_use_the_server_summary():
    """Badges and subtitles must share the backend's actionable-leaf count.

    Counting unfinished rows in React double-counts an outcome while one of its
    steps is still open, so App may only project ``partner_summary.open_count``.
    """
    app = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
           / "App.jsx").read_text()
    page = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
            / "pages" / "PartnerPage.jsx").read_text()
    assert "state.partner_summary?.open_count" in app
    assert "summary={state.partner_summary}" in app
    assert "filter((t) => !t.done).length" not in app
    assert "summary?.open_count" in page


def test_partner_steps_are_one_level_accessible_and_reversible():
    """The light one-level list needs explicit hierarchy and safe removal."""
    page = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
            / "pages" / "PartnerPage.jsx").read_text()
    api = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
           / "lib" / "api.js").read_text()
    assert "aria-expanded={expanded}" in page and "aria-controls={panelId}" in page
    assert "Mark ${kindLabel} done" in page
    assert "parent._pending" in page and "Sync to add steps" in page
    assert "/archive/${batchId}/restore" in page and "queueable: true" in page
    assert "archive_batch_id" in page and "toast(" in page
    assert "mutation_id: mutation.mutation_id" in api, (
        "offline archive must expose its stable receipt id so Undo can target the same batch"
    )


def test_partner_controls_have_real_44px_targets():
    """Hierarchy controls are used with one thumb, at every viewport width."""
    for selector in (".partner-check", ".partner-delete", ".partner-disclosure",
                     ".partner-add-step", ".partner-done-toggle"):
        pattern = re.escape(selector)
        rule = re.search(rf"{pattern}[^{{}}]*\{{[^}}]*(?:min-)?height:\s*44px", CSS)
        assert rule, f"{selector} has no real 44px hit target"


def test_ask_agent_mobile_sheet_is_single_column_and_thumb_safe():
    mobile = "".join(b for c, b in _blocks(CSS)
                     if c and "max-width" in c and "900px" in c)
    assert re.search(r"\.ask-agent-actions\s*\{[^}]*grid-template-columns:\s*1fr", mobile)
    assert re.search(r"\.ask-room-options\s*\{[^}]*grid-template-columns:\s*1fr", mobile)
    assert "safe-area-inset-bottom" in mobile
    for selector in (".sheet-close", ".ask-agent-more", ".agent-ask", ".command-ask"):
        rule = re.search(rf"{re.escape(selector)}[^{{}}]*\{{[^}}]*(?:min-)?height:\s*44px", CSS)
        assert rule, f"{selector} has no 44px target"
    for selector in (".ask-agent-mode button", ".ask-room-option", ".ask-room-contribution summary"):
        rule = re.search(rf"{re.escape(selector)}[^{{}}]*\{{[^}}]*min-height:\s*(\d+)px", CSS)
        assert rule and int(rule.group(1)) >= 44, f"{selector} has no 44px target"


def test_plaid_money_connection_is_explicit_online_only_and_oauth_resumable():
    root = Path(__file__).resolve().parent.parent / "dashboard" / "src"
    money = (root / "pages" / "MoneyPage.jsx").read_text()
    plaid = (root / "lib" / "plaid.js").read_text()
    assert "Connect Chase" in money and "Connect Capital One" in money
    # SPEC-v24 BUILD 3 replaced the separate "Connected portfolio" /
    # "Connected cash & cards" cards with one grouped account list built
    # from financial_accounts (see groupForAccount).
    assert "financial_accounts" in money and "Linked accounts" in money
    assert "groupForAccount" in money
    assert "resumePlaidLink" in money and "startPlaidLink" in money
    assert "queueable" not in plaid, "bank credentials must never enter the offline queue"
    assert "receivedRedirectUri" in plaid and "oauth_state_id" in plaid
    assert "public_token" in plaid and "access_token" not in plaid
    for selector in (".money-connect summary", ".money-connect-actions .btn"):
        rule = re.search(rf"{re.escape(selector)}[^{{}}]*\{{[^}}]*(?:min-)?height:\s*44px", CSS)
        assert rule, f"{selector} has no 44px target"


def test_editing_a_target_does_not_require_the_whole_goal_form():
    """Changing a number was a trip through the full form. The number itself is
    now the control, and it PATCHes only `target`, sending the whole goal back
    would let a stale field in the form clobber something you never touched."""
    src = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
           / "components" / "goals" / "PillarGoalPanel.jsx").read_text()
    assert "InlineTarget" in src
    patch = re.search(r"api\(`/api/goals/\$\{goal\.id\}`,\s*'PATCH',\s*\{([^}]*)\}", src)
    assert patch, "InlineTarget does not PATCH the goal"
    assert patch.group(1).strip().startswith("target"), (
        f"only the target should travel, got: {patch.group(1).strip()}"
    )


def test_goal_panel_is_a_component_not_a_nested_page_root():
    """Goal panels appear both as a whole Life surface and inside larger pages.
    Their reusable wrapper must expose component hooks without inheriting the
    width and spacing contract of a second page root."""
    src = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
           / "components" / "goals" / "PillarGoalPanel.jsx").read_text()
    assert 'className="pillar-goal-panel"' in src
    assert 'className="panel pillar-goal-panel__surface"' in src
    assert 'className="page-stack"' not in src


def test_plan_creates_a_block_where_you_tapped():
    """Tapping 9:40 and getting 09:00 means correcting every block you make."""
    src = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
           / "pages" / "PlanPage.jsx").read_text()
    assert re.search(r"Math\.round\(y\s*/\s*PX\s*/\s*15\)\s*\*\s*15", src), (
        "the create tap does not snap to 15-minute precision"
    )


def test_dragging_a_block_needs_a_long_press_and_can_stop_the_scroll():
    """A vertical calendar and a vertical scroller want the same gesture.

    Two things resolve it, and losing either breaks Plan on a phone: a block is
    picked up only after a long press (so an ordinary drag still scrolls), and
    the touchmove listener is non-passive (only a non-passive listener may
    preventDefault, without which the ribbon scrolls out from under the block
    you are dragging). SPEC-v10 §4.1.
    """
    src = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
           / "pages" / "PlanPage.jsx").read_text()
    assert re.search(r"LONG_PRESS_MS\s*=\s*\d+", src), "no long-press gate"
    assert re.search(r"addEventListener\(\s*'touchmove',[^)]*passive:\s*false", src), (
        "touchmove is passive: preventDefault will be ignored and the ribbon "
        "will scroll while you drag"
    )
    assert "preventDefault()" in src


def test_a_drag_never_also_opens_the_edit_sheet():
    """The block is a <button>; finishing a drag on it still fires click."""
    src = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
           / "pages" / "PlanPage.jsx").read_text()
    assert "suppressClick" in src


def test_agent_identity_lives_in_exactly_one_place():
    """Colour and glyph come from lib/agents.js so an agent looks the same on a
    memo, a proposal and its roster card. App.jsx used to keep a private copy of
    the colour table, which is how two of them silently drift apart."""
    src = (Path(__file__).resolve().parent.parent / "dashboard" / "src")
    agents = (src / "lib" / "agents.js").read_text()
    assert "export const ROLE_COLORS" in agents and "export const ROLE_GLYPHS" in agents
    for f in ("App.jsx", "components/RoleTag.jsx"):
        text = (src / f).read_text()
        assert "roleColor" in text, f"{f} does not use the shared colour"
        assert "const ROLE_COLORS" not in text, f"{f} keeps its own colour table"


def test_the_roster_never_scores_ian():
    """The record is the AGENT's: 'you took 2 of 4' is about its advice, not
    about him. No percentage, no streak, nothing that reads as a verdict on Ian
    (the same law the gym streak and The Line are built on)."""
    page = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
            / "pages" / "RosterPage.jsx").read_text()
    assert "%" not in page.split("*/")[-1], "a percentage leaked into the roster UI"
    assert "--crit" not in page


def test_the_osui_skill_stays_in_step_with_the_gates():
    """The skill is the design law an agent reads before touching the UI. If it
    drifts from the tests, it becomes confident, well-written misinformation."""
    skill = (Path(__file__).resolve().parent.parent
             / ".claude" / "skills" / "osui" / "SKILL.md").read_text()
    assert skill.startswith("---") and "name: osui" in skill, "missing frontmatter"
    for law in ("100dvh", "min-width", "safe-area-inset", "--nav-h",
                "44", "overscroll-behavior-y", "!!", "prefers-reduced-motion"):
        assert law in skill, f"the skill no longer mentions {law!r}"
    # the inherited product law it must never let anyone weaken
    for inherited in ("--crit", "journal", "agents", "streak"):
        assert inherited in skill, f"the skill dropped inherited law: {inherited!r}"
    assert "375" in skill and "667" in skill, "the fold target is unstated"
    assert "em dash" in skill.lower() or "Anti-slop" in skill, (
        "the skill must state the anti-slop / no-em-dash copy law"
    )


def test_dashboard_has_no_em_dashes():
    """PRODUCT.md Voice + docs/ANTI-SLOP.md: em dashes are banned in UI source."""
    root = Path(__file__).resolve().parent.parent / "dashboard" / "src"
    offenders = []
    for p in root.rglob("*"):
        if p.suffix not in {".jsx", ".js", ".css"}:
            continue
        text = p.read_text(encoding="utf-8")
        if "\u2014" in text or "\u2013" in text:
            offenders.append(str(p.relative_to(root.parent.parent)))
    assert not offenders, f"em/en dashes in UI source: {offenders}"


def test_a_row_that_owns_horizontal_gestures_opts_out_of_the_pillar_swipe():
    """Two horizontal gestures on the same pixel is one gesture too many. A goal
    row marks itself `data-swipe-own` so the pillar ring ignores touches that
    start there, otherwise one drag both opens the row and changes pillar."""
    swipe = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
             / "lib" / "swipe.js").read_text()
    assert "swipeOwn" in swipe, "the ring has no opt-out for gesture-owning rows"
    panel = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
             / "components" / "goals" / "PillarGoalPanel.jsx").read_text()
    assert "data-swipe-own" in panel, "the goal row does not claim its gestures"


def test_retiring_a_goal_is_reversible():
    """A swipe is a thumb-slip away from a tap, so what hangs off it may not be
    a hard DELETE. Archive is a flag with an Undo, and Undo must restore the
    SAME row: metrics resolve off goal ids, so re-creating one is not a restore."""
    panel = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
             / "components" / "goals" / "PillarGoalPanel.jsx").read_text()
    assert "/archive" in panel, "the row swipe does not use the archive endpoint"
    assert "'DELETE'" not in panel, "a destructive delete is wired to the swipe"
    assert "restore=true" in panel, "archive has no undo"

    api_src = (Path(__file__).resolve().parent.parent / "api" / "main.py").read_text()
    assert "/api/goals/{goal_id}/archive" in api_src


def test_archived_goals_are_hidden_from_everything_at_once():
    """all_goals is the single read path: /api/state, metrics, pillars and the
    agents' read_goals. Filtering there hides a retired goal everywhere,
    including from the nightly run, rather than in each caller separately."""
    db_src = (Path(__file__).resolve().parent.parent / "core" / "db.py").read_text()
    fn = db_src[db_src.index("def all_goals("):]
    fn = fn[:fn.index("\ndef ", 1)]
    assert "archived" in fn, "all_goals still returns archived goals"


def test_notes_use_one_component_at_every_width():
    """The desktop two-pane is an enhancement of the same markup (L1), not a
    second layout. An earlier pass deferred it by misreading that law."""
    page = (Path(__file__).resolve().parent.parent / "dashboard" / "src"
            / "pages" / "NotesPage.jsx").read_text()
    assert "notes-list-pane" in page and "notes-editor-pane" in page
    css = CSS
    two_pane = [b for c, b in _blocks(css)
                if c and "min-width" in c and "notes-page" in b]
    assert two_pane, "no min-width rule builds the two-pane layout"


def test_a_goal_title_is_not_starved_by_its_meter():
    """220px of meter in a 261px row left 25px for the name, and 'Gym every
    weekday' wrapped to one word per line, 60px tall."""
    mobile = "".join(b for c, b in _blocks(CSS)
                     if c and "max-width" in c and "900px" in c)
    rule = re.search(r"\.goal-row\s*\{[^}]*grid-template-columns:\s*([^;]+);", mobile)
    assert rule, "no mobile column rule for .goal-row"
    assert "meter-w" not in rule.group(1), (
        f"the meter still takes a fixed column on mobile: {rule.group(1).strip()}"
    )


def test_the_single_scroller_does_not_chain():
    """The app shell is one viewport with .page-content scrolling inside it
    (SPEC-v10 §9.6). Without overscroll containment the scroll chains to the
    page behind at the ends, which on iOS reads as the app coming apart."""
    assert re.search(r"\.page-content\s*\{[^}]*overscroll-behavior-y:\s*contain", CSS)


def test_agent_chat_is_the_command_surface():
    """SPEC-v29: chat is shell-mounted chrome (mounted once in App.jsx,
    sibling to Nav and the toast stack), never a page and never inline on
    Command. It survives every tab switch because it was never inside a
    page's own lifecycle to begin with; Command only hosts the trigger."""
    root = Path(__file__).resolve().parent.parent / "dashboard" / "src"
    app = (root / "App.jsx").read_text()
    nav = (root / "components" / "Nav.jsx").read_text()
    command = (root / "pages" / "CommandPage.jsx").read_text()

    # It stopped being a page: no route, no nav entry, no stale title.
    assert "'chat'" not in app.split("const PAGES")[1].split("]")[0]
    assert "id: 'chat'" not in nav
    assert "'chat'" not in nav.split("ALL_MOBILE_MORE")[1].split("]")[0]
    assert "Daytime consult" not in app
    # The old route still lands somewhere sane instead of 404ing to home by
    # accident, and the five-tab law is untouched.
    assert "h === 'chat'" in app and "return 'home'" in app
    assert "TAB_PAGES" in app
    assert "'chat'" not in app.split("TAB_PAGES")[1].split("]")[0]
    # Command hosts the trigger, not the conversation; AgentChat mounts once
    # at the shell level, outside any page's own render tree.
    assert "<AgentChat" not in command and "onOpenChat" in command
    assert "<AgentChat" in app
    assert (root / "components" / "AgentChat.jsx").exists()
    assert not (root / "pages" / "ChatPage.jsx").exists()


def test_chat_composer_is_thumb_safe_and_does_not_choose_a_free_model():
    root = Path(__file__).resolve().parent.parent / "dashboard" / "src"
    page = (root / "components" / "AgentChat.jsx").read_text()
    assert "Money" in page and "Mail" in page and "Calendar" in page
    # All four plan models are offered; none is invented client-side.
    for label in ("Haiku", "Sonnet", "Opus", "Fable"):
        assert label in page
    # SPEC-v27: effort is a real control, and xhigh is deliberately absent
    # because it falls back silently on most models.
    for label in ("Low", "Medium", "High", "Max"):
        assert label in page
    assert "xhigh" not in page
    assert "<select" not in page
    assert "queueable" not in page
    assert "rememberActiveChatTurn" in page
    assert "That turn expired. Ask again." in page
    assert "cost_usd" not in page
    # SPEC-v29 Phase 3: focus-trapping moved into the shared Sheet primitive
    # (asserted directly on Sheet.jsx in test_ask_agent_dialog_is_resumable_
    # accessible_and_safe); AgentChat's own sheets render through it instead
    # of duplicating a useFocusTrap call.
    assert "import Sheet from './Sheet.jsx'" in page
    assert "ContextSheet" in page and "ReasoningSheet" in page and "FileDraftDialog" in page
    # SPEC-v27 moved the field inside the composer pill.
    textarea = re.search(r"\.ac-bar textarea\s*\{[^}]*font-size:\s*16px", CSS)
    assert textarea, "chat textarea must be 16px so iOS does not zoom-jack"
    send = re.search(r"\.ac-send\s*\{[^}]*height:\s*44px", CSS)
    assert send, "chat send is not a 44px target"
    # The flex column must pin every non-scroller child, or chip rows
    # collapse around their own contents (osui traps table).
    # SPEC-v40: the flex column is .consult-panel (.agent-chat rendered nowhere).
    assert re.search(r"\.consult-panel\s*>\s*\.ac-dock\s*\{[^}]*flex:\s*0\s+0\s+auto", CSS)
    assert not re.search(r"\.agent-chat\s*[>{,.:]", CSS), "no rule may target the dead .agent-chat class"
    assert re.search(r"\.ac-stream\s*\{[^}]*overflow-y:\s*auto", CSS)
    assert "prefers-reduced-motion" in CSS
    for cond, body in _blocks(CSS):
        if re.search(r"\.nav-mobile\s*\{[^}]*display:\s*none", body):
            assert cond and "min-width" in cond
    # A failed turn softens; it never reddens (inherited product law).
    # SPEC-v27 gave every agent its identity colour on this surface, and
    # Hermione's identity colour IS --crit everywhere else in the product.
    # The only permitted mention is the guard that maps her away from it.
    # Comments explaining the guard are fine; what must not exist is crit
    # being APPLIED, so only the comparison that maps it away may reference it.
    code = [
        ln for ln in page.splitlines()
        if "--crit" in ln and not ln.lstrip().startswith(("*", "/*", "//"))
    ]
    assert code == ["  return raw === 'var(--crit)' ? '#fbbf24' : raw"], code
    assert "chatRoleColor" in page
    assert "mailto:" not in page


def test_command_grid_stays_permanently_visible():
    """SPEC-v29: Command reverted to the grid. The Order hero and the
    ActionStack/PillarStrip rail are both unconditionally visible, no
    collapsing disclosure hides either one (the "old version" Ian named as
    liked), and chat is no longer mounted inline on this page at all."""
    root = Path(__file__).resolve().parent.parent / "dashboard" / "src"
    command = (root / "pages" / "CommandPage.jsx").read_text()
    assert "command-grid" in command and "command-hero" in command and "command-rail" in command
    assert "<ActionStack" in command and "<PillarStrip" in command
    # ActionStack/PillarStrip are unconditional siblings, never behind the
    # collapsing "Today" disclosure SPEC-v26 introduced and SPEC-v29 removed.
    assert "<details" not in command
    assert "cmd-pin" not in command and "cmd-today" not in command
    assert "command-chat-page" not in command
    assert "<AgentChat" not in command


def test_fixed_tab_bar_rides_the_keyboard_inset():
    """SPEC-v26: the bar is fixed to the LAYOUT viewport, which iOS does not
    shrink for the keyboard. Without the inset it parks behind the keyboard
    the moment Ian types, which reads as a bar that is not really fixed."""
    root = Path(__file__).resolve().parent.parent / "dashboard"
    html = (root / "index.html").read_text()
    viewport = (root / "src" / "lib" / "viewport.js").read_text()

    # Declarative fix first, for browsers that honour it.
    assert "interactive-widget=resizes-content" in html
    # Measured fallback for the ones that do not (iOS Safari).
    assert "visualViewport" in viewport and "--kb" in viewport
    # The cold-start gap fix must not be re-broken by syncing app height.
    assert "root.style.setProperty('--app-height', '100vh')" in viewport

    # The bar and the shell both consume the inset.
    nav_rule = re.search(r"\.nav-mobile\s*\{[^}]*\}", CSS, re.S)
    assert nav_rule and "bottom: var(--kb, 0px)" in nav_rule.group(0)
    shell = re.search(r"\.app-shell\s*\{[^}]*\}", CSS, re.S)
    assert shell and "var(--kb, 0px)" in shell.group(0)


def test_chat_surface_carries_the_agent_identity_colour():
    """SPEC-v27: the room takes the colour of whoever is answering.

    ianOS already had a colour per agent and spent it on one glyph. Letting
    it wash the surface is the fastest answer to "who am I talking to",
    which is the question an distractible user asks after every interruption.
    """
    root = Path(__file__).resolve().parent.parent / "dashboard" / "src"
    page = (root / "components" / "AgentChat.jsx").read_text()

    # The surface and both portaled sheets receive the colour; a sheet is
    # portaled to body, so it cannot inherit it.
    assert "'--agent': chatRoleColor(role)" in page
    assert page.count("'--agent': accent") >= 2

    # Colour is spent on the parts that answer a question, not sprinkled.
    for selector in (".ac-said", ".ac-send", ".ac-plus", ".ac-verdict", ".ac-empty-mark"):
        assert selector in CSS, selector
    assert "--agent-soft" in CSS and "--agent-line" in CSS

    # Motion explains or it goes: every new animation has a reduced-motion
    # answer, and the colour survives it because colour carries meaning.
    reduced = "".join(b for c, b in _blocks(CSS) if c and "prefers-reduced-motion" in c)
    for cls in ("ac-empty-mark", "ac-plus-count"):
        assert cls in reduced, cls
    # The surface-change budget is 320ms and state is 200ms (osui L7).
    assert "320ms" in CSS and "200ms" in CSS
    assert not re.search(r"\.ac-[a-z-]+\s*\{[^}]*transition:[^;}]*\b([6-9]\d\d|\d{4,})ms", CSS), \
        "chat motion must stay inside the osui budget"


def test_chat_borders_use_the_hairline_token_not_the_line_brand():
    """--line is The Line's brand colour (SPEC-v9), not a hairline.

    Its name reads like a border token, and using it as one paints every
    divider in saturated accent blue. The hairline is --glass-border.
    """
    root = Path(__file__).resolve().parent.parent / "dashboard" / "src"
    css = (root / "styles.css").read_text()
    chat_css = css[css.index("/* ── SPEC-v26 Agent Chat"):]
    assert "var(--line)" not in chat_css, (
        "chat CSS must use var(--glass-border) for hairlines"
    )
    assert "var(--glass-border)" in chat_css
    # The token still means what SPEC-v9 made it mean.
    assert "--line: #6ea8ff" in css
    assert "--line-glow" in css and "--line-soft" in css


def test_school_notes_have_a_real_fullscreen_writing_mode():
    """The School editor must fill the app, remain escapable, and keep one
    continuous scroller with room below the last typed line."""
    root = Path(__file__).resolve().parent.parent / "dashboard" / "src"
    page = (root / "pages" / "SchoolNotebookPage.jsx").read_text()
    app = (root / "App.jsx").read_text()

    # Arrange / Act: inspect the shipped route and its responsive contract.
    # Assert: the control has a state for assistive tech and Escape always
    # restores the surrounding dashboard.
    assert "aria-pressed={fullScreen}" in page
    assert "event.key === 'Escape' && fullScreen" in page
    assert "classList.toggle('school-note-fullscreen', active)" in page
    assert "page !== 'schoolnotebook'" in app

    # Fullscreen changes the app topology, not only the note's internal grid.
    assert re.search(
        r"body\.school-note-fullscreen \.app-shell\s*\{[^}]*grid-template-columns:\s*1fr",
        CSS,
    )
    assert re.search(
        r"body\.school-note-fullscreen \.nav-wrap,[^}]*display:\s*none",
        CSS,
        re.S,
    )
    full_main = re.search(r"body\.school-note-fullscreen \.app-main\s*\{[^}]*\}", CSS, re.S)
    assert full_main and "safe-area-inset-top" in full_main.group(0)
    assert "school-note-fullscreen-button { display: inline-flex" in CSS

    # Long documents scroll inside the writer and retain a visible runway
    # after the last paragraph instead of ending at the viewport edge.
    writer_rules = re.findall(r"\.school-note-writing\s*\{[^}]*\}", CSS, re.S)
    surface_rules = re.findall(r"\.school-note-editor-surface\s*\{[^}]*\}", CSS, re.S)
    toolbar_rules = re.findall(r"\.school-note-toolbar\s*\{[^}]*\}", CSS, re.S)
    assert any("overflow-y: auto" in rule for rule in writer_rules)
    assert any("scroll-padding-block-end: 28vh" in rule for rule in writer_rules)
    assert any("30vh" in rule for rule in surface_rules)
    assert any("position: sticky" in rule for rule in toolbar_rules)


def test_school_note_copy_is_direct_and_not_motivational():
    root = Path(__file__).resolve().parent.parent / "dashboard" / "src"
    page = (root / "pages" / "SchoolNotebookPage.jsx").read_text()
    # The placeholder text moved into schema.js in 2026-09 when it became a
    # Tiptap decoration instead of an element stacked over the prose; both
    # files are the writing surface's copy as far as this rule is concerned.
    editor = (
        (root / "components" / "school-notes" / "SchoolNoteEditor.jsx").read_text()
        + (root / "components" / "school-notes" / "schema.js").read_text()
    )

    assert "Start typing." in editor
    for phrase in (
        "Ready for this week’s work?",
        "Your next class note starts here.",
        "Start with a light structure",
        "Capture the class. Keep it rough",
        "Wrap class",
        "Class pulse",
    ):
        assert phrase not in page and phrase not in editor


def test_school_note_hardening_keeps_controls_and_recovery_reachable():
    """The writing surface must stay usable with overlays, long text, and
    narrow touch screens instead of only working for the happy-path note."""
    root = Path(__file__).resolve().parent.parent / "dashboard" / "src"
    page = (root / "pages" / "SchoolNotebookPage.jsx").read_text()
    editor = (root / "components" / "school-notes" / "SchoolNoteEditor.jsx").read_text()

    # Arrange / Act: inspect the shipped composition and responsive contract.
    # Assert: an open Sheet owns the first Escape, and the note itself has one
    # screen-reader heading rather than becoming a nested main landmark.
    assert "fullScreen && !pulseOpen && !fileShelfOpen && !studyShelfOpen" in page
    assert '<section className="school-note-writing" aria-labelledby="school-note-heading">' in page
    assert '<h1 className="sr-only" id="school-note-heading">' in page
    assert '<main className="school-note-writing">' not in page
    assert 'className="school-note-save-error" role="alert"' in page

    # Insert remains visible while the larger formatting strip scrolls; its
    # popover is no longer inside the clipping container.
    assert 'className="school-note-toolbar-scroll"' in editor
    assert 'className="school-note-insert-menu"' in editor
    assert ".school-note-toolbar-scroll" in CSS
    assert ".school-note-toolbar {" in CSS and "overflow: visible" in CSS

    # Phone writing hides the unreachable tab bar, keeps a persistent exit
    # row in fullscreen, and breaks unbroken pasted strings instead of
    # widening the writing surface.
    assert "body.school-note-editing .nav-mobile { visibility: hidden;" in CSS
    assert "body.school-note-fullscreen .school-note-mobile-actions" in CSS
    assert CSS.count("overflow-wrap: anywhere") >= 2


def test_header_has_no_clock_or_focus_chips():
    """SPEC-v41 §2.1/§2.5: the header strip (status dot, clock, focus chips,
    the "Nd to client" countdown, "Agents ran Xm ago") is deleted outright,
    not hidden, replaced by the day arc + agent pulse."""
    app = (Path(__file__).resolve().parent.parent / "dashboard" / "src" / "App.jsx").read_text()
    for banned in ("function Clock(", "function LastAgentRun(", "function FocusChips(", "daysToClient"):
        assert banned not in app, f"{banned} still in App.jsx"
    for selector in (r"\.clock\s*\{", r"\.focus-chip", r"\.countdown\s*\{",
                      r"\.sys-dot\s*\{", r"\.agent-run-hint\s*\{"):
        assert not re.search(selector, CSS), f"{selector} still in styles.css"


def test_pulse_never_crit():
    """SPEC-v41 §2.3: the pulse is on every page including Plan/Journal/The
    Line, where --crit is banned; its worst state is --warn."""
    js = (Path(__file__).resolve().parent.parent / "dashboard" / "src" / "lib" / "dayArc.js").read_text()
    assert "crit" not in js


_TAGLINE_PATTERNS = [
    re.compile(r"\bone place for\b", re.I),
    re.compile(r"\bone workspace\b", re.I),
    re.compile(r"\bat a glance\b", re.I),
    re.compile(r",\s*one\s+.*?\s+at a time", re.I),
    re.compile(r"\bworkspace for the\b", re.I),
    re.compile(r"\beverything else\b", re.I),
]
_TAGLINE_ARRAY_SUFFIXES = ("WHISPERS", "MOTTOS", "TAGLINES")


def _strip_js_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def test_no_taglines():
    """SPEC-v41 §3.3: the executable version of "no taglines" (osui skill,
    CLAUDE.md anti-slop). A tripwire, not a linter, on the constructions that
    have actually shipped here."""
    root = Path(__file__).resolve().parent.parent / "dashboard" / "src"
    offenders = []
    for p in root.rglob("*.jsx"):
        text = _strip_js_comments(p.read_text(encoding="utf-8"))
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern in _TAGLINE_PATTERNS:
                if pattern.search(line):
                    offenders.append(f"{p.relative_to(root.parent.parent)}:{lineno}: {line.strip()}")
            m = re.search(r"\b([A-Z_]+)\s*=\s*\[", line)
            if m and m.group(1).endswith(_TAGLINE_ARRAY_SUFFIXES):
                offenders.append(f"{p.relative_to(root.parent.parent)}:{lineno}: {line.strip()}")
    assert not offenders, f"tagline constructions found: {offenders}"
