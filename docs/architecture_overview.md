# Architecture Overview

## System Diagram

The data flows linearly from Source to Destination:

1.  **Sources** (RSS Config `feeds.yaml`)
    ↓
2.  **Parser** (`feeds/parser.py`) - Fetches and normalizes RSS data
    ↓
3.  **Filter & Dedup** (`storage/dedupe.py`) - Checks SQLite DB to skip existing URLs
    ↓
4.  **Rewriter** (`rewriter/openai_client.py`) - Transforms content via LLM
    ↓
5.  **Image Extractor** (`images/rss_extractor.py`) - Finds/Downsamples images
    ↓
6.  **Publisher** (`wordpress/client.py`) - Uploads media & creates Post via REST API
    ↓
7.  **Database Update** (`storage/dedupe.py`) - Marks URL as processed

## Key Components

### 1. The Controller (`cli.py`)
- Entry point for the application.
- Orchestrates the loop through all feeds.
- Handles global error logging and final reporting.

### 2. The Deduplication Store (`storage/dedupe.py`)
- **Technology:** SQLite (`data/processed.db`).
- **Concept:** Stores a hash or direct URL of every processed article.
- **Persistence:** This file must be persisted between runs (e.g., via GitHub Actions cache or persistent volume) to avoid re-posting every 15 minutes.

### 3. The Rewriter (`rewriter/openai_client.py`)
- Wraps the OpenAI API.
- Handles the "Prompt Engineering" logic.
- Returns a structured dictionary (Headline, Body, Tags).

### 4. The Wordpress Client (`wordpress/client.py`)
- A wrapper around `requests` for the WP REST API components.
- Handles:
    - Media uploads (and retrieving the resulting Media ID).
    - Category/Tag lookup (getting `term_id` from a string name).
    - Post creation status (Draft vs. Publish).

## Operational Context

- **Run Frequency:** Designed to run every 15–60 minutes.
- **State:** Stateless execution *except* for the `processed.db` SQLite file.
- **Logs:** comprehensive logging is used; in production, logs should be directed to a file or monitoring service.
