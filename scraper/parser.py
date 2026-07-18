"""
NLP and Regex Parsing for LinkedIn Job Descriptions
====================================================

CS Concepts Demonstrated:
    - Regular Expressions (Regex) & Finite Automata:
        Regex engines compile patterns into NFAs (Nondeterministic Finite
        Automata), then simulate them on input text. Key behaviors to
        understand:
          * Greedy vs Lazy quantifiers: `(\\d+)` is greedy (matches as
            many digits as possible), `(\\d+?)` would be lazy (minimal match).
          * Backtracking: When a regex fails partway through a match, the
            engine "backtracks" to try alternative paths. Catastrophic
            backtracking occurs when the engine explores exponentially
            many paths — we avoid this by keeping patterns simple.
          * Word boundaries: `\\b` matches the transition between a word
            character (\\w = [a-zA-Z0-9_]) and a non-word character. This
            prevents "java" from matching inside "javascript".
          * re.IGNORECASE: The `i` flag. Makes the pattern match both
            uppercase and lowercase. In some engines this is O(1), in
            others it increases state space.

    - False-Positive Filtering (Denylist Strategy):
        Regex alone is naive — it matches patterns without semantics.
        "Team of 5 engineers" would match the experience regex (the "5"
        looks like years). We apply a DENYLIST of false-positive patterns
        FIRST, removing them from the text before the main regex runs.
        This is simpler than a machine learning approach for a
        well-defined, narrow domain.

    - Entity Extraction from Unstructured Text:
        We extract three types of entities from raw job descriptions:
          1. Numeric (years of experience) — regex + filtering
          2. Categorical (tech stack, AI tools) — keyword matching
          3. Boolean (junior title, AI presence) — classification
        This is a rule-based approach (no ML). Rule-based extraction
        works well when the vocabulary is small and patterns are
        predictable.

    - Composition Over Inheritance:
        The parse_job() function COMPOSES the individual parsers rather
        than inheriting from a base class. Each parser function is
        independently testable, reusable, and understandable.

    - Data Structure: Set for O(1) membership testing:
        extract_tech_stack() uses a Python set() to deduplicate
        technologies. Hash sets provide average O(1) insertion and
        lookup, making them ideal for removing duplicates from a stream.

Architecture Role:
    This module is a collection of PURE FUNCTIONS — no I/O, no database,
    no network, no global state. Given the same input, they always
    return the same output (deterministic). This makes them:
      - Trivially testable (no mocking needed)
      - Cacheable (memoize if needed)
      - Parallelizable (no shared state = no race conditions)

    Input:  Raw dict from scraper (linkedin_job_id, title, company,
            location, posted_date, job_description)
    Output: Parsed dict with extracted metrics (years_experience_required,
            tech_stack, etc.)

Dependencies & Rationale:
    - re       (stdlib): Python's regex engine. Sufficient for our pattern
                complexity; we don't need the regex library's
                additional features (named groups, Unicode categories).
    - datetime (stdlib): Date arithmetic for parse_posted_date().
"""

import re
from datetime import datetime, timedelta, timezone

# ═══════════════════════════════════════════════════════════════════
# TECH STACK DETECTION
# ═══════════════════════════════════════════════════════════════════
#
# Strategy: For each technology, maintain a list of search variants
# (aliases, abbreviations, alternate spellings). Match ANY variant
# using word-boundary regex, then store the NORMALIZED name.
#
# This implements a form of string normalization — different surface
# forms (e.g., "Node.js", "nodejs", "node") all map to the same
# canonical label ("node"). This is the same principle behind database
# normalization (one canonical representation per entity).

# Format: { normalized_name: [variant_strings] }
#
# "word boundary" (\b) — The zero-width anchor between a word character
# ([a-zA-Z0-9_]) and a non-word character. Critical because:
#   - Without \b: "java" would match inside "javascript"
#   - Without \b: "c++" can't use \b because '+' isn't a word char
#
# The variant lists are curated manually based on common LinkedIn
# job description vocabulary. This is a finite vocabulary problem
# — we know the set of technologies in advance.

