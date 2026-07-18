"""
LinkedIn Job Scraper — Browser Automation with Playwright
==========================================================

CS Concepts Demonstrated:
    - Async/Await (Cooperative Concurrency):
        async/await is Python's implementation of cooperative multitasking.
        Unlike threads (which are preempted by the OS), coroutines
        voluntarily yield control with 'await'. When a coroutine awaits
        an I/O operation (network request, sleep), the event loop
        switches to another coroutine that's ready to run.

        This is ideal for web scraping because:
          - 99% of time is spent WAITING (network I/O), not computing
          - An event loop can handle thousands of concurrent waits
          - No thread overhead (8MB stack per thread vs <1KB per coroutine)
          - No locking needed (only one coroutine runs at a time)

        The event loop model: Think of it as a single-threaded scheduler
        that maintains a queue of "ready" coroutines. At each 'await'
        point, the current coroutine is suspended and a ready coroutine
        is resumed. This is similar to how an OS scheduler works, but
        at the application level.

    - Headless Browser Automation:
        A "headless" browser is a full Chromium browser running without
        a visible window. It still renders pages, executes JavaScript,
        manages cookies, etc. — it just doesn't draw pixels to a screen.
        This makes it efficient for servers/CI runners (no GPU needed).

        Playwright vs Selenium:
          - Playwright is newer, has a cleaner API, faster startup
          - Playwright uses the Chrome DevTools Protocol directly
            (not WebDriver), giving it more control
          - Playwright has auto-waiting built in (click waits for
            element to be visible, enabled, and stable)
          - Playwright can also control Firefox and WebKit

    - Exponential Backoff (Retry Pattern):
        When a request fails (rate limit, timeout), waiting a fixed
        time and retrying is naive — if the server is overloaded, all
        clients retrying at the same interval create a "thundering herd."
        Exponential backoff spaces retries increasingly far apart:
          Attempt 1: wait 10s    (10 × 2^0)
          Attempt 2: wait 20s    (10 × 2^1)
          Attempt 3: wait 40s    (10 × 2^2)
        This gives the server time to recover between retry waves.

    - Anti-Detection Evasion:
        Websites use multiple signals to detect bots:
          1. navigator.webdriver property (set to true by WebDriver)
          2. User-Agent string (headless browsers sometimes have unique UAs)
          3. Fixed behavior timing (bots click at exact intervals)
          4. Missing browser features (headless Chrome lacks some APIs)
          5. Viewport size (bots often use default or unusual sizes)
        We counter several of these; the specifics are in the code.

    - Graceful Degradation:
        Instead of crashing on the first error, we handle each failure
        gracefully: skip the problematic job, log a warning, continue
        with the remaining jobs. The finally block ensures the browser
        is always closed, even on fatal errors. This principle is
        critical for automated pipelines that must run unattended.

    - CSS Selectors & DOM Traversal:
        CSS selectors are patterns that match DOM elements. They form
        a language for tree traversal:
          .class-name      = elements with this class
          [attribute]      = elements with this attribute
          :has-text("X")   = elements containing text X (a Playwright extension)
          parent > child   = direct child selector
          ancestor descendant = any descendant selector
        Understanding CSS selector specificity is essential for web scraping.

    - Separation of Concerns (SoC):
        This module orchestrates the scraping pipeline but delegates
        specific responsibilities:
          - URL construction  → build_search_url()
          - Text extraction   → extract_text(), extract_job_card_data()
          - Parsing           → parser.parse_job() (separate module)
          - Persistence       → db.upsert_jobs() (separate module)
        Each concern lives in its own function/module, making the
        code testable in isolation.

Architecture Role:
    This is the INGESTION TIER's orchestrator. It:
      - Receives: CLI args (limit, keywords, location, headless flag)
      - Does: Launches Playwright browser, navigates LinkedIn,
              extracts job data from the DOM, delegates to parser
      - Produces: List of parsed job dicts for database upsert

    The pipeline is:
      main() → scrape_jobs() → [navigate → load → extract → parse] × N → upsert

Dependencies & Rationale:
    - playwright: Browser automation (Chromium via CDP)
    - scraper.parser: Job description parsing (pure functions)
    - scraper.db: Database persistence (ORM)
    - scraper.utils: Logging, env vars, delays, User-Agent rotation
    - asyncio: Python's async runtime (stdlib)
    - argparse: CLI argument parsing (stdlib)

Usage:
    python scraper/main.py                    # Default: 5 jobs
    python scraper/main.py --limit 20         # 20 jobs
    python scraper/main.py --limit 100        # Full CI/CD run
    python scraper/main.py --no-headless      # Debug: show browser
    python scraper/main.py --search-keywords "Python Dev" --location "London, UK"
"""

