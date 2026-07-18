# RealityCheck

> **A CS Student's Guide to Building Real-World Data Pipelines**

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10+-blue.svg)

RealityCheck is an end-to-end automated data pipeline and analytics dashboard that tracks the "entry-level requiring 3 years of experience" paradox in the junior software engineering job market. It scrapes LinkedIn daily, parses job descriptions with NLP techniques, stores structured data in PostgreSQL, and visualizes the results through an interactive dashboard.

**This project is designed to be read like a textbook.** Every module teaches a specific set of computer science concepts through real, production-grade code. If you are a CS student or a junior developer, study this codebase to understand how theoretical concepts translate into working software.

---

## What CS Concepts Will You Learn?

| CS Domain | Concepts Demonstrated | Where to Look |
|-----------|----------------------|---------------|
| **Algorithms** | Regex with backtracking, false-positive filtering, tokenization by word boundaries | `scraper/parser.py` |
| **Data Structures** | Hash maps (dict/set for deduplication), adjacency matrices (tech co-occurrence), stacks (event loop), priority-by-frequency (Counter) | `scraper/parser.py`, `app.py` |
| **Concurrency** | Async/await event loop, non-blocking I/O, race conditions, connection pooling | `scraper/main.py`, `scraper/db.py` |
| **Databases** | ORM vs raw SQL tradeoffs, ACID transactions, upsert semantics (INSERT ... ON CONFLICT), GIN indexes on JSONB, schema-normalization decisions | `scraper/db.py` |
| **Networking** | HTTP 429 rate limiting, exponential backoff retry pattern, TLS/SSL via sslmode, DOM-based scraping | `scraper/main.py`, `scraper/utils.py` |
| **NLP** | Regex-based information extraction, keyword matching, false-positive filtering, text normalization | `scraper/parser.py` |
| **SE Practices** | Test-driven development (83 tests), CI/CD pipelines, environment management, caching strategies, modular design, separation of concerns | `tests/`, `.github/workflows/` |
| **Data Viz** | Histograms/binning, time-series trends, co-occurrence heatmaps, aggregated leaderboards | `app.py` |
| **System Design** | 3-tier architecture, singleton pattern, batch orchestration, graceful degradation, anti-detection strategies | `scraper/main.py`, `scraper/batch.py` |

---

## Architecture

RealityCheck follows a **3-tier architecture** — a classic pattern you will encounter in virtually every production web application:

```
┌──────────────────────────────────────────────────────┐
│                   INGESTION TIER                      │
│  GitHub Actions (cron) ─► Playwright (headless)      │
│  Scrapes LinkedIn, parses job descriptions           │
│  scraper/main.py  ·  scraper/parser.py               │
└──────────────────────┬───────────────────────────────┘
                       │  upsert via SQLAlchemy
                       ▼
┌──────────────────────────────────────────────────────┐
│                   STORAGE TIER                        │
│  PostgreSQL (Neon.tech serverless)                   │
│  Single `jobs` table with JSONB for tech stack       │
│  scraper/db.py                                       │
└──────────────────────┬───────────────────────────────┘
                       │  SELECT via SQLAlchemy/Pandas
                       ▼
┌──────────────────────────────────────────────────────┐
│                 PRESENTATION TIER                     │
│  Streamlit Community Cloud                           │
│  5 metrics  ·  7 charts  ·  Searchable table          │
│  app.py                                              │
└──────────────────────────────────────────────────────┘
```

**Why this architecture?** Each tier can be developed, tested, deployed, and scaled independently. The ingestion tier runs on a schedule (GitHub Actions cron), the storage tier is always-on (Neon.tech free tier), and the presentation tier loads data on demand (Streamlit caches for 1 hour). Total cost: **$0/month**.

---

## Project Structure

