# Deployment Guide: RealityCheck

This guide outlines the step-by-step process to deploy the RealityCheck system into a production environment using free cloud services.

## Phase 1: Database Provisioning (Neon.tech)
1. Navigate to [Neon.tech](https://neon.tech/) and create a free account.
2. Create a new Project named `RealityCheck`.
3. Create a PostgreSQL database.
4. Navigate to the **Dashboard** and copy the Connection String. It will look like: 
   `postgresql://username:password@ep-cold-wave-123456.us-east-2.aws.neon.tech/neondb?sslmode=require`
5. Save this connection string securely.

## Phase 2: Ingestion Pipeline Deployment (GitHub Actions)
1. Push the local repository to GitHub.
2. In the GitHub Repository, navigate to **Settings** > **Secrets and variables** > **Actions**.
3. Click **New repository secret**.
4. Name: `DATABASE_URL`. Value: [Paste the Neon Connection String].
5. Ensure the `.github/workflows/scraper.yml` file is present in the `main` branch.
6. Navigate to the **Actions** tab in GitHub.
7. Select the "Run Daily Job Scraper" workflow and click **Run workflow** to manually trigger the first ingestion cycle.
8. Verify the Action completes successfully and data is inserted into the Neon database.

## Phase 3: Presentation Tier Deployment (Streamlit Community Cloud)
1. Navigate to [Streamlit Community Cloud](https://share.streamlit.io/) and log in with your GitHub account.
2. Click **New app**.
3. Select the `RealityCheck` repository and the `main` branch.
4. Set the **Main file path** to `app.py`.
5. Click **Advanced settings**.
6. In the Secrets text area, paste the database URL in TOML format:
   ```toml
   DATABASE_URL = "postgresql://username:password@ep-cold-wave-123456.us-east-2.aws.neon.tech/neondb?sslmode=require"
   ```
7. Click **Deploy!**
8. Streamlit will build the environment from `requirements.txt` and launch the app. The URL provided by Streamlit is the live production link.

## Ongoing Maintenance
- **Monitoring**: Check the GitHub Actions tab periodically for scraper failures caused by LinkedIn DOM changes.
- **Updates**: If LinkedIn changes its layout, update `scraper/main.py`, commit, and push. GitHub Actions will automatically use the new code on the next run.
