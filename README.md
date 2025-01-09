# Job Search Automation Script

## Overview

This Python script automates job searches on LinkedIn, Indeed, and Upwork, filters jobs based on salary and fitness to the provided resume, and sends details along with a customized cover letter via email. It leverages multiple tools, including Selenium, Anthropic's API, and AWS utilities.

## Features

- **Automated Job Scraping**: Extracts job postings from LinkedIn, Indeed, and Upwork based on specified criteria.
- **Fitness Scoring**: Scores job postings against your resume based on relevance, seniority, location, and other factors.
- **Cover Letter Generation**: Dynamically creates tailored cover letters for each job posting.
- **Email Integration**: Emails job details and cover letters to a specified recipient.
- **Salary Processing**: Advanced salary detection from various formats (hourly, yearly, ranges) in job descriptions.
- **Logging**: Maintains detailed logs of processed jobs and any errors encountered.
- **Metrics Tracking**: Tracks and displays statistics about processed jobs, including seen jobs, salary/fitness filtered jobs, and successfully processed jobs.

## Prerequisites

### Tools and Libraries
- Python 3.8 or above
- Selenium with [undetected-chromedriver](https://pypi.org/project/undetected-chromedriver/)
- Microsoft Word (via `python-docx`)
- AWS SDK for Python (`boto3`)
- [Anthropic Claude API](https://www.anthropic.com/product)
- dotenv for environment variable management
- Beautiful Soup 4 for HTML parsing

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
   - `Ryan J Alder Resume.txt`: Your plain text resume.
   - `Ryan J Alder Header Template.docx`: A Word template for cover letters.

### ChromeDriver
Ensure the latest version of Chrome is installed, and [undetected-chromedriver](https://github.com/ultrafunkamsterdam/undetected-chromedriver) is configured.

## Usage

Run the script using the command line with the desired job search platform:

```bash
python job_search.py <website>
```

### Arguments
- `linkedin`: Search for jobs on LinkedIn
- `indeed`: Search for jobs on Indeed
- `upwork`: Search for jobs on Upwork
- `all`: Search on all supported platforms

### Example
```bash
python job_search.py upwork
```

## Key Functions

- `search_linkedin`: Searches LinkedIn for job postings matching the criteria
- `search_indeed`: Searches Indeed for job postings
- `search_upwork`: Searches Upwork for job postings and handles both hourly and fixed-price contracts
- `get_fitness_rating(description)`: Scores a job description against your resume
- `get_cover_letter(company, title, description)`: Generates a customized cover letter
- `get_salary_from_description(description)`: Extracts salary information from job descriptions using pattern matching
- `parse_duration_hours(duration_text)`: Parses duration and hours information from Upwork job listings
- `awsutils.send_email`: Sends the job details and cover letter via email

## Logs

Logs are saved to `job_processing.log` and include details of processed jobs, skipped entries, and errors. The script also displays real-time metrics during execution, showing counts of:
- Already seen jobs
- Jobs filtered due to salary requirements
- Jobs filtered due to fitness score
- Jobs with failed description retrieval
- Successfully processed jobs

## Limitations

- Job websites may introduce anti-bot measures. The script handles these cases where possible but may require manual intervention.
- The Anthropic API usage may incur costs depending on the frequency of job searches and fitness scoring.
- Some Upwork job listings may be private and inaccessible for detailed analysis.

## Disclaimer

Use this script responsibly. Ensure that your usage complies with the terms of service for LinkedIn, Indeed, Upwork, and other APIs used in this project.