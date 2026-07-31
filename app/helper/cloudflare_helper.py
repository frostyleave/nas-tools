import os

from pyquery import PyQuery

import log

ACCESS_DENIED_TITLES = [
    # Cloudflare
    'Access denied',
    # Cloudflare http://bitturk.net/ Firefox
    'Attention Required! | Cloudflare'
]
ACCESS_DENIED_SELECTORS = [
    # Cloudflare
    'div.cf-error-title span.cf-code-label span',
    # Cloudflare http://bitturk.net/ Firefox
    '#cf-error-details div.cf-error-overview h1'
]
CHALLENGE_TITLES = [
    # Cloudflare
    'Just a moment...',
    '请稍候…',
    # DDoS-GUARD
    'DDOS-GUARD',
]
CHALLENGE_SELECTORS = [
    # Cloudflare Turnstile
    '.cf-turnstile', 'script[src*="challenges.cloudflare.com/turnstile"]',
    # Cloudflare
    '#cf-challenge-running', '.ray_id', '.attack-box', '#cf-please-wait', '#challenge-spinner', '#trk_jschal_js',
    # Custom CloudFlare for EbookParadijs, Film-Paleis, MuziekFabriek and Puur-Hollands
    'td.info #js_info',
    # Fairlane / pararius.com
    'div.vc div.text-box h2'
]
SHORT_TIMEOUT = 6
CF_TIMEOUT = int(os.getenv("NASTOOL_CF_TIMEOUT", "60"))

# Pre-join all challenge selectors so they can be checked in a single DOM query
_COMBINED_CHALLENGE_SELECTOR = ', '.join(CHALLENGE_SELECTORS)
# Pre-lowercased titles for fast substring matching
_CHALLENGE_TITLES_LOWER = [t.lower() for t in CHALLENGE_TITLES]
# Distinctive markers for fast plain-text detection (matched case-insensitively)
_FAST_TEXT_MARKERS = [
    'challenges.cloudflare.com/turnstile',
    'cf-turnstile',
]


def under_challenge(html_text: str) -> bool:
    """
    Check if the page is under a Cloudflare / DDoS-GUARD challenge.

    Uses fast plain-text substring matching first (no DOM parsing).
    Falls back to a single PyQuery DOM query only when the text check
    is inconclusive.

    :param html_text: raw HTML content of the page
    :return: True if a challenge page is detected
    """
    if not html_text:
        return False

    html_lower = html_text.lower()

    # ---- fast path: substring match against raw HTML (no parsing) ----
    for title in _CHALLENGE_TITLES_LOWER:
        if title in html_lower:
            log.debug(f"under_challenge detected via title text: {title}")
            return True

    for marker in _FAST_TEXT_MARKERS:
        if marker in html_lower:
            log.debug(f"under_challenge detected via text marker: {marker}")
            return True

    # ---- slow path: single PyQuery instance for both title & selectors ----
    doc = PyQuery(html_text)

    # <title> check (more precise than raw substring)
    page_title = doc('title').text()
    if page_title:
        page_title_lower = page_title.lower()
        for title in _CHALLENGE_TITLES_LOWER:
            if title in page_title_lower:
                log.debug(f"under_challenge detected via <title>: {page_title}")
                return True

    # combined CSS selector check (all selectors in one call)
    if doc(_COMBINED_CHALLENGE_SELECTOR):
        log.debug("under_challenge detected via challenge selector")
        return True

    return False