TECH_VARIANTS = {
    "python":      ["python"],
    "java":        ["java"],            # \b prevents matching "javascript"
    "javascript":  ["javascript", "js", "ecmascript"],
    "typescript":  ["typescript", "ts"],
    "react":       ["react", "reactjs", "react.js"],
    "angular":     ["angular", "angularjs", "angular.js"],
    "vue":         ["vue", "vuejs", "vue.js"],
    "node":        ["node", "nodejs", "node.js"],
    "next":        ["next", "nextjs", "next.js"],
    "django":      ["django"],
    "flask":       ["flask"],
    "spring":      ["spring", "spring boot", "springboot"],
    "dotnet":      [".net", "dotnet", "asp.net", "aspnet"],
    "php":         ["php"],
    "ruby":        ["ruby", "ruby on rails"],
    "rails":       ["rails"],
    # NOTE: "go" deliberately only matches "golang", NOT the word "go".
    # The word "go" is one of the most common English verbs. Matching
    # it blindly would produce massive false positives ("go to meetings",
    # "go above and beyond", "let's go"). We take the conservative
    # approach: only "golang" triggers the "go" label. This trades
    # recall (we might miss "Go programming" if the author uses "Go"
    # without "golang") for precision (we don't incorrectly flag every
    # sentence that contains the word "go").
    "go":          ["golang"],
    "rust":        ["rust"],
    "swift":       ["swift"],
    "kotlin":      ["kotlin"],
    "c++":         ["c++", "c++"],
    "c#":          ["c#", "c sharp", "csharp"],
    "sql":         ["sql", "mysql", "postgresql", "postgres", "mssql", "t-sql"],
    "mongodb":     ["mongodb", "mongo"],
    "redis":       ["redis"],
    "aws":         ["aws", "amazon web services"],
    "azure":       ["azure"],
    "gcp":         ["gcp", "google cloud"],
    "docker":      ["docker"],
    "kubernetes":  ["kubernetes", "k8s"],    # k8s = common abbreviation ("k" + 8 letters + "s")
    "terraform":   ["terraform", "terraform"],
    "git":         ["git", "github", "gitlab"],
    "linux":       ["linux", "unix"],
    "rest":        ["rest", "restful", "rest api"],
    "graphql":     ["graphql"],
    "ci/cd":       ["ci/cd", "ci cd", "ci-cd", "jenkins", "github actions"],
}


# ═══════════════════════════════════════════════════════════════════
# AI TOOLS DETECTION
# ═══════════════════════════════════════════════════════════════════
#
# Strategy: Simple substring search (case-insensitive). We use
# Python's 'in' operator (which calls __contains__ on the string)
# instead of regex. Why?
#   - These are specific brand names — no word-boundary issues
#   - 'in' is faster than regex (no pattern compilation needed)
#   - Simpler code = fewer bugs

AI_KEYWORDS = [
    "copilot",
    "cursor",
    "chatgpt",
    "chat gpt",            # Space-separated variant
    "openai",
    "claude",
    "llm",                 # "Large Language Model" — the acronym
    "large language model",# The expanded form
    "gemini",
    "codex",
    "tabnine",
    "code whisperer",      # Amazon CodeWhisperer (now Amazon Q)
]


# ═══════════════════════════════════════════════════════════════════
# JUNIOR TITLE DETECTION
# ═══════════════════════════════════════════════════════════════════
#
# Strategy: Case-insensitive substring matching against a curated
# list of junior-indicating keywords.
#
# "jr." and "jr " are separate entries because:
#   - "Jr. Software Engineer" — the period changes the match boundary
#   - "Jr Software Engineer" — without the period
# Both need to be caught. A more elegant solution would be `jr\.?\s`
# as a regex, but substring matching is simpler and fast enough.

JUNIOR_TITLE_KEYWORDS = [
    "junior",
    "jr.",
    "jr ",
    "entry",
    "entry-level",
    "entry level",
    "associate",
    "graduate",
    "new grad",
    "trainee",
    "intern",
    "internship",
]


