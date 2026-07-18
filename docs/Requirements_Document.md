# Product Requirements Document (PRD): RealityCheck

## 1. Product Overview
**RealityCheck** is an automated data aggregation and visualization tool built to track and analyze the junior software engineer job market on LinkedIn. Its primary goal is to expose the paradox of "entry-level" roles requiring excessive years of experience, effectively demonstrating that the traditional entry-level market has shifted drastically due to AI tooling and heightened expectations.

## 2. Target Audience
- **Computer Science Students/Graduates**: To understand the real skills and experience they need to build before applying to entry-level jobs.
- **Academics/Professors**: To demonstrate that the theoretical foundation is still required because "juniors" are now expected to do mid-level architectural work.
- **Industry Analysts**: To track the adoption of AI tools (Copilot, Cursor) as mandatory requirements for junior developers.

## 3. Functional Requirements
- **Data Ingestion**: The system must scrape job listings for "Junior Software Engineer" from LinkedIn daily.
- **Data Parsing**: The system must parse unstructured job descriptions to extract:
  - Minimum years of experience required.
  - Mention of specific AI development tools.
  - Required technology stacks.
- **Data Storage**: The system must persist structured data in a relational database, avoiding duplicate entries for the same job posting.
- **Visualization**: The system must provide a public web dashboard displaying:
  - Average years of experience required for junior roles.
  - Percentage of roles requiring AI tools.
  - Top 10 most requested technologies in the junior market.

## 4. Non-Functional Requirements
- **Automation**: The pipeline must run completely autonomously without manual intervention.
- **Cost**: The entire infrastructure (compute, storage, hosting) must operate on free tiers ($0/month).
- **Resilience**: The scraper must gracefully handle rate limiting, CAPTCHAs (by failing gracefully and retrying later), and dynamic DOM changes.
- **Performance**: The frontend dashboard must load in under 2 seconds.

## 5. Success Metrics
- Successfully ingesting 100+ unique job postings per day.
- A public Streamlit dashboard that remains continuously live and updates its metrics within 24 hours of data ingestion.
- 0% duplication of jobs in the database.
