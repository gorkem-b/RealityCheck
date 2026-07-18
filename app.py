"""
RealityCheck Dashboard — Streamlit Data Visualization App
==========================================================

CS Concepts Demonstrated:
    - Data Pipeline TTL Caching:
        Streamlit's @st.cache_data decorator implements a Time-To-Live
        (TTL) cache. The decorated function's return value is stored
        and reused for 'ttl' seconds. On cache hit, the function body
        is skipped entirely. This is critical for database-backed apps
        because querying the database on every UI interaction would be
        slow and expensive (especially for cloud databases that charge
        per compute second).

        How TTL caching works:
          1. First call: execute function, store result + timestamp
          2. Subsequent calls within TTL: return cached result (instant)
          3. Call after TTL expires: execute function again, update cache
        This implements a read-through cache: the cache sits between the
        UI and the database, transparent to both.

    - Statistical Aggregation:
        The dashboard computes these aggregate statistics:
          - Mean (average): Sum of values / count. Sensitive to outliers.
          - Count: Number of jobs matching a filter.
          - Sum: Total number of jobs mentioning AI tools.
          - Percentage: (subset / total) × 100.
        These are implemented via Pandas groupby() operations, which
        are optimized C-level implementations (not Python loops).

    - Histogram Binning:
        Converting continuous data (years of experience) into categorical
        bins (0, 1, 2, 3-5, 6-7, 8-10, 10+). Pandas' pd.cut() does
        this efficiently. The bin edges are chosen to be meaningful:
          - 0-2: These are actually "entry level" in years
          - 3-5: The classic "entry-level requiring 3 years" paradox
          - 6-7, 8-10, 10+: Senior/staff level (junior in title only)

    - Co-occurrence Matrices (Adjacency Matrix):
        The tech co-occurrence heatmap uses an adjacency matrix: a 2D
        array where cell [i][j] = number of jobs that mention BOTH
        technology i AND technology j. The diagonal (i=j) counts jobs
        that mention each technology (not shown in the heatmap but
        kept in the matrix). The matrix is symmetric by construction:
        matrix[i][j] == matrix[j][i] because co-occurrence is symmetric.

        Building the matrix involves:
          1. Count all technology occurrences (for top-N selection)
          2. Count all pairwise co-occurrences using itertools.combinations()
          3. Fill the matrix with co-occurrence counts
          4. Render via Plotly Heatmap

        itertools.combinations(iterable, 2) generates all unique pairs
        from a list — for a list of n items, it produces n*(n-1)/2 pairs.
        This is O(n²) for the pair counting phase.

    - Streamlit's Reactive Model:
        Streamlit re-runs the entire script from top to bottom on every
        user interaction (button click, text input, dropdown change).
        This is a departure from traditional frontend frameworks (React,
        Vue) where you manage state explicitly. Streamlit's approach:
          - Write declarative Python code (like a script)
          - Streamlit re-executes on every interaction
          - @st.cache_data prevents expensive operations from re-running
          - st.session_state persists values across re-runs

        This is simpler to reason about (no useEffect/state management)
        but less flexible for complex interactive UIs.

Architecture Role:
    This is the PRESENTATION TIER. It:
      - Receives: DataFrame from scraper.db.fetch_all_jobs()
      - Does: Filters, aggregates, renders charts and tables
      - Produces: An interactive web dashboard (HTML/CSS/JS via Streamlit)

Dependencies & Rationale:
    - streamlit: Web app framework (turns Python scripts into reactive dashboards)
    - pandas: Data manipulation (filtering, grouping, aggregation)
    - numpy: Matrix operations (co-occurrence heatmap)
    - plotly: Heatmap rendering (Streamlit's native charts don't support heatmaps)
    - collections.Counter: Frequency counting with O(1) increment
    - itertools.combinations: Generate unique pairs for co-occurrence
"""

from collections import Counter  # Hash-table-based frequency counter
from itertools import combinations  # Generate unique pairs for co-occurrence matrix

