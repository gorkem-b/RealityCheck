# Database Schema: RealityCheck

This document details the PostgreSQL schema used to store the aggregated job market data.

## Table: `jobs`

The primary table holding all scraped job postings.

| Column Name | Data Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER` | `PRIMARY KEY, AUTO INCREMENT` | Auto-incrementing internal ID. |
| `linkedin_job_id` | `VARCHAR(255)` | `UNIQUE, NOT NULL, INDEXED` | The unique ID assigned to the job by LinkedIn. Used to prevent duplicate insertions via UPSERT operations. |
| `title` | `VARCHAR(255)` | `NOT NULL` | The exact job title (e.g., "Junior Backend Engineer"). |
| `company` | `VARCHAR(255)` | | The name of the hiring company. |
| `location` | `VARCHAR(255)` | | The geographic location or "Remote". |
| `posted_date` | `VARCHAR(255)` | | The date the job was posted, as scraped from LinkedIn (relative strings like "3 days ago" converted to ISO format YYYY-MM-DD, or kept as raw text if parsing fails). |
| `years_experience_required` | `INTEGER` | | The numeric minimum years of experience extracted from the job description. `NULL` if none detected. |
| `is_junior_title` | `BOOLEAN` | | Flag indicating if the title explicitly contains "Junior", "Entry", "Jr", "Associate", etc. |
| `ai_tools_mentioned` | `BOOLEAN` | `DEFAULT FALSE` | Flag indicating if tools like Copilot, Cursor, or ChatGPT were found in the description. |
| `tech_stack` | `JSONB` | | A JSON array of extracted normalized technologies (e.g., `["node", "python", "react"]`). |
| `scraped_at` | `TIMESTAMP` | `DEFAULT CURRENT_TIMESTAMP` | The exact time this record was inserted **or last updated** by the scraper. Updated on re-scrape of the same job. |

## Indexes

To optimize the queries performed by the Streamlit dashboard, the following indexes are maintained:

1. **Job ID Index** (Created automatically by `UNIQUE` constraint):
   ```sql
   CREATE UNIQUE INDEX idx_linkedin_job_id ON jobs(linkedin_job_id);
   ```
   *Purpose*: Fast lookups during the scraping process to prevent duplicates.

2. **Scraped At Index**:
   ```sql
   CREATE INDEX idx_scraped_at ON jobs(scraped_at DESC);
   ```
   *Purpose*: Fast retrieval of the most recent job postings for the dashboard timeline and "New Today" metric.

3. **Tech Stack GIN Index**:
   ```sql
   CREATE INDEX idx_tech_stack ON jobs USING GIN (tech_stack);
   ```
   *Purpose*: Enables rapid searching and counting of specific technologies within the JSONB array.

## Upsert Behavior

When the scraper encounters a `linkedin_job_id` that already exists in the database, **all fields** are updated (not just new ones):

- `title`, `company`, `location` — updated to reflect any changes.
- `posted_date` — updated, since LinkedIn's relative dates change over time.
- `years_experience_required`, `is_junior_title`, `ai_tools_mentioned`, `tech_stack` — updated with latest parsed values.
- `scraped_at` — updated to the current timestamp, so trend charts and the "New Today" dashboard metric accurately reflect latest activity.

## Sample Analytical Queries

**1. Average Experience for Junior Titles:**
```sql
SELECT AVG(years_experience_required) 
FROM jobs 
WHERE is_junior_title = TRUE 
  AND years_experience_required IS NOT NULL;
```

**2. Percentage of Jobs Requiring AI Tools:**
```sql
SELECT 
    (SUM(CASE WHEN ai_tools_mentioned THEN 1 ELSE 0 END) * 100.0 / COUNT(*)) AS ai_percentage
FROM jobs;
```

**3. Jobs Updated Today:**
```sql
SELECT COUNT(*) FROM jobs
WHERE scraped_at::date = CURRENT_DATE;
```
