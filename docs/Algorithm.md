# Algorithms: RealityCheck

## 1. Scraping Algorithm (Ingestion)

The scraper extracts job postings from LinkedIn's public job board using Playwright with anti-detection measures and retry/backoff logic.

**Input**: Job search parameters (keywords, location, limit).
**Output**: A list of structured, parsed job dictionaries ready for the database.

### Navigation & Anti-Detection

1. Launch headless Chromium with `--disable-blink-features=AutomationControlled` and a randomly selected User-Agent from a pool of 4.
2. Inject init script to override `navigator.webdriver` to `undefined`.
3. Navigate to the LinkedIn search URL using `navigate_with_retry()`:
   - Checks HTTP response status for 429 (rate limit).
   - Scrapes page text for block/challenge indicators: "unusual activity", "verify you're human", "security verification", "captcha", "too many requests", "rate limit", "access denied".
   - On block or timeout, backs off with exponential delay (10s, 20s, 40s) up to 3 retry attempts.
4. Dismiss overlays (cookie banners, sign-in modals) via 8 selector fallbacks + double Escape key press.

### Loading Job Cards

5. Scroll the job list container (or entire page) to trigger lazy loading.
6. Wait random 2–5s between scrolls.
7. Click "See more jobs" / "Show more" button when it appears.
8. Stop when target count reached, no new cards loaded, or max 20 scroll attempts exhausted.

### Extracting Card Data

9. For each job card element:
   - Extract `linkedin_job_id` from `data-job-id` or `data-entity-urn` attribute.
   - Extract `title`, `company`, `location`, `posted_date` using multi-selector fallback (3–4 CSS selectors per field) via `extract_text()`.
10. Click the card to load full description in the right pane.
11. Wait up to 10s for `.jobs-description__content` or 6 other fallback description selectors.
12. Parse the raw `posted_date` string into ISO format via `parse_posted_date()`.

### Mid-Scrape Rate-Limit Check

13. Every 15 cards, re-run `is_blocked()` on the page content. If blocked, stop gracefully and return whatever has been collected so far.

---

## 2. Parsing Algorithm (Transformation)

Pure functions that extract structured metrics from unstructured text. No I/O, no database, no network.

**Input**: Raw job dictionary (`linkedin_job_id`, `title`, `company`, `location`, `posted_date`, `job_description`).
**Output**: Structured dictionary with extracted numeric/boolean/list fields.

### 2.1 Experience Extraction (`extract_experience`)

Regex: `r"(?:at\s+least\s+|minimum\s+|min\s+|over\s+|more\s+than\s+)?(\d+)(?:\s*(?:to|-|\u2013|\u2014)\s*\d+)?\+?\s*(?:years?|yrs?)(?:\s*of\s*)?(?:experience|commercial|professional|work|industry)?"`

1. Strip false-positive patterns first: "team of N", "N engineers", "N members", "N people", "$N", "N%", "N days/weeks/months".
2. Run the experience regex on cleaned text.
3. Return **first** matching integer (the lower bound for ranges like "3–5 years").
4. Cap at 15 — any match > 15 is discarded as a false positive.
5. Return `None` if no match found.

Supports: `"3+ years"`, `"3-5 years"`, `"at least 5 years"`, `"minimum 2 years"`, `"min 2 years"`, `"over 4 years"`, `"more than 6 years"`, `"1 to 3 yrs of commercial exp"`, `"1 year experience"`.

### 2.2 Tech Stack Extraction (`extract_tech_stack`)

Uses a variant-matching dictionary of 36 normalized technology names (35+ technologies). Each normalized name has one or more variant strings (e.g., `"go"` → `["golang"]`; `"javascript"` → `["javascript", "js", "ecmascript"]`; `"node"` → `["node", "nodejs", "node.js"]`).

1. Lowercase the description text.
2. For each normalized name → variants entry, check if any variant matches via word-boundary regex (`\b` for alphanumeric, character-class boundaries for symbols like `C++`).
3. If matched, add the **normalized** name to the result set.
4. Return sorted list of unique matches.