import numpy as np  # Matrix operations (ndarray)
import pandas as pd  # DataFrame — spreadsheet-like data structure
import plotly.graph_objects as go  # Plotly's "graph objects" API (lower-level than express)
import streamlit as st  # Web dashboard framework

from scraper.db import fetch_all_jobs, get_engine, init_db
from scraper.utils import load_env

# ═══════════════════════════════════════════════════════════════════
# PAGE CONFIGURATION
# ═══════════════════════════════════════════════════════════════════
#
# st.set_page_config() MUST be called before any other Streamlit
# command. It configures the page's HTML metadata and appearance.

st.set_page_config(
    page_title="RealityCheck - Junior SWE Job Market",
    page_icon=":bar_chart:",          # Emoji shortcut (Streamlit maps these to icons)
    layout="wide",                     # Use the full browser width (instead of centered column)
    initial_sidebar_state="collapsed", # Hide sidebar by default (we don't have filters there)
)

load_env()    # Load .env file so get_engine() can read DATABASE_URL


# ═══════════════════════════════════════════════════════════════════
# DATA LOADING WITH TTL CACHE
# ═══════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600)    # Cache for 3600 seconds = 1 hour
def load_data() -> pd.DataFrame:
    """
    Load all job data from the database. Cached for 1 hour.

    The TTL cache means:
      - First user to open the dashboard: DB query executes
      - Next users within 1 hour: Get the same DataFrame from cache (instant)
      - After 1 hour: DB query executes again on next access

    Why 3600 seconds? The scraper runs once per day (midnight UTC).
    Data doesn't change between scrapes. 3600s is a generous cache
    window — it could be 86400s (24h) but 1h is a reasonable default
    that balances freshness with performance.

    The cache key is based on the function signature. Since load_data()
    takes no arguments, the cache key is "empty" — it's effectively a
    singleton cache entry. Adding arguments (e.g., filters) would
    create separate cache entries per argument combination.
    """
    engine = get_engine()
    init_db(engine)
    return fetch_all_jobs(engine)


# ═══════════════════════════════════════════════════════════════════
# METRIC COMPUTATION
# ═══════════════════════════════════════════════════════════════════

def compute_metrics(df: pd.DataFrame) -> dict:
    """
    Compute all aggregate metrics from the DataFrame.

    Metrics computed:
        1. total_jobs: Total number of scraped jobs in the database
        2. new_today: Jobs scraped in the last 24 hours (since midnight today)
        3. last_scrape: Timestamp of the most recent scrape
        4. avg_experience_junior: Mean years of experience required for
           jobs with "Junior" or "Entry" in the title
        5. ai_percentage: What % of all jobs mention AI tools

    These metrics are displayed as "metric cards" at the top of the
    dashboard. They give an at-a-glance overview of the job market.

    Handling empty data:
        If the database is empty (no scrapes yet), all metrics display
        "N/A" or 0. This is the "empty state" of the dashboard — the
        user is prompted to run the scraper first.

    Args:
        df: DataFrame from load_data() with all job records.

    Returns:
        dict with keys: total_jobs, new_today, last_scrape,
        avg_experience_junior, ai_percentage, junior_count, ai_count.
    """
    total_jobs = len(df)
    if total_jobs == 0:
        return {
            "total_jobs": 0,
            "new_today": 0,
            "last_scrape": None,
            "avg_experience_junior": None,
            "ai_percentage": None,
            "junior_count": 0,
            "ai_count": 0,
        }

    # Filter to only jobs with junior/entry titles
    junior = df[df["is_junior_title"]]
    junior_count = len(junior)

    # Mean years of experience for junior-titled roles.
    # dropna() removes NULL values (jobs where the parser couldn't find
    # experience info). Including NULLs would make the mean misleading.
    avg_exp = (
        junior["years_experience_required"].dropna().mean()
        if junior_count > 0
        else None
    )

    # AI tools mentioned: count of True values in the boolean column.
    # In Pandas, .sum() on a boolean column counts True values
    # (True = 1, False = 0 in arithmetic context).
    ai_count = int(df["ai_tools_mentioned"].sum())
    ai_pct = (ai_count / total_jobs * 100) if total_jobs > 0 else None

    # Find the most recent scrape timestamp
    if "scraped_at" in df.columns and not df["scraped_at"].isna().all():
        last_scrape = pd.to_datetime(df["scraped_at"]).max()
        today = pd.Timestamp.now().normalize()    # Midnight of today
        # Count jobs scraped today (normalize removes time, compare dates)
        new_today = (
            pd.to_datetime(df["scraped_at"]).dt.normalize() >= today
        ).sum()
    else:
        last_scrape = None
        new_today = 0

    return {
        "total_jobs": total_jobs,
        "new_today": int(new_today),
        "last_scrape": last_scrape,
        "avg_experience_junior": avg_exp,
        "ai_percentage": ai_pct,
        "junior_count": junior_count,
        "ai_count": ai_count,
    }


