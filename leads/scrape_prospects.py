#!/usr/bin/env python3
"""
scrape_prospects.py. Clockwork's two-market prospect engine.

Supersedes scrape_contractors.py. What's new:

  * TWO MARKETS. "north" = the Naperville-Aurora corridor. "south" = Champaign-
    Urbana plus Bloomington-Normal. Every row is tagged, so one file drives
    both dial lists.
  * THREE SEGMENTS. The six trades, plus property managers (a college-town
    goldmine: they dispatch maintenance daily and refer every trade they use)
    and 24/7 emergency services (highest missed-call pain of any local business).
  * DECISION-MAKER NAMES. Google gives you a phone. It does not give you a name,
    and the name is what gets you past "can I ask who's calling?". Three free
    layers recover one for a large share of rows: the business name itself,
    the owner's first name mined out of customer review text, and the shop's
    own About page.
  * THE MISS SIGNAL. Review text is swept for complaints about unanswered calls
    ("never called back", "no response"). That snippet IS the pitch, quoted back
    to the owner from his own reviews. It is the highest-value column here.

Outputs growth/prospects.csv, ordered for dialing, with empty call-log columns
so the audit report writes itself out of the same file.

-- Setup (already done if growth/.env has a key) -----------------------------
  1. https://console.cloud.google.com/ -> create a project
  2. "APIs & Services" -> enable **Places API (New)**
  3. "Credentials" -> "Create credentials" -> "API key"
  4. Put it in growth/.env:   GOOGLE_PLACES_API_KEY=paste_key_here

-- Run -----------------------------------------------------------------------
  python3 growth/scrape_prospects.py --dry-run          # show the API budget
  python3 growth/scrape_prospects.py                    # both markets
  python3 growth/scrape_prospects.py --market south     # Champaign only
  python3 growth/scrape_prospects.py --no-web           # skip About-page fetch

-- Cost ----------------------------------------------------------------------
Rating and review data put these calls in the Places "Enterprise" SKU, which
carries 1,000 free requests/month. A full two-market sweep at the default two
pages costs roughly 450 requests, so it fits inside the free tier with room to
re-run once. --dry-run prints the exact number before you spend anything.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def _ssl_context() -> ssl.SSLContext:
    """A context with a CA bundle that actually exists on this machine.

    A python.org framework build on macOS ships without root certificates until
    you run its "Install Certificates.command", so the default context fails
    every HTTPS call with CERTIFICATE_VERIFY_FAILED. Fall back to certifi, then
    to the system bundle, rather than making the user go fix their Python.
    """
    for cafile in (_certifi_path(), "/etc/ssl/cert.pem"):
        if cafile and os.path.exists(cafile):
            try:
                return ssl.create_default_context(cafile=cafile)
            except Exception:
                continue
    return ssl.create_default_context()


def _certifi_path() -> str:
    try:
        import certifi

        return certifi.where()
    except Exception:
        return ""


SSL_CTX = _ssl_context()


def _load_env_file(path: str) -> None:
    """Load KEY=VALUE lines from a .env file (no deps). Real env vars win."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(os.path.join(HERE, ".env"))

API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# ---------------------------------------------------------------------------
# Markets and segments
# ---------------------------------------------------------------------------

MARKETS = {
    # Where Ian is now. Feet on the street until the move; this is the market
    # where in-person counter demos are still possible.
    "north": [
        "Naperville IL", "Aurora IL", "Bolingbrook IL", "Plainfield IL",
        "Wheaton IL", "Lisle IL", "Downers Grove IL", "Warrenville IL",
        "Oswego IL",
    ],
    # Where Ian is going. Audit calls work over the phone from anywhere, so
    # this list gets worked BEFORE the move and walked in person after it.
    "south": [
        "Champaign IL", "Urbana IL", "Savoy IL", "Mahomet IL", "Rantoul IL",
        "Bloomington IL", "Normal IL",
    ],
}

SEGMENTS = {
    "trades": [
        "HVAC contractor", "air conditioning repair", "furnace repair",
        "plumber", "electrician", "roofing contractor",
    ],
    "property": [
        "property management company", "apartment rental agency",
        "student housing rental",
    ],
    "emergency": [
        "water damage restoration", "garage door repair", "locksmith",
        "emergency plumber", "towing service",
    ],
}