```
RealityCheck/
│
├── scraper/                        # INGESTION TIER
│   ├── __init__.py                 #   Python package marker
│   ├── main.py                     #   Playwright async scraper (563 lines)
│   │                               #   - Async I/O event loop
│   │                               #   - Headless browser automation
│   │                               #   - Exponential backoff retry
│   │                               #   - Anti-bot detection evasion
│   ├── parser.py                   #   NLP/regex job description parser (348 lines)
│   │                               #   - Regex pattern design
│   │                               #   - False-positive filtering
│   │                               #   - Entity extraction from unstructured text
│   ├── db.py                       #   SQLAlchemy ORM + PostgreSQL (236 lines)
│   │                               #   - Declarative ORM mapping
│   │                               #   - Connection pooling (singleton pattern)
│   │                               #   - Upsert (INSERT ... ON CONFLICT)
│   │                               #   - GIN indexes on JSONB
│   ├── batch.py                    #   Multi-keyword batch orchestrator (203 lines)
│   │                               #   - Batch processing with cooldowns
│   │                               #   - Error isolation (one failure doesn't kill the batch)
│   └── utils.py                    #   Shared utilities (62 lines)
│                                   #   - Env variable management
│                                   #   - Structured logging
│                                   #   - Random User-Agent rotation
│
├── tests/                          # TEST SUITE (83 tests)
│   ├── __init__.py                 #   Test package marker
│   ├── conftest.py                 #   Shared fixtures + mock job descriptions
│   ├── test_parser.py              #   50+ unit tests — regex, NLP parsing
│   ├── test_db.py                  #   5 integration tests — SQLite in-memory
│   └── test_scraper.py             #   12 unit tests — URL builder, CLI args
│
├── docs/                           # Technical documentation (9 files)
│   ├── Requirements_Document.md
│   ├── System_Design_Document.md
│   ├── Technical_Design_Document.md
│   ├── Algorithm.md
│   ├── Database_Schema.md
│   ├── Deployment_Guide.md
│   ├── Testing_Strategy.md
│   ├── Project_Structure.md
│   └── CI_CD_Pipeline.md
│
├── .github/workflows/scraper.yml   # CI/CD: Daily cron + manual trigger
├── app.py                          # Streamlit dashboard (480 lines)
│                                   #   5 metrics · 7 charts · Searchable table
├── pyproject.toml                  # Ruff linter + pytest + coverage config
├── requirements.txt                # 12 pinned dependencies
├── .env.example                    # Template for DATABASE_URL
├── .gitignore                      # Excludes secrets, venv, caches
└── README.md                       # You are here
```

---

## Technology Stack

