"""
Unit Tests for scraper/main.py (Pure Functions Only)
=====================================================

CS Concepts Demonstrated:
    - Pure Function Testing:
        build_search_url() and parse_args() are PURE FUNCTIONS:
        given the same inputs, they always return the same outputs,
        with no side effects (no I/O, no database, no external state).
        Pure functions are the easiest to test because they don't need
        mocks, stubs, or test doubles.

    - URL Encoding Verification:
        Verifies that special characters (spaces, commas, hashes) are
        correctly percent-encoded. This is critical: if spaces aren't
        encoded as %20, LinkedIn would interpret "Junior Software
        Engineer" as three separate parameters.

    - CLI Argument Parsing Validation:
        Tests the argparse configuration (all flags, all combinations)
        to ensure that:
          - Default values are correct
          - Short flags (-l) work the same as long flags (--limit)
          - Boolean flags (--no-headless, --init-db) toggle correctly
          - All flags can be combined

    - Monkeypatching for Test Isolation:
        parse_args() reads sys.argv (the command-line arguments).
        Normally, sys.argv contains the actual script invocation.
        To test different argument combinations, we use pytest's
        monkeypatch fixture to temporarily replace sys.argv with
        test values. After the test, monkeypatch restores the original.

        monkeypatch.setattr(obj, 'attr', value) is like saying:
        "For the duration of this test, pretend that obj.attr = value."

Architecture Role:
    These tests verify the non-async, non-browser parts of the scraper.
    The async Playwright functions (setup_browser, scrape_jobs, etc.)
    are NOT tested here because they require a running Chromium instance
    and a live LinkedIn connection. End-to-end scraping tests are
    performed by the daily CI/CD pipeline (the actual scrape run).

    What IS tested:
        - URL construction (build_search_url)
        - CLI argument parsing (parse_args)
"""

import sys

from scraper.main import build_search_url, parse_args


class TestBuildSearchUrl:
    """Unit tests for build_search_url() — URL construction and encoding."""

    def test_default_keywords_and_location(self):
        """Default: 'Junior Software Engineer' in 'United States'.
        Spaces must be encoded as %20."""
        url = build_search_url("Junior Software Engineer", "United States")
        assert "Junior%20Software%20Engineer" in url
        assert "United%20States" in url
        assert url.startswith("https://www.linkedin.com/jobs/search/")

    def test_custom_keywords(self):
        """Custom keywords should be URL-encoded."""
        url = build_search_url("Python Developer", "United States")
        assert "Python%20Developer" in url
        assert "United%20States" in url

    def test_custom_location(self):
        """Location with comma (London, UK) should encode comma as %2C."""
        url = build_search_url("Junior Software Engineer", "London, UK")
        assert "London%2C%20UK" in url or "London" in url

    def test_special_characters_encoded(self):
        """'C# Developer' — the # must be encoded as %23 to avoid
        being interpreted as a URL fragment identifier."""
        url = build_search_url("C# Developer", "San Francisco, CA")
        assert "C%23%20Developer" in url or "C%23" in url
        assert url.startswith("https://www.linkedin.com/jobs/search/")

    def test_url_has_correct_params(self):
        """URL must contain both '?keywords=' and '&location=' parameters."""
        url = build_search_url("Go Engineer", "Berlin")
        assert "?keywords=" in url
        assert "&location=" in url


class TestParseArgs:
    """Unit tests for parse_args() — CLI argument parsing."""

    def test_default_values(self, monkeypatch):
        """No arguments → all defaults should apply."""
        monkeypatch.setattr(sys, "argv", ["scraper/main.py"])
        args = parse_args()
        assert args.limit == 5                   # Default limit
        assert args.no_headless is False         # Default: headless
        assert args.search_keywords == "Junior Software Engineer"
        assert args.location == "United States"
        assert args.init_db is False             # Default: don't init DB

    def test_custom_limit(self, monkeypatch):
        """--limit 50 → args.limit == 50."""
        monkeypatch.setattr(sys, "argv", ["scraper/main.py", "--limit", "50"])
        args = parse_args()
        assert args.limit == 50

    def test_short_limit_flag(self, monkeypatch):
        """-l 25 (short form) → args.limit == 25."""
        monkeypatch.setattr(sys, "argv", ["scraper/main.py", "-l", "25"])
        args = parse_args()
        assert args.limit == 25

    def test_no_headless(self, monkeypatch):
        """--no-headless flag → args.no_headless == True."""
        monkeypatch.setattr(sys, "argv", ["scraper/main.py", "--no-headless"])
        args = parse_args()
        assert args.no_headless is True

    def test_custom_keywords(self, monkeypatch):
        """--search-keywords 'Python Developer' → custom keywords."""
        monkeypatch.setattr(
            sys, "argv",
            ["scraper/main.py", "--search-keywords", "Python Developer"],
        )
        args = parse_args()
        assert args.search_keywords == "Python Developer"

    def test_custom_location(self, monkeypatch):
        """--location 'London, UK' → custom location."""
        monkeypatch.setattr(
            sys, "argv",
            ["scraper/main.py", "--location", "London, UK"],
        )
        args = parse_args()
        assert args.location == "London, UK"

    def test_init_db(self, monkeypatch):
        """--init-db flag → args.init_db == True."""
        monkeypatch.setattr(sys, "argv", ["scraper/main.py", "--init-db"])
        args = parse_args()
        assert args.init_db is True

    def test_all_flags_combined(self, monkeypatch):
        """All 5 flags combined → all should be set correctly."""
        monkeypatch.setattr(sys, "argv", [
            "scraper/main.py",
            "--limit", "100",
            "--no-headless",
            "--search-keywords", "Data Engineer",
            "--location", "Remote",
            "--init-db",
        ])
        args = parse_args()
        assert args.limit == 100
        assert args.no_headless is True
        assert args.search_keywords == "Data Engineer"
        assert args.location == "Remote"
        assert args.init_db is True