# Only ask for the fields we use. `reviews` is what powers name-mining and the
# miss signal; if the key's SKU rejects it we fall back automatically.
_CORE_FIELDS = [
    "places.displayName",
    "places.nationalPhoneNumber",
    "places.websiteUri",
    "places.rating",
    "places.userRatingCount",
    "places.formattedAddress",
    "places.googleMapsUri",
    "nextPageToken",
]
FIELD_MASK_FULL = ",".join(_CORE_FIELDS + ["places.reviews"])
FIELD_MASK_LEAN = ",".join(_CORE_FIELDS)

# ---------------------------------------------------------------------------
# Name mining
# ---------------------------------------------------------------------------

# Words that look like names but aren't. Trades, towns, brands, and the words
# that show up capitalized in reviews for boring reasons.
_NOT_A_NAME = {
    # trades / business words
    "air", "heating", "cooling", "plumbing", "electric", "electrical", "roofing",
    "hvac", "service", "services", "company", "sons", "brothers", "inc", "llc",
    "corp", "group", "solutions", "systems", "mechanical", "comfort", "climate",
    "home", "quality", "premier", "reliable", "expert", "master", "pro", "pros",
    "advantage", "american", "national", "united", "general", "total", "complete",
    "restoration", "property", "management", "rental", "rentals", "realty",
    "storage", "door", "doors", "garage", "lock", "towing", "sewer", "drain",
    "water", "waste", "energy", "power", "temp", "temperature", "furnace",
    "boiler", "duct", "vent", "chimney", "gutter", "siding", "window", "windows",
    # geography
    "naperville", "aurora", "bolingbrook", "plainfield", "wheaton", "lisle",
    "downers", "grove", "warrenville", "oswego", "champaign", "urbana", "savoy",
    "mahomet", "rantoul", "bloomington", "normal", "illinois", "chicago",
    "chicagoland", "midwest", "county", "dupage", "kane", "will", "kendall",
    # brands that appear constantly in HVAC reviews
    "trane", "carrier", "lennox", "rheem", "goodman", "bryant", "amana", "york",
    "daikin", "mitsubishi", "navien", "rinnai", "kohler", "moen", "generac",
    "nest", "honeywell", "ecobee",
    # pronouns, question words, determiners: the biggest source of false
    # "names", because "She was great" and "How was it" both match the
    # person-verb pattern.
    "he", "she", "they", "we", "it", "you", "i", "him", "her", "them", "us",
    "his", "hers", "its", "our", "your", "my", "mine", "who", "whom", "whose",
    "how", "what", "when", "where", "why", "which", "that", "this", "these",
    "those", "there", "their", "some", "any", "every", "each", "both", "most",
    "many", "few", "all", "another", "other", "others", "none", "neither",
    "either", "such", "same", "one", "two", "three", "first", "second", "last",
    # sentence starters and connectives
    "however", "also", "then", "than", "after", "before", "since", "while",
    "although", "because", "unless", "until", "once", "even", "still", "just",
    "only", "never", "always", "overall", "finally", "instead", "maybe",
    "perhaps", "unfortunately", "fortunately", "honestly", "basically",
    "eventually", "immediately", "originally", "apparently", "supposedly",
    "yes", "no", "not", "now", "here", "well", "so", "but", "and", "for",
    "from", "with", "without", "about", "over", "under", "into", "onto",
    # generic business/rental nouns that appear capitalized
    "maintenance", "management", "office", "staff", "team", "front", "desk",
    "leasing", "apartment", "apartments", "building", "owner", "manager",
    "landlord", "tenant", "resident", "unit", "lease", "rent", "move",
    "everyone", "someone", "anyone", "nobody", "everything", "nothing",
    "something", "anything", "guys", "guy", "lady", "man", "woman", "people",
    "tech", "technician", "crew", "worker", "workers", "employee", "customer",
    "landlords", "tenants", "residents", "legends", "village", "place",
    # review filler
    "would", "could", "should", "very", "really", "great", "good", "best",
    "highly", "thank", "thanks", "excellent", "professional", "recommend",
    "recommended", "definitely", "absolutely", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "sunday", "january",
    "february", "march", "april", "june", "july", "august", "september",
    "october", "november", "december", "christmas", "google", "yelp",
    "facebook", "covid", "call", "called", "phone",
}

