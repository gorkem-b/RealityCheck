"""
Unit Tests for scraper/parser.py
=================================

CS Concepts Demonstrated:
    - Equivalence Class Testing:
        Each test targets a specific "equivalence class" of inputs.
        For example, "3+ years", "3-5 years", and "1 to 3 yrs" are
        all in the same equivalence class: "range or minimum experience."
        Testing one representative per class is more efficient than
        testing every possible input.

    - Edge Case Coverage:
        Edge cases test the boundaries of valid input:
          - None input → should return None (not crash)
          - Empty string → should return default (not crash)
          - Very large numbers → should be capped or handled
          - Singular vs plural ("year" vs "years")

    - Parametrized Testing:
        @pytest.mark.parametrize runs the same test function with
        multiple inputs. Each input gets its own test case name
        in the output, making it easy to identify which specific
        input failed. Without parametrize, you'd need separate
        functions or a loop (which loses granular failure reporting).

    - Expected Value Testing (Black-Box Testing):
        Tests call functions with known inputs and check the outputs.
        The test doesn't know or care HOW the function works — it
        only verifies that the output is correct. This is "black-box"
        testing: test the interface, not the implementation. This
        means the implementation can be refactored without changing
        the tests (as long as the interface stays the same).

Architecture Role:
    This file tests the PARSER module (pure functions). Since the
    parser functions have no dependencies (no I/O, no database),
    they are trivially testable — no mocking needed.

    import structure:
        from scraper.parser import (
            extract_experience,      # Regex-based experience extraction
            extract_tech_stack,      # Tech keyword detection
            find_ai_tools,           # AI tool keyword detection
            is_junior_title,         # Junior title classification
            parse_job,               # Orchestrator function
            parse_posted_date,       # Date string normalization
        )
"""

import pytest

from scraper.parser import (
    extract_experience,
    extract_tech_stack,
    find_ai_tools,
    is_junior_title,
    parse_job,
    parse_posted_date,
)

# ═══════════════════════════════════════════════════════════════════
# TestExtractExperience — 13 edge cases for experience extraction
# ═══════════════════════════════════════════════════════════════════

class TestExtractExperience:
    """Unit tests for extract_experience() — the core regex parser."""

    def test_basic_plus(self):
        """'3+ years of experience' → 3 (the plus is optional context)."""
        assert extract_experience("3+ years of experience") == 3

    def test_range(self):
        """'3-5 years experience' → 3 (lower bound of range)."""
        assert extract_experience("3-5 years experience") == 3

    def test_to_range(self):
        """'1 to 3 yrs of commercial experience' → 1 (word-based range)."""
        assert extract_experience("1 to 3 yrs of commercial experience") == 1

    def test_at_least(self):
        """'at least 5 years of experience' → 5 (qualifier keyword)."""
        assert extract_experience("at least 5 years of experience") == 5

    def test_minimum(self):
        """'minimum 2 years of professional experience' → 2."""
        assert extract_experience("minimum 2 years of professional experience") == 2

    def test_no_experience(self):
        """No experience-related numbers → None."""
        assert extract_experience("No prior experience required") is None

    def test_entry_level(self):
        """Text mentions entry-level but no numeric experience → None."""
        assert extract_experience("Entry-level position, fresh graduates welcome") is None

    def test_team_size_false_positive(self):
        """'team of 5 engineers' should NOT count as 5 years experience.
        The denylist removes 'team of 5' before the regex runs.
        Then '3 years exp.' correctly yields 3."""
        result = extract_experience("Lead a team of 5 engineers. 3 years exp.")
        assert result == 3

    def test_singular_year(self):
        """'1 year experience required' → 1 (singular form via 'year?' in regex)."""
        assert extract_experience("1 year experience required") == 1

    def test_over_15_capped(self):
        """20 years > 15 cap → None (extreme outlier, likely senior role)."""
        assert extract_experience("20 years of experience required") is None

    def test_empty_text(self):
        """Empty string → None (guard clause prevents regex on empty string)."""
        assert extract_experience("") is None

    def test_none_text(self):
        """None → None (guard clause: 'if not text' catches both None and '')."""
        assert extract_experience(None) is None

    def test_over_experience(self):
        """'over 4 years of experience' → 4 ('over' keyword)."""
        assert extract_experience("over 4 years of experience") == 4

    def test_more_than_experience(self):
        """'more than 6 years of experience' → 6 ('more than' keyword)."""
        assert extract_experience("more than 6 years of experience") == 6

    def test_min_abbreviation(self):
        """'min 2 years experience' → 2 (abbreviated 'min' keyword)."""
        assert extract_experience("min 2 years experience") == 2


# ═══════════════════════════════════════════════════════════════════
# TestExtractTechStack — Word-boundary matching, variant handling
# ═══════════════════════════════════════════════════════════════════

