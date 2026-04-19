# Job Search Automation

Automated job search across multiple job boards. Scrapes listings, filters by salary and resume fit using Claude AI, generates tailored cover letters, and emails matches to you.

## Supported Job Boards

- **LinkedIn** (via API)
- **Indeed**, **ZipRecruiter**, **Dice** (remote + hybrid searches)
- **Upwork**, **Insight Global**, **CyberCoders**, **Monster**, **Kforce**

## How It Works

1. Scrapes job listings from selected board(s)
2. Deduplicates against DynamoDB (skips already-seen jobs)
3. Extracts salary info; filters below threshold
4. Scores job fitness against your resume using Claude AI
5. Generates a tailored cover letter (.docx)
6. Emails job details + cover letter via AWS SES

## Setup

### Prerequisites

- Python 3.8+
- Google Chrome
- AWS account (DynamoDB + SES configured)
- Anthropic API key
- LinkedIn credentials (for LinkedIn board)

### Installation

```bash
pip install -r requirements.txt
```

### Configuration

1. **Secrets** — Copy `.env.sample` to `.env` and fill in your credentials:
   ```bash
   cp .env.sample .env
   ```

2. **Config** — Copy `config.example.yaml` to `config.yaml` and customize:
   ```bash
   cp config.example.yaml config.yaml
   ```
   Key settings in `config.yaml`:
   - `user.name` / `user.location` — used in cover letters and fitness scoring
   - `thresholds` — minimum salary, hourly rate, and fitness score
   - `searches` — paste your search URLs from each job board
   - `filters` — job titles, companies, and keywords to filter out
   - `email` — where to send job matches

3. **Resume** — Create `resume.txt` with your plain-text resume (see `resume.example.txt`)

4. **Cover letter template** — Create `header_template.docx` with your letterhead (see `header_template.example.docx`)

5. **AWS DynamoDB** — Create tables for each board you'll use (e.g., `linkedin_jobs`, `indeed_jobs`, etc.) with `job_id` as the partition key. LinkedIn also needs a `linkedin_spam` table.

## Usage

```bash
python main.py <board>           # search a specific board
python main.py all               # search all boards
python main.py selenium          # search all browser-based boards (excludes LinkedIn API)
python main.py indeed --debug    # enable debug logging to debug.log
python main.py all --cron        # suppress progress output (for cron jobs)
python main.py dice --head       # run Chrome visibly (not headless)
python main.py all --config /path/to/config.yaml  # custom config path
```

## Project Structure

```
main.py              # CLI and orchestration
config.py            # loads config.yaml + .env
config.yaml          # your settings (gitignored)
models.py            # Job and DescriptionResult dataclasses
browser.py           # Selenium browser setup, Cloudflare handling
ai.py                # Claude API: fitness scoring, cover letters
salary.py            # salary parsing from text and descriptions
db.py                # DynamoDB operations
notifications.py     # email via AWS SES
scrapers/            # one module per job board
  registry.py        # maps board names to scraper functions
  linkedin.py        # uses API, not Selenium
  indeed.py
  upwork.py
  insight.py
  ziprecruiter.py
  cybercoders.py
  dice.py
  monster.py
  kforce.py
utils/linkedin_api/  # vendored LinkedIn API library
```

## Fitness Scoring

Jobs are scored 0-100 based on:
- **Base (0-60):** match between core requirements and resume experience
- **+20:** infrastructure operations/maintenance focus (AWS, Linux, DR)
- **+10:** seniority level match
- **+10:** remote or near your configured location
- **-20:** primary software development role
- **-15:** mixed software/infrastructure
- **-10:** occasional coding, infrastructure only in "nice to have"
- **-15:** sales/solutions or management roles

## Troubleshooting

- **Cloudflare blocks:** the script handles most cases, but some may need `--head` for manual intervention
- **Debug logging:** use `--debug` to write detailed logs to `debug.log`
- **LinkedIn errors:** verify credentials in `.env`; copy `~/.linkedin_api/cookies/jar` if running on a new machine
- **AWS errors:** ensure DynamoDB tables exist and AWS credentials are configured