# ═══════════════════════════════════════════════════════════════════
# EXPERIENCE EXTRACTION REGEX
# ═══════════════════════════════════════════════════════════════════
#
# This regex is the heart of the experience parser. Let's break it down:
#
# Pattern (in verbose terms):
#   (?:at least|minimum|min|over|more than)?   # Optional qualifier (non-capturing)
#   (\d+)                                         # Capture group 1: the number
#   (?:\s*(?:to|-|–|—)\s*\d+)?                 # Optional range suffix: " to N" or "-N"
#   \+?\s*                                        # Optional plus sign: "3+"
#   (?:years?|yrs?)                               # "year(s)" or "yr(s)"
#   (?:\s*of\s*)?                                 # Optional "of"
#   (?:experience|commercial|professional|work|industry)?   # Optional context word
#
# Examples matched:
#   "3+ years of experience"                  → groups(1) = "3"
#   "1-3 years experience"                    → groups(1) = "1" (lower bound)
#   "at least 5 years"                        → groups(1) = "5"
#   "minimum 2 years of professional exp"     → groups(1) = "2"
#   "2 to 5 yrs of commercial experience"     → groups(1) = "2"
#
# Design choices:
#   - We extract the LOWER bound of ranges ("1-3" → 1). This is
#     conservative: an employer saying "1-3 years" means the minimum
#     acceptable is 1 year. The upper bound is aspirational.
#   - The qualifier group (at least, minimum, etc.) is non-capturing
#     (?:...) because we don't need to extract it — we just need to
#     know the number came from a context like "minimum X years".
#   - The en-dash (–) and em-dash (—) are included because some HR
#     systems convert hyphens to typographic dashes in job descriptions.
#
# Character classes used:
#   \d   = [0-9]       — any decimal digit
#   \s   = [ \t\n\r\f\v] — any whitespace character
#   \+   = literal plus sign
#   (?:...) = non-capturing group — groups the pattern but doesn't
#             create a backreference, which is slightly faster
#             and avoids polluting the match.groups() output

EXPERIENCE_PATTERN = re.compile(
    r"(?:at\s+least\s+|minimum\s+|min\s+|over\s+|more\s+than\s+)?"
    r"(\d+)"
    r"(?:\s*(?:to|-|\u2013|\u2014)\s*\d+)?"
    r"\+?\s*"
    r"(?:years?|yrs?)"
    r"(?:\s*of\s*)?"
    r"(?:experience|commercial|professional|work|industry)?",
    re.IGNORECASE,
)

# False-positive patterns — these are patterns that contain a number
# followed by words that could be confused with "years of experience"
# but actually mean something else.
#
# Each is removed from the text BEFORE the main experience regex runs.
# This is a denylist approach: we identify known false-positive sources
# and eliminate them first.
#
# Example: "team of 5 engineers" would match EXPERIENCE_PATTERN because
# of "5" followed by "engineers" (which doesn't match our context words,
# so it wouldn't match — but the denylist is an extra safety layer).
#
# The \d+ in each pattern matches any number, making these general filters
# rather than specific number filters.

EXPERIENCE_FALSE_POSITIVE_PATTERNS = [
    r"team\s+of\s+\d+",       # "team of 5" — team size, not experience
    r"\d+\s+engineers?",       # "5 engineers" — headcount
    r"\d+\s+developers?",      # "3 developers" — headcount
    r"\d+\s+members?",         # "2 members" — headcount
    r"\d+\s+people",           # "10 people" — headcount
    r"\d+\s+employees?",       # "50 employees" — headcount
    r"\d+\s+direct\s+reports?",# "3 direct reports" — management scope
    r"\$\d+",                  # "$50000" — salary, not experience
    r"\d+\s*(?:%|percent)",    # "50%" — percentage, not experience
    r"\d+\s*(?:days?|weeks?|months?)",  # "3 months" — time duration
]