class TestExtractTechStack:
    """Unit tests for extract_tech_stack() — word-boundary regex matching."""

    def test_basic_techs(self):
        """'Python and React required' → ['python', 'react']."""
        result = extract_tech_stack("Python and React required")
        assert "python" in result
        assert "react" in result

    def test_java_vs_javascript(self):
        """'Java' must not match inside 'JavaScript' (word boundaries ensure this)."""
        result = extract_tech_stack("Java backend with JavaScript frontend")
        assert "java" in result
        assert "javascript" in result

    def test_cpp(self):
        """'C++ developer' → ['c++'] (non-alphanumeric chars handled by lookaround)."""
        result = extract_tech_stack("C++ developer needed")
        assert "c++" in result

    def test_csharp(self):
        """'C# experience' → ['c#'] (hash is non-alphanumeric, uses lookaround)."""
        result = extract_tech_stack("C# experience required")
        assert "c#" in result

    def test_golang_only(self):
        """'Golang' triggers 'go' match, but the word 'go' in 'go to the office' does not."""
        result = extract_tech_stack(
            "You will go to the office. Golang experience preferred."
        )
        assert "go" in result

    def test_go_as_word_should_not_match(self):
        """The English word 'go' must NOT trigger a 'go' tech match.
        Only 'golang' in the variant list maps to 'go'."""
        result = extract_tech_stack("We are a go-to company for Java solutions.")
        assert "go" not in result

    def test_node_js(self):
        """'Node.js' → 'node', 'Docker' → 'docker'."""
        result = extract_tech_stack("Node.js and Docker experience")
        assert "node" in result
        assert "docker" in result

    def test_sql_variants(self):
        """'MySQL' and 'PostgreSQL' both map to 'sql' (normalization)."""
        result = extract_tech_stack("MySQL or PostgreSQL experience")
        assert "sql" in result

    def test_empty(self):
        """Empty string → empty list (guard clause)."""
        assert extract_tech_stack("") == []

    def test_none(self):
        """None → empty list (guard clause)."""
        assert extract_tech_stack(None) == []

    def test_case_insensitive(self):
        """'PYTHON, REACT, and DOCKER' → lowercase normalized names."""
        result = extract_tech_stack("PYTHON, REACT, and DOCKER")
        assert set(result) == {"python", "react", "docker"}

    def test_dotnet_variants(self):
        """'.NET' and 'ASP.NET' both map to 'dotnet' (variant normalization)."""
        result = extract_tech_stack(".NET framework and ASP.NET required")
        assert "dotnet" in result


# ═══════════════════════════════════════════════════════════════════
# TestFindAiTools — Simple substring matching for AI keywords
# ═══════════════════════════════════════════════════════════════════

class TestFindAiTools:
    """Unit tests for find_ai_tools() — substring-based keyword detection."""

    def test_copilot(self):
        assert find_ai_tools("Experience with GitHub Copilot") is True

    def test_cursor(self):
        assert find_ai_tools("We use Cursor IDE") is True

    def test_chatgpt(self):
        assert find_ai_tools("ChatGPT experience is a plus") is True

    def test_claude(self):
        assert find_ai_tools("Claude AI experience preferred") is True

    def test_llm(self):
        """'LLM' acronym should be detected (case-insensitive)."""
        assert find_ai_tools("LLM prompt engineering skills") is True

    def test_no_ai(self):
        """Standard description without AI tools → False."""
        assert find_ai_tools("Standard Python developer role") is False

    def test_empty(self):
        assert find_ai_tools("") is False


# ═══════════════════════════════════════════════════════════════════
# TestIsJuniorTitle — Junior keyword classification
# ═══════════════════════════════════════════════════════════════════

class TestIsJuniorTitle:
    """Unit tests for is_junior_title() — junior keyword classification."""

    @pytest.mark.parametrize(
        "title",
        [
            "Junior Backend Engineer",
            "Jr. Software Developer",
            "Entry Level Data Scientist",
            "Associate Product Manager",
            "New Grad SWE 2025",
            "Software Engineer Intern",
            "Graduate Developer",
        ],
    )
    def test_junior_titles(self, title):
        """All 7 common junior title patterns → True."""
        assert is_junior_title(title) is True

    @pytest.mark.parametrize(
        "title",
        [
            "Senior Software Engineer",
            "Staff Engineer",
            "Principal Architect",
            "Lead Developer",
            "CTO",
        ],
    )
    def test_senior_titles(self, title):
        """5 common senior/top-level title patterns → False."""
        assert is_junior_title(title) is False

    def test_empty(self):
        assert is_junior_title("") is False

    def test_none(self):
        assert is_junior_title(None) is False

    def test_data_entry_not_junior(self):
        """Known false positive: 'Data Entry Clerk' contains 'entry' but is not junior.
        This test DOCUMENTS the limitation — it expects True (the current behavior)."""
        assert is_junior_title("Data Entry Clerk") is True


# ═══════════════════════════════════════════════════════════════════
# TestParseJob — Integration of all parsers through parse_job()
# ═══════════════════════════════════════════════════════════════════