import argparse
import asyncio  # Python's async runtime — provides the event loop

from playwright.async_api import (  # Playwright's async Python API
    Page,  # Represents a single browser tab
    async_playwright,  # Context manager for Playwright lifecycle
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeout,  # Playwright's timeout (distinct from asyncio.TimeoutError)
)

from scraper.db import get_engine, init_db, upsert_jobs
from scraper.parser import parse_job, parse_posted_date
from scraper.utils import (
    get_random_user_agent,  # User-Agent rotation for anti-detection
    load_env,  # Load .env file
    random_delay,  # Async sleep with random duration
    setup_logging,  # Structured logging
)

logger = setup_logging(__name__)


# ═══════════════════════════════════════════════════════════════════
# LINKEDIN CONFIGURATION
# ═══════════════════════════════════════════════════════════════════
#
# This is the default search URL. The build_search_url() function
# dynamically constructs this with custom keywords and location.
# LinkedIn's search URL format:
#   /jobs/search/?keywords={URL-ENCODED}&location={URL-ENCODED}
#
# LinkedIn URL-encodes spaces as %20 (not +). Using + sometimes
# still works but %20 is the official encoding per RFC 3986.

LINKEDIN_SEARCH_URL = (
    "https://www.linkedin.com/jobs/search/"
    "?keywords=Junior%20Software%20Engineer"
    "&location=United%20States"
)


# ═══════════════════════════════════════════════════════════════════
# DOM SELECTORS — The Bridge Between Code and the Browser
# ═══════════════════════════════════════════════════════════════════
#
# SELECTORS maps semantic names ("job_card") to CSS selector strings.
# Each selector string may contain MULTIPLE selectors separated by commas.
# Playwright's $$, wait_for_selector, etc. try them in order and use
# the first that matches. This makes the scraper resilient to DOM changes.
#
# Why multiple selectors per element?
#   LinkedIn frequently changes their CSS class names as part of UI
#   redesigns. Using multiple fallback selectors (old + new class names)
#   means the scraper keeps working through minor changes. Only a major
#   structural change would require updating these.
#
# Selector design principles:
#   1. Prefer class selectors (.class-name) — they're moderately stable
#   2. Prefer data attributes ([data-*]) — they're purpose-built, unlikely
#      to change
#   3. Avoid nth-child, ID selectors — highly volatile
#   4. Use Playwright's :has-text() and :text() pseudo-selectors for
#      text-based matching (Playwright-specific extensions to CSS)

SELECTORS = {
    # Job cards in the left sidebar list
    "job_card": (
        ".job-search-card, "                          # Old LinkedIn UI (pre-2024)
        "[data-entity-urn*='jobPosting'], "           # Data attribute with partial match
        ".base-search-card"                           # New LinkedIn UI (2024+)
    ),
    # Job title text within each card
    "job_title": (
        ".base-search-card__title, "
        ".job-search-card__title"
    ),
    # Company name within each card
    "company": (
        ".base-search-card__subtitle, "               # Text node in new UI
        ".job-search-card__subtitle, "                # Text node in old UI
        "a.job-search-card__subtitle-link"            # Link variant (clickable company name)
    ),
    # Location text within each card
    "location": (
        ".job-search-card__location, "
        ".base-search-card__metadata"                  # New UI nests location in metadata
    ),
    # "See more jobs" / "Show more" pagination button
    "see_more": (
        "button:has-text('See more jobs'), "           # :has-text() is a Playwright pseudo-selector
        "button:has-text('Show more'), "
        ".see-more-jobs__viewed-all"                   # CSS class for "all viewed" state
    ),
    # Job description area (right pane, appears after clicking a card)
    "description": (
        ".jobs-description__content, "                 # New UI (2024+)
        ".jobs-description, "
        "#job-details, "                               # Very old UI (pre-2022)
        ".jobs-box__html-content, "                    # Old UI variant
        "div.jobs-description, "
        ".decorated-job-posting__details, "            # A/B test variant
        "[data-test-job-description]"                  # Structured data attribute
    ),
    # Posted date within each card (e.g., "3 days ago")
    "posted_date": (
        ".job-search-card__listdate, "
        ".job-search-card__listdate--new, "            # "new" variant (just posted)
        "time, "                                       # HTML <time> element (semantic)
        ".base-search-card__metadata time"             # New UI nests time in metadata
    ),
    # The scrollable container that holds all job cards
    "job_list": (
        ".jobs-search__results-list, "
        ".jobs-search-results-list, "                  # Old UI variant (no underscore)
        ".scaffold-layout__list, "                     # Generic layout class
        ".two-pane-serp-page__results-list"            # SERP = Search Engine Results Page
    ),
}