# ═══════════════════════════════════════════════════════════════════
# CHART FUNCTIONS
# ═══════════════════════════════════════════════════════════════════
#
# Each chart function takes a DataFrame and renders one chart.
# This modular design means:
#   - Charts can be rearranged by reordering function calls
#   - Each chart can be tested independently (with mock DataFrames)
#   - Adding a new chart is just adding a new function


def chart_tech_stack(df: pd.DataFrame):
    """
    Bar chart: Top 10 most requested technologies across all jobs.

    Computes frequency counts using collections.Counter, which is a
    hash-table-based frequency counter. Each technology's count is
    incremented once per job that requires it.

    Counter.most_common(n) returns the n most frequent items as
    (item, count) tuples. Internally, it uses heapq.nlargest() —
    O(k log n) where k=10 and n=number of unique technologies.

    The chart is horizontal (horizontal=True) because:
      1. Technology names have varying lengths (easier to read horizontally)
      2. More technologies fit on screen (vertical scroll if needed)
      3. The count axis (x-axis) is intuitive for horizontal bars
    """
    all_techs = []
    for techs in df["tech_stack"].dropna():
        if isinstance(techs, list):
            all_techs.extend(techs)

    if not all_techs:
        st.info("No technology data available yet.")
        return

    tech_counts = Counter(all_techs).most_common(10)
    if not tech_counts:
        return

    # Convert Counter output to DataFrame for Streamlit charting
    chart_df = pd.DataFrame(tech_counts, columns=["Technology", "Count"])
    chart_df = chart_df.sort_values("Count")    # Ascending = top items on top
    st.bar_chart(chart_df.set_index("Technology"), horizontal=True)


def chart_experience_distribution(df: pd.DataFrame):
    """
    Histogram: Distribution of years of experience for junior-titled roles.

    This chart answers: "When an employer says 'Junior SWE', how many
    years do they actually want?"

    Binning strategy:
        pd.cut() divides continuous data into discrete bins. We use
        predefined bin edges that correspond to career stages:
          0   = "no experience needed"          (actual entry level)
          1   = "1 year"                         (internship-like)
          2   = "2 years"                        (associate level)
          3-5 = "3-5 years"                      (THE PARADOX ZONE)
          6-7 = "6-7 years"                      (mid-level, but titled "junior")
          8-10= "8-10 years"                     (senior, but titled "junior")
          10+ = "10+ years"                      (staff/principal, but titled "junior")

    The right=True parameter means bins include the right edge:
        (0, 1] → 1 year goes in bin "1"
    Without right=True: (0, 1) → 1 year falls between bins.
    """
    junior = df[df["is_junior_title"]]
    exp = junior["years_experience_required"].dropna()

    if exp.empty:
        st.info("No experience data for junior roles yet.")
        return

    bins = [0, 1, 2, 3, 5, 7, 10, 100]    # 100 is effectively "infinity"
    labels = ["0", "1", "2", "3-5", "6-7", "8-10", "10+"]
    exp_binned = pd.cut(exp, bins=bins, labels=labels, right=True)
    counts = exp_binned.value_counts().sort_index()    # Sort by bin order, not count

    st.bar_chart(counts)


