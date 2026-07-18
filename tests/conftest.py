"""
RealityCheck Test Suite
=======================

CS Concepts Demonstrated:
    - Test-Driven Development (TDD):
        In TDD, you write tests BEFORE writing the implementation code.
        The cycle is: Red (failing test) → Green (make it pass) → Refactor (clean up).
        This project follows a "test-first documentation" approach: the
        tests define expected behavior, and the source code fulfills it.

    - Test Pyramid:
        The test suite follows the classic "test pyramid":
          1. Unit tests (base, most numerous): Test individual functions
             in isolation. Fast, reliable, run on every change.
          2. Integration tests (middle): Test how modules work together.
             Slightly slower, test real interactions.
          3. End-to-end tests (top, fewest): Test the full pipeline end-to-end.
             Slow, brittle, run in CI/CD only. (The live LinkedIn scrape
             is e2e but not automated — it runs on schedule.)
        We have ~50 unit tests, ~5 integration tests, and 0 automated e2e tests
        (the daily CI/CD run effectively tests e2e in production).

    - Fixtures (Dependency Injection for Tests):
        Pytest fixtures are a form of dependency injection. Instead of
        each test creating its own database connection, the 'db_engine'
        fixture provides a shared, pre-configured connection. Fixtures
        can be:
          - Function-scoped (default): Fresh per test function
          - Module-scoped: Shared across all tests in a module
          - Session-scoped: Shared across the entire test session
        The db_engine fixture is function-scoped to ensure test isolation
        (each test starts with a clean, empty database).

    - Mock Data Design:
        The mock_job_texts fixture provides 11 job description scenarios
        covering normal cases, edge cases, and error cases. Each mock
        includes both input (title, company, location, description) and
        expected output (expected years, tech stack, AI flag, junior flag).

    - In-Memory SQLite for Testing:
        Tests use SQLite (sqlite:///:memory:) instead of PostgreSQL.
        This is a test double — it mimics the real database but:
          - Requires no network (tests run offline)
          - Is ephemeral (data disappears after the test)
          - Starts empty (no data pollution from previous tests)
          - Is much faster (no I/O, no network round-trips)
        SQLite doesn't support all PostgreSQL features (JSONB, GIN indexes),
        but it supports the SQL standard enough for our ORM-based tests.

    - Parametrized Testing:
        @pytest.mark.parametrize runs the same test function multiple
        times with different inputs. This is more DRY (Don't Repeat
        Yourself) than writing separate test functions for each input.
        Example: parametrize("title", ["Junior SWE", "Sr. Eng"])
        runs the test twice, once per title value.
"""

import pytest
from sqlalchemy import create_engine

from scraper.db import Base


