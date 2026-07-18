"""
Database Models and Upsert Logic for RealityCheck
==================================================

CS Concepts Demonstrated:
    - Object-Relational Mapping (ORM):
        An ORM bridges the gap between object-oriented programming
        (classes, objects, methods) and relational databases (tables,
        rows, SQL). Instead of writing raw SQL strings, you work with
        Python objects, and the ORM translates operations into SQL.

        Tradeoffs of ORM:
          PRO: Type safety (Mapped[int] won't accept strings)
          PRO: Migrations are easier (schema changes = class changes)
          PRO: Less SQL injection risk (parameters are escaped automatically)
          CON: Performance overhead (translating objects → SQL → rows → objects)
          CON: Complex queries can be harder to express than raw SQL
          CON: You need to understand both the ORM AND the underlying SQL

        For RealityCheck, the tradeoff favors ORM because:
          - Our queries are simple (CRUD + upsert + SELECT *)
          - We benefit from connection pooling being built-in
          - The type-safe column definitions catch bugs at startup, not runtime

    - Connection Pooling:
        Creating a new PostgreSQL connection is expensive (~50ms for
        TLS handshake + authentication). A connection pool keeps a set
        of pre-opened connections and reuses them across requests.

        pool_size=5:   Maximum number of persistent connections.
        max_overflow=10: Additional temporary connections allowed beyond pool_size
                        before new requests must wait.
        pool_pre_ping=True: Before using a connection, the pool tests it
                            with a lightweight "SELECT 1" query. If the
                            connection has timed out or been killed by
                            the server, a fresh one is created.
                            Without this, you get "server closed the
                            connection unexpectedly" errors.

        Total max connections = pool_size + max_overflow = 15.
        Neon.tech free tier limit: 20 connections. We stay safely under.

    - Singleton Pattern (Module-Level):
        The engine is stored as a module-level variable (_engine).
        Subsequent calls to get_engine() return the same engine object
        instead of creating a new one. This is a LAZY singleton:
        the engine is created on first use, not at import time.

        Why a singleton? Creating a connection pool per request would
        exhaust database connection limits (15 requests × 15 connections
        = 225 connections — way over Neon's 20-connection limit).

    - Upsert (UPDATE or INSERT):
        An upsert combines INSERT and UPDATE into one logical operation.
        If the row doesn't exist → INSERT. If it does → UPDATE.
        This is idempotent: running it multiple times with the same
        data produces the same result (no duplicates).

        We implement upsert at the application level (select → decide
        → insert or update) rather than using PostgreSQL's native
        INSERT ... ON CONFLICT ... DO UPDATE because:
          1. It's easier to read and maintain
          2. We need access to the full ORM model for validation
          3. The performance difference is negligible for batch inserts
             of < 1000 rows
        Tradeoff: application-level upsert is NOT atomic (race condition
        between SELECT and INSERT). Two concurrent scrapes could both
        see "no row exists" and both try to INSERT, causing an
        IntegrityError on the UNIQUE constraint. We handle this with
        a try/except for IntegrityError + rollback.

    - JSONB Column Type:
        PostgreSQL's JSONB stores JSON data in a binary format that
        supports indexing via GIN (Generalized Inverted Index).
        Unlike the plain JSON type (which stores text and parses it
        on every query), JSONB is pre-parsed and indexable.

        Why not a separate join table (jobs ↔ job_techs)?
          - More complex schema (2 tables instead of 1)
          - Dashboard queries would need JOINs (slower for simple reads)
          - The tech_stack array is small (usually < 10 items)
          - We only query it for dashboard aggregations (fetch all, filter in Python)

    - GIN Index on JSONB:
        GIN = Generalized Inverted Index. It's like a book index:
        each value maps to the rows that contain it. For a JSONB array,
        GIN indexes each element, enabling queries like:
          SELECT * FROM jobs WHERE tech_stack @> '["python"]';
        (Find all jobs whose tech_stack array CONTAINS "python".)

        Without a GIN index, PostgreSQL would have to scan every row
        and parse the JSONB for each one — O(n) where n = number of
        rows. With GIN, it's O(log n) for indexed lookups.

Architecture Role:
    This module is the STORAGE TIER. It:
      - Receives: parsed job dicts from main.py/batch.py
      - Does: validates, deduplicates, persists to PostgreSQL
      - Provides: Job model for ORM queries, fetch_all_jobs() for dashboard

Dependencies & Rationale:
    - SQLAlchemy: ORM with declarative mapping, connection pooling, session management
    - Pandas: Converts query results to DataFrame (dashboard needs DataFrames)
    - psycopg2: Low-level PostgreSQL driver (SQLAlchemy uses it under the hood)
"""

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import (
    JSON,
    Engine,
    create_engine,
    text,
)
from sqlalchemy.dialects.postgresql import BOOLEAN, INTEGER, TIMESTAMP, VARCHAR
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

