"""Shared transaction categorization for CSV and SimpleFIN ingest."""

KEYWORD_CATEGORIES = {
    "anthropic": "ai",
    "twilio": "telecom",
    "railway": "hosting",
    "namecheap": "domain",
    "godaddy": "domain",
    "google workspace": "saas",
    "canva": "saas",
    "fiverr": "marketing",
    "fedex office": "marketing",
    "il sec of state": "legal",
    "ilsos": "legal",
}


def categorize(description: str) -> str:
    low = description.lower()
    return next((cat for kw, cat in KEYWORD_CATEGORIES.items() if kw in low), "")
