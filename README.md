# Job Search Automation Script

## Overview

This Python script automates job searches across multiple job platforms, filters jobs based on salary requirements and fitness to your resume, and sends tailored cover letters via email. It leverages Selenium for web scraping, Anthropic's Claude API for analyzing job descriptions and generating cover letters, and AWS services for persistence and email delivery.

## Features

- **Multi-Platform Scraping**: Extracts job postings from LinkedIn, Indeed, Upwork, Insight Global, ZipRecruiter, CyberCoders, Dice, WeWorkRemotely, Monster, and Kforce
- **Intelligent Job Assessment**: 
  - Scores job postings against your resume using Anthropic's Claude API
  - Filters out software development roles and other poor fit positions
  - Prioritizes infrastructure and cloud engineering positions
- **Salary Processing**: 
  - Detects and normalizes salary information from various formats (hourly, yearly, ranges)
  - Filters jobs below specified salary thresholds
- **Cover Letter Generation**: Dynamically creates tailored cover letters for each job posting
- **Email Integration**: Automatically emails job details and cover letters to a specified recipient
- **Persistence**: Tracks already-seen jobs using DynamoDB to prevent duplicate processing
- **Metrics Tracking**: Monitors and displays statistics about processed jobs

## Prerequisites

### Tools and Libraries
- Python 3.8 or above
- Selenium with undetected-chromedriver
- Microsoft Word (via `python-docx`)
- AWS SDK for Python (`boto3`) for DynamoDB and SES
- Anthropic Claude API
- dotenv for environment variable management

### Environment Setup
1. Install required Python libraries:
   ```bash
   pip install selenium undetected-chromedriver python-docx boto3 anthropic python-dotenv
   ```

2. Set up a `.env` file in the project root with the following keys:
   ```
   ANTHROPIC_API_KEY=<your-anthropic-api-key>
   LINKEDIN_EMAIL=<your-linkedin-email>
   LINKEDIN_PASSWORD=<your-linkedin-password>
   ```

3. Ensure AWS credentials are configured locally for DynamoDB and SES functionality.

4. Place your resume and Word template in the script directory:
   - `Ryan J Alder Resume.txt`: Your plain text resume
   - `Ryan J Alder Header Template.docx`: A Word template for cover letters

### Additional Requirements
- Google Chrome browser installed
- AWS DynamoDB tables set up for each job board (linkedin_jobs, indeed_jobs, etc.)
- AWS SES configured for sending emails

## Usage

Run the script using the command line with the desired job search platform:

```bash
python job_search.py <website> [--cron] [--debug]
```

### Arguments
- `website`: The job board to search - one of:
  - `linkedin`: LinkedIn
  - `indeed`: Indeed
  - `upwork`: Upwork
  - `insight`: Insight Global
  - `ziprecruiter`: ZipRecruiter
  - `cybercoders`: CyberCoders
  - `dice`: Dice
  - `wwr`: WeWorkRemotely
  - `monster`: Monster
  - `kforce`: Kforce
  - `all`: Search on all supported platforms
  - `selenium`: Search on all platforms that require Selenium (excludes LinkedIn API)
- `--cron`: Suppress progress output for cron jobs
- `--debug`: Enable detailed logging to debug.log

### Examples
```bash
python job_search.py linkedin
python job_search.py all --cron
python job_search.py selenium --debug
```

## Configuration

Several constants in the script can be adjusted to modify the behavior:

- `salary_threshold`: Minimum annual salary in thousands (default: 180)
- `hourly_threshold`: Minimum hourly rate (default: 80)
- `fitness_threshold`: Minimum job fitness score (default: 75)
- `mail_to`: Email address to receive job notifications
- `poor_fit_titles`: List of job titles to automatically filter out
- `poor_fit_companies`: List of companies to automatically filter out
- `software_role_indicatiors`: List of keywords indicating software development roles

## Job Processing Workflow

1. The script scrapes job listings from the selected platform(s)
2. For each job:
   - Checks if already processed using DynamoDB
   - Retrieves detailed job description
   - Extracts salary information
   - Filters out jobs below salary threshold
   - Calculates fitness score using Claude API
   - Filters out jobs below fitness threshold
   - Generates tailored cover letter using Claude API
   - Emails job details and cover letter to specified recipient
   - Records job ID in DynamoDB to prevent future reprocessing

## Fitness Scoring

Jobs are scored on a 0-100 scale based on:
- Match between job requirements and resume experience (base score 0-60)
- Infrastructure operations/maintenance focus (+20 points)
- Appropriate seniority level (+10 points)
- Remote or local to Grass Valley, CA (+10 points)

Deductions for:
- Primary focus on software development (-20 points)
- Mixed software/infrastructure roles (-15 points)
- Minor coding requirements (-10 points)
- Sales/solutions or management roles (-15 points)

## Anti-Detection Measures

The script incorporates several techniques to avoid detection as a bot:
- Using undetected-chromedriver
- Adding random window sizes
- Implementing human-like delays between actions
- Handling Cloudflare verification screens
- Using realistic user agent strings

## Limitations

- Job websites may introduce new anti-bot measures requiring script updates
- Anthropic API usage incurs costs based on usage volume
- Some job listings may be inaccessible due to login requirements or private listings
- Script requires regular maintenance to handle website structure changes

## Troubleshooting

- If you encounter Cloudflare detection issues, the script attempts to handle them but may need manual intervention
- Debug logging can be enabled with the `--debug` flag to investigate issues
- For LinkedIn API errors, verify your credentials in the .env file
- For AWS errors, check your AWS credentials and ensure DynamoDB tables exist

## Disclaimer

Use this script responsibly. Ensure that your usage complies with the terms of service for all job platforms and APIs used in this project.
