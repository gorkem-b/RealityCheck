# Project Structure: RealityCheck

This document outlines the complete directory and file structure of the RealityCheck project.

## Directory Tree

```text
RealityCheck/
│
├── .github/
│   └── workflows/
│       └── scraper.yml           # GitHub Actions CI/CD — daily cron + manual trigger
│
├── docs/                         # Project Documentation
│   ├── Algorithm.md              # Detailed algorithms for all 4 tiers
│   ├── CI_CD_Pipeline.md         # GitHub Actions YAML documentation
│   ├── Database_Schema.md        # PostgreSQL schema, indexes, sample queries
│   ├── Deployment_Guide.md       # Step-by-step deployment to Neon, GitHub, Streamlit Cloud
│   ├── Project_Structure.md      # This file
│   ├── Requirements_Document.md  # Product Requirements Document (PRD)
│   ├── System_Design_Document.md # High-level three-tier architecture with Mermaid diagram
│   ├── Technical_Design_Document.md # Tech stack, schema, scraper, parser implementation details
│   └── Testing_Strategy.md       # Multi-layer testing plan
│
├── scraper/                      # The Ingestion Tier
│   ├── __init__.py               # Package docstring
│   ├── main.py                   # Playwright async scraper — browser automation, card extraction, retry/backoff
│   ├── parser.py                 # Pure NLP/regex functions — experience, tech stack, AI tools, junior detection, dates
│   ├── db.py                     # SQLAlchemy ORM — Job model, upsert logic, connection pooling (singleton engine)
│   └── utils.py                  # Logging, env loading, User-Agent rotation, random delays
│
├── tests/                        # Test Suite
│   ├── __init__.py               # Package docstring
│   ├── conftest.py               # Shared fixtures — in-memory SQLite engine, 11 mock job descriptions
│   ├── test_parser.py            # Unit tests — 50+ cases for all parser functions
│   ├── test_db.py                # Integration tests — insert, dedup, upsert updates, empty lists
│   └── test_scraper.py           # Unit tests — URL builder, CLI argument parsing
│
├── .env                          # Local DATABASE_URL (NOT committed)
├── .env.example                  # Template for DATABASE_URL
├── .gitignore                    # Excludes venv, .env, __pycache__, IDE/OS files
├── app.py                        # Streamlit Dashboard — 5 metrics, 7 charts, searchable job table
├── GUIDE.md                      # General coding principles guide
├── pyproject.toml                # Ruff linting config, pytest config, coverage config
├── README.md                     # Project overview, quickstart, architecture, doc links
└── requirements.txt              # Pinned Python dependencies (12 packages)
```

## Module Responsibilities

| File | Tier | Responsibility |
|------|------|---------------|
| `scraper/main.py` | Ingestion | Orchestrates headless browser, navigates LinkedIn, dismisses overlays, extracts card data, retries on rate-limit, passes to parser. |
| `scraper/parser.py` | Ingestion/Parsing | Pure functions: `extract_experience()`, `extract_tech_stack()`, `find_ai_tools()`, `is_junior_title()`, `parse_posted_date()`, `parse_job()`. No I/O. |
| `scraper/db.py` | Storage | `Job` SQLAlchemy model, `get_engine()` (singleton with connection pooling), `upsert_jobs()` (insert-or-update), `fetch_all_jobs()` (returns DataFrame), `init_db()` (creates tables + indexes). |
| `scraper/utils.py` | Shared | `load_env()`, `get_database_url()`, `setup_logging()`, `random_delay()`, `get_random_user_agent()`. |
| `app.py` | Presentation | Streamlit dashboard — loads all data from DB, computes 5 metric cards, renders 7 charts (histogram, bar, line, area, heatmap), provides searchable/filterable job table. |
| `tests/test_parser.py` | Testing | 50+ unit tests covering experience, tech stack, AI tools, junior titles, date parsing, full job parsing. |
| `tests/test_db.py` | Testing | 5 integration tests covering table creation, insert, deduplication, upsert updates (including `scraped_at`/`posted_date`), empty input handling. |
| `tests/test_scraper.py` | Testing | 12 unit tests for `build_search_url()` and `parse_args()` — URL encoding, CLI flag combinations. |