# Common US first names, weighted toward the 35-70 bracket that owns trade
# shops. Used to gate name-from-business-name, which is otherwise happy to
# decide that "Plumb Crazy Plumbing" is run by a man named Plumb Crazy.
_FIRST_NAMES = set("""
aaron adam adrian al alan albert alex alexander alfred allen alvin andre andrew
andy angel angela angelo anita ann anna anne annette anthony antonio april arnold
art arthur ashley austin barbara barry beau ben benjamin bernard beth betty bill
billy blake bob bobby brad bradley brandon brenda brent brett brian bruce bryan
bryce byron calvin cameron carl carlos carmen carol carole caroline carrie casey
catherine cathy cecil chad charles charlie chase chester chris christian christina
christine christopher chuck cindy claire clarence claude clay clayton cliff
clifford clint clinton clyde cody colin connie conner cooper corey cory craig
curt curtis cynthia dale dallas dan dana daniel danny darrell darren darryl dave
david dawn dean deborah debra dennis derek derrick diana diane dick dominic don
donald donna doug douglas drew duane dustin dwayne dwight earl ed eddie edgar
edward edwin elaine eli elizabeth ellen elmer emily eric erica erik ernest ernie
ethan eugene evan everett felix fernando floyd forrest frances francis frank
franklin fred freddie frederick gabriel gail garrett gary gene geoffrey george
gerald gilbert glen glenn gordon grant greg gregory guy hal hank harold harry
harvey heather hector helen henry herb herbert herman holly homer howard hugh
hunter ian ira irene irvin isaac ivan jack jackie jacob jake james jamie jan jane
janet janice jared jason jay jean jeff jeffery jeffrey jenkins jennifer jeremy
jerome jerry jesse jessica jill jim jimmy joan joann joe joel john johnnie johnny
jon jonathan jordan jorge jose joseph josh joshua joyce juan judith judy julia
julie justin karen karl kate katherine kathleen kathy keith kelly ken kendall
kenneth kent kevin kim kimberly kirk kris kristen kurt kyle lance larry laura
lauren lawrence lee leo leon leonard leroy leslie lester lewis linda lisa lloyd
logan lois lonnie loren lori lorraine louis louise lowell lucas luis luke lyle
lynn mack madison marc marcus margaret maria marian marie marilyn mario marion
mark marlin marshall martha martin marvin mary mason matt matthew maurice max
maxwell megan melissa melvin michael micheal michelle mickey mike miguel mike
milton mitchell monica morgan morris murray myron nancy nate nathan nathaniel
neal neil nelson nicholas nick nicole noah norman oliver oscar otis owen pam
pamela pat patricia patrick patty paul paula pedro peggy perry pete peter phil
philip phillip phyllis rachel ralph ramon randall randy raul ray raymond reggie
reginald rene rex rich richard rick rickey ricky rita rob robert roberto robin
rod rodney roger roland ron ronald ronnie rosa rose ross roy ruben rudy russ
russell ruth ryan sally sam samuel sandra sandy sara sarah scott sean seth shane
shannon sharon shaun shawn sheila shelly sherry shirley sidney simon stacy stan
stanley stephanie stephen steve steven stuart sue susan sylvester tammy tanner
ted terrance terrence terry theodore theresa thomas tim timothy tina toby todd
tom tommy tony tracy travis trent trevor troy tyler tyrone valerie vance vaughn
verne vernon vicki victor vincent virgil virginia wade wallace walter warren
wayne wendell wendy wes wesley wilbur will william willie wilson zach zachary
""".split())


# High-precision: a capitalized word doing something a person does.
_PERSON_VERB = re.compile(
    r"\b([A-Z][a-z]{2,11})\s+"
    r"(?:came|come|was|were|did|does|fixed|installed|showed|arrived|explained|"
    r"went|took|walked|gave|answered|called|checked|replaced|repaired|quoted|"
    r"diagnosed|serviced|and his|and her|is the|the owner)\b"
)

