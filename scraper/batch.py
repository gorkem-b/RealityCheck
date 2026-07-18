"""
Batch Orchestration for the RealityCheck LinkedIn Scraper
==========================================================

CS Concepts Demonstrated:
    - Batch Processing Patterns:
        Batch processing means executing the same operation on multiple
        inputs in sequence. Unlike stream processing (continuous),
        batch processing runs periodically (daily cron job). This is
        the classic "ETL" pattern (Extract, Transform, Load):
          Extract  → scrape_jobs() for each keyword/location combo
          Transform → parse_job() inside scrape_jobs()
          Load     → upsert_jobs() after each combo
        We load incrementally (after each combo) rather than all at
        once, so that partial results are saved even if a later combo
        fails completely.

    - Error Isolation (Bulkhead Pattern):
        If one keyword/location combo fails (e.g., LinkedIn blocks
        a specific search term), the batch CONTINUES with the remaining
        combos. The failure is logged but doesn't bring down the entire
        pipeline. This is the "bulkhead" pattern: compartments are
        isolated so that a failure in one doesn't flood the others.

    - Rate Limiting via Cooldowns:
        Between each combo, we pause for a configurable number of
        seconds. This prevents:
          1. LinkedIn from detecting rapid-fire searches from the same IP
          2. Hitting Neon.tech's connection limits (20 simultaneous connections)
          3. Overwhelming the GitHub Actions runner's resources

    - Aggregate Metrics Collection:
        As each combo completes, we record its results in a list.
        At the end, we emit an aggregate summary showing total scraped,
        inserted, and updated counts. This is the "collector" pattern:
        each batch unit reports its result independently; the collector
        aggregates them.

    - Configuration as Code (JSON):
        The DEFAULT_COMBOS list is "configuration as code" — the combo
        definitions live in the Python source rather than a separate
        config file. For custom runs, the --config-file flag accepts
        a JSON file, which is "configuration as data." The tradeoff:
          - Code config: Easy to version, no file parsing, but requires
            a code change to modify
          - JSON config: Can be modified without touching code, but
            requires parsing and validation

Architecture Role:
    This module wraps the single-search scrape_jobs() function from
    main.py in a batch loop. It's the CI/CD entry point: the GitHub
    Actions workflow calls `python -m scraper.batch`, not
    `python scraper/main.py`.

Dependencies & Rationale:
    - scraper.main: scrape_jobs() — the single-search scraping function
    - scraper.db: get_engine(), init_db(), upsert_jobs() — persistence
    - scraper.utils: load_env(), setup_logging() — shared utilities
    - argparse, asyncio, json: Standard library

Usage:
    python -m scraper.batch                     # Default combos, headless, 60s cooldown
    python -m scraper.batch --limit 50          # 50 jobs per combo
    python -m scraper.batch --no-headless       # Show browser for debugging
    python -m scraper.batch --config-file combos.json  # Custom combos
    python -m scraper.batch --cooldown 120      # 2 min between combos
    python -m scraper.batch --init-db           # Init DB on first run

Note: This module is invoked as `python -m scraper.batch` (module mode),
not `python scraper/batch.py` (script mode). Module mode is preferred
because it:
  - Uses absolute imports correctly (from scraper.main import ...)
  - Works from any working directory
  - Is the standard for Python package CLIs
"""

import argparse
import asyncio
import json

from scraper.db import get_engine, init_db, upsert_jobs
from scraper.main import scrape_jobs
from scraper.utils import load_env, setup_logging

logger = setup_logging(__name__)


