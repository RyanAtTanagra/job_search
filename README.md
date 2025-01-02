
# Job Search Automation Script

## Overview

This Python script automates job searches on LinkedIn and Indeed, filters jobs based on salary and fitness to the provided resume, and sends details along with a customized cover letter via email. It leverages multiple tools, including Selenium, Anthropic's API, and AWS utilities.

## Features

- **Automated Job Scraping**: Extracts job postings from LinkedIn and Indeed based on specified criteria.
- **Fitness Scoring**: Scores job postings against your resume based on relevance, seniority, location, and other factors.
- **Cover Letter Generation**: Dynamically creates tailored cover letters for each job posting.
- **Email Integration**: Emails job details and cover letters to a specified recipient.
- **Logging**: Maintains logs of processed jobs and any errors encountered.

## Prerequisites

### Tools and Libraries
- Python 3.8 or above
- Selenium with [undetected-chromedriver](https://pypi.org/project/undetected-chromedriver/)
- Microsoft Word (via `python-docx`)
- AWS SDK for Python (`boto3`)
- [Anthropic Claude API](https://www.anthropic.com/product)
- dotenv for environment variable management

### Environment Setup
1. Install required Python libraries:
   ```bash
   pip install -r requirements.txt
   ```
2. Set up a `.env` file in the project root with the following keys:
   ```
   ANTHROPIC_API_KEY=<your-anthropic-api-key>
   LINKEDIN_EMAIL=<your-linkedin-email>
   LINKEDIN_PASSWORD=<your-linkedin-password>
   ```
3. Ensure AWS credentials are configured locally for DynamoDB and SES functionality.

4. Place your resume and Word template in the script directory:
   - `RyanJAlder Resume.txt`: Your plain text resume.
   - `RyanJAlder Header Template.docx`: A Word template for cover letters.

### ChromeDriver
Ensure the latest version of Chrome is installed, and [undetected-chromedriver](https://github.com/ultrafunkamsterdam/undetected-chromedriver) is configured.

## Usage

Run the script using the command line with the desired job search platform:

```bash
python job_search.py <website>
```

### Arguments
- `linkedin`: Search for jobs on LinkedIn.
- `indeed`: Search for jobs on Indeed.
- `all`: Search on both platforms.

### Example
```bash
python job_search.py linkedin
```

## Key Functions

- `search_linkedin`: Searches LinkedIn for job postings matching the criteria.
- `search_indeed`: Searches Indeed for job postings.
- `get_fitness_rating(description)`: Scores a job description against your resume.
- `get_cover_letter(company, title, description)`: Generates a customized cover letter.
- `emailutils.send_ses_email`: Sends the job details and cover letter via email.

## Logs

Logs are saved to `job_processing.log` and include details of processed jobs, skipped entries, and errors.

## Limitations

- LinkedIn and Indeed websites may introduce anti-bot measures. The script handles these cases where possible but may require manual intervention.
- The Anthropic API usage may incur costs depending on the frequency of job searches and fitness scoring.

## Disclaimer

Use this script responsibly. Ensure that your usage complies with the terms of service for LinkedIn, Indeed, and other APIs used in this project.