# ═══════════════════════════════════════════════════════════════════
# CONSTANTS — Configuration Values That Shouldn't Change at Runtime
# ═══════════════════════════════════════════════════════════════════
#
# These are module-level constants (UPPER_CASE convention). They exist
# so that parameters aren't "magic numbers" buried in the code.
# A reader can see all tunable values in one place.

DEFAULT_JOB_LIMIT = 5          # Safe default for local testing (quick, won't trigger rate limits)
CI_JOB_LIMIT = 100             # Full run for CI/CD pipeline
MAX_SCROLL_ATTEMPTS = 20       # Maximum scroll cycles before giving up (prevents infinite loops)
SCROLL_PAUSE_MIN = 2           # Minimum seconds between scrolls (seconds)
SCROLL_PAUSE_MAX = 5           # Maximum seconds between scrolls (seconds)


# ═══════════════════════════════════════════════════════════════════
# CLI ARGUMENT PARSING
# ═══════════════════════════════════════════════════════════════════
#
# argparse is Python's standard library for parsing command-line
# arguments. It handles:
#   - Type conversion (--limit 50 → args.limit = 50, an int)
#   - Default values (--limit omitted → args.limit = DEFAULT_JOB_LIMIT)
#   - Help text generation (--help flag)
#   - Flag vs positional argument distinction
#   - Error messages for invalid input

def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments into a Namespace object.

    Returns an argparse.Namespace with attributes:
        limit: int               — max jobs to scrape
        no_headless: bool        — True = show browser, False = headless
        search_keywords: str     — LinkedIn search terms
        location: str            — LinkedIn search location
        init_db: bool            — True = create tables before scraping

    argparse.Namespace is a simple object whose attributes are set
    from the CLI arguments. Think of it as a typed dict with dot-notation
    access (args.limit instead of args["limit"]).
    """
    parser = argparse.ArgumentParser(
        description="Scrape LinkedIn for junior software engineer jobs."
    )
    # --limit / -l: Maximum number of jobs to scrape
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=DEFAULT_JOB_LIMIT,
        help=f"Maximum number of jobs to scrape (default: {DEFAULT_JOB_LIMIT})",
    )
    # --no-headless: Flag (True if present, False if absent)
    # action="store_true" means no value is expected — just the flag presence
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browser in visible mode (for debugging)",
    )
    parser.add_argument(
        "--search-keywords",
        default="Junior Software Engineer",
        help="LinkedIn search keywords",
    )
    parser.add_argument(
        "--location",
        default="United States",
        help="LinkedIn search location",
    )
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="Initialize database schema before scraping",
    )
    return parser.parse_args()


# ═══════════════════════════════════════════════════════════════════
# BROWSER SETUP — Launching and Configuring Playwright
# ═══════════════════════════════════════════════════════════════════

async def setup_browser(headless: bool = True):
    """
    Launch Playwright Chromium browser with anti-detection measures.

    The Playwright lifecycle has 4 objects:
        1. Playwright (the browser automation framework)
        2. Browser (a browser instance — Chromium, Firefox, or WebKit)
        3. BrowserContext (an isolated browsing session — cookies, storage, etc.)
        4. Page (a single browser tab)

    Think of it like: you run a program (Playwright), open an application
    (Browser), create a new profile (Context), and open a tab (Page).

    Returns a 4-tuple: (playwright, browser, context, page).
    The caller is responsible for closing resources in reverse order.

    Anti-detection measures explained:
        1. --disable-blink-features=AutomationControlled:
           Blink is Chrome's rendering engine. "AutomationControlled" is
           a flag that Chrome adds when launched via automation (WebDriver,
           CDP). Disabling this flag makes Chrome behave more like a
           user-launched browser.

        2. navigator.webdriver override:
           In JavaScript, navigator.webdriver is true for automated
           browsers and undefined for normal browsers. LinkedIn checks
           this property. We use add_init_script() to inject JavaScript
           that runs before any page scripts, overwriting the property
           to return undefined (normal browser behavior).

        3. User-Agent rotation:
           Random selection from a pool of 4 browser/OS combinations
           (see utils.py). Prevents all requests from looking identical.

        4. Viewport size 1920×1080:
           The most common desktop resolution. Unusual viewport sizes
           (especially headless defaults like 800×600) are a bot signal.

        5. locale="en-US":
           Sets Accept-Language header and navigator.language to US English,
           matching the expected locale for job searches in the US.

    Args:
        headless: True = invisible browser, False = visible (for debugging).

    Returns:
        Tuple: (playwright, browser, context, page)
    """
    # Start Playwright — this is the top-level automation framework
    playwright = await async_playwright().start()

    # Launch a Chromium browser instance
    browser = await playwright.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",                        # Required for running as root (CI/Docker)
            "--disable-dev-shm-usage",             # Workaround for limited /dev/shm in Docker
        ],
    )

    # Create an isolated browser context (new cookies/storage per run)
    context = await browser.new_context(
        user_agent=get_random_user_agent(),
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
    )

    # Inject anti-detection JavaScript BEFORE any page loads.
    # This is critical: if the page loads first, it can read the
    # original navigator.webdriver value and cache it. By running
    # BEFORE page scripts, our override takes effect immediately.
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });
    """)

    page = await context.new_page()
    logger.info("Browser launched (headless=%s).", headless)

    return playwright, browser, context, page


# ═══════════════════════════════════════════════════════════════════
# URL CONSTRUCTION
# ═══════════════════════════════════════════════════════════════════

def build_search_url(keywords: str, location: str) -> str:
    """
    Build a LinkedIn job search URL with URL-encoded parameters.

    URL encoding (also called percent-encoding) converts special
    characters into %XX hexadecimal format:
        Space  → %20
        #      → %23
        ,      → %2C
        &      → %26  (critical — & is the query parameter separator!)

    Without encoding, a search for "C# Developer" would produce:
        ?keywords=C# Developer&location=...
    The # would be interpreted as a fragment identifier, truncating
    the search term. With encoding, we get:
        ?keywords=C%23%20Developer&location=...

    urllib.parse.quote() is Python's URL encoder. It escapes all
    characters except letters, digits, and _.-~ (the "unreserved"
    characters per RFC 3986).

    Args:
        keywords: Search keywords (e.g., "Junior Software Engineer").
        location: Location filter (e.g., "United States").

    Returns:
        Fully qualified LinkedIn search URL as a string.
    """
    from urllib.parse import quote
    return (
        "https://www.linkedin.com/jobs/search/"
        f"?keywords={quote(keywords)}"
        f"&location={quote(location)}"
    )


# ═══════════════════════════════════════════════════════════════════
# OVERLAY DISMISSAL — Clearing Popups and Modals
# ═══════════════════════════════════════════════════════════════════

async def dismiss_overlays(page: Page):
    """
    Dismiss cookie banners, sign-in modals, and other overlays
    that block interaction with job cards.

    Strategy: Try multiple known selector patterns, clicking any
    visible match. Catch exceptions silently — an overlay that
    doesn't exist is not an error.

    Why two Escape presses?
        Some LinkedIn layouts use stacked modals — the sign-in modal
        overlays the cookie banner. One Escape dismisses the sign-in
        modal; the second dismisses the cookie banner. Pressing Escape
        is safer than clicking "X" buttons because:
          - Escape works on any modal (standard browser behavior)
          - No need to locate the close button in the DOM
          - Works regardless of CSS class name changes

    The try/except pattern here is intentional: each selector is
    an optional optimization, not a requirement. If none match,
    the page might not have overlays — proceed normally.

    Args:
        page: Playwright Page object (the browser tab).
    """
    await random_delay(1, 2)    # Give overlays time to render

    # Known overlay types and their dismiss buttons
    dismissals = [
        ("button:has-text('Accept all')", "cookie accept all"),
        ("button:has-text('Accept')", "cookie accept"),
        ("button:has-text('Dismiss')", "dismiss button"),
        ("[aria-label='Dismiss']", "aria dismiss"),
        ("button.modal__dismiss", "modal dismiss"),
        ("button[aria-label='Dismiss']", "modal aria dismiss"),
        ("text=Not now", "not now"),
        ("text=Skip", "skip"),
        ("text=Maybe later", "maybe later"),
    ]

    for selector, label in dismissals:
        try:
            el = await page.query_selector(selector)
            if el and await el.is_visible():
                await el.click()
                await random_delay(0.5, 1.5)
                logger.info("Dismissed overlay: %s", label)
        except Exception:
            pass    # Selector not found or not clickable — expected, continue

    # Fallback: Press Escape twice to dismiss any remaining modals
    await page.keyboard.press("Escape")
    await random_delay(0.5, 1)
    await page.keyboard.press("Escape")
    await random_delay(0.5, 1)


# ═══════════════════════════════════════════════════════════════════
# JOB CARD LOADING — Infinite Scroll
# ═══════════════════════════════════════════════════════════════════