# ═══════════════════════════════════════════════════════════════════
# DEFAULT SEARCH COMBINATIONS
# ═══════════════════════════════════════════════════════════════════
#
# These 9 keyword/location pairs were chosen to capture a broad
# sample of the junior SWE job market. Each uses different
# terminology that employers use for entry-level roles:
#
#   "Junior Software Engineer" — most common title
#   "Entry Level Developer"     — alternative phrasing
#   "Associate Software Engineer"— used by consulting firms/finance
#   "Junior Full Stack Developer" — specific role type
#   "Junior Backend Developer"    — backend specialization
#   "Junior Frontend Developer"   — frontend specialization
#   "Junior Developer" (UK)       — geographical variation
#   "Junior Software Engineer" (Canada) — international market
#   "New Grad Software Engineer"  — campus recruiting terminology
#
# Limit of 9 combos is pragmatic: 9 combos × 100 jobs each = 900 jobs.
# At ~30 seconds per job (including delays), that's ~7.5 hours.
# With a 60-second cooldown between combos, total ≈ 7.5 + (9 × 60s) = 7.5h + 9m.
# At 100 jobs per combo, a full batch takes too long for a single
# CI run. That's why the CI workflow uses --limit 100 (100 total jobs
# per combo) — but in practice, many results overlap (same job appears
# for multiple searches), so unique jobs is much lower.

DEFAULT_COMBOS = [
    {"keywords": "Junior Software Engineer", "location": "United States"},
    {"keywords": "Entry Level Developer", "location": "United States"},
    {"keywords": "Associate Software Engineer", "location": "United States"},
    {"keywords": "Junior Full Stack Developer", "location": "United States"},
    {"keywords": "Junior Backend Developer", "location": "United States"},
    {"keywords": "Junior Frontend Developer", "location": "United States"},
    {"keywords": "Junior Developer", "location": "United Kingdom"},
    {"keywords": "Junior Software Engineer", "location": "Canada"},
    {"keywords": "New Grad Software Engineer", "location": "United States"},
]

