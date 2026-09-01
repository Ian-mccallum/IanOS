#!/usr/bin/env python3
"""
enrich_prospects.py, turn the scraped list into a qualified, tiered pipeline.

The scrape answers "who exists and can I reach them". Enrichment answers the
three questions that actually decide where a cold call goes:

    FIT    Can this shop buy, and are they the size that has the problem?
    PAIN   Is there evidence they are losing calls right now?
    REACH  Do I know who to ask for and how to follow up?

Those are scored separately on purpose. A high-fit / low-pain shop is a
different conversation from a high-pain / low-fit one, and blending them into
a single number hides which call to make.

Everything here is free and comes from the business's own public website plus
the data already in prospects.csv. No paid enrichment API, no key required.

What it pulls off each site:
  * email addresses, ranked (a named owner's inbox beats info@)
  * owner / founder names from schema.org JSON-LD and About-page bylines
  * franchise detection (a SERVPRO branch cannot buy software on its own)
  * COMPETITOR DETECTION - Podium, Broadly, Birdeye, Signpost. If they already
    run a text-back tool, this is a displacement call or a skip, and either way
    you must know before you dial.
  * platform signals (ServiceTitan/Housecall Pro = already automated; Wix or
    GoDaddy = the ICP)
  * "24/7 emergency service" claims, which combined with a miss signal is the
    single strongest pitch in the file: they promise it and do not deliver
  * years in business, socials, extra phone numbers

-- Run -----------------------------------------------------------------------
    python3 growth/enrich_prospects.py               # all rows with a website
    python3 growth/enrich_prospects.py --limit 200   # try it on a slice first
    python3 growth/enrich_prospects.py --no-fetch    # re-tier without refetching

Pages are cached under growth/.cache/, so a second run is nearly instant and
costs the sites nothing.

Outputs, all in growth/:
    enriched.csv        every row, every field, every score
    tier_a_call_first.csv
    tier_b_high_value.csv
    tier_c_working.csv
    tier_d_skip.csv
    email_ready.csv     everything with a usable address, for the cold sequence
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import hashlib
import html
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache")

# Reuse the scraper's name lists and SSL handling rather than duplicating them.
# Loaded by path (not a plain import) so this works from any cwd; argv is
# swapped because the scraper parses args at import time.
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location(
    "scrape_prospects", os.path.join(HERE, "scrape_prospects.py")
)
_sp = _ilu.module_from_spec(_spec)
_sys_argv, sys.argv = sys.argv, ["scrape_prospects"]
_spec.loader.exec_module(_sp)
sys.argv = _sys_argv

FIRST_NAMES = _sp._FIRST_NAMES
NOT_A_NAME = _sp._NOT_A_NAME
SSL_CTX = _sp.SSL_CTX

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"

# ---------------------------------------------------------------------------
# Signal dictionaries
# ---------------------------------------------------------------------------

# A franchise branch runs corporate marketing and cannot buy software on its
# own. Knowing this before you dial saves the call.
FRANCHISE_BRANDS = [
    "servpro", "puroclean", "roto-rooter", "roto rooter", "mr. rooter",
    "mr rooter", "servicemaster", "paul davis", "one hour heating",
    "one hour air", "aire serv", "mister sparky", "benjamin franklin plumbing",
    "rainbow restoration", "rainbow international", "restoration 1",
    "chem-dry", "chemdry", "precision garage door", "precision door",
    "mr. handyman", "mr handyman", "window world", "erie home", "leaffilter",
    "leaf filter", "bath fitter", "911 restoration", "rytech",
    "ace handyman", "dryer vent wizard", "911restoration", "anytime fitness",
    "five star bath", "re-bath", "renewal by andersen", "budget blinds",
    "molly maid", "jan-pro", "wow 1 day painting", "certapro",
    "the grounds guys", "conserva irrigation", "sila", "zoom drain",
    "duraclean", "steamatic", "amerispec", "handyman connection",
    "united water restoration", "next door & window", "sears",
]

# They already bought a missed-call / review / text-back tool. This is the
# most important single field in the file: it converts a cold pitch into a
# displacement pitch, or tells you to walk away.
COMPETITOR_TOOLS = {
    "podium": ["podium.com", "podium.co", "widget.podium", "podiumwidget"],
    "birdeye": ["birdeye.com", "birdeye.co", "bec-widget", "birdeyewidget"],
    "broadly": ["broadly.com", "broadly.co"],
    "signpost": ["signpost.com"],
    "thryv": ["thryv.com"],
    "reviewsonmyweb": ["reviewsonmyweb"],
    "nicejob": ["nicejob.com", "nicejob.co"],
    "swell": ["swellcx.com"],
    "textrequest": ["textrequest.com"],
    "weave": ["getweave.com", "weavehelp"],
    "slicktext": ["slicktext.com"],
    "avochato": ["avochato.com"],
    "numa": ["numa.com"],
    "chatbot/livechat": ["tawk.to", "livechatinc", "tidio", "intercom.io",
                          "drift.com", "olark.com", "purechat"],
}

# Field-service platforms. Not disqualifying, but a shop on ServiceTitan is
# bigger and likelier to have some automation already.
PLATFORMS = {
    "servicetitan": ["servicetitan"],
    "housecallpro": ["housecallpro", "housecall pro"],
    "jobber": ["getjobber", "jobber.com"],
    "fieldedge": ["fieldedge"],
    "servicefusion": ["servicefusion"],
    "workiz": ["workiz"],
}

# Site builders. A bare Wix or GoDaddy site is an unsophisticated shop, which
# is exactly the ICP.
BUILDERS = {
    "wix": ["wix.com", "wixsite", "_wixcssimports"],
    "squarespace": ["squarespace.com", "static1.squarespace"],
    "godaddy": ["godaddy", "websitebuilder", "starfieldtech"],
    "wordpress": ["wp-content", "wp-includes"],
    "weebly": ["weebly.com"],
    "duda": ["dudamobile", "duda.co"],
}

_247_RE = re.compile(
    r"24\s*/\s*7|24-7|24 hours a day|24hr|24 hr|around the clock|"
    r"emergency service|emergency repair|anytime, day or night|"
    r"available (?:24|any ?time)|always (?:available|here|on call)|"
    r"same[- ]day service|nights? (?:and|&) weekends",
    re.I,
)

_SINCE_RE = re.compile(
    r"(?:since|established|est\.?|serving .{0,40}? since|founded in|"
    r"in business since|family owned since)\s*(19[5-9]\d|20[0-2]\d)", re.I
)
_YEARS_RE = re.compile(r"(?:over|more than|nearly)\s+(\d{2})\+?\s+years", re.I)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

_EMAIL_JUNK = (
    "example.com", "domain.com", "yourdomain", "email.com", "sentry",
    "wixpress", "godaddy", "squarespace", "no-reply", "noreply", "donotreply",
    "do-not-reply", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css",
    ".js", "@2x", "u003e", "yoursite", "test@", "abc@", "name@", "@sentry.io",
    "@wordpress", "@example", "core-js", "react", "npmjs",
)

_PERSONAL_INBOX = ("gmail.com", "yahoo.com", "aol.com", "hotmail.com",
                   "outlook.com", "comcast.net", "sbcglobal.net", "att.net",
                   "msn.com", "icloud.com", "live.com", "ameritech.net")

_ROLE_LOCALS = ("info", "office", "contact", "sales", "service", "admin",
                "hello", "support", "help", "team", "customerservice",
                "scheduling", "dispatch", "estimates", "billing", "accounting")

_SOCIAL = {
    "Facebook": re.compile(r"https?://(?:www\.)?facebook\.com/[A-Za-z0-9_.\-/]{3,60}", re.I),
    "Instagram": re.compile(r"https?://(?:www\.)?instagram\.com/[A-Za-z0-9_.\-]{3,40}", re.I),
    "LinkedIn": re.compile(r"https?://(?:www\.)?linkedin\.com/(?:company|in)/[A-Za-z0-9_.\-]{3,60}", re.I),
}

_PHONE_RE = re.compile(r"\(?\b(\d{3})\)?[\s.\-]?(\d{3})[\s.\-]?(\d{4})\b")

# Owner bylines. Same discipline as the scraper: the NAME must be properly
# capitalized, so no global IGNORECASE.
_NAME_TOKEN = r"[A-Z][a-z]{1,14}"
_PERSON = rf"{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,2}}"
_TITLE = r"(?i:owner|co-owner|founder|co-founder|president|proprietor|" \
         r"general manager|operations manager)"
_OWNER_PATTERNS = [
    re.compile(rf"\b({_PERSON})\s*[,\--: ]\s*(?:the\s+)?{_TITLE}\b"),
    re.compile(rf"{_TITLE}\s*[:,\--: ]\s*({_PERSON})\b"),
    re.compile(rf"\b({_PERSON})\s+(?:is|has\s+been)\s+(?:the\s+|a\s+)?(?:proud\s+)?{_TITLE}\b"),
    re.compile(rf"(?i:meet)\s+({_PERSON})\b"),
    re.compile(rf"\b({_PERSON})\s+(?:founded|started|opened)\s+(?:the\s+)?(?:company|business)"),
]


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _cache_path(url: str) -> str:
    return os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + ".html")


# Set by --no-fetch: serve from cache, never touch the network. Extraction
# still runs, which is the whole point of the flag.
OFFLINE = False


def fetch(url: str, timeout: float = 7.0) -> str:
    """Fetch a URL with an on-disk cache. Returns "" on any failure."""
    cp = _cache_path(url)
    if os.path.exists(cp):
        try:
            with open(cp, encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception:
            return ""
    if OFFLINE:
        return ""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
            if resp.status != 200:
                raw = ""
            else:
                raw = resp.read(600_000).decode("utf-8", "replace")
    except Exception:
        raw = ""
    try:
        os.makedirs(CACHE, exist_ok=True)
        with open(cp, "w", encoding="utf-8") as f:
            f.write(raw)
    except Exception:
        pass
    return raw


def fetch_site(base: str) -> tuple[str, str]:
    """Fetch a few pages of one site. Returns (combined_html, status)."""
    base = (base or "").strip().rstrip("/")
    if not base:
        return "", "none"
    if not base.startswith("http"):
        base = "https://" + base

    pages, got = [], False
    for path in ("", "/contact", "/contact-us", "/about", "/about-us"):
        raw = fetch(base + path)
        if raw:
            got = True
            pages.append(raw)
        if len(pages) >= 3:
            break
    return "\n".join(pages), ("ok" if got else "failed")


def visible_text(raw: str) -> str:
    txt = re.sub(r"<script.*?</script>|<style.*?</style>|<!--.*?-->", " ",
                 raw, flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return " ".join(html.unescape(txt).split())


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_emails(raw: str, site_domain: str) -> list[str]:
    """Return de-duplicated emails, best first."""
    found = set()
    for m in _EMAIL_RE.finditer(raw):
        e = m.group(0).strip(".,;:'\"").lower()
        if len(e) > 60 or any(j in e for j in _EMAIL_JUNK):
            continue
        if e.count("@") != 1:
            continue
        local, _, dom = e.partition("@")
        if not local or len(local) > 34 or dom.count(".") > 3:
            continue
        # Long hex-looking locals are tracking IDs, not people.
        if re.fullmatch(r"[0-9a-f]{16,}", local):
            continue
        found.add(e)

    def rank(e: str) -> tuple:
        local, _, dom = e.partition("@")
        on_domain = bool(site_domain) and site_domain in dom
        personal_inbox = dom in _PERSONAL_INBOX
        is_role = local.split(".")[0] in _ROLE_LOCALS
        looks_named = local.split(".")[0] in FIRST_NAMES
        # Lower sorts first.
        return (
            0 if (on_domain and looks_named) else
            1 if (personal_inbox and looks_named) else
            2 if (on_domain and not is_role) else
            3 if personal_inbox else
            4 if on_domain else 5,
            len(e),
        )

    return sorted(found, key=rank)[:6]


def extract_owner(raw: str, text: str, business_name: str) -> tuple[str, str]:
    """Owner name from schema.org JSON-LD first, then About-page bylines."""
    # JSON-LD is structured and authoritative when present.
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        raw, re.S | re.I,
    ):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:
            continue
        for node in _walk_json(data):
            if not isinstance(node, dict):
                continue
            for key in ("founder", "employee", "owner", "author"):
                val = node.get(key)
                for person in (val if isinstance(val, list) else [val]):
                    if isinstance(person, dict) and person.get("@type") == "Person":
                        nm = (person.get("name") or "").strip()
                        if _valid_person(nm):
                            return nm, "schema.org"
                    elif isinstance(person, str) and _valid_person(person.strip()):
                        return person.strip(), "schema.org"

    biz_words = {w.lower() for w in re.findall(r"[A-Za-z]+", business_name)}
    for pat in _OWNER_PATTERNS:
        for m in pat.finditer(text):
            cand = (m.group(1) or "").strip()
            if _valid_person(cand) and cand.split()[0].lower() not in biz_words:
                return cand, "about page"
    return "", ""


def _walk_json(node):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk_json(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_json(v)


def owner_from_email(email: str) -> str:
    """Recover a first name from the email's local part.

    A small shop's inbox is usually the owner's: lisa@mackierentals,
    tom@propmantech, ricksatisfied@gmail. Role addresses (info@, service@)
    are excluded, and a prefix match needs four characters so "servicetom"
    style noise cannot sneak a name through.
    """
    local = (email or "").split("@")[0].lower()
    if not local or local.split(".")[0] in _ROLE_LOCALS:
        return ""

    # lisa.smith@ / tom_h@ / rick-2@
    first = re.split(r"[._\-0-9]+", local)[0]
    if first in FIRST_NAMES:
        return first.title()

    # ericjonesmyemail@: longest first-name prefix wins.
    best = ""
    for name in FIRST_NAMES:
        if len(name) >= 4 and local.startswith(name) and len(name) > len(best):
            best = name
    if not best:
        return ""

    # A prefix match must never truncate a longer real name: gabrielle.giddings
    # would otherwise become "Gabriel", and Danielle/Roberta/Stephanie would be
    # shortened into a different person's name. When the local part had a clean
    # separator, that token is the name, not the prefix hiding inside it.
    # The 12-char ceiling separates a single long name from a run-on local
    # part: "gabrielle" is a name, "ericjonesmyemail" is three words glued
    # together and only its "eric" prefix should survive.
    if (first.isalpha() and first.startswith(best)
            and len(best) < len(first) <= 12):
        return first.title()
    return best.title()


def _valid_person(name: str) -> bool:
    toks = name.split()
    if not 1 <= len(toks) <= 3:
        return False
    if any(t.lower() in NOT_A_NAME for t in toks):
        return False
    if not all(re.fullmatch(r"[A-Z][a-z]{1,14}", t) for t in toks):
        return False
    return toks[0].lower() in FIRST_NAMES


def detect(raw_lower: str, table) -> str:
    hits = [name for name, needles in table.items()
            if any(n in raw_lower for n in needles)]
    return ", ".join(sorted(hits))


def extract_since(text: str) -> str:
    m = _SINCE_RE.search(text)
    if m:
        return m.group(1)
    m = _YEARS_RE.search(text)
    if m:
        try:
            return str(2026 - int(m.group(1)))
        except Exception:
            return ""
    return ""


def extract_socials(raw: str) -> dict:
    out = {}
    for label, pat in _SOCIAL.items():
        m = pat.search(raw)
        if m:
            url = m.group(0)
            if not re.search(r"/(sharer|share|plugins|intent|login|tr\?)", url, re.I):
                out[label] = url[:120]
    return out


def extract_phones(text: str, known: str) -> str:
    known_digits = re.sub(r"\D", "", known or "")
    seen, out = {known_digits}, []
    for m in _PHONE_RE.finditer(text):
        d = "".join(m.groups())
        if d in seen or d.startswith(("000", "111", "800", "888", "877", "866", "855")):
            continue
        if len(set(d)) <= 2:
            continue
        seen.add(d)
        out.append(f"({d[:3]}) {d[3:6]}-{d[6:]}")
        if len(out) >= 2:
            break
    return "; ".join(out)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_row(r: dict) -> dict:
    """Score FIT, PAIN and REACH separately, then tier on the combination."""
    try:
        reviews = int(r["Reviews"]) if r["Reviews"] else None
    except ValueError:
        reviews = None
    try:
        rating = float(r["Rating"]) if r["Rating"] else None
    except ValueError:
        rating = None

    fit, pain, reach, why = 0, 0, 0, []

    # --- FIT: can they buy, and are they the size with the problem?
    if reviews is not None:
        if 15 <= reviews <= 150:
            fit += 3; why.append("right-size shop")
        elif 151 <= reviews <= 400:
            fit += 1
        elif reviews > 500:
            fit -= 3; why.append("too big / likely enterprise")
        elif reviews < 8:
            fit -= 2; why.append("very small footprint")
    if r["Franchise"]:
        fit -= 5; why.append(f"FRANCHISE ({r['Franchise']})")
    if r["Competitor Tool"]:
        fit -= 4; why.append(f"ALREADY HAS {r['Competitor Tool'].upper()}")
    if r["Platform"]:
        fit -= 2; why.append(f"on {r['Platform']}")
    if not r["Website"]:
        fit += 1; why.append("no website")
    elif r["Builder"] in ("wix", "godaddy", "weebly"):
        fit += 1; why.append(f"{r['Builder']} site")

    # --- PAIN: is there evidence they are losing calls now?
    if r["Miss Signal"]:
        pain += 4; why.append("review complains of no answer")
    if r["Claims 24/7"]:
        pain += 2
        if r["Miss Signal"]:
            why.append("PROMISES 24/7 AND MISSES CALLS")
        else:
            why.append("promises 24/7")
    if rating is not None and reviews and reviews >= 30:
        if rating < 3.0:
            pain += 2; why.append("rating under 3.0")
        elif rating <= 4.3:
            pain += 1

    # --- REACH: do I know who to ask for, and can I follow up?
    if r["Owner Name"]:
        reach += 3; why.append(f"ask for {r['Owner Name']}")
    if r["Email"]:
        reach += 2
        local = r["Email"].split("@")[0].split(".")[0].lower()
        if local in FIRST_NAMES:
            reach += 1; why.append("personal email")
    if r.get("Facebook"):
        reach += 1
    if not r["Phone"]:
        reach -= 5; why.append("NO PHONE")

    # --- Tier
    if r["Competitor Tool"] or r["Franchise"] or not r["Phone"]:
        tier = "D"
    elif pain >= 4 and reach >= 3 and fit >= 0:
        tier = "A"
    elif fit >= 3 and reach >= 2:
        tier = "B"
    elif fit >= 0 and r["Phone"]:
        tier = "C"
    else:
        tier = "D"

    return {
        "Tier": tier, "Fit": fit, "Pain": pain, "Reach": reach,
        "Total": fit + pain + reach, "Why": "; ".join(why[:6]),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def enrich_one(row: dict, do_fetch: bool) -> dict:
    r = dict(row)
    site = r.get("Website", "")
    domain = ""
    if site:
        try:
            domain = urllib.parse.urlparse(
                site if site.startswith("http") else "https://" + site
            ).netloc.lower().replace("www.", "")
        except Exception:
            domain = ""

    raw = ""
    status = "none" if not site else "skipped"
    if site and do_fetch:
        raw, status = fetch_site(site)

    text = visible_text(raw) if raw else ""
    low = raw.lower()

    name_l = r["Business Name"].lower()
    franchise = next(
        (b for b in FRANCHISE_BRANDS if b in name_l or (low and b in low[:20000])), ""
    )

    emails = extract_emails(raw, domain) if raw else []
    owner, osrc = ("", "")
    if raw:
        owner, osrc = extract_owner(raw, text, r["Business Name"])
    if not owner and r.get("Owner Name"):
        owner, osrc = r["Owner Name"], r.get("Owner Confidence", "") or "scrape"
    if not owner and emails:
        from_email = owner_from_email(emails[0])
        if from_email:
            owner, osrc = from_email, "email"

    socials = extract_socials(raw) if raw else {}

    r.update({
        "Site Status": status,
        "Email": emails[0] if emails else "",
        "All Emails": "; ".join(emails[1:4]),
        "Owner Name": owner,
        "Owner Source": osrc,
        "Franchise": franchise.title() if franchise else "",
        "Competitor Tool": detect(low, COMPETITOR_TOOLS) if raw else "",
        "Platform": detect(low, PLATFORMS) if raw else "",
        "Builder": detect(low, BUILDERS) if raw else "",
        "Claims 24/7": "yes" if (text and _247_RE.search(text)) else "",
        "Since": extract_since(text) if text else "",
        "Facebook": socials.get("Facebook", ""),
        "Instagram": socials.get("Instagram", ""),
        "LinkedIn": socials.get("LinkedIn", ""),
        "Extra Phones": extract_phones(text, r.get("Phone", "")) if text else "",
    })
    r.update(score_row(r))
    return r


OUT_COLUMNS = [
    "Tier", "Total", "Fit", "Pain", "Reach", "Why",
    "Market", "Segment", "Business Name", "Owner Name", "Owner Source",
    "Phone", "Extra Phones", "Email", "All Emails", "City", "Service Type",
    "Miss Signal", "Claims 24/7", "Rating", "Reviews", "Since",
    "Franchise", "Competitor Tool", "Platform", "Builder",
    "Website", "Facebook", "Instagram", "LinkedIn", "Address",
    "Owner Lookup", "Maps URL", "Site Status",
    "Call 1 Date", "Call 1 Time", "Answered?", "Text Back?", "Outcome",
    "Call 2 Date", "Next Step", "Notes",
]


def write_csv(path: str, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in OUT_COLUMNS})


def main() -> None:
    ap = argparse.ArgumentParser(description="Enrich and tier the prospect list.")
    ap.add_argument("--in", dest="infile", default=os.path.join(HERE, "prospects.csv"))
    ap.add_argument("--limit", type=int, default=0, help="Only process the first N rows.")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--no-fetch", action="store_true",
                    help="Re-score from cache only; do not hit any website.")
    args = ap.parse_args()

    global OFFLINE
    OFFLINE = args.no_fetch

    if not os.path.exists(args.infile):
        sys.exit(f"{args.infile} not found. Run scrape_prospects.py first.")

    rows = list(csv.DictReader(open(args.infile, encoding="utf-8")))
    if args.limit:
        rows = rows[: args.limit]
    sites = sum(1 for r in rows if r.get("Website"))
    print(f"{len(rows)} rows, {sites} with a website.")
    if not args.no_fetch:
        print(f"Fetching up to 3 pages each, {args.workers} at a time. "
              f"Cached under growth/.cache/ so re-runs are free.\n")

    out, done = [], 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(enrich_one, r, True) for r in rows]
        for fut in cf.as_completed(futures):
            done += 1
            try:
                out.append(fut.result())
            except Exception as e:
                print(f"  ! row failed: {e}")
            if done % 200 == 0:
                print(f"  ...{done}/{len(rows)}")

    out.sort(key=lambda r: (r["Tier"], -r["Total"], r["Business Name"]))

    tiers = {t: [r for r in out if r["Tier"] == t] for t in "ABCD"}
    emailable = [r for r in out if r["Email"] and r["Tier"] in ("A", "B", "C")]
    emailable.sort(key=lambda r: -r["Total"])

    write_csv(os.path.join(HERE, "enriched.csv"), out)
    write_csv(os.path.join(HERE, "tier_a_call_first.csv"), tiers["A"])
    write_csv(os.path.join(HERE, "tier_b_high_value.csv"), tiers["B"])
    write_csv(os.path.join(HERE, "tier_c_working.csv"), tiers["C"])
    write_csv(os.path.join(HERE, "tier_d_skip.csv"), tiers["D"])
    write_csv(os.path.join(HERE, "email_ready.csv"), emailable)

    def pct(n):
        return f"{n * 100 // max(len(out), 1)}%"

    print(f"\n  Wrote enriched.csv  ({len(out)} rows)\n")
    print(f"  TIER A  call first      {len(tiers['A']):5}   pain + a name to ask for")
    print(f"  TIER B  high value      {len(tiers['B']):5}   right size and reachable")
    print(f"  TIER C  working list    {len(tiers['C']):5}   volume dialing")
    print(f"  TIER D  skip            {len(tiers['D']):5}   franchise / competitor / no phone")
    print()
    print(f"  emails found            {sum(1 for r in out if r['Email']):5}  ({pct(sum(1 for r in out if r['Email']))})")
    print(f"  owner names             {sum(1 for r in out if r['Owner Name']):5}  ({pct(sum(1 for r in out if r['Owner Name']))})")
    print(f"  claims 24/7             {sum(1 for r in out if r['Claims 24/7']):5}")
    print(f"  promises 24/7 + misses  {sum(1 for r in out if r['Claims 24/7'] and r['Miss Signal']):5}  <- the best pitch in the file")
    print(f"  franchises flagged      {sum(1 for r in out if r['Franchise']):5}")
    print(f"  competitor installed    {sum(1 for r in out if r['Competitor Tool']):5}")
    print(f"  facebook pages          {sum(1 for r in out if r['Facebook']):5}")


if __name__ == "__main__":
    main()