# "Mike's Plumbing" -> Mike
_POSSESSIVE_NAME = re.compile(r"^([A-Z][a-z]{2,11})'s\s")
# "Mike Smith Plumbing" / "Dave Anderson Heating" -> Mike Smith
_FULL_NAME_LEAD = re.compile(
    r"^([A-Z][a-z]{2,11})\s+([A-Z][a-z]{2,15})\s+"
    r"(?:Plumbing|Heating|Cooling|HVAC|Electric|Electrical|Roofing|Mechanical|"
    r"Construction|Contracting|Services?|Company|Restoration|Property)"
)
# "Anderson & Sons" -> Anderson
_AMPERSAND_SONS = re.compile(r"^([A-Z][a-z]{2,15})\s*(?:&|and)\s+Sons?\b")

# Owner titles on an About page, either order.
#
# Deliberately NOT re.IGNORECASE: that flag makes [A-Z] match lowercase too,
# which turns every "...property owner..." in nav text into a fake name. The
# title is made case-insensitive with an inline group instead, so the NAME
# still has to be properly capitalized like a real one.
_NAME_TOKEN = r"[A-Z][a-z]{1,14}"
_PERSON = rf"{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,2}}"
_TITLE = r"(?i:owner|co-owner|founder|co-founder|president|proprietor)"
_ABOUT_NAME = re.compile(
    rf"\b({_PERSON})\s*[,\--: ]\s*(?:the\s+)?{_TITLE}\b"
    rf"|{_TITLE}\s*[:,\--: ]\s*({_PERSON})\b"
    rf"|\b({_PERSON})\s+(?:is|has\s+been)\s+(?:the\s+|a\s+)?(?:proud\s+)?{_TITLE}\b"
)


def _looks_like_person(candidate: str) -> bool:
    """Reject nav text, headings, and job titles masquerading as a name.

    The first token has to be a real first name. Without that rule an About
    page yields things like "Directors Jane" and "Our Team", which are worse
    than no name at all when you open a call with them.
    """
    tokens = candidate.split()
    if not 1 <= len(tokens) <= 3:
        return False
    if any(t.lower() in _NOT_A_NAME for t in tokens):
        return False
    if not all(re.fullmatch(r"[A-Z][a-z]{1,14}", t) for t in tokens):
        return False
    return tokens[0].lower() in _FIRST_NAMES

# The pitch, in their own customers' words.
#
# Every pattern here must be unambiguously NEGATIVE. An earlier version matched
# a bare "left a voicemail", which also appears in glowing reviews ("left a
# voicemail at 7am and Ray got right back to me") and produced false pitches.
# A miss signal you quote back to an owner has to be real, so recall loses to
# precision here every time.
_MISS_PATTERNS = [
    r"never (?:called|got|heard|came) back",
    r"never (?:answered|returned|responded)",
    r"didn'?t (?:answer|call back|return|respond)",
    r"did not (?:answer|call back|return|respond)",
    r"no (?:answer|response|call ?back)",
    r"no return(?:ed)? (?:phone )?call",
    r"with no (?:return|reply|response)",
    r"wouldn'?t (?:answer|return|call)",
    r"couldn'?t (?:reach|get a hold of|get ahold of)",
    r"still waiting (?:for|on) (?:a |an )?(?:call|reply|response|quote|estimate)",
    r"unresponsive", r"ghosted",
    r"no one (?:answered|picked up|called|got back)",
    r"nobody (?:answered|picked up|called)",
    r"took (?:days|a week|weeks) to (?:respond|call|hear)",
    r"had to call (?:back |them )?(?:multiple|several|three|four|\d+) times",
    r"called (?:multiple|several|three|four|\d+) times",
    r"(?:several|multiple|three|four) (?:messages|voicemails).{0,30}no",
]
_MISS_RE = re.compile("|".join(_MISS_PATTERNS), re.IGNORECASE)


def _clean_token(tok: str) -> str:
    return re.sub(r"[^A-Za-z]", "", tok)


def owner_from_business_name(name: str) -> tuple[str, str]:
    """Return (name, confidence) mined from the business name itself.

    Gated on a real first name. "Josh Phillips HVAC" is a person; "Plumb Crazy
    Plumbing" and "Max Volts Electricians" are not, and only the first-name
    check reliably tells them apart.
    """
    # "Josh Phillips HVAC LLC" -> Josh Phillips
    m = _FULL_NAME_LEAD.match(name)
    if m:
        first, last = _clean_token(m.group(1)), _clean_token(m.group(2))
        if first.lower() in _FIRST_NAMES and last.lower() not in _NOT_A_NAME:
            return f"{m.group(1)} {m.group(2)}", "high"

    # "Ray's Heating" -> Ray   (but not "House's Services")
    m = _POSSESSIVE_NAME.match(name)
    if m and _clean_token(m.group(1)).lower() in _FIRST_NAMES:
        return m.group(1), "high"

    # "Lance & Sons Electricians" -> Lance
    m = _AMPERSAND_SONS.match(name)
    if m and _clean_token(m.group(1)).lower() in _FIRST_NAMES:
        return m.group(1), "medium"
    return "", ""