DEFAULT_LIMIT = 100        # Jobs per combo
DEFAULT_COOLDOWN = 60      # Seconds between combos


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments for batch mode.

    Additional arguments beyond main.py's CLI:
        --cooldown: Seconds between combos. This is the key rate-limiting
                    mechanism. 60s is a heuristic — long enough to not
                    trigger LinkedIn's rate limiting (which typically
                    kicks in after ~100 requests/minute), short enough
                    to complete the batch in a reasonable time.
        --config-file: Path to a JSON file with custom search combos.
                       The JSON format is:
                       [
                         {"keywords": "Data Engineer", "location": "Remote"},
                         {"keywords": "ML Engineer", "location": "San Francisco, CA"}
                       ]
    """
    parser = argparse.ArgumentParser(
        description="Batch scrape LinkedIn for junior software engineer jobs."
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Jobs per combo (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browser in visible mode",
    )
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="Initialize database schema before first combo",
    )
    parser.add_argument(
        "--cooldown",
        type=int,
        default=DEFAULT_COOLDOWN,
        help=f"Seconds between combos (default: {DEFAULT_COOLDOWN})",
    )
    parser.add_argument(
        "--config-file",
        type=str,
        default=None,
        help="Path to JSON file with custom combo definitions",
    )
    return parser.parse_args()


def load_combos(config_file: str | None) -> list[dict]:
    """
    Load search combinations from a JSON file or use defaults.

    JSON format:
        [
            {"keywords": "...", "location": "..."},
            ...
        ]

    json.load() deserializes the file into Python objects:
        JSON array    → Python list
        JSON object   → Python dict
        JSON string   → Python str
        JSON number   → Python int or float

    Args:
        config_file: Path to JSON config, or None to use defaults.

    Returns:
        list[dict]: Search combos with "keywords" and "location" keys.
    """
    if config_file:
        with open(config_file) as f:
            return json.load(f)
    return DEFAULT_COMBOS


async def run_batch(
    combos: list[dict],
    limit: int,
    headless: bool = True,
    init_db_flag: bool = False,
    cooldown: int = DEFAULT_COOLDOWN,
):
    """
    Execute multiple keyword/location scrapes sequentially.

    This is the batch orchestrator — it calls scrape_jobs() once per
    combo, handles errors per-combo, and reports aggregate results.

    Flow per combo:
        1. Log combo header
        2. Call scrape_jobs(keywords, location, limit, headless)
        3. If jobs returned: upsert to database, count new vs updated
        4. If no jobs: log warning, record zero results
        5. If exception: log error, record failure, continue
        6. If not last combo: await cooldown

    The cooldown happens AFTER each combo (before the next one), NOT
    before the first combo. This is intentional: the first combo runs
    immediately; subsequent combos are spaced out.

    Args:
        combos: List of dicts with "keywords" and "location" keys.
        limit: Max jobs to scrape per combo.
        headless: True = invisible browser.
        init_db_flag: True = create tables before scraping.
        cooldown: Seconds to wait between combos.
    """
    load_env()
    engine = get_engine()

    if init_db_flag:
        init_db(engine)

    total_scraped = 0    # Running count of jobs scraped across all combos
    total_inserted = 0   # Running count of new jobs inserted
    total_updated = 0    # Running count of existing jobs updated
    results: list[dict] = []    # Per-combo result records for summary

    for i, combo in enumerate(combos):
        keywords = combo["keywords"]
        location = combo["location"]

        logger.info("=" * 60)
        logger.info(
            "Combo %d/%d: '%s' in '%s' (limit: %d)",
            i + 1, len(combos), keywords, location, limit,
        )
        logger.info("=" * 60)

        try:
            # Run the single-search scraper for this combo
            jobs = await scrape_jobs(
                limit=limit,
                headless=headless,
                search_keywords=keywords,
                location=location,
            )

            if jobs:
                inserted = upsert_jobs(engine, jobs)
                # updated = total processed - new insertions
                # (the rest were existing jobs that got updated)
                updated = len(jobs) - inserted
                total_scraped += len(jobs)
                total_inserted += inserted
                total_updated += updated
                results.append({
                    "combo": i + 1,
                    "keywords": keywords,
                    "location": location,
                    "scraped": len(jobs),
                    "inserted": inserted,
                    "updated": updated,
                })
                logger.info(
                    "Combo %d result: %d scraped, %d inserted, %d updated.",
                    i + 1, len(jobs), inserted, updated,
                )
            else:
                # No jobs returned (LinkedIn might have changed DOM, or all results
                # were filtered, or the page failed to load in a recoverable way)
                logger.warning("Combo %d: no jobs scraped.", i + 1)
                results.append({
                    "combo": i + 1,
                    "keywords": keywords,
                    "location": location,
                    "scraped": 0,
                    "inserted": 0,
                    "updated": 0,
                })

        except Exception as e:
            # Per-combo error isolation: log the error, record failure,
            # continue with the next combo. The exc_info=True parameter
            # includes the full traceback in the log, which helps
            # debugging CI/CD failures from log output alone.
            logger.error("Combo %d failed: %s", i + 1, e, exc_info=True)
            results.append({
                "combo": i + 1,
                "keywords": keywords,
                "location": location,
                "scraped": 0,
                "inserted": 0,
                "updated": 0,
                "error": str(e),    # Store the error message for the summary
            })

        # Cooldown between combos (except after the last one)
        # asyncio.sleep() is used (not time.sleep()) because we're in
        # an async context. time.sleep() would block the event loop.
        if i < len(combos) - 1:
            logger.info("Cooldown: %ds before next combo...", cooldown)
            await asyncio.sleep(cooldown)

    # ─── Aggregate Summary ─────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("BATCH COMPLETE")
    logger.info("  Combos run: %d", len(combos))
    logger.info("  Total scraped: %d", total_scraped)
    logger.info("  Total inserted: %d", total_inserted)
    logger.info("  Total updated: %d", total_updated)
    logger.info("=" * 60)

    for r in results:
        if r.get("error"):
            logger.info(
                "  #%d FAILED — '%s' / '%s' — %s",
                r["combo"], r["keywords"], r["location"], r["error"],
            )
        else:
            logger.info(
                "  #%d: %d scraped (%d new) — '%s' / '%s'",
                r["combo"], r["scraped"], r["inserted"],
                r["keywords"], r["location"],
            )


async def main():
    """Module entry point — parse args, load combos, run batch."""
    try:
        args = parse_args()

        combos = load_combos(args.config_file)

        await run_batch(
            combos=combos,
            limit=args.limit,
            headless=not args.no_headless,
            init_db_flag=args.init_db,
            cooldown=args.cooldown,
        )
    except Exception as e:
        import sys
        # Print the error as a GitHub Actions annotation so it shows up in the summary
        print(f"::error::Fatal error during scraping: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