def chart_company_leaderboard(df: pd.DataFrame):
    """
    Bar chart: Top 15 companies posting junior roles with the highest
    experience demands.

    Shows the average years_experience_required per company for
    junior-titled roles. This reveals which companies are the "worst
    offenders" for the entry-level experience paradox.

    groupby() is Pandas' SQL GROUP BY equivalent. It splits the
    DataFrame into groups (by company), applies aggregation functions
    (mean, count), and combines the results. The implementation is
    highly optimized C code — much faster than Python loops.
    """
    junior = df[df["is_junior_title"]]
    if junior.empty:
        st.info("No junior role data available yet.")
        return

    company_stats = (
        junior.groupby("company")
        .agg(
            avg_exp=("years_experience_required", "mean"),    # Average years per company
            job_count=("linkedin_job_id", "count"),            # How many postings
        )
        .dropna(subset=["avg_exp"])      # Remove companies with no experience data
        .sort_values("job_count", ascending=False)
        .head(15)                         # Top 15 companies by posting volume
    )

    if company_stats.empty:
        st.info("No company data available yet.")
        return

    st.bar_chart(company_stats[["avg_exp"]], horizontal=True)


def chart_location_breakdown(df: pd.DataFrame):
    """
    Bar chart: Average experience required for junior roles by location.

    Minimum 3 jobs per location — this threshold prevents outlier
    locations with just 1-2 jobs from dominating the chart.

    sort_values(ascending=False).head(10) shows the 10 locations
    with the HIGHEST experience demands for junior roles — the
    "worst offenders" geographically.
    """
    junior = df[df["is_junior_title"]]
    if junior.empty:
        st.info("No location data available yet.")
        return

    location_stats = (
        junior.groupby("location")
        .agg(
            avg_exp=("years_experience_required", "mean"),
            job_count=("linkedin_job_id", "count"),
        )
        .dropna(subset=["avg_exp"])
    )
    location_stats = location_stats[location_stats["job_count"] >= 3]
    location_stats = location_stats.sort_values("avg_exp", ascending=False).head(10)

    if location_stats.empty:
        st.info("No location data with sufficient samples yet.")
        return

    st.bar_chart(location_stats[["avg_exp"]], horizontal=True)


def chart_trend_over_time(df: pd.DataFrame):
    """
    Line chart: Average experience required for junior roles over time.

    Shows whether the experience requirement is trending up (employers
    demanding more experience) or down (market improving for juniors).

    Requires at least 2 distinct scrape dates to draw a trend line.
    With only 1 date, the chart shows "Need at least 2 scrape days..."
    This is a UX guard — single-point line charts are misleading.

    dt.date extracts just the date portion (ignoring time), so all
    jobs scraped on the same day are grouped together regardless of
    the specific hour.
    """
    if "scraped_at" not in df.columns or df["scraped_at"].isna().all():
        st.info(
            "No historical data available yet. "
            "Trends will appear after multiple scrapes."
        )
        return

    df = df.copy()    # Avoid SettingWithCopyWarning by working on a copy
    df["scrape_date"] = pd.to_datetime(df["scraped_at"]).dt.date
    junior = df[df["is_junior_title"]]

    daily = (
        junior.groupby("scrape_date")
        .agg(avg_experience=("years_experience_required", "mean"))
        .dropna()
    )

    if len(daily) < 2:
        st.info("Need at least 2 scrape days to show a trend. Run the scraper again tomorrow.")
        return

    st.line_chart(daily["avg_experience"])