async def load_job_cards(page: Page, target_count: int) -> int:
    """
    Scroll the job list to load job cards via LinkedIn's lazy loading.

    LinkedIn (like many modern web apps) uses INFINITE SCROLL: job cards
    are loaded dynamically as the user scrolls down. The initial page
    load only has ~7-10 cards; more are fetched via XHR/fetch as you
    scroll. This function simulates that scrolling behavior.

    Algorithm:
        1. Count current job cards in the DOM
        2. If count >= target: done
        3. Scroll to bottom of the job list container
        4. Wait for new cards to load (random delay mimics human)
        5. If a "See more jobs" button appears, click it
        6. If no new cards loaded after scrolling: done (reached end)
        7. Goto 1 (up to MAX_SCROLL_ATTEMPTS times)

    Termination conditions:
        a. Enough cards loaded (count >= target)
        b. No new cards after scrolling (end of list)
        c. MAX_SCROLL_ATTEMPTS reached (prevents infinite loop)

    The .evaluate() method runs JavaScript in the browser context.
    "el => el.scrollTop = el.scrollHeight" is an arrow function
    that sets the scroll position to the very bottom of the element.
    This triggers LinkedIn's scroll event handler, which fetches
    more job cards.

    Args:
        page: Playwright Page object.
        target_count: Desired number of job cards.

    Returns:
        int: Actual number of job cards loaded (may be less than target
             if LinkedIn has fewer results).
    """
    for attempt in range(MAX_SCROLL_ATTEMPTS):
        cards = await page.query_selector_all(SELECTORS["job_card"])
        current_count = len(cards)
        logger.info(
            "Scroll attempt %d/%d: %d cards loaded (target: %d)",
            attempt + 1, MAX_SCROLL_ATTEMPTS, current_count, target_count,
        )

        if current_count >= target_count:
            break    # Done — enough cards loaded

        # Try to find the scrollable job list container
        job_list = await page.query_selector(SELECTORS["job_list"])
        if job_list:
            # Scroll the job list container itself (new LinkedIn UI)
            await job_list.evaluate("el => el.scrollTop = el.scrollHeight")
        else:
            # Fallback: scroll the whole page (old LinkedIn UI)
            await page.evaluate("window.scrollBy(0, 1000)")

        # Random delay mimics human reading time between scrolls
        await random_delay(SCROLL_PAUSE_MIN, SCROLL_PAUSE_MAX)

        # LinkedIn sometimes shows a "See more jobs" button instead of
        # auto-loading on scroll. This button loads another batch.
        see_more = await page.query_selector(SELECTORS["see_more"])
        if see_more:
            try:
                await see_more.click()
                logger.info("Clicked 'See more jobs' button")
                await random_delay(2, 4)    # Longer delay after button click
            except PlaywrightTimeout:
                pass

        # Check if scrolling actually loaded new cards
        cards_after = await page.query_selector_all(SELECTORS["job_card"])
        if len(cards_after) == current_count:
            # No new cards — likely reached the end of results
            logger.info("No new cards loaded - stopping scroll loop.")
            break

    cards = await page.query_selector_all(SELECTORS["job_card"])
    logger.info("Finished loading: %d job cards available.", len(cards))
    return len(cards)


# ═══════════════════════════════════════════════════════════════════
# DATA EXTRACTION — Reading Text from DOM Elements
# ═══════════════════════════════════════════════════════════════════

async def extract_text(element, selector_list: str) -> str | None:
    """
    Try multiple CSS selectors on an element, return first non-empty text.

    A multi-selector fallback function. Given a parent element and a
    comma-separated list of CSS selectors, it tries each selector in
    order until one yields text content.

    Why not just use one selector?
        LinkedIn runs A/B tests and regional variations — different users
        see different DOM structures. A selector that works today might
        not work tomorrow (they might change a class name). Multi-selector
        fallback provides resilience without constant maintenance.

    .text_content() vs .inner_text():
        text_content() returns ALL text including hidden elements.
        inner_text() returns only visible text (respects CSS display:none).
        We use text_content() because it's faster and more predictable.

    Args:
        element: Parent Playwright ElementHandle.
        selector_list: Comma-separated CSS selectors to try.

    Returns:
        str | None: Trimmed text content, or None if no selector matches.
    """
    for sel in [s.strip() for s in selector_list.split(",")]:
        try:
            el = await element.query_selector(sel)
            if el:
                text = await el.text_content()
                if text and text.strip():
                    return text.strip()
        except Exception:
            continue    # Selector failed — try the next one
    return None


async def extract_job_card_data(card) -> dict[str, str | None]:
    """
    Extract basic info from a job card element in the list.

    LinkedIn job cards contain metadata in both the DOM content (text)
    and element attributes (data-job-id, data-entity-urn). We extract
    both.

    The linkedin_job_id is critical — without it, we can't deduplicate
    jobs. It's extracted from two possible sources:
        1. data-job-id attribute (newer LinkedIn UI, direct ID)
        2. data-entity-urn attribute (older UI, URN format)
           URN format: "urn:li:jobPosting:3876543210"
           We split on ":" and take the last segment as the ID.

    Returns dict with linkedin_job_id, title, company, location,
    posted_date_raw (unparsed).

    Args:
        card: Playwright ElementHandle for a job card.

    Returns:
        dict with keys: linkedin_job_id, title, company, location,
        posted_date_raw.
    """
    # Extract the unique job ID from card attributes
    job_id = await card.get_attribute("data-job-id")
    if not job_id:
        # Fallback: try the URN format
        urn = await card.get_attribute("data-entity-urn")
        if urn and ":" in urn:
            job_id = urn.split(":")[-1]    # "urn:li:jobPosting:123" → "123"

    title = await extract_text(card, SELECTORS["job_title"])
    company = await extract_text(card, SELECTORS["company"])
    location = await extract_text(card, SELECTORS["location"])
    posted_date_raw = await extract_text(card, SELECTORS["posted_date"])

    return {
        "linkedin_job_id": job_id or "",
        "title": title or "",
        "company": company or "",
        "location": location or "",
        "posted_date_raw": posted_date_raw or "",
    }


async def extract_job_description(page: Page) -> str | None:
    """
    Extract the full job description from the right pane.

    MUST be called AFTER clicking a job card — the description only
    appears in the right pane after a card is selected.

    page.wait_for_selector() is a Playwright auto-wait: it waits up
    to the timeout (10 seconds) for the element to appear in the DOM.
    If the element is already present, it returns immediately.
    This is the key difference between Playwright and Selenium:
    Playwright auto-waits (you don't need explicit time.sleep() before
    each action).

    The 10-second timeout balances:
        - Fast: 1-2 seconds is typical for description to load
        - Tolerance: Occasionally LinkedIn's API is slow under load
        - Efficiency: Waiting too long slows down the entire batch

    Args:
        page: Playwright Page object.

    Returns:
        str | None: Job description text, or None if not found within timeout.
    """
    try:
        desc_el = await page.wait_for_selector(
            SELECTORS["description"],
            timeout=10000,    # 10 seconds
        )
        if desc_el:
            return await desc_el.text_content()
    except PlaywrightTimeout:
        logger.warning("Timed out waiting for job description to load.")
    return None


# ═══════════════════════════════════════════════════════════════════
# RATE LIMIT & BLOCK DETECTION
# ═══════════════════════════════════════════════════════════════════

# These are text fragments that LinkedIn uses on its block/challenge pages.
# When we detect these, we stop scraping and back off.
# The list is based on observed LinkedIn behavior and is not exhaustive.
BLOCK_INDICATORS = [
    "unusual activity",          # "We've detected unusual activity from your network"
    "verify you're human",       # CAPTCHA challenge
    "security verification",      # "Security verification required"
    "captcha",                    # Generic CAPTCHA detection
    "too many requests",          # Rate limit response
    "rate limit",                 # Explicit rate limiting
    "access denied",              # IP block
    "please try again",           # Generic error
]

RETRY_MAX_ATTEMPTS = 3            # How many times to retry before giving up
RETRY_BASE_DELAY = 10             # Base delay in seconds (for exponential backoff)


async def is_blocked(page: Page) -> bool:
    """
    Check if LinkedIn is showing a block, challenge, or rate-limit page.

    Two checks:
        1. Body text: Search for block indicator keywords in the page
           content. Case-insensitive substring matching.
        2. Page title: LinkedIn's login/sign-in page always has
           "Login" or "Sign In" in the <title>. If we see this, we've
           been redirected away from the search results.

    Why check both? Some block pages don't mention "blocked" explicitly
    but instead redirect to the login page (LinkedIn assumes you got
    rate-limited and wants you to log in to "verify" you're human).

    Returns:
        bool: True if the page appears to be a block/rate-limit page.
    """
    try:
        content = await page.text_content("body")
        if content:
            content_lower = content.strip().lower()
            for indicator in BLOCK_INDICATORS:
                if indicator in content_lower:
                    logger.warning("Block indicator detected: '%s'", indicator)
                    return True
    except Exception:
        pass    # If we can't read the body, assume not blocked (proceed with caution)

    page_title = await page.title()
    title_lower = page_title.lower()
    if "login" in title_lower or "sign in" in title_lower:
        logger.warning("Redirected to login/auth page.")
        return True

    return False


