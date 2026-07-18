# CI/CD Pipeline: RealityCheck

This document describes the GitHub Actions workflow that runs the automated scraping pipeline.

## `.github/workflows/scraper.yml`

The workflow runs daily at midnight UTC and can also be triggered manually.

```yaml
name: Run Daily Job Scraper

on:
  schedule:
    - cron: '0 0 * * *'  # Daily at midnight UTC
  workflow_dispatch:       # Manual trigger from GitHub UI

jobs:
  scrape:
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'
          cache: 'pip'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          playwright install chromium --with-deps

      - name: Run Scraper
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
        run: |
          python scraper/main.py --limit 100 --init-db
```

## Key Details

- **Schedule**: Daily at midnight UTC.
- **Manual trigger**: `workflow_dispatch` allows running from the GitHub Actions UI at any time.
- **Scraper flags**: `--limit 100` (target 100 jobs per run), `--init-db` (ensures schema and indexes exist before scraping).
- **Timeout**: 30-minute cap to prevent runaway scraping.
- **Playwright**: Chromium installed with system dependencies (`--with-deps`).
- **Pip cache**: `cache: 'pip'` speeds up subsequent runs.

## Security Posture
- The `DATABASE_URL` is loaded from GitHub Secrets and never appears in logs or source code.
- The workflow uses `cache: 'pip'` to reduce action execution time, staying well within GitHub's free tier limits (2,000 minutes/month).
- No credentials are hardcoded in the YAML or Python source.