def chart_ai_tools_trend(df: pd.DataFrame):
    """
    Area chart: Percentage of jobs mentioning AI tools over time.

    Tracks whether employers are increasingly requiring AI tool
    proficiency (Copilot, ChatGPT, Cursor, etc.) in their job
    descriptions. An upward trend suggests AI tools are becoming
    a standard expectation rather than a "nice to have."

    The percentage formula: (jobs mentioning AI / total jobs that day) × 100.
    This normalizes for varying scrape volumes per day.
    """
    if "scraped_at" not in df.columns or df["scraped_at"].isna().all():
        st.info("No historical data available yet.")
        return

    df = df.copy()
    df["scrape_date"] = pd.to_datetime(df["scraped_at"]).dt.date

    daily = (
        df.groupby("scrape_date")
        .agg(
            total=("linkedin_job_id", "count"),    # Total jobs scraped that day
            ai_count=("ai_tools_mentioned", "sum"), # Jobs mentioning AI that day
        )
    )
    daily["ai_percentage"] = daily["ai_count"] / daily["total"] * 100

    if len(daily) < 2:
        st.info("Need at least 2 scrape days to show a trend.")
        return

    st.area_chart(daily["ai_percentage"])


def chart_tech_cooccurrence(df: pd.DataFrame):
    """
    Heatmap: Which technologies appear together most often in the
    same job posting.

    This reveals technology "ecosystems" — combinations that employers
    commonly request together:
      - "Python + AWS + Docker" → cloud-native backend
      - "React + Node + TypeScript" → full-stack JavaScript
      - "Java + Spring + SQL" → enterprise backend

    Matrix construction (step by step):
        1. Count all individual technologies (tech_freq Counter)
        2. Select top 15 technologies by frequency (top_techs list)
        3. Count all pairwise co-occurrences for top 15 (pair_counts Counter)
        4. Create a 15x15 zero matrix (NumPy ndarray)
        5. Fill matrix[i][j] with the count of (tech_i, tech_j) pairs
        6. Matrix is symmetric: matrix[i][j] = matrix[j][i]

    The heatmap is rendered via Plotly (not Streamlit native) because
    Streamlit doesn't have a built-in heatmap component. Plotly's
    go.Heatmap is an interactive SVG-based heatmap with hover tooltips
    and zoom.
    """
    tech_pairs = []
    tech_freq = Counter()

    for techs in df["tech_stack"].dropna():
        if isinstance(techs, list) and len(techs) >= 2:
            tech_freq.update(techs)    # Update per-tech frequency
            # Generate all unique unordered pairs from the tech list
            # sorted() ensures consistent pair ordering: (A, B) not (B, A)
            for t1, t2 in combinations(sorted(techs), 2):
                tech_pairs.append((t1, t2))

    if not tech_pairs:
        st.info("Not enough tech stack data for co-occurrence analysis yet.")
        return

    # Select top 15 technologies by frequency
    top_techs = [t for t, _ in tech_freq.most_common(15)]
    # Map technology name → matrix index
    tech_index = {t: i for i, t in enumerate(top_techs)}

    # Initialize zero matrix: 15x15 of float zeros
    matrix = np.zeros((len(top_techs), len(top_techs)))
    pair_counts = Counter(tech_pairs)
    for (a, b), count in pair_counts.items():
        if a in tech_index and b in tech_index:
            i, j = tech_index[a], tech_index[b]
            matrix[i][j] = count
            matrix[j][i] = count    # Symmetric: (A, B) same as (B, A)

    # Plotly "graph objects" API gives full control over the visualization.
    # The colorscale "Blues" is a perceptually uniform gradient from
    # white (0 co-occurrences) to dark blue (most co-occurrences).
    fig = go.Figure(
        data=go.Heatmap(
            z=matrix,
            x=top_techs,             # X-axis labels (technology names)
            y=top_techs,             # Y-axis labels (same as X — symmetric)
            colorscale="Blues",
            text=matrix.astype(int), # Show integer counts in each cell
            texttemplate="%{text}",   # Format inside each cell
            textfont={"size": 10},
        )
    )
    fig.update_layout(
        height=550,
        xaxis_title=None,
        yaxis_title=None,
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
    )
    st.plotly_chart(fig, use_container_width=True)


