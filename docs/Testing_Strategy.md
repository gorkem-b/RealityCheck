# Testing Strategy: RealityCheck

To ensure data integrity and system reliability, RealityCheck utilizes a multi-layered testing strategy.

## 1. Unit Testing (Data Parsing)

The most fragile part of the system is the NLP and Regex parsing of unstructured text.

- **Framework**: `pytest` with `pytest-cov` for coverage tracking.
- **Target**: `scraper/parser.py` — **100% coverage**.
- **Strategy**: 
  - Suite of 11 mock job descriptions covering edge cases (basic, range, no-experience, senior, AI tools, Java vs JavaScript, Golang, associate title, empty description, at-least, team-size false-positive).
  - Assert `extract_experience()` returns correct integer or `None` for "3+ years", "3–5 years", "at least 5 years", "minimum 2 years", "over 4 years", "more than 6 years", "min 2 years", false-positive stripping, >15 cap, empty/None input.
  - Assert `extract_tech_stack()` correctly identifies 36 technologies with variant matching, while avoiding false positives (e.g., "Java" vs "JavaScript", "go" common word vs "golang").
  - Assert `find_ai_tools()` detects all 12 AI tool keywords.
  - Assert `is_junior_title()` detects all 12 junior title keywords, rejects senior titles, handles empty/None.
  - Assert `parse_posted_date()` handles all relative and absolute date formats.
  - Assert `parse_job()` orchestrates all parsers correctly on 11 mock scenarios.

## 2. Unit Testing (Scraper Pure Functions)

Pure functions from the scraper module tested without browser dependencies.

- **Target**: `scraper/main.py` — `build_search_url()`, `parse_args()`.
- **Strategy**:
  - Verify URL encoding for keywords, locations, and special characters (C#, commas).
  - Verify `parse_args()` with default values, custom flags, short flags, flag combinations.

## 3. Integration Testing (Database)

Ensures the SQLAlchemy ORM correctly translates Python objects to records and handles upsert logic.

- **Framework**: `pytest` with an **in-memory SQLite** database for fast, isolated tests.
- **Target**: `scraper/db.py` — 66% coverage (PostgreSQL-specific engine/init code excluded from SQLite tests).
- **Strategy**:
  - Create `jobs` table via `Base.metadata.create_all()`.
  - Insert a mock job record via `upsert_jobs()` and verify correct insertion.
  - Attempt to insert the same `linkedin_job_id` and verify deduplication (returns 0 inserted, no error).
  - Verify upsert updates all fields on existing records, including `posted_date`, `scraped_at`, `ai_tools_mentioned`, `years_experience_required`.
  - Verify empty job list handling returns 0 without error.

## 4. End-to-End (E2E) Testing (Scraping)

Tests actual browser automation against the live LinkedIn site.

- **Target**: `scraper/main.py` — 17% coverage (requires live LinkedIn, excluded from CI tests).
- **Strategy**:
  - Run the scraper locally with `--limit 5 --no-headless` for visual debugging.
  - Verify DOM selectors are still valid and raw HTML is successfully captured.
  - Verify retry/backoff logic triggers correctly when rate-limited.
  - *Note*: Run manually or weekly — frequent E2E runs risk IP bans from LinkedIn.

## 5. Frontend Testing

Tests the presentation layer.

- **Framework**: Manual inspection + Streamlit `AppTest` (for future automation).
- **Strategy**:
  - Run `streamlit run app.py` locally against the test database.
  - Visually verify metric cards (total jobs, new today, last scrape, avg experience, AI %).
  - Verify all 7 charts render correctly with appropriate data.
  - Verify the searchable/filterable job table works with text search and dropdown filters.

## 6. Linting

Code quality enforced through static analysis.

- **Tool**: `ruff` (with pycodestyle, pyflakes, isort, flake8-bugbear, pyupgrade rules).
- **Config**: `pyproject.toml`.
- **Command**: `python -m ruff check .`

## Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ -v --cov=scraper --cov-report=term-missing

# Run linting
python -m ruff check .

# Auto-fix lint issues
python -m ruff check . --fix
```