@pytest.fixture
def db_engine():
    """
    In-memory SQLite engine for integration tests.

    Each test that uses this fixture gets a fresh, empty database
    with the full schema (tables created via Base.metadata.create_all).
    After the test, the engine is disposed (connections closed).

    Yielding (instead of returning) makes this a setup/teardown fixture:
      - Code before 'yield' runs BEFORE the test (setup)
      - Code after 'yield' runs AFTER the test (teardown)
    This ensures resources are cleaned up even if the test fails.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def mock_job_texts():
    """
    Collection of mock job descriptions for parser testing.

    Returns a dict mapping scenario names to test case objects.
    Each test case has:
        title, company, location     — metadata
        description                   — raw job description text (input)
        expected_experience           — expected years (or None)
        expected_tech                 — expected tech stack (list of names)
        expected_ai                   — expected AI tools boolean
        expected_junior               — expected junior title boolean

    Test case categories:
        1. Normal cases (basic, range_experience) — typical job descriptions
        2. No experience (no_experience, associate_title) — actual entry-level jobs
        3. Senior roles (senior_role) — non-junior titles with high experience
        4. AI tools (ai_tools_mentioned) — jobs explicitly mentioning AI tools
        5. Ambiguous matching (java_vs_javascript, golang) — tests word boundaries
        6. Edge cases (empty_description, at_least_experience) — boundary values
        7. False positives (team_size_should_not_match) — numbers that aren't experience

    This fixture is used by both test_parser.py and test_db.py.
    """
    return {
        "basic": {
            "title": "Junior Software Engineer",
            "company": "TechCorp",
            "location": "San Francisco, CA",
            "description": (
                "We are looking for a Junior Software Engineer to join our team. "
                "Requirements: 3+ years of experience with Python and React. "
                "Experience with GitHub Copilot is a plus."
            ),
            "expected_experience": 3,
            "expected_tech": ["python", "react"],
            "expected_ai": True,
            "expected_junior": True,
        },
        "range_experience": {
            "title": "Junior Developer",
            "company": "StartupInc",
            "location": "Remote",
            "description": (
                "Must have 2-5 years of commercial experience with Java and AWS. "
                "Familiarity with Docker and Kubernetes preferred."
            ),
            "expected_experience": 2,    # Lower bound of range
            "expected_tech": ["aws", "docker", "java", "kubernetes"],
            "expected_ai": False,
            "expected_junior": True,
        },
        "no_experience": {
            "title": "Entry Level Software Developer",
            "company": "NewCo",
            "location": "Austin, TX",
            "description": (
                "No prior experience required! We will train you on the job. "
                "Looking for motivated graduates familiar with TypeScript and Node.js."
            ),
            "expected_experience": None,    # Truly entry-level — no experience mentioned
            "expected_tech": ["node", "typescript"],
            "expected_ai": False,
            "expected_junior": True,
        },
        "senior_role": {
            "title": "Senior Software Engineer",
            "company": "BigCorp",
            "location": "New York, NY",
            "description": (
                "10+ years of experience required. Expert knowledge of C++, Rust, and SQL. "
                "Must have led team of 5 engineers."
            ),
            "expected_experience": 10,
            "expected_tech": ["c++", "rust", "sql"],
            "expected_ai": False,
            "expected_junior": False,
        },
        "ai_tools_mentioned": {
            "title": "Software Engineer",
            "company": "AICo",
            "location": "Seattle, WA",
            "description": (
                "Experience with Cursor, ChatGPT, and GitHub Copilot is mandatory. "
                "2 years of Python experience."
            ),
            "expected_experience": 2,
            "expected_tech": ["python"],
            "expected_ai": True,
            "expected_junior": False,
        },
        "java_vs_javascript": {
            "title": "Full Stack Developer",
            "company": "WebCo",
            "location": "Chicago, IL",
            "description": "Java backend with JavaScript frontend. Must know both.",
            "expected_experience": None,
            "expected_tech": ["java", "javascript"],    # Both must match, not just "java"
            "expected_ai": False,
            "expected_junior": False,
        },
        "golang": {
            "title": "Backend Engineer",
            "company": "CloudCo",
            "location": "Remote",
            "description": (
                "Looking for a Golang developer with 4 years of experience. "
                "We use Go for all our microservices."
            ),
            "expected_experience": 4,
            "expected_tech": ["go"],    # "Golang" triggers "go" but "Go" alone does not
            "expected_ai": False,
            "expected_junior": False,
        },
        "associate_title": {
            "title": "Associate Software Engineer",
            "company": "ConsultingFirm",
            "location": "Boston, MA",
            "description": "Fresh graduates welcome. Will train in React and Node.js.",
            "expected_experience": None,
            "expected_tech": ["node", "react"],
            "expected_ai": False,
            "expected_junior": True,    # "Associate" is a junior keyword
        },
        "empty_description": {
            "title": "Junior DevOps Engineer",
            "company": "OpsCo",
            "location": "Denver, CO",
            "description": "",
            "expected_experience": None,
            "expected_tech": [],
            "expected_ai": False,
            "expected_junior": True,
        },
        "at_least_experience": {
            "title": "Junior Developer",
            "company": "MinCo",
            "location": "Miami, FL",
            "description": (
                "Minimum 2 years of professional experience required. "
                "Must know Docker."
            ),
            "expected_experience": 2,    # "minimum" keyword triggers experience extraction
            "expected_tech": ["docker"],
            "expected_ai": False,
            "expected_junior": True,
        },
        "team_size_should_not_match": {
            "title": "Software Engineer",
            "company": "LargeCo",
            "location": "Dallas, TX",
            "description": (
                "Join a team of 5 engineers. 3 years of Python experience required."
            ),
            "expected_experience": 3,       # Should be 3 (from "3 years"), NOT 5 (from "team of 5")
            "expected_tech": ["python"],
            "expected_ai": False,
            "expected_junior": False,
        },
    }
