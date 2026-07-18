# Technical Design Document: RealityCheck

## 1. Introduction
This document specifies the technical implementations for the RealityCheck project, a data pipeline tracking the junior software engineer job market on LinkedIn.

## 2. Technology Stack
- **Language**: Python 3.10+
- **Browser Automation**: `playwright` (Python async API) for scraping LinkedIn. Playwright is preferred over Selenium due to better headless mode reliability and built-in auto-waiting mechanisms.
- **HTML Parsing**: `beautifulsoup4` for targeted DOM extraction if Playwright locators are insufficient.
- **Data Manipulation**: `pandas` for grouping, filtering, and cleaning.
- **Database ORM**: `SQLAlchemy` 2.0+ combined with `psycopg2-binary` to manage PostgreSQL connections and schema.
- **Database**: PostgreSQL (Neon.tech or Supabase free tier).
- **Frontend**: Streamlit Community Cloud, with `plotly` for advanced charts (heatmap) and `numpy` for co-occurrence matrices.
- **CI/CD**: GitHub Actions.
- **Linting**: `ruff` with pycodestyle, pyflakes, isort, flake8-bugbear, pyupgrade rules.

## 3. Database Schema
The database consists of a primary `jobs` table:

```sql
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    linkedin_job_id VARCHAR(255) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    company VARCHAR(255),
    location VARCHAR(255),
    posted_date VARCHAR(255),
    years_experience_required INTEGER,
    is_junior_title BOOLEAN,
    ai_tools_mentioned BOOLEAN DEFAULT FALSE,
    tech_stack JSONB,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

- `tech_stack` stores a JSON array of normalized technology names (e.g., `["node", "python", "react"]`).
- `posted_date` is stored as a string (ISO format YYYY-MM-DD) since LinkedIn provides relative dates.
- `scraped_at` is updated on every upsert, enabling trend charts and "new today" metrics.

## 4. Playwright LinkedIn Scraper Specifications

### 4.1 Browser Configuration
- **Headless mode**: Used in CI; can be disabled with `--no-headless` for local debugging.
- **Anti-Detection**:
  - Spoofed `User-Agent` from a pool of 4 rotating strings (Chrome/Firefox on Windows/Mac/Linux).
  - `--disable-blink-features=AutomationControlled` launch flag.
  - JavaScript injection to override `navigator.webdriver` to `undefined`.
  - Randomized delays of 0.3–5 seconds between all interactions.

### 4.2 Retry & Rate-Limit Handling
- **Navigation**: Retried up to 3 times with exponential backoff (10s → 20s → 40s).
- **HTTP 429 detection**: Response status checked after navigation.
- **Block/challenge detection**: Page text scanned for indicators: "unusual activity", "verify you're human", "captcha", "rate limit", "access denied", etc.
- **Redirect detection**: Checks for login/auth wall pages.
- **Mid-scrape check**: Every 15 job cards, re-verifies the page hasn't been blocked.

### 4.3 DOM Selectors
Multiple fallback CSS selectors per element to survive LinkedIn DOM changes:

| Element | Fallbacks |
|---------|-----------|
| Job card | `.job-search-card`, `[data-entity-urn*='jobPosting']`, `.base-search-card` |
| Job title | `.base-search-card__title`, `.job-search-card__title` |
| Company | `.base-search-card__subtitle`, `.job-search-card__subtitle` |
| Location | `.job-search-card__location`, `.base-search-card__metadata` |
| Description | `.jobs-description__content`, `#job-details`, `.decorated-job-posting__details` (7 fallbacks) |
| Posted date | `.job-search-card__listdate`, `time` element, `.base-search-card__metadata time` |

### 4.4 CLI Interface
```
python scraper/main.py [--limit N] [--no-headless] [--search-keywords KEYWORDS]
                        [--location LOCATION] [--init-db]
```
- `--limit` (default 5 local, 100 CI) — max jobs to scrape
- `--init-db` — creates tables and indexes before scraping
- `--search-keywords` / `--location` — customize the LinkedIn search

## 5. NLP and Parsing Implementation

### 5.1 Experience Extraction
**Full Regex**: `r"(?:at\s+least\s+|minimum\s+|min\s+|over\s+|more\s+than\s+)?(\d+)(?:\s*(?:to|-|\u2013|\u2014)\s*\d+)?\+?\s*(?:years?|yrs?)(?:\s*of\s*)?(?:experience|commercial|professional|work|industry)?"`

- Supports: `"3+ years"`, `"3-5 years"`, `"1 to 3 yrs"`, `"at least 5 years"`, `"minimum 2 years"`, `"min 2 years"`, `"over 4 years"`, `"more than 6 years"`.
- Returns the **first** match (lower bound for ranges).
- Capped at 15 — higher values discarded as false positives.
- False-positive filter strips phrases like "team of 5 engineers", "20 members", "$100,000", "5 days", etc.
- Returns `None` if no valid experience found.

### 5.2 AI Tools Detection
Case-insensitive exact substring search for 12 keywords:
`copilot`, `cursor`, `chatgpt`, `chat gpt`, `openai`, `claude`, `llm`, `large language model`, `gemini`, `codex`, `tabnine`, `code whisperer`.

### 5.3 Tech Stack Extraction
Uses a variant-matching dictionary of 36 normalized technology names with word-boundary regex:

| Normalized | Variants |
|-----------|----------|
| `python` | `python` |
| `javascript` | `javascript`, `js`, `ecmascript` |
| `typescript` | `typescript`, `ts` |
| `react` | `react`, `reactjs`, `react.js` |
| `node` | `node`, `nodejs`, `node.js` |
| `go` | `golang` (only — avoids matching the common word "go") |
| `c++` | `c++`, `c++` |
| `c#` | `c#`, `c sharp`, `csharp` |
| `dotnet` | `.net`, `dotnet`, `asp.net`, `aspnet` |
| `sql` | `sql`, `mysql`, `postgresql`, `postgres`, `mssql`, `t-sql` |

(Full list of 36 entries: python, java, javascript, typescript, react, angular, vue, node, next, django, flask, spring, dotnet, php, ruby, rails, go, rust, swift, kotlin, c++, c#, sql, mongodb, redis, aws, azure, gcp, docker, kubernetes, terraform, git, linux, rest, graphql, ci/cd.)

### 5.4 Junior Title Detection
Case-insensitive substring search for 12 keywords:
`junior`, `jr.`, `jr `, `entry`, `entry-level`, `entry level`, `associate`, `graduate`, `new grad`, `trainee`, `intern`, `internship`.

### 5.5 Date Parsing
Converts LinkedIn relative dates to ISO format: "Just now"/"Today"/"N hours ago" → today; "N days ago" → today−N; "N weeks ago" → today−(N×7); "N months ago" → today−(N×30, approximate). Absolute dates passed through as-is. Returns `None` for unrecognized formats.

## 6. Security & Credentials
- All credentials (`DATABASE_URL`) stored strictly as GitHub Secrets and Streamlit Secrets.
- Environment variables loaded locally via `python-dotenv`.
- No credentials ever committed to the repository (enforced via `.gitignore`).

## 7. Code Quality
- Linting via `ruff` (pycodestyle, pyflakes, isort, flake8-bugbear, pyupgrade rules).
- Configuration in `pyproject.toml`.
- Test coverage tracked via `pytest-cov`. Parser at 100%, DB at 66%, scraper at 17% (Playwright-dependent code excluded).