def owner_from_reviews(reviews: list[str], business_name: str) -> tuple[str, str]:
    """Mine a recurring personal first name out of customer review text.

    Customers write "Mike came out same day". A first name that shows up in two
    or more separate reviews, doing something a person does, is almost always
    the owner or the lead tech of a small shop.
    """
    biz_words = {w.lower() for w in re.findall(r"[A-Za-z]+", business_name)}
    hits: dict[str, int] = {}
    for text in reviews:
        seen_here = set()
        for m in _PERSON_VERB.finditer(text or ""):
            tok = m.group(1)
            low = tok.lower()
            if low in _NOT_A_NAME or low in biz_words or low in seen_here:
                continue
            seen_here.add(low)
            hits[tok] = hits.get(tok, 0) + 1
    if not hits:
        return "", ""
    best, count = max(hits.items(), key=lambda kv: kv[1])
    # One mention is noise: a passing staff member, or a stoplist miss. Two
    # separate customers naming the same person is a real signal. A wrong name
    # on a cold call is worse than no name, so only the recurring one ships.
    if count >= 2:
        return best, "medium"
    return "", ""


def miss_signal(reviews: list[str]) -> str:
    """Return a short quoted snippet of a customer complaining about no answer."""
    for text in reviews:
        m = _MISS_RE.search(text or "")
        if not m:
            continue
        start, end = max(0, m.start() - 55), min(len(text), m.end() + 55)
        snippet = " ".join(text[start:end].split())
        return f"...{snippet}..."
    return ""


def owner_from_website(url: str, timeout: float = 4.0) -> tuple[str, str]:
    """Fetch the shop's About page and look for an owner/founder byline."""
    if not url:
        return "", ""
    base = url.rstrip("/")
    for path in ("/about", "", "/about-us"):
        try:
            req = urllib.request.Request(
                base + path,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ClockworkProspect/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
                if resp.status != 200:
                    continue
                raw = resp.read(400_000).decode("utf-8", "replace")
        except Exception:
            continue

        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = " ".join(text.split())

        for m in _ABOUT_NAME.finditer(text):
            candidate = (m.group(1) or m.group(2) or m.group(3) or "").strip()
            if candidate and _looks_like_person(candidate):
                return candidate, "high"
    return "", ""


# ---------------------------------------------------------------------------
# Places API
# ---------------------------------------------------------------------------

_request_count = 0


def _post(body: dict, field_mask: str) -> dict:
    global _request_count
    req = urllib.request.Request(
        SEARCH_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": API_KEY,
            "X-Goog-FieldMask": field_mask,
        },
        method="POST",
    )
    _request_count += 1
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
        return json.load(resp)


def search(query: str, max_pages: int, field_mask: str):
    """Yield place dicts for one text query, paging up to max_pages."""
    body = {"textQuery": query, "pageSize": 20, "regionCode": "US"}
    for _ in range(max_pages):
        data = _post(body, field_mask)
        for place in data.get("places", []):
            yield place
        token = data.get("nextPageToken")
        if not token:
            break
        time.sleep(2)  # the page token needs a moment to become valid
        body = {"textQuery": query, "pageSize": 20, "regionCode": "US", "pageToken": token}


def norm_phone(p: str) -> str:
    return re.sub(r"\D", "", p or "")


_STATE_ZIP = re.compile(r"^[A-Z]{2}\s+\d{5}")


def city_from_address(addr: str) -> str:
    """Pull the city out of a Google formatted address.

    Google returns "123 Main St, Naperville, IL 60540" here, sometimes with a
    trailing ", USA" and sometimes not, so a fixed index lands on the street
    half the time. Anchor on the "IL 60540" part and take what precedes it.
    """
    parts = [x.strip() for x in (addr or "").split(",")]
    for i, part in enumerate(parts):
        if _STATE_ZIP.match(part) and i > 0:
            return parts[i - 1]
    return parts[-2] if len(parts) >= 2 else ""