from scraper.utils import get_database_url, setup_logging

logger = setup_logging(__name__)


# ═══════════════════════════════════════════════════════════════════
# ORM DECLARATIVE BASE
# ═══════════════════════════════════════════════════════════════════
#
# DeclarativeBase is SQLAlchemy's modern (2.0+) base class for ORM models.
# All model classes inherit from Base, and Base.metadata tracks all tables.
# This is the "declarative" style: you declare Python classes that map
# to database tables, and SQLAlchemy handles the SQL generation.
#
# In SQLAlchemy 1.x, you'd use `declarative_base()`. The 2.0+ approach
# with `class Base(DeclarativeBase)` is preferred for better type-hinting
# support and cleaner inheritance.

class Base(DeclarativeBase):
    pass


# ═══════════════════════════════════════════════════════════════════
# JOB MODEL — Maps to the 'jobs' PostgreSQL table
# ═══════════════════════════════════════════════════════════════════
#
# This class defines both the Python interface AND the database schema.
# SQLAlchemy uses the class attributes to:
#   1. Generate CREATE TABLE statements (via Base.metadata.create_all)
#   2. Map query result rows to Python objects
#   3. Validate attribute types at the Python level
#
# Column types use PostgreSQL-specific dialects (e.g., VARCHAR(255))
# rather than generic types (String(255)) because we target PostgreSQL
# exclusively. This gives us access to PostgreSQL-specific features
# like JSONB and GIN indexes.

class Job(Base):
    """
    SQLAlchemy model for the 'jobs' table.

    Maps 1:1 with the schema defined in docs/Database_Schema.md
    and README.md.
    """
    __tablename__ = "jobs"

    # PRIMARY KEY: Auto-incrementing integer.
    # This is a SURROGATE key (artificial, not from the data itself).
    # Surrogate keys are preferred over natural keys because:
    #   - They never change (LinkedIn might change their job IDs)
    #   - Integer comparisons are faster than string comparisons
    #   - Integer keys make JOINs faster (smaller index entries)
    id: Mapped[int] = mapped_column(INTEGER, primary_key=True, autoincrement=True)

    # NATURAL KEY: LinkedIn's own job identifier from the URL.
    # UNIQUE constraint prevents duplicate job entries.
    # INDEX speeds up upsert lookups (the WHERE clause in SELECT).
    # VARCHAR(255) is sufficient for LinkedIn job IDs (typically 10 digits).
    linkedin_job_id: Mapped[str] = mapped_column(
        VARCHAR(255), unique=True, nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    company: Mapped[str | None] = mapped_column(VARCHAR(255))
    location: Mapped[str | None] = mapped_column(VARCHAR(255))

    # Stored as string because:
    #   - The dates are already parsed into ISO format by parse_posted_date()
    #   - We don't need date arithmetic in SQL (dashboard does it in Pandas)
    #   - VARCHAR avoids timezone conversion issues in PostgreSQL
    # Using the PostgreSQL DATE type would be cleaner, but VARCHAR is simpler
    # for a project of this scale.
    posted_date: Mapped[str | None] = mapped_column(VARCHAR(255))

    # Nullable: If the parser couldn't find experience info, this stays NULL.
    # The dashboard filters out NULLs for average calculations.
    years_experience_required: Mapped[int | None] = mapped_column(INTEGER)
    is_junior_title: Mapped[bool | None] = mapped_column(BOOLEAN)

    # DEFAULT FALSE: Most jobs don't mention AI tools, so FALSE is the
    # sensible default. The SERVER_DEFAULT ensures that even if the
    # application doesn't set this field, the database fills it in.
    ai_tools_mentioned: Mapped[bool] = mapped_column(
        BOOLEAN, default=False, server_default=text("FALSE")
    )

    # JSONB column stores the tech stack as a PostgreSQL JSONB array.
    # SQLAlchemy's JSON type maps to JSONB when used with PostgreSQL.
    # The list[str] type hint tells Python what type to expect,
    # and JSON tells SQLAlchemy how to serialize/deserialize it.
    #   Python: ["python", "react", "docker"]
    #   Stored: ["python", "react", "docker"]  (binary JSONB representation)
    #   Returned: ["python", "react", "docker"]  (Python list, deserialized)
    tech_stack: Mapped[list | None] = mapped_column(JSON)

    # TIMESTAMP WITH NO TIMEZONE: We store UTC timestamps without timezone
    # info to avoid DST complications. The application always generates
    # UTC values. This is a pragmatic choice — ideally you'd use
    # TIMESTAMP WITH TIMEZONE and handle timezone everywhere, but for
    # a single-region dashboard it's unnecessary complexity.
    #
    # server_default=CURRENT_TIMESTAMP: The DB fills this when a row is
    # created. On upsert (UPDATE), the application explicitly sets a new
    # timestamp so we know when the job was last re-scraped.
    scraped_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=False),
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        server_default=text("CURRENT_TIMESTAMP"),
    )

    def __repr__(self) -> str:
        """
        String representation for debugging. Shows key identifying fields.

        Example output: <Job(id=42, title='Junior SWE', company='TechCorp')>
        """
        return f"<Job(id={self.id}, title='{self.title}', company='{self.company}')>"