async def navigate_with_retry(
    page: Page, url: str, max_attempts: int = RETRY_MAX_ATTEMPTS
) -> bool:
    """
    Navigate to a URL with exponential backoff on failure.

    This implements the classic "retry with exponential backoff" pattern:

        Attempt 1: navigate → if fail, wait 10s  (10 × 2^(1-1))
        Attempt 2: navigate → if fail, wait 20s  (10 × 2^(2-1))
        Attempt 3: navigate → if fail, give up   (10 × 2^(3-1))

    Failure conditions that trigger a retry:
        - HTTP 429 (Too Many Requests): LinkedIn's explicit rate limit
        - Block page detected: LinkedIn is showing a challenge/block page
        - Timeout: Page didn't load within 30 seconds

    Why exponential and not linear?
        Linear backoff (10s, 10s, 10s) produces a "thundering herd"
        of simultaneous retries. Exponential backoff (10s, 20s, 40s)
        spreads retries across time, giving the server room to recover.

    wait_until="domcontentloaded":
        This tells Playwright to consider navigation complete when the
        DOM has been parsed (HTML loaded, DOM tree built). We DON'T wait
        for "networkidle" (all network requests finished) because
        LinkedIn makes many background XHR/analytics requests that may
        never "finish". Using "networkidle" would cause timeouts on
        otherwise-loaded pages.

    Args:
        page: Playwright Page object.
        url: Target URL to navigate to.
        max_attempts: Maximum retry attempts before giving up.

    Returns:
        bool: True if navigation succeeded, False after exhausting all attempts.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000,    # 30 seconds
            )

            # HTTP 429 = Too Many Requests (RFC 6585)
            # LinkedIn explicitly telling us to slow down
            if response and response.status == 429:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "HTTP 429 rate limit (attempt %d/%d). Backing off %ds...",
                    attempt, max_attempts, delay,
                )
                await asyncio.sleep(delay)
                continue

            await random_delay(3, 5)

            # Check if the loaded page is a block/challenge page
            if await is_blocked(page):
                if attempt < max_attempts:
                    delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "Block/challenge page detected (attempt %d/%d). Backing off %ds...",
                        attempt, max_attempts, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error(
                    "Block/challenge page persists after %d attempts.", max_attempts
                )
                return False

            # Success: URL loaded, no block detected
            return True

        except PlaywrightTimeout:
            if attempt < max_attempts:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "Page load timed out (attempt %d/%d). Backing off %ds...",
                    attempt, max_attempts, delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "Page load timed out after %d attempts.", max_attempts
                )

    return False    # All attempts exhausted


# ═══════════════════════════════════════════════════════════════════
# MAIN SCRAPING ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════

async def scrape_jobs(
    limit: int = DEFAULT_JOB_LIMIT,
    headless: bool = True,
    search_keywords: str = "Junior Software Engineer",
    location: str = "United States",
) -> list[dict]:
    """
    Main scraping orchestration — the "conductor" of the pipeline.

    Pipeline steps:
        1. Launch browser with anti-detection measures
        2. Navigate to LinkedIn search results (with retry)
        3. Dismiss cookie banners and sign-in overlays
        4. Load job cards via infinite scroll (simulate human scrolling)
        5. For each card (up to limit):
           a. Extract card metadata (title, company, location, date)
           b. Click the card (loads description in right pane)
           c. Extract the job description text
           d. Parse the description (delegates to parser.py)
           e. Collect parsed job into results list
        6. Return parsed job list

    Error handling strategy (graceful degradation):
        - Individual card failures: Catch, log, skip — continue with
          the next card
        - Mid-scrape rate limits: Check is_blocked() every 15 cards,
          stop if detected
        - Fatal errors: Catch in outer try/except, log traceback,
          return partial results (whatever was scraped before the error)

    Resource cleanup (finally block):
        The browser MUST be closed even if an error occurs. An orphaned
        headless browser consumes memory and might persist in the process
        table. The finally block guarantees cleanup regardless of how
        the try block exits (success, exception, or even return).

    Args:
        limit: Maximum number of jobs to scrape.
        headless: True = invisible browser, False = visible debug mode.
        search_keywords: LinkedIn search terms.
        location: LinkedIn search location.

    Returns:
        list[dict]: Parsed job records ready for database upsert.
                    Empty list on failure.
    """
    playwright = None
    browser = None

    try:
        # Step 1: Launch browser
        playwright, browser, context, page = await setup_browser(headless)

        # Step 2: Navigate to LinkedIn search
        url = build_search_url(search_keywords, location)
        logger.info("Navigating to: %s", url)

        if not await navigate_with_retry(page, url):
            logger.error("Failed to navigate to LinkedIn. Aborting.")
            return []

        # Step 3: Dismiss overlays
        await dismiss_overlays(page)

        # Step 4: Load job cards via scrolling
        card_count = await load_job_cards(page, limit)
        if card_count == 0:
            logger.warning("No job cards found - LinkedIn may have changed its DOM.")
            return []

        # Don't try to process more cards than are actually available
        actual_limit = min(limit, card_count)
        cards = await page.query_selector_all(SELECTORS["job_card"])
        cards = cards[:actual_limit]

        # Step 5: Process each card
        parsed_jobs = []
        for i, card in enumerate(cards):
            logger.info("Processing job %d/%d", i + 1, actual_limit)

            # Periodic rate-limit check (every 15 cards)
            if i > 0 and i % 15 == 0:
                if await is_blocked(page):
                    logger.warning(
                        "Rate-limit detected mid-scrape at job %d. Stopping.", i + 1
                    )
                    break    # Exit scrape loop, return whatever we have

            try:
                # 5a: Extract basic info from the card
                raw_data = await extract_job_card_data(card)

                if not raw_data["linkedin_job_id"]:
                    logger.warning("Skipping job %d: no linkedin_job_id", i + 1)
                    continue    # Skip cards without a job ID (can't store them)

                # 5b: Click the card to load the description in the right pane
                # scroll_into_view_if_needed() ensures the card is visible
                # before clicking. Clicking a non-visible element can fail.
                await card.scroll_into_view_if_needed()
                await random_delay(0.3, 0.8)    # Short pause before click
                await card.click()
                await random_delay(1, 3)         # Wait for description to load

                # 5c: Extract job description from the right pane
                description = await extract_job_description(page)
                posted_date = parse_posted_date(raw_data["posted_date_raw"])

                # 5d: Package raw data for the parser
                raw_job = {
                    "linkedin_job_id": raw_data["linkedin_job_id"],
                    "title": raw_data["title"],
                    "company": raw_data["company"],
                    "location": raw_data["location"],
                    "posted_date": posted_date,
                    "job_description": description or "",
                }

                # 5e: Delegate parsing to parser.py (pure function, no I/O)
                parsed = parse_job(raw_job)
                parsed_jobs.append(parsed)

                logger.info(
                    "  -> %s | %s | Exp: %s | Tech: %s",
                    parsed["title"][:50],
                    parsed["company"][:30],
                    parsed["years_experience_required"],
                    parsed["tech_stack"],
                )

            except PlaywrightTimeout as e:
                logger.warning("Timeout on job %d: %s", i + 1, e)
                continue    # Skip this card, continue with the next
            except Exception as e:
                logger.error("Error on job %d: %s", i + 1, e)
                continue    # Skip this card, continue with the next

        logger.info(
            "Scraping complete: %d jobs parsed from %d cards attempted.",
            len(parsed_jobs), actual_limit,
        )
        return parsed_jobs

    except Exception as e:
        # Outer catch-all: any fatal error that prevents the entire
        # scrape from continuing (e.g., browser crash, network failure)
        logger.error("Fatal scraping error: %s", e, exc_info=True)
        return []    # Return empty list rather than crashing

    finally:
        # ALWAYS close the browser, even on errors.
        # Close order matters: browser before playwright.
        #   - browser.close(): Closes all pages and the browser process
        #   - playwright.stop(): Shuts down the automation framework
        # If page.close() is called first, it's fine — browser.close()
        # handles already-closed pages gracefully.
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()


# ═══════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

async def main():
    """
    Main entry point for the scraper CLI.

    Connects the CLI arguments → scraping pipeline → database pipeline:
        1. Parse command-line arguments
        2. Load environment variables (.env file)
        3. Get/initialize database engine
        4. Optionally create tables (--init-db)
        5. Run the scraper with specified parameters
        6. Upsert results to the database
        7. Log summary

    asyncio.run(main()) is the standard way to run an async function
    from synchronous Python code (like __main__). It:
        1. Creates a new event loop
        2. Runs the coroutine until it completes
        3. Closes the event loop
        4. Returns the result (or raises the exception)
    """
    args = parse_args()

    # Load .env file BEFORE any code tries to access DATABASE_URL
    load_env()

    logger.info("=" * 60)
    logger.info("RealityCheck Scraper starting...")
    logger.info(
        "Target: %d jobs | Keywords: %s | Location: %s",
        args.limit, args.search_keywords, args.location,
    )
    logger.info("=" * 60)

    # Database setup
    engine = get_engine()
    if args.init_db:
        init_db(engine)

    # Run the scraping pipeline
    jobs = await scrape_jobs(
        limit=args.limit,
        headless=not args.no_headless,
        search_keywords=args.search_keywords,
        location=args.location,
    )

    if not jobs:
        logger.warning("No jobs scraped. Exiting.")
        return

    # Persist results to database
    inserted = upsert_jobs(engine, jobs)
    logger.info(
        "Done: %d new jobs inserted (total %d processed).",
        inserted, len(jobs),
    )


# Python's entry point convention:
#   if __name__ == "__main__" is True when this file is executed directly
#   (python scraper/main.py). It's False when this file is imported as
#   a module (from scraper.main import scrape_jobs in batch.py).
# This allows the same file to serve as both a script and a library module.
if __name__ == "__main__":
    asyncio.run(main())
