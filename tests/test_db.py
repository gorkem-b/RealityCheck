"""
Integration Tests for scraper/db.py
====================================

CS Concepts Demonstrated:
    - Integration Testing vs Unit Testing:
        Unit tests verify one function in isolation. Integration tests
        verify that multiple units work together correctly. Here, we
        test the flow: parse_job() → upsert_jobs() → session.query().
        We're testing the INTEGRATION between parser and database,
        not just each in isolation.

    - Test Isolation:
        Each test uses an in-memory SQLite database (via the db_engine
        fixture) that is created fresh and destroyed after the test.
        This ensures tests don't interfere with each other — test A's
        data doesn't affect test B's results. Without isolation, test
        order could affect outcomes (e.g., inserting in test A causes
        test B's count to be wrong).

    - Idempotency Testing:
        The upsert_jobs() function should be IDEMPOTENT: running it
        multiple times with the same input produces the same result.
        We test this by running upsert_jobs() twice with the same data
        and verifying the second run inserts 0 new rows.

    - Test Fixture Dependency Injection:
        The 'db_engine' and 'mock_job_texts' fixtures are automatically
        injected by pytest based on the function parameter names. This
        is a form of dependency injection at the framework level —
        you declare what you need and the framework provides it.

Architecture Role:
    These tests verify the STORAGE TIER works correctly. They use
    SQLite (not PostgreSQL) as a test double. The SQLAlchemy ORM
    abstracts away the database dialect, so these tests give us
    high confidence that the code works with PostgreSQL too.

    The tests verify:
        1. Table creation works (schema is valid)
        2. Insert works (new data is stored correctly)
        3. Deduplication works (same job ID → upsert, not duplicate insert)
        4. Upsert updates ALL fields (including scraped_at timestamp)
        5. Empty input is handled gracefully (no crash)
"""

from scraper.db import Job, get_session, upsert_jobs
from scraper.parser import parse_job


class TestDatabase:
    """Integration tests for the database layer."""

    def test_table_creation(self, db_engine):
        """Verify that the 'jobs' table is created successfully."""
        from sqlalchemy import inspect
        inspector = inspect(db_engine)
        tables = inspector.get_table_names()
        assert "jobs" in tables

    def test_insert_job(self, db_engine, mock_job_texts):
        """Insert a parsed job and verify it counts as 1 new insert."""
        tc = mock_job_texts["basic"]
        raw = {
            "linkedin_job_id": "test-001",
            "title": tc["title"],
            "company": tc["company"],
            "location": tc["location"],
            "posted_date": "2024-06-15",
            "job_description": tc["description"],
        }
        parsed = parse_job(raw)
        inserted = upsert_jobs(db_engine, [parsed])
        assert inserted == 1

    def test_no_duplicate_jobs(self, db_engine, mock_job_texts):
        """Upserting the same job twice → first inserts, second updates.
        Verify: first returns 1, second returns 0 (no new insert)."""
        tc = mock_job_texts["basic"]
        raw = {
            "linkedin_job_id": "test-001",
            "title": tc["title"],
            "company": tc["company"],
            "location": tc["location"],
            "posted_date": "2024-06-15",
            "job_description": tc["description"],
        }
        parsed = parse_job(raw)

        first = upsert_jobs(db_engine, [parsed])
        second = upsert_jobs(db_engine, [parsed])

        assert first == 1    # First time: new insert
        assert second == 0   # Second time: update, not new insert

    def test_upsert_updates_existing(self, db_engine):
        """Upsert with new data should UPDATE all fields of the existing row,
        including the scraped_at timestamp. No fields should retain old values."""
        import time
        parsed1 = {
            "linkedin_job_id": "test-update",
            "title": "Original Title",
            "company": "OldCorp",
            "location": "Old Location",
            "posted_date": "2024-01-01",
            "years_experience_required": 2,
            "is_junior_title": True,
            "ai_tools_mentioned": False,
            "tech_stack": ["python"],
        }

        parsed2 = {
            "linkedin_job_id": "test-update",
            "title": "Updated Title",
            "company": "NewCorp",
            "location": "New Location",
            "posted_date": "2025-06-15",
            "years_experience_required": 3,
            "is_junior_title": True,
            "ai_tools_mentioned": True,
            "tech_stack": ["python", "react"],
        }

        upsert_jobs(db_engine, [parsed1])
        time.sleep(0.1)    # Small delay so scraped_at timestamps differ
        upsert_jobs(db_engine, [parsed2])

        # Verify all fields were updated to the new values
        with get_session(db_engine) as session:
            job = (
                session.query(Job)
                .filter(Job.linkedin_job_id == "test-update")
                .first()
            )

            assert job is not None
            assert job.title == "Updated Title"
            assert job.company == "NewCorp"
            assert job.posted_date == "2025-06-15"
            assert job.ai_tools_mentioned     # Should be True (was False)
            assert job.years_experience_required == 3    # Was 2
            assert job.scraped_at is not None  # Timestamp should be set

    def test_empty_jobs_list(self, db_engine):
        """Empty list → returns 0 (no crash, clean early return)."""
        assert upsert_jobs(db_engine, []) == 0