# ═══════════════════════════════════════════════════════════════════
# ENGINE MANAGEMENT (Singleton Pattern)
# ═══════════════════════════════════════════════════════════════════
#
# An Engine is SQLAlchemy's entry point — it manages:
#   1. Connection pool lifecycle (open, check, close)
#   2. Database dialect (PostgreSQL-specific SQL generation)
#   3. Execution context (transaction boundaries)
#
# We store the engine as module-level globals. This is a deliberate
# design choice, not an accident. The alternatives:
#   - Global variable: Simple, but creates engine at import time (bad for testing)
#   - Per-function create: Creates a new pool every time (exhausts connection limits)
#   - Singleton get_engine(): Creates lazily, caches, reuses — the chosen approach

_engine: Engine | None = None     # The cached engine instance
_engine_url: str | None = None    # Tracks which URL the engine was created with


def _create_engine(database_url: str) -> Engine:
    """
    Internal: Create a new SQLAlchemy engine for PostgreSQL.

    Connection pool parameters explained:
        pool_pre_ping=True:
            Tests connections with "SELECT 1" before using them.
            This is the "fix" for connections that get killed by
            Neon.tech's idle timeout (connections idle for >5 min
            get terminated). Without this, you'd get sporadic
            "OperationalError: server closed the connection unexpectedly"
            errors. The cost: one extra query per connection check.
            For our access pattern (one scrape batch every 24 hours),
            this cost is zero in practice.

        pool_size=5:
            Keep 5 persistent connections open. More = faster for
            concurrent access, but consumes more database resources.
            For a single-user dashboard + batch scraper, 5 is plenty.

        max_overflow=10:
            Allow up to 10 extra connections beyond pool_size if all
            5 are in use. Total possible connections = 5 + 10 = 15.
            Neon.tech free tier allows 20 simultaneous connections,
            so we stay 5 under the limit.

        echo=False:
            Don't log every SQL query. Set to True for debugging.
            In production, SQL logs would be noise (the scraper makes
            ~100-200 queries per run).

    ARIA label for accessibility compliance is NOT set because this
    is a backend CLI tool, not a web UI component.
    """
    logger.info("Creating database engine...")
    return create_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


def get_engine(database_url: str | None = None) -> Engine:
    """
    Return a cached SQLAlchemy engine (lazy singleton pattern).

    Behavior:
        - First call: Creates engine, caches it, returns it.
        - Subsequent calls (same URL): Returns cached engine. O(1).
        - Subsequent calls (different URL): Disposes old engine,
          creates new one with new URL.

    The URL-change detection matters for testing: tests pass a different
    URL (SQLite in-memory), which triggers a new engine creation.

    This function is NOT thread-safe. For a multi-threaded application,
    you'd need a lock (threading.Lock) around the engine creation.
    But since our application is single-threaded (async, not threaded),
    this is fine.

    Args:
        database_url: Connection string. If None, reads DATABASE_URL
                     from environment via get_database_url().

    Returns:
        SQLAlchemy Engine instance (cached).

    Raises:
        RuntimeError: If DATABASE_URL is not available.

    Example connection string:
        postgresql://user:password@ep-misty-rain-123456.us-east-2.aws.neon.tech/neondb?sslmode=require
        ├── protocol ─┤├─── credentials ───┤├──────────── host ─────────────────┤├─db──┤├── params ──┤
    """
    global _engine, _engine_url
    url = database_url or get_database_url()

    # Cache hit: same URL, valid engine → return cached
    if _engine is not None and _engine_url == url:
        return _engine

    # URL changed: dispose old engine, create new one
    if _engine is not None:
        _engine.dispose()

    _engine = _create_engine(url)
    _engine_url = url
    return _engine