def extract_experience(text: str) -> int | None:
    """
    Extract minimum years of experience from job description text.

    Algorithm (two-pass):
        1. DENYLIST PASS: Remove all known false-positive patterns from
           the text. This prevents "team of 5 engineers" from being
           interpreted as "5 years of experience".

        2. EXTRACTION PASS: Run the EXPERIENCE_PATTERN regex on the
           cleaned text and return the first valid number found.

    Why filter then extract?
        It's simpler than trying to write a regex that both matches
        the desired pattern AND excludes all false positives in one
        shot. The two-pass approach separates concerns: one pass
        removes noise, the other pass captures signal.

    Edge cases handled:
        "3+ years of experience"          -> 3
        "3-5 years experience"           -> 3  (lower bound, conservative)
        "1 to 3 yrs of commercial exp"   -> 1
        "at least 5 years"               -> 5
        "minimum 2 years"                -> 2
        "over 4 years"                   -> 4
        "more than 6 years"              -> 6
        "min 2 years"                    -> 2
        "2 year" (singular)              -> 2  ("year?" in regex)
        "no experience required"         -> None  (no number before "experience")
        "team of 5 engineers"            -> None  (false positive filter)
        "20 years of experience"         -> None  (capped at 15 — see below)
        "" (empty string)                -> None
        None                             -> None

    The 15-year cap:
        We assume any number > 15 is either:
          (a) A false positive (e.g., "15 days of PTO" — but the FP
              filter should catch most of these)
          (b) A senior/expert role (20+ years is Staff/Principal level,
              not relevant to our junior job market analysis)

    Time Complexity: O(n), where n = len(text).
        - False-positive filter: O(k * n) where k = len(FP patterns),
          but each pattern uses regex which is O(n) in the worst case
          (though typically much faster in practice).
        - findall(): O(n) — a single pass over the text.

    Args:
        text: Raw job description string. May be empty or None.

    Returns:
        int if experience found and <= 15, None otherwise.
    """
    if not text:
        return None

    # Step 1: Remove false positives by substituting them with empty strings.
    # re.sub() returns a new string — the original is not mutated (strings
    # are immutable in Python).
    cleaned = text
    for fp_pattern in EXPERIENCE_FALSE_POSITIVE_PATTERNS:
        cleaned = re.sub(fp_pattern, "", cleaned, flags=re.IGNORECASE)

    # Step 2: Find all experience pattern matches in the cleaned text.
    # re.findall() returns a list of captured groups (not full matches)
    # because we have a capturing group (\d+) in the pattern.
    matches = EXPERIENCE_PATTERN.findall(cleaned)
    if not matches:
        return None

    # Step 3: Return the first valid match (they appear in order of
    # appearance in the text). Jobs typically state required experience
    # in the first few paragraphs.
    for match in matches:
        years = int(match)
        if years <= 15:
            return years

    return None


def extract_tech_stack(text: str) -> list[str]:
    """
    Extract mentioned technologies from job description text.

    Algorithm: For each technology in TECH_VARIANTS, try each variant
    string against the text using word-boundary regex matching. When
    a variant matches, add the normalized tech name to the result set.

    Why word-boundary matching?
        Consider these two job descriptions:
          "Java experience required"       → should match "java"
          "JavaScript experience required"  → should match "javascript", NOT "java"
        Without \b, "java" (as a substring) would match inside "javascript".
        With \bjava\b, the 'j' must be at a word boundary (start of word)
        and the 'a' must end at a word boundary, so "java" won't match
        inside "javascript" because after 'a' comes 's' (still a word char).

    Why \b doesn't work for non-alphanumeric chars:
        \\b matches between \\w and \\W. Since '+' is \\W (not a word char),
        a pattern like \bc\\+\\+\b would need '+' followed by a word char
        for \b to match. Instead, we use lookarounds:
          (?<![a-zA-Z0-9])C\\+\\+(?![a-zA-Z0-9])
        This says: "C++" must not be preceded OR followed by a letter/digit.

    Data structure: set()
        Python sets provide average O(1) insertion and membership testing
        via hash tables. Using a set means duplicate detections are
        automatically eliminated — e.g., if the text says "React" twice,
        we only record it once.

    The sorted() call at the end:
        Returns results in alphabetical order. This is deterministic
        (same input → same output order), making tests predictable
        and database output consistent.

    Time Complexity: O(t * v * n), where:
        - t = number of technologies (36 in TECH_VARIANTS)
        - v = average variants per tech (~2)
        - n = length of text
        In practice, this is instantaneous for job descriptions
        (typically 500-2000 characters).

    Args:
        text: Raw job description string.

    Returns:
        Sorted list of normalized technology names found in the text.
        Returns empty list for empty/None input.

    Examples:
        "Need React and Node.js experience"     -> ["node", "react"]
        "C++ developers wanted"                 -> ["c++"]
        "JavaScript framework experience"       -> ["javascript"]
        "5 years of Go"                         -> []  (no match: "Go" NOT in variants)
        "Experience with Golang"                -> ["go"]
    """
    if not text:
        return []

    text_lower = text.lower()    # Case normalization: "Python" → "python"
    found = set()

    for normalized, variants in TECH_VARIANTS.items():
        for variant in variants:
            # re.escape() converts a string into a regex-safe literal.
            # E.g., re.escape("c++") → "c\+\+"
            escaped = re.escape(variant)

            # Strategy: if variant is purely alphanumeric, use \b;
            # otherwise use lookaround assertions (for chars like '+', '#')
            if variant.isalnum():
                pattern = r"\b" + escaped + r"\b"
            else:
                pattern = r"(?<![a-zA-Z0-9])" + escaped + r"(?![a-zA-Z0-9])"

            if re.search(pattern, text_lower):
                found.add(normalized)
                # BREAK: Once any variant matches, stop checking other
                # variants for this technology. This is an optimization —
                # we only need ONE match to confirm the tech is present.
                break

    return sorted(found)