def score_prospect(rating, reviews_n, has_site, has_phone, has_owner, has_miss, segment):
    """Higher score = call this one first."""
    score, signals = 0, []
    if has_miss:
        score += 3
        signals.append("REVIEW COMPLAINS OF NO ANSWER")
    if reviews_n is not None and 15 <= reviews_n <= 150:
        score += 2
        signals.append("right-size shop")
    if has_owner:
        score += 2
        signals.append("owner named")
    if rating is not None and 3.6 <= rating <= 4.6:
        score += 1
        signals.append("active reviews")
    if not has_site:
        score += 1
        signals.append("no website")
    if segment == "emergency":
        score += 1
        signals.append("24/7 pain")
    if not has_phone:
        score -= 5
        signals.append("NO PHONE")
    return score, "; ".join(signals)


def owner_lookup_url(name: str, city: str) -> str:
    """One-click Google query that surfaces the owner on the top page."""
    q = f'"{name}" {city} Illinois owner OR president OR "principal contact"'
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(q)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

COLUMNS = [
    "Priority", "Market", "Segment", "Business Name", "Owner Name",
    "Owner Confidence", "Phone", "City", "Service Type", "Miss Signal",
    "Rating", "Reviews", "Website", "Address", "Signal", "Owner Lookup",
    "Maps URL",
    # Call log: filled in by hand while dialing. The audit report is a
    # pivot table over these four columns.
    "Call 1 Date", "Call 1 Time", "Answered?", "Text Back?", "Outcome",
    "Call 2 Date", "Next Step", "Notes",
]


