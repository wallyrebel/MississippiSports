# AI Rewriting Strategy

## Overview
The goal of this project is not just to aggregate RSS feeds, but to transform press releases and short blurbs into high-quality, AP-style news articles suitable for a general news audience. This is handled by the `OpenAIRewriter` class.

**File:** `src/rss_to_wp/rewriter/openai_client.py`

## The Process

### 1. Content Cleaning
Before sending text to the AI, we clean the raw RSS/HTML content:
- **Strip HTML:** Remove `<div>`, `<span>`, and other non-text elements.
- **Remove Boilerplate:** Attempt to cut off "Read More" links, "Copyright", or "Privacy Policy" footers often included in feed descriptions.

### 2. Prompt Engineering
The system uses a carefully crafted system prompt to guide the AI. Key instructions include:
- **Role:** "Expert news editor and reporter."
- **Style:** "AP Style (Associated Press)."
- **Tone:** "Objective, professional, informative."
- **Constraint:** "Do not use 'clickbait' headlines."
- **Constraint:** "Do not invent facts not present in the source."

### 3. Model Waterfall
To balance quality and cost/availability, we use a fallback integration strategy:

**Primary Model:** `gpt-5-mini`
- Used for 99% of requests.
- Offers the best balance of reasoning and speed.

**Fallback Model:** `gpt-4.1-nano` (or similar configured backup)
- If the primary model call fails (API error, rate limit), the system automatically retries with the lighter model.
- This ensures the pipeline doesn't break due to a temporary outage of the flagship model.

### 4. Output Structure
The AI is instructed to return a JSON object containing:
- `headline`: The rewritten, engaging news headline.
- `body`: The full HTML body of the article (paragraphs `<p>`, etc.).
- `excerpt`: A 1-2 sentence summary for the front page.
- `tags`: A list of relevant keywords (e.g., "Men's Basketball", "Jones College", "Score").

## Configuration
Settings are managed in `.env`:
- `OPENAI_API_KEY`: Required.
- `OPENAI_MODEL`: Defaults to `gpt-5-mini` but can be overridden.