def find_ai_tools(text: str) -> bool:
    """
    Check if job description mentions AI-assisted development tools.

    Strategy: Simple substring search (case-insensitive) using Python's
    'in' operator. This is O(n * k) where n = text length and k = number
    of keywords (12). For job descriptions (typically < 2000 chars),
    this completes in microseconds — no regex needed.

    Why not use regex here?
        - These are specific brand names ("copilot", "chatgpt") that
          don't have word-boundary ambiguities.
        - 'substring' in 'text' is simpler code, faster for simple
          use cases, and less prone to silent errors.
        - Regex would add compilation overhead with no benefit.

    Python's 'in' operator on strings:
        Internally, it uses an efficient substring search algorithm
        (Boyer-Moore-like or two-way algorithm, depending on the
        Python implementation). It's not naive O(n*m) for most cases.

    Args:
        text: Raw job description string.

    Returns:
        True if at least one AI tool keyword is found, False otherwise.

    Examples:
        "Experience with GitHub Copilot"   -> True
        "We use Cursor for development"    -> True
        "No AI tools mentioned"            -> False
        ""                                 -> False
    """
    if not text:
        return False

    text_lower = text.lower()
    for keyword in AI_KEYWORDS:
        if keyword in text_lower:
            return True
    return False


def is_junior_title(title: str) -> bool:
    """
    Determine if a job title indicates a junior/entry-level position.

    Strategy: Case-insensitive substring matching against a curated
    list of 12 junior-indicating keywords. This is a heuristic — it
    will have both false positives and false negatives.

    False positive example:
        "Data Entry Clerk" → matches "entry" → returns True
        (The word "entry" in "Data Entry" means data input, not entry-level)

    False negative example:
        "Software Engineer I" → no keyword match → returns False
        (Some companies use "I", "II", "III" instead of "Junior/Senior")

    These edge cases are acceptable for a dashboard that shows aggregate
    statistics (averages over hundreds of jobs). Individual misclassifications
    are diluted by the large sample size.

    Args:
        title: Job title string from LinkedIn.

    Returns:
        True if title contains any junior-indicating keyword.

    Examples:
        "Junior Backend Engineer"            -> True
        "Jr. Software Developer"             -> True
        "Entry Level Data Scientist"         -> True
        "Associate Product Manager"          -> True
        "New Grad SWE 2025"                  -> True
        "Senior Software Engineer"           -> False
        "Staff Engineer"                     -> False
    """
    if not title:
        return False

    title_lower = title.lower()
    for keyword in JUNIOR_TITLE_KEYWORDS:
        if keyword in title_lower:
            return True
    return False