Key protections: "go" is NOT matched from the common word "go" — only `"golang"` triggers it. "Java" and "JavaScript" are distinct entries with separate variant lists.

### 2.3 AI Tools Detection (`find_ai_tools`)

Case-insensitive substring search for 12 AI tool keywords: `copilot`, `cursor`, `chatgpt`, `chat gpt`, `openai`, `claude`, `llm`, `large language model`, `gemini`, `codex`, `tabnine`, `code whisperer`.

Returns `True` if any keyword found, `False` otherwise.

### 2.4 Junior Title Detection (`is_junior_title`)

Case-insensitive substring search against 12 title keywords: `junior`, `jr.`, `jr `, `entry`, `entry-level`, `entry level`, `associate`, `graduate`, `new grad`, `trainee`, `intern`, `internship`.

Returns `True` if any keyword found in title, `False` otherwise.

Known false-positive: "Data Entry Clerk" matches on `"entry"`. Acceptable trade-off for LinkedIn SWE search results.

### 2.5 Date Parsing (`parse_posted_date`)

Converts LinkedIn relative date strings to ISO format (YYYY-MM-DD):

| Input | Output |
|-------|--------|
| "Just now" / "Today" | Today's date |
| "N hours ago" | Today's date |
| "N days ago" | Today − N |
| "N weeks ago" | Today − N×7 |
| "N months ago" | Today − N×30 (approximate) |
| Absolute date ("2024-03-15") | Same date |
| Unrecognized | `None` |

### 2.6 Orchestration (`parse_job`)

Calls all above parsers on the raw job dict and returns a single structured dict with fields: `linkedin_job_id`, `title`, `company`, `location`, `posted_date`, `years_experience_required`, `is_junior_title`, `ai_tools_mentioned`, `tech_stack`.

---

## 3. Database Upsert Algorithm (Load)

**Input**: Engine, list of parsed job dicts (output of `parse_job`).
**Output**: Database updated; returns count of newly inserted records.

1. For each job in the list, query by `linkedin_job_id`.
2. **If NOT found**: Create a new `Job` row with all fields (`title`, `company`, `location`, `posted_date`, `years_experience_required`, `is_junior_title`, `ai_tools_mentioned`, `tech_stack`, `scraped_at`).
3. **If FOUND (upsert)**: Update all fields on the existing row, including `posted_date` (LinkedIn may change the relative date) and `scraped_at` (timestamp of this scrape). This ensures trend charts and "New Today" metrics remain accurate across re-scrapes.
4. Commit transaction; rollback on `IntegrityError`.
5. Return count of **new** inserts (updated rows not counted).

---

## 4. Frontend Visualization Algorithm (Presentation)

**Input**: Page load event in Streamlit.
**Output**: Interactive dashboard with metrics, charts, and searchable table.

1. **Load & Cache**: Fetch all rows from the `jobs` table via SQLAlchemy into a Pandas DataFrame. Cached with `@st.cache_data(ttl=3600)` — refreshes from DB once per hour.
2. **Compute 5 Metric Cards**: Total jobs, new today (by `scraped_at`), last scrape timestamp, average experience for junior titles, percentage of jobs mentioning AI tools.
3. **Render 7 Charts**:
   - Experience Distribution histogram (junior roles, binned 0/1/2/3/4-5/6-7/8-10/10+)
   - Top 10 Technologies horizontal bar chart
   - Average Experience Over Time line chart
   - AI Tools Adoption Over Time area chart
   - Company Leaderboard bar chart (top 15 by job count)
   - Location Breakdown bar chart (min 3 jobs per location, top 10)
   - Technology Co-occurrence Heatmap (Plotly, 15×15 matrix)
4. **Searchable Job Table**: Filter by title/company text search, role level (all/junior/non-junior), experience range (0-1/2-3/4-5/6+/unspecified). Rendered as a sortable, paginated dataframe.