def main() -> None:
    ap = argparse.ArgumentParser(description="Scrape a two-market prospect list.")
    ap.add_argument("--market", choices=["north", "south", "both"], default="both")
    ap.add_argument("--segment", choices=list(SEGMENTS) + ["all"], default="all")
    ap.add_argument("--max-pages", type=int, default=2,
                    help="Pages per query (20 results each). Default 2.")
    ap.add_argument("--no-web", action="store_true",
                    help="Skip About-page fetching (much faster, fewer owner names).")
    ap.add_argument("--web-limit", type=int, default=400,
                    help="Max About pages to fetch, highest-priority first. Default 400.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the API request budget and exit without calling.")
    ap.add_argument("--out", default=os.path.join(HERE, "prospects.csv"))
    args = ap.parse_args()

    markets = list(MARKETS) if args.market == "both" else [args.market]
    segments = list(SEGMENTS) if args.segment == "all" else [args.segment]

    combos = sum(
        len(SEGMENTS[s]) * len(MARKETS[m]) for m in markets for s in segments
    )
    budget = combos * args.max_pages

    print(f"Markets:  {', '.join(markets)}")
    print(f"Segments: {', '.join(segments)}")
    print(f"Queries:  {combos}  ->  up to {budget} API requests "
          f"({args.max_pages} pages each)")
    print("Places 'Enterprise' SKU includes 1,000 free requests/month.")
    if args.dry_run:
        print("\nDry run. Nothing called, nothing spent.")
        return
    if budget > 900:
        print(f"\nThat budget ({budget}) is close to the 1,000/month free tier.")
        if input("Continue? [y/N] ").strip().lower() != "y":
            return
    print()

    if not API_KEY:
        sys.exit("Set GOOGLE_PLACES_API_KEY first, see the setup notes up top.")

    field_mask = FIELD_MASK_FULL
    seen: set[str] = set()
    rows: list[dict] = []

    for market in markets:
        for segment in segments:
            for trade in SEGMENTS[segment]:
                for town in MARKETS[market]:
                    query = f"{trade} in {town}"
                    before = len(rows)
                    try:
                        places = list(search(query, args.max_pages, field_mask))
                    except urllib.error.HTTPError as e:
                        detail = e.read().decode("utf-8", "replace")[:200]
                        # A key without the Enterprise SKU rejects `reviews`.
                        # Drop it once and keep going with the lean mask.
                        if e.code == 400 and "reviews" in detail and field_mask == FIELD_MASK_FULL:
                            print("  ! 'reviews' field rejected: continuing without "
                                  "review mining (no owner names from reviews, no miss signal).")
                            field_mask = FIELD_MASK_LEAN
                            try:
                                places = list(search(query, args.max_pages, field_mask))
                            except Exception as e2:
                                print(f"  ! {query}: {e2}")
                                continue
                        else:
                            print(f"  ! {query}: HTTP {e.code}: {detail}")
                            continue
                    except Exception as e:
                        print(f"  ! {query}: {e}")
                        continue

                    for place in places:
                        name = (place.get("displayName") or {}).get("text", "").strip()
                        phone = (place.get("nationalPhoneNumber") or "").strip()
                        key = norm_phone(phone) or name.lower()
                        if not key or key in seen:
                            continue
                        seen.add(key)

                        review_texts = [
                            (r.get("text") or {}).get("text", "")
                            for r in (place.get("reviews") or [])
                        ]
                        rating = place.get("rating")
                        reviews_n = place.get("userRatingCount")
                        site = (place.get("websiteUri") or "").strip()
                        addr = (place.get("formattedAddress") or "").strip()
                        city = city_from_address(addr)

                        owner, conf = owner_from_business_name(name)
                        if not owner:
                            owner, conf = owner_from_reviews(review_texts, name)
                        miss = miss_signal(review_texts)

                        prio, signal = score_prospect(
                            rating, reviews_n, bool(site), bool(phone),
                            bool(owner), bool(miss), segment,
                        )

                        rows.append({
                            "Priority": prio,
                            "Market": market,
                            "Segment": segment,
                            "Business Name": name,
                            "Owner Name": owner,
                            "Owner Confidence": conf,
                            "Phone": phone,
                            "City": city,
                            "Service Type": trade,
                            "Miss Signal": miss,
                            "Rating": rating if rating is not None else "",
                            "Reviews": reviews_n if reviews_n is not None else "",
                            "Website": site,
                            "Address": addr,
                            "Signal": signal,
                            "Owner Lookup": owner_lookup_url(name, city),
                            "Maps URL": place.get("googleMapsUri", ""),
                            "Call 1 Date": "", "Call 1 Time": "", "Answered?": "",
                            "Text Back?": "", "Outcome": "", "Call 2 Date": "",
                            "Next Step": "", "Notes": "",
                        })
                    print(f"  [{market}/{segment}] {query}: +{len(rows) - before} "
                          f"({len(rows)} total)")

    if not rows:
        sys.exit("\nNo results. Usually the API key lacks billing, or "
                 "'Places API (New)' isn't enabled. See the setup notes up top.")

    rows.sort(key=lambda r: (-r["Priority"], r["Market"], r["Business Name"]))

    # About-page pass, only for the highest-priority rows still missing a name.
    # These are the ones getting dialed first, so they are the only ones worth
    # the fetch. Modest concurrency across many different small-business sites.
    if not args.no_web:
        pending = [r for r in rows if not r["Owner Name"] and r["Website"]][: args.web_limit]
        print(f"\nFetching About pages for the top {len(pending)} shops still "
              f"missing a name...")
        done = 0
        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(owner_from_website, r["Website"]): r for r in pending}
            for fut in cf.as_completed(futures):
                row = futures[fut]
                done += 1
                try:
                    found, conf = fut.result()
                except Exception:
                    found, conf = "", ""
                if found:
                    row["Owner Name"], row["Owner Confidence"] = found, conf
                    row["Priority"] += 2
                    row["Signal"] = (row["Signal"] + "; owner named").strip("; ")
                if done % 50 == 0:
                    print(f"  ...{done}/{len(pending)}")

        rows.sort(key=lambda r: (-r["Priority"], r["Market"], r["Business Name"]))

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    named = sum(1 for r in rows if r["Owner Name"])
    phoned = sum(1 for r in rows if r["Phone"])
    missed = sum(1 for r in rows if r["Miss Signal"])
    north = sum(1 for r in rows if r["Market"] == "north")

    print(f"\nWrote {len(rows)} prospects -> {args.out}")
    print(f"  {phoned} with a phone number    (the dial list)")
    print(f"  {named} with a decision-maker name  ({named * 100 // max(len(rows), 1)}%)")
    print(f"  {missed} with a review complaining about no answer  <- CALL THESE FIRST")
    print(f"  {north} north / {len(rows) - north} south")
    print(f"  {_request_count} API requests used this run")


if __name__ == "__main__":
    main()