def table_searchable_jobs(df: pd.DataFrame):
    """
    Searchable, filterable table of all scraped jobs.

    This is the "raw data" view. Users can:
      - Search by title or company name (text input)
      - Filter by role level (Junior, Non-Junior, All)
      - Filter by experience years (0-1, 2-3, 4-5, 6+, Not specified)

    The filtering is done in Pandas (in-memory) rather than SQL because:
      - The entire dataset fits in memory (< 100k rows)
      - Pandas filtering is fast (vectorized C operations)
      - We avoid another database round-trip per filter change

    st.dataframe() is Streamlit's interactive table component. The
    column_config parameter maps database column names to human-readable
    labels and configures special column types (ListColumn for tech_stack,
    DatetimeColumn for scraped_at).
    """
    st.subheader(":mag: Search Job Listings")

    col1, col2, col3 = st.columns(3)
    with col1:
        search = st.text_input("Search title/company", placeholder="Type to filter...")
    with col2:
        junior_filter = st.selectbox(
            "Role Level",
            options=["All", "Junior/Entry only", "Non-Junior only"],
        )
    with col3:
        exp_filter = st.selectbox(
            "Experience Required",
            options=[
                "All", "0-1 years", "2-3 years", "4-5 years",
                "6+ years", "Not specified",
            ],
        )

    filtered = df.copy()

    # Text search: case-insensitive substring match on title OR company
    # str.contains() is Pandas' vectorized string matching.
    # na=False means NULL values are treated as "not matching" (not errors).
    if search:
        mask = (
            filtered["title"].str.contains(search, case=False, na=False)
            | filtered["company"].str.contains(search, case=False, na=False)
        )
        filtered = filtered[mask]

    # Role level filter
    if junior_filter == "Junior/Entry only":
        filtered = filtered[filtered["is_junior_title"]]
    elif junior_filter == "Non-Junior only":
        filtered = filtered[~filtered["is_junior_title"]]    # ~ is boolean NOT in Pandas

    # Experience filter: uses .between() for range queries
    if exp_filter == "0-1 years":
        filtered = filtered[filtered["years_experience_required"].between(0, 1)]
    elif exp_filter == "2-3 years":
        filtered = filtered[filtered["years_experience_required"].between(2, 3)]
    elif exp_filter == "4-5 years":
        filtered = filtered[filtered["years_experience_required"].between(4, 5)]
    elif exp_filter == "6+ years":
        filtered = filtered[filtered["years_experience_required"] >= 6]
    elif exp_filter == "Not specified":
        filtered = filtered[filtered["years_experience_required"].isna()]

    st.metric("Results", len(filtered))

    display_cols = [
        "title", "company", "location", "years_experience_required",
        "is_junior_title", "ai_tools_mentioned", "tech_stack", "scraped_at",
    ]
    available = [c for c in display_cols if c in filtered.columns]
    st.dataframe(
        filtered[available],
        hide_index=True,                # Don't show numeric row index
        use_container_width=True,       # Fill available horizontal space
        column_config={
            "title": "Job Title",
            "company": "Company",
            "location": "Location",
            "years_experience_required": "Exp. Years",
            "is_junior_title": "Junior Title?",
            "ai_tools_mentioned": "AI Tools?",
            "tech_stack": st.column_config.ListColumn("Tech Stack"),
            "scraped_at": st.column_config.DatetimeColumn("Scraped At"),
        },
    )


# ═══════════════════════════════════════════════════════════════════
# MAIN LAYOUT — Streamlit Entry Point
# ═══════════════════════════════════════════════════════════════════