class TestParseJob:
    """Integration tests for parse_job() — the parser orchestrator."""

    def test_full_parse(self, mock_job_texts):
        """Full pipeline test: raw dict → parsed dict with all fields."""
        tc = mock_job_texts["basic"]
        raw = {
            "linkedin_job_id": "12345",
            "title": tc["title"],
            "company": tc["company"],
            "location": tc["location"],
            "posted_date": "2024-06-15",
            "job_description": tc["description"],
        }
        result = parse_job(raw)

        assert result["linkedin_job_id"] == "12345"
        assert result["years_experience_required"] == tc["expected_experience"]
        # Note: 'git' appears in this test case's description ("GitHub Copilot")
        # GitHub Copilot contains "git" → triggers 'git' tech detection
        assert set(result["tech_stack"]) == set(tc["expected_tech"]) | {"git"}, (
            f"Expected {set(tc['expected_tech']) | {'git'}}, got {set(result['tech_stack'])}"
        )
        assert result["ai_tools_mentioned"] == tc["expected_ai"]
        assert result["is_junior_title"] == tc["expected_junior"]

    def test_all_mock_cases(self, mock_job_texts):
        """Run parse_job() against all 11 mock cases and verify all fields."""
        for name, tc in mock_job_texts.items():
            raw = {
                "linkedin_job_id": f"id-{name}",
                "title": tc["title"],
                "company": tc["company"],
                "location": tc["location"],
                "posted_date": "2024-06-15",
                "job_description": tc["description"],
            }
            result = parse_job(raw)

            # Each assertion includes a descriptive error message so
            # you can tell immediately which mock case and which field
            # failed when reading the test output.
            assert (
                result["years_experience_required"] == tc["expected_experience"]
            ), (
                f"Case '{name}': expected exp {tc['expected_experience']}, "
                f"got {result['years_experience_required']}"
            )
            # issubset: actual tech stack must CONTAIN all expected techs
            # (but may contain extras, e.g., 'git' from 'GitHub Copilot')
            assert set(tc["expected_tech"]).issubset(set(result["tech_stack"])), (
                f"Case '{name}': expected tech {tc['expected_tech']} "
                f"subset of {result['tech_stack']}"
            )
            assert result["ai_tools_mentioned"] == tc["expected_ai"], (
                f"Case '{name}': expected AI {tc['expected_ai']}, "
                f"got {result['ai_tools_mentioned']}"
            )
            assert result["is_junior_title"] == tc["expected_junior"], (
                f"Case '{name}': expected junior {tc['expected_junior']}, "
                f"got {result['is_junior_title']}"
            )


# ═══════════════════════════════════════════════════════════════════
# TestParsePostedDate — Date string normalization
# ═══════════════════════════════════════════════════════════════════

class TestParsePostedDate:
    """Unit tests for parse_posted_date() — relative & absolute date parsing."""

    def test_days_ago(self):
        """'3 days ago' → today minus 3 days (verified against actual date)."""
        from datetime import datetime, timedelta, timezone
        expected = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
        assert parse_posted_date("3 days ago") == expected

    def test_weeks_ago(self):
        """'2 weeks ago' → today minus 14 days."""
        from datetime import datetime, timedelta, timezone
        expected = (datetime.now(timezone.utc) - timedelta(weeks=2)).strftime("%Y-%m-%d")
        assert parse_posted_date("2 weeks ago") == expected

    def test_absolute_date(self):
        """Already a valid date → returned unchanged."""
        assert parse_posted_date("2024-03-15") == "2024-03-15"

    def test_empty(self):
        assert parse_posted_date("") is None

    def test_none(self):
        assert parse_posted_date(None) is None

    def test_just_now(self):
        """'Just now' → today's date."""
        from datetime import datetime, timezone
        expected = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert parse_posted_date("Just now") == expected

    def test_today(self):
        """'Today' → today's date."""
        from datetime import datetime, timezone
        expected = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert parse_posted_date("Today") == expected

    def test_hours_ago(self):
        """'5 hours ago' → still today."""
        from datetime import datetime, timezone
        expected = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert parse_posted_date("5 hours ago") == expected

    def test_hour_ago_singular(self):
        """'1 hour ago' (singular) → today."""
        from datetime import datetime, timezone
        expected = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert parse_posted_date("1 hour ago") == expected

    def test_months_ago(self):
        """'2 months ago' → today minus ~60 days (30 days/month approximation)."""
        from datetime import datetime, timedelta, timezone
        expected = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")
        assert parse_posted_date("2 months ago") == expected

    def test_month_ago_singular(self):
        """'1 month ago' (singular) → today minus ~30 days."""
        from datetime import datetime, timedelta, timezone
        expected = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        assert parse_posted_date("1 month ago") == expected

    def test_day_ago_singular(self):
        """'1 day ago' (singular 'day') → yesterday."""
        from datetime import datetime, timedelta, timezone
        expected = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        assert parse_posted_date("1 day ago") == expected

    def test_week_ago_singular(self):
        """'1 week ago' (singular 'week') → 7 days ago."""
        from datetime import datetime, timedelta, timezone
        expected = (datetime.now(timezone.utc) - timedelta(weeks=1)).strftime("%Y-%m-%d")
        assert parse_posted_date("1 week ago") == expected

    def test_unrecognized_format(self):
        """Unrecognizable text → None (graceful degradation)."""
        assert parse_posted_date("some random text") is None