def parse_posted_date(date_text: str) -> str | None:
    """
    Convert LinkedIn relative date strings to ISO 8601 format (YYYY-MM-DD).

    Algorithm: Pattern-match against known LinkedIn date formats using
    a cascade of regex patterns, from most common to least common.

    LinkedIn date format variants:
        Relative:
          "Just now" / "Today"                → today
          "3 hours ago" / "1 hour ago"        → today (same day)
          "2 days ago" / "1 day ago"          → today - N days
          "3 weeks ago" / "1 week ago"         → today - N*7 days
          "2 months ago" / "1 month ago"       → today - N*30 days (approximate)
          "1 year ago" / "3 years ago"         → today - N*365 days (approximate)
        Absolute:
          "2024-03-15"                        → "2024-03-15"
          "03/15/2024"                        → "2024-03-15"
          "15/03/2024"                        → "2024-03-15"
          "March 15, 2024"                    → "2024-03-15"

    Why 30 days for a month?
        It's an approximation (months have 28-31 days). An exact approach
        would need calendar-aware date arithmetic (using relativedelta from
        python-dateutil), but for a dashboard showing aggregate trends,
        being off by 1-2 days per 30-day window is negligible.

    Timezone handling:
        We use UTC dates (datetime.now(timezone.utc).date()) to avoid
        DST/timezone ambiguity. The dashboard is global, so UTC is the
        least ambiguous reference point.

    Fallback strategy:
        If relative date parsing fails, we try 4 absolute date formats.
        If ALL formats fail, we return None (the dashboard handles None
        gracefully).

    Args:
        date_text: Raw date string from LinkedIn (may be None or empty).

    Returns:
        ISO 8601 date string (e.g., "2024-03-15") or None if unparseable.

    Time Complexity: O(1) — constant number of regex matches
    (each O(len(date_text)), which is typically < 30 chars).
    """
    if not date_text:
        return None

    date_text = date_text.strip().lower()
    today = datetime.now(timezone.utc).date()

    # Instant / today
    if date_text in ("just now", "today"):
        return today.isoformat()

    # Hours ago (still today)
    hours_match = re.match(r"(\d+)\s+hours?\s+ago", date_text)
    if hours_match:
        return today.isoformat()

    # Days ago
    days_match = re.match(r"(\d+)\s+days?\s+ago", date_text)
    if days_match:
        days = int(days_match.group(1))
        return (today - timedelta(days=days)).isoformat()

    # Weeks ago
    weeks_match = re.match(r"(\d+)\s+weeks?\s+ago", date_text)
    if weeks_match:
        weeks = int(weeks_match.group(1))
        return (today - timedelta(weeks=weeks)).isoformat()

    # Months ago (approximate: 30 days per month)
    months_match = re.match(r"(\d+)\s+months?\s+ago", date_text)
    if months_match:
        months = int(months_match.group(1))
        return (today - timedelta(days=months * 30)).isoformat()

    # Years ago (approximate: 365 days per year)
    years_match = re.match(r"(\d+)\s+years?\s+ago", date_text)
    if years_match:
        years = int(years_match.group(1))
        return (today - timedelta(days=years * 365)).isoformat()

    # Absolute dates — try multiple formats
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(date_text, fmt).date().isoformat()
        except ValueError:
            continue

    return None


def parse_job(raw_job: dict) -> dict:
    """
    Parse a raw scraped job dictionary into a structured record.

    This is the ORCHESTRATOR function of the parser module. It composes
    all individual parsers into a single pipeline.

    The composition pattern:
        Instead of building a monolithic parser that does everything at
        once, we DECOMPOSE the problem into small, single-responsibility
        functions, then COMPOSE them back together in parse_job().
        Each sub-parser is independently testable and replaceable.

    This follows the "functional core, imperative shell" pattern:
        - The sub-parsers (extract_experience, extract_tech_stack, etc.)
          are pure functions (the "functional core")
        - parse_job() orchestrates them and handles the input/output
          mapping (the "imperative shell")

    Input format (from scraper):
        {
            "linkedin_job_id": "3876543210",          # Unique LinkedIn ID
            "title": "Junior Software Engineer",      # Job title
            "company": "TechCorp",                     # Company name
            "location": "San Francisco, CA",           # Job location
            "posted_date": "2024-06-15",              # Already parsed by parse_posted_date()
            "job_description": "Requirements: ...",    # Full raw description text
        }

    Output format (to database):
        {
            "linkedin_job_id": "3876543210",
            "title": "Junior Software Engineer",
            "company": "TechCorp",
            "location": "San Francisco, CA",
            "posted_date": "2024-06-15",
            "years_experience_required": 3,            # Parsed from description
            "is_junior_title": True,                   # Parsed from title
            "ai_tools_mentioned": True,                # Parsed from description
            "tech_stack": ["docker", "python", "react"],# Parsed from description
        }

    Args:
        raw_job: Dict from the scraper with raw text fields.

    Returns:
        Dict with the same keys plus parsed metrics. Ready for database upsert.
    """
    description = raw_job.get("job_description", "")
    title = raw_job.get("title", "")

    return {
        "linkedin_job_id": raw_job.get("linkedin_job_id", ""),
        "title": title,
        "company": raw_job.get("company", ""),
        "location": raw_job.get("location", ""),
        "posted_date": raw_job.get("posted_date", ""),
        "years_experience_required": extract_experience(description),
        "is_junior_title": is_junior_title(title),
        "ai_tools_mentioned": find_ai_tools(description),
        "tech_stack": extract_tech_stack(description),
    }