def main():
    """
    Main Streamlit dashboard layout.

    Layout structure (top to bottom):
        1. Header (title + caption)
        2. Key Metrics (5 metric cards in a row)
        3. Experience & Technology Analysis (2-column layout)
        4. Trends Over Time (2-column layout)
        5. Company & Location Breakdown (2-column layout)
        6. Technology Co-occurrence Heatmap (full width)
        7. Searchable Job Table (full width)
        8. Footer

    The 2-column layouts use st.columns(2), which creates a responsive
    grid. On wide screens, columns are side-by-side. On narrow screens,
    they stack vertically.

    Error handling: If the database connection fails, we show a clear
    error message instead of a cryptic traceback. This is especially
    important for Streamlit Cloud deployment, where users may not have
    access to server logs.
    """
    try:
        df = load_data()
    except Exception:
        st.error(
            "Failed to connect to the database. The database may be "
            "unavailable or the connection string may be incorrect. "
            "Please check the DATABASE_URL environment variable and try again."
        )
        return    # Stop rendering — nothing works without data

    metrics = compute_metrics(df)

    # ─── Header ───────────────────────────────────────────────────
    st.title("RealityCheck :chart_with_upwards_trend:")
    st.caption(
        "Tracking the junior software engineer job market. "
        "Data scraped from LinkedIn daily. :orange[0% duplication guaranteed.]"
    )
    st.divider()

    # ─── Row 1: Key Metrics ───────────────────────────────────────
    st.subheader(":bar_chart: Key Metrics")

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total Jobs Scraped", metrics["total_jobs"])
    with col2:
        st.metric("New Today", metrics["new_today"])
    with col3:
        if metrics["last_scrape"]:
            st.metric(
                "Last Scrape",
                metrics["last_scrape"].strftime("%b %d, %H:%M")
                if metrics["last_scrape"] else "N/A",
            )
        else:
            st.metric("Last Scrape", "Never")
    with col4:
        avg = metrics["avg_experience_junior"]
        st.metric(
            "Avg Experience Required (Junior Roles)",
            f"{avg:.1f} years" if avg else "N/A",
            help=(
                "Average years of experience listed in job descriptions "
                "with 'Junior' or 'Entry' in the title."
            ),
        )
    with col5:
        ai_pct = metrics["ai_percentage"]
        st.metric(
            "AI Tools Required",
            f"{ai_pct:.1f}%" if ai_pct else "N/A",
            help=(
                "Percentage of all job postings that mention AI tools "
                "(Copilot, ChatGPT, Cursor, etc.)"
            ),
        )

    if df.empty:
        st.warning(
            ":warning: No data yet! Run the scraper first with "
            "`python scraper/main.py`."
        )
        return    # Stop — nothing to visualize

    st.divider()

    # ─── Row 2: Experience + Technology ───────────────────────────
    st.subheader(":chart_with_upwards_trend: Experience & Technology Analysis")
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("#### Experience Distribution (Junior Roles)")
        st.caption("How many years of experience do 'junior' roles actually require?")
        chart_experience_distribution(df)

    with col_right:
        st.markdown("#### Top 10 Most Requested Technologies")
        st.caption("What tech stacks are junior roles asking for?")
        chart_tech_stack(df)

    st.divider()

    # ─── Row 3: Trends Over Time ──────────────────────────────────
    st.subheader(":calendar: Trends Over Time")
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("#### Average Experience Over Time")
        st.caption("Is the experience requirement increasing or decreasing?")
        chart_trend_over_time(df)

    with col_right:
        st.markdown("#### AI Tools Adoption Over Time")
        st.caption("Are more employers expecting AI tool proficiency?")
        chart_ai_tools_trend(df)

    st.divider()

    # ─── Row 4: Company + Location ────────────────────────────────
    st.subheader(":office: Company & Location Breakdown")
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("#### Top Companies (Junior Roles)")
        st.caption(
            "Which companies post the most junior roles with high experience demands?"
        )
        chart_company_leaderboard(df)

    with col_right:
        st.markdown("#### Experience by Location")
        st.caption("Where are the worst offenders? (Min. 3 jobs per location)")
        chart_location_breakdown(df)

    st.divider()

    # ─── Row 5: Tech Co-occurrence ────────────────────────────────
    st.subheader(":link: Technology Co-occurrence Heatmap")
    st.caption(
        "Which technologies appear together most often in the same job posting?"
    )
    chart_tech_cooccurrence(df)

    st.divider()

    # ─── Row 6: Searchable Table ──────────────────────────────────
    table_searchable_jobs(df)

    # ─── Footer ───────────────────────────────────────────────────
    st.divider()
    st.caption(
        "RealityCheck - Automated daily scraping via GitHub Actions. "
        "Database: Neon.tech (free tier). Dashboard: Streamlit Community Cloud."
    )


if __name__ == "__main__":
    main()