| Layer | Technology | Version | Why This? |
|-------|-----------|---------|-----------|
| **Browser Automation** | Playwright (async Python) | 1.61+ | More modern than Selenium; native async/await support; built-in anti-detection capabilities; auto-installs Chromium binaries |
| **HTML Parsing** | BeautifulSoup4 | 4.15+ | Industry-standard HTML parser; handles malformed HTML robustly; used as a fallback for complex DOM extraction |
| **ORM** | SQLAlchemy | 2.0+ | The most powerful Python ORM; declarative models with type hints; connection pooling built-in; supports both low-level SQL and high-level ORM patterns |
| **Database Driver** | psycopg2-binary | 2.9+ | High-performance PostgreSQL adapter; implements the DB-API 2.0 specification; binary distribution avoids C compiler dependency |
| **Database** | PostgreSQL (Neon.tech) | — | JSONB column type for tech_stack arrays; GIN indexes for array containment queries; free tier is generous (0.5 GB storage, 1 GB RAM) |
| **Data Manipulation** | Pandas + NumPy | latest | Pandas: DataFrame abstraction perfect for tabular job data; NumPy: matrix operations for co-occurrence heatmap |
| **Dashboard** | Streamlit | 1.59+ | Turns Python scripts into interactive web apps with zero frontend code; built-in @st.cache_data for TTL caching; free Community Cloud hosting |
| **Charts** | Plotly | 6.9+ | Interactive heatmaps (Streamlit native charts don't support heatmaps natively); hover tooltips; export to PNG |
| **Environment** | python-dotenv | 1.2+ | Loads `.env` files; keeps secrets out of version control; supports variable interpolation |
| **Testing** | pytest + pytest-cov | latest | Industry-standard Python test framework; fixtures, parametrize, monkeypatching; coverage reporting |
| **Linting** | Ruff | 0.15+ | 10-100x faster than flake8/pylint (written in Rust); combines isort, pyflakes, pycodestyle, bugbear, pyupgrade into one tool |
| **CI/CD** | GitHub Actions | — | Free for public repos (2,000 mins/month); native secrets management; cron scheduling |

---

## Learning Roadmap for CS Students

Read the codebase in this order for the most educational experience:

### Phase 1: Foundations (Pure Logic, No External Dependencies)

1. **`scraper/utils.py`** — Learn: logging design, environment variable management, async/await syntax, random sampling for User-Agent rotation
2. **`pyproject.toml`** — Learn: project metadata, linter configuration, coverage exclusions, CI integration
3. **`tests/conftest.py`** — Learn: pytest fixtures, mock data design, in-memory SQLite strategy

### Phase 2: Core Algorithms (Parsing & NLP)

4. **`scraper/parser.py`** — Learn: regex engine behavior (backtracking, greedy vs lazy), false-positive filtering strategies, entity extraction from unstructured text, composition pattern
5. **`tests/test_parser.py`** — Learn: equivalence class testing, parametrized tests, edge case enumeration

### Phase 3: Data Persistence (ORM & Databases)

6. **`scraper/db.py`** — Learn: ORM declarative mapping, connection pooling mechanics, singleton pattern tradeoffs, upsert race conditions, JSONB/GIN indexes, transaction boundaries
7. **`tests/test_db.py`** — Learn: integration testing with in-memory databases, idempotency testing, test isolation

### Phase 4: Web Scraping (Async I/O & DOM)

8. **`scraper/main.py`** — Learn: async/await event loop mechanics, CSS selector specificity, retry with exponential backoff math, anti-bot detection evasion, graceful degradation patterns
9. **`tests/test_scraper.py`** — Learn: pure-function testing, monkeypatching, CLI arg parsing validation

### Phase 5: Orchestration

10. **`scraper/batch.py`** — Learn: batch processing patterns, rate-limiting via cooldowns, error isolation, aggregate metrics collection

### Phase 6: Visualization

11. **`app.py`** — Learn: TTL caching, statistical aggregation, histogram binning, co-occurrence matrices, Plotly heatmap construction, Streamlit reactive layouts

---

## Getting Started

### Prerequisites

- **Python 3.10+** — We use the `|` union type syntax (introduced in 3.10) for type hints.
- **A free PostgreSQL database** — [Neon.tech](https://neon.tech/) provides a free serverless PostgreSQL (0.5 GB storage, 1 GB RAM, 100 compute hours/month). Sign up takes 60 seconds.
- **Playwright browsers** — Playwright manages its own Chromium binary; no system-level browser needed.

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/RealityCheck.git
cd RealityCheck

# 2. Create a virtual environment (isolates project dependencies from system Python)
python -m venv venv
venv\Scripts\activate        # Windows PowerShell
# source venv/bin/activate   # macOS / Linux

# 3. Install Python dependencies (see requirements.txt for the full list)
pip install -r requirements.txt

# 4. Install Chromium browser binary for Playwright
playwright install chromium
```

### Configuration

Create a `.env` file in the project root (never commit this file — it's in `.gitignore`):

```env
DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require
```

**What is `sslmode=require`?** It enforces TLS encryption between your application and PostgreSQL. Without it, credentials would travel in plaintext over the network. In production, this is non-negotiable.

### Running the Scraper

```bash
# Default: 5 jobs, headless browser, Junior SWE in United States
python scraper/main.py

# Full run: 100 jobs, initialize DB tables + indexes first
python scraper/main.py --limit 100 --init-db

# Debug mode: visible browser window (watch what the scraper does)
python scraper/main.py --no-headless

# Custom search: any keywords, any location
python scraper/main.py --search-keywords "Python Developer" --location "London, UK"

# Batch mode: 9 keyword/location combos with cooldowns
python -m scraper.batch --limit 100 --init-db
```

### Running the Dashboard

```bash
streamlit run app.py
```

Opens a browser tab at `http://localhost:8501`. The dashboard reads from PostgreSQL (configured via `DATABASE_URL` in `.env`).

### Running Tests

```bash
python -m pytest tests/ -v                # All 83 tests, verbose output
python -m pytest tests/ --cov=scraper     # With code coverage report
python -m ruff check .                    # Lint check
python -m ruff check . --fix              # Auto-fix linting issues
```

---

## Database Schema

The entire application uses a single table. This is intentional: for a focused analytics project, denormalization into one table simplifies queries and avoids expensive JOINs.

```
Table: jobs
┌────────────────────────────┬──────────────┬──────────────────────────────────────┐
│ Column                     │ Type         │ Notes                                │
├────────────────────────────┼──────────────┼──────────────────────────────────────┤
│ id                         │ INTEGER      │ Primary key, auto-increment           │
│ linkedin_job_id            │ VARCHAR(255) │ Unique, indexed — natural key from URL│
│ title                      │ VARCHAR(255) │ Raw job title from page               │
│ company                    │ VARCHAR(255) │ Nullable — some postings lack company │
│ location                   │ VARCHAR(255) │ Nullable — not always present         │
│ posted_date                │ VARCHAR(255) │ ISO format (YYYY-MM-DD) after parsing │
│ years_experience_required  │ INTEGER      │ Parsed from description, or NULL      │
│ is_junior_title            │ BOOLEAN      │ True if title contains junior keyword │
│ ai_tools_mentioned         │ BOOLEAN      │ DEFAULT FALSE — set at insert time    │
│ tech_stack                 │ JSONB        │ Array of strings, GIN-indexed         │
│ scraped_at                 │ TIMESTAMP    │ Updated on re-scrape (upsert logic)   │
└────────────────────────────┴──────────────┴──────────────────────────────────────┘

Indexes:
  - linkedin_job_id (UNIQUE B-tree) — enables fast upsert lookups
  - idx_scraped_at (DESC) — powers "most recent first" queries in the dashboard
  - idx_tech_stack (GIN) — enables efficient JSONB containment queries
```

**Why JSONB for tech_stack?** PostgreSQL's JSONB is a binary JSON format that supports indexing via GIN (Generalized Inverted Index). A GIN index on `tech_stack` makes queries like "find all jobs requiring Python AND React" use index scans instead of full table scans. The alternative — a separate join table — adds complexity for a schema this focused.

**Upsert behavior:** When a job with the same `linkedin_job_id` is scraped again, ALL fields (including `scraped_at`) are updated. This means the dashboard always shows the latest data for each job, and we never have duplicate entries.

---

## CI/CD Pipeline

The scraper runs automatically via GitHub Actions. Here's how the workflow works:

```yaml
# .github/workflows/scraper.yml
on:
  schedule:
    - cron: '0 0 * * *'      # Runs every day at midnight UTC
  workflow_dispatch:           # Manual trigger button in GitHub UI
```

**Cron syntax: `0 0 * * *`** breaks down as:
- Minute 0 of Hour 0 (midnight) of every Day of every Month of every Day-of-Week.

**Workflow steps:**
1. **Checkout** — clones the repository onto the GitHub Actions runner (Ubuntu VM)
2. **Setup Python** — installs Python 3.10 with pip caching for faster subsequent runs
3. **Install dependencies** — `pip install -r requirements.txt` then `playwright install chromium --with-deps`
4. **Run scraper** — `python -m scraper.batch --init-db --limit 100` with `DATABASE_URL` injected from GitHub Secrets

**Why 35-minute timeout?** LinkedIn scraping is inherently slow (rate limiting + random delays that mimic human browsing). 9 combos × ~3 minutes each = ~27 minutes, leaving ~8 minutes of buffer.

---

## Documentation

The `docs/` directory contains 9 detailed technical documents:

| Document | What It Covers |
|----------|---------------|
| [Requirements Document](docs/Requirements_Document.md) | Product requirements — what the system must do |
| [System Design Document](docs/System_Design_Document.md) | High-level architecture with Mermaid diagrams |
| [Technical Design Document](docs/Technical_Design_Document.md) | Technology choices, schema design, component details |
| [Algorithm Design](docs/Algorithm.md) | Scraping and parsing algorithms in detail |
| [Database Schema](docs/Database_Schema.md) | Full DDL, indexes, sample queries, migration plan |
| [Deployment Guide](docs/Deployment_Guide.md) | Step-by-step for Neon, GitHub Actions, Streamlit Cloud |
| [Testing Strategy](docs/Testing_Strategy.md) | Test pyramid, coverage targets, manual vs automated |
| [Project Structure](docs/Project_Structure.md) | File-by-file reference with module responsibilities |
| [CI/CD Pipeline](docs/CI_CD_Pipeline.md) | GitHub Actions workflow details, secrets, troubleshooting |

---

## License

MIT — do whatever you want. Attribution is appreciated but not required.