def dispose_engine():
    """
    Dispose the cached engine and release all connection pool resources.

    Should be called during application shutdown to clean up gracefully.
    In practice, the CI/CD runner and Streamlit Cloud both terminate
    the process after execution, so not calling this is harmless —
    but it's good practice for long-running applications.

    The dispose() method:
        1. Closes all connections in the pool
        2. Removes them from the pool
        3. Calls each connection's close() method
        After dispose(), the engine is unusable until re-created.
    """
    global _engine, _engine_url
    if _engine is not None:
        _engine.dispose()
        _engine = None
        _engine_url = None


def get_session(engine: Engine) -> Session:
    """
    Create a new SQLAlchemy session bound to the given engine.

    What is a Session?
        A session is a "workspace" for database operations. It:
          - Tracks changes to objects (the "identity map" pattern)
          - Batches INSERT/UPDATE/DELETE operations
          - Manages transaction boundaries (begin/commit/rollback)

        Think of it as a "shopping cart" for database changes: you add
        items (inserts), modify items (updates), and when you're ready,
        you "checkout" (commit). If something goes wrong, you "abandon
        cart" (rollback).

    sessionmaker is a factory function that creates Session classes
    pre-configured with a specific engine binding.
    """
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def init_db(engine: Engine):
    """
    Create all tables and indexes if they don't exist. Idempotent.

    Idempotent = safe to call multiple times. Running this on an
    already-initialized database skips creation of existing objects
    (PostgreSQL uses IF NOT EXISTS internally).

    Why create indexes manually instead of in the model?
        - SQLAlchemy's Index() construct works for some indexes but
          not all (GIN indexes on JSONB are PostgreSQL-specific and
          not supported by the generic Index() API)
        - CREATE INDEX IF NOT EXISTS is a PostgreSQL extension to SQL
          standard — it's not portable anyway, so we embrace it
        - Manual index creation gives us explicit control over the
          index type (GIN vs B-tree) and sort order (DESC)

    Indexes created:
        1. idx_scraped_at (B-tree, DESC):
           Speeds up "ORDER BY scraped_at DESC" — the dashboard's
           most common query. Without this index, PostgreSQL would
           do a full table scan + sort for every dashboard load.
           With it, it walks the index in reverse — O(log n).

        2. idx_tech_stack (GIN on JSONB):
           Speeds up containment queries like:
             SELECT * FROM jobs WHERE tech_stack @> '["python", "react"]';
           The GIN index allows efficient inversion: instead of
           scanning rows and checking if they contain "python",
           it looks up "python" in the index and returns the rows
           directly. Think of it as a book's index: "python, pages
           15, 42, 103" vs reading every page.

    Without these indexes, the dashboard would slow down linearly
    as the jobs table grows (O(n) full table scans).
    """
    logger.info("Initializing database schema...")

    # Create all tables defined in the declarative Base
    Base.metadata.create_all(engine)

    # Create additional PostgreSQL-specific indexes
    with engine.connect() as conn:
        # B-tree index on scraped_at (DESC) for fast "most recent first" queries
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_scraped_at ON jobs(scraped_at DESC)"
        ))
        # GIN index on tech_stack JSONB for fast containment queries
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_tech_stack ON jobs USING GIN (tech_stack)"
        ))
        conn.commit()

    logger.info("Database schema initialized successfully.")


def upsert_jobs(
    engine: Engine,
    jobs: list[dict],
) -> int:
    """
    Insert or update job records. Returns count of NEW insertions.

    Algorithm per job:
        1. Extract linkedin_job_id from job dict
        2. Query: SELECT ... WHERE linkedin_job_id = ?
        3a. If EXISTS:  Update all fields (including scraped_at)
        3b. If NOT EXISTS: Create new Job object, add to session
        4. Commit the session (all operations in one transaction)
        5. If IntegrityError: Rollback, re-raise

    Why update scraped_at on existing jobs?
        This tracks freshness — the dashboard can show "last scraped X
        hours ago" for each job. Without this, a job scraped on day 1
        would look stale on day 30 even if it was re-scraped daily.

    Race condition and IntegrityError handling:
        Scenario: Two scrapers run simultaneously. Both see job X doesn't
        exist. Both try to INSERT. The first succeeds. The second gets
        an IntegrityError on the UNIQUE(linkedin_job_id) constraint.

        We handle this with try/except + rollback. The rollback is
        critical: without it, the failed transaction leaves the session
        in an unusable state (PostgreSQL would reject subsequent queries).

    For production systems, PostgreSQL's native INSERT ... ON CONFLICT ...
    DO UPDATE is preferable because it's atomic (no race condition).
    But our approach is simpler to read and maintain.

    Args:
        engine: SQLAlchemy engine.
        jobs: List of dicts from parser.parse_job() output.

    Returns:
        int: Number of NEW jobs inserted (not counting updated existing jobs).

    Raises:
        IntegrityError: If a UNIQUE constraint violation occurs and
                       cannot be recovered from.
    """
    if not jobs:
        logger.info("No jobs to upsert.")
        return 0

    inserted = 0    # Count of new rows inserted
    updated = 0     # Count of existing rows updated

    # Context manager (with statement) ensures session.close() is called
    # even if an exception occurs. This returns connections to the pool.
    with get_session(engine) as session:
        for job_data in jobs:
            job_id = job_data.get("linkedin_job_id")
            if not job_id:
                logger.warning(
                    "Skipping job with no linkedin_job_id: %s",
                    job_data.get("title"),
                )
                continue

            # Step 3a: Check if this job already exists in the database
            existing = (
                session.query(Job)
                .filter(Job.linkedin_job_id == job_id)
                .first()
            )

            if existing:
                # Step 3a (UPDATE): Overwrite all fields with fresh data
                existing.title = job_data.get("title", existing.title)
                existing.company = job_data.get("company", existing.company)
                existing.location = job_data.get("location", existing.location)
                existing.posted_date = job_data.get("posted_date", existing.posted_date)
                existing.years_experience_required = job_data.get("years_experience_required")
                existing.is_junior_title = job_data.get("is_junior_title")
                existing.ai_tools_mentioned = job_data.get("ai_tools_mentioned", False)
                existing.tech_stack = job_data.get("tech_stack", [])
                # Update the scrape timestamp — this job was just re-scraped
                existing.scraped_at = datetime.now(timezone.utc).replace(tzinfo=None)
                updated += 1
            else:
                # Step 3b (INSERT): Create a new Job object from the parsed dict
                new_job = Job(
                    linkedin_job_id=job_data["linkedin_job_id"],
                    title=job_data.get("title", ""),
                    company=job_data.get("company", ""),
                    location=job_data.get("location", ""),
                    posted_date=job_data.get("posted_date"),
                    years_experience_required=job_data.get("years_experience_required"),
                    is_junior_title=job_data.get("is_junior_title"),
                    ai_tools_mentioned=job_data.get("ai_tools_mentioned", False),
                    tech_stack=job_data.get("tech_stack", []),
                )
                session.add(new_job)
                inserted += 1

        # Step 4: Commit all changes in a single transaction.
        # ACID guarantees: All changes succeed or none do (Atomicity).
        try:
            session.commit()
            logger.info(
                "Upsert complete: %d inserted, %d updated, %d total.",
                inserted, updated, len(jobs),
            )
        except IntegrityError as e:
            # Step 5: Rollback on constraint violation
            session.rollback()
            logger.error("Integrity error during upsert: %s", e)
            raise

    return inserted


def fetch_all_jobs(engine: Engine) -> pd.DataFrame:
    """
    Fetch all job records as a Pandas DataFrame, ordered newest first.

    This is the single query that powers the entire dashboard.
    The dashboard does all filtering/aggregation in-memory (Pandas)
    rather than writing complex SQL queries. This is a tradeoff:

    PRO:
      - Dashboard code is simpler (Pandas API is expressive)
      - One database round-trip instead of many
      - No need for complex SQL joins/window functions

    CON:
      - All data is loaded into memory (okay for < 100k rows)
      - Dashboard rechunks the same data for each chart

    The Streamlit caching layer (@st.cache_data(ttl=3600) in app.py)
    mitigates the performance concern by caching the DataFrame for
    1 hour. So even if 100 people open the dashboard, the database
    is only queried once per hour.

    Returns:
        pd.DataFrame with columns matching the Job model.
        Empty DataFrame (0 rows) if no jobs have been scraped yet.
    """
    with get_session(engine) as session:
        query = session.query(Job).order_by(Job.scraped_at.desc())
        # pd.read_sql() converts SQLAlchemy query → DataFrame.
        # This is efficient: Pandas uses SQLAlchemy's result set
        # directly, no intermediate Python objects needed.
        df = pd.read_sql(query.statement, session.bind)
    return df
