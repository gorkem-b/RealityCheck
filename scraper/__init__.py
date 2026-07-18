"""
RealityCheck: LinkedIn Junior SWE Job Market Analysis Pipeline
==============================================================

CS Concepts Demonstrated:
    - Python Package System:
        The __init__.py file marks a directory as a Python package.
        Without it, Python treats the directory as a namespace
        (implicit namespace packages were introduced in Python 3.3,
        but explicit __init__.py is still the conventional approach
        and ensures backward compatibility).

        This file is minimal by design. It only contains a docstring
        describing the package. All actual functionality lives in
        the submodules (main, parser, db, utils, batch), which are
        imported explicitly by consumers:
            from scraper.parser import parse_job
            from scraper.db import get_engine

        This is the principle of "least surprise": importing scraper
        doesn't trigger side effects or heavy initialization.

Architecture Role:
    This is the root of the scraper package. The package follows a
    modular design where:
      - utils.py    has NO internal dependencies (foundation)
      - parser.py   depends only on standard library (pure functions)
      - db.py       depends on utils.py (for DATABASE_URL + logging)
      - main.py     depends on db.py, parser.py, utils.py (orchestrator)
      - batch.py    depends on main.py, db.py, utils.py (batch wrapper)

    This is a DAG (Directed Acyclic Graph) — no circular imports.
"""
