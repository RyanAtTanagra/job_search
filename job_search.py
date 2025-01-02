import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from docx import Document
from docx.shared import Pt
import re
import os
import anthropic
import argparse
import random
from time import sleep
from utils import awsutils
from utils.linkedin_api import Linkedin
import logging
import warnings
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qs

logging.basicConfig(level=logging.INFO, filename='job_processing.log')
logging.getLogger("fontTools").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)
warnings.filterwarnings("ignore", category=DeprecationWarning)

load_dotenv()
anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
if not anthropic_api_key:
    raise ValueError("Anthropic API key is not set in the .env file!")

linkedin_email = os.getenv("LINKEDIN_EMAIL")
linkedin_password = os.getenv("LINKEDIN_PASSWORD")
if not linkedin_email or not linkedin_password:
    raise ValueError("LinkedIn email or password is not set in the .env file!")

# Resume used for fitness scoring and cover letter generation
resume_path = "RyanJAlder Resume.txt"
# Template used for cover letter
template_path = "RyanJAlder Header Template.docx"

metrics = {
    "seen_count": 0,
    "description_count": 0,
    "salary_count": 0,
    "fitness_count": 0,
    "valid_count": 0,
    }

# Used for Indeed scraper
def setup_chrome_driver():
    options = uc.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--enable-javascript')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    
    # Add a realistic user agent
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36')
    
    driver = uc.Chrome(options=options)
    return driver

def get_linkedin_job_details(id):
    try:
        api = Linkedin(linkedin_email, linkedin_password)
    except Exception as e:
        logging.info(f"Error connecting to LinkedIn to get job description")
        return None
    result = api.get_job_description(id)
    return(result)

def scrape_indeed_jobs(url):
    offset = 0
    driver = setup_chrome_driver()
    paginated_url = f"{url}&start={offset}"
    logging.info(f"Loading URL: {paginated_url}")
    driver.get(paginated_url)
    with open("indeed_last_html.html", "w", encoding="utf-8") as file:
        file.write(driver.page_source)

    # Wait for Turnstile iframe
    wait = WebDriverWait(driver, 10)
    try:
        # Look for multiple possible selectors that might indicate the challenge
        turnstile_frame = wait.until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR, 
                "iframe[src*='challenges.cloudflare.com'], iframe[src*='turnstile'], #challenge-form iframe"
            ))
        )
            
        logging.info("Found verification iframe, switching to it...")
        driver.switch_to.frame(turnstile_frame)
        
        # Try to find and interact with the challenge
        try:
            checkbox = wait.until(
                EC.element_to_be_clickable((
                    By.CSS_SELECTOR, 
                    ".turnstile-checkbox, .challenge-checkbox"
               ))
            )
            checkbox.click()
            logging.info("Clicked verification checkbox")
        except Exception as e:
            logging.info(f"Could not find checkbox: {e}")
            
        # Switch back to main content
        driver.switch_to.default_content()
            
        # Wait for page to load after verification
        sleep(5)
            
    except Exception as e:
        logging.info(f"Error handling verification: {e}")

    jobs = []
    while True:
        # Adjust URL for pagination
        paginated_url = f"{url}&start={offset}"
        logging.info(f"Loading URL: {paginated_url}")
        driver.get(paginated_url)

        #print("Waiting for job cards...")
        try:
            wait = WebDriverWait(driver, 10)
            job_cards = driver.find_elements(By.CLASS_NAME, "job_seen_beacon")
            logging.info(f"Found {len(job_cards)} Indeed jobs")
            if len(job_cards) == 0:
                return jobs
        except Exception as e:
            logging.info(f"Error finding job cards: {e}")
            return []

        for idx,card in enumerate(job_cards):
            try:
                job = {}
                
                job['title'] = next((elem.text.strip() for elem in card.find_elements(By.CSS_SELECTOR, 'span[id^="jobTitle"]')), None)
                job['company'] = next((elem.text.strip() for elem in card.find_elements(By.CSS_SELECTOR, '[data-testid="company-name"]')), None)
                job['description'] = next((elem.text.strip() for elem in card.find_elements(By.CSS_SELECTOR, '[data-testid="jobsnippet_footer"]')), None)
                
                # Salary processing
                job['salary_text'] = next((elem.text.strip() for elem in card.find_elements(By.CSS_SELECTOR, '.metadata.salary-snippet-container')), None)
                if job['salary_text'] is None:
                    job['salary_text'] = get_salary_from_description(job['description'])
                if job['salary_text'] is None:
                    job['highest_salary'] = None
                    continue
                if ' - ' in job['salary_text']:
                    highest_salary_part = job['salary_text'].split(' - ')[1]
                    # Remove everything after 'a' (e.g., 'a year', 'an hour')
                    highest_salary_clean = highest_salary_part.split(' a ')[0]
                else:
                    higehst_salary_clean = job['salary_text'].split(' a ')[0]
                # Clean and convert to float
                highest_salary_clean = highest_salary_clean.replace('$', '').replace(',', '')
                job['highest_salary'] = float(highest_salary_clean) / 1000  # Convert to thousands
                
                try:
                    job['url'] = next((elem.get_attribute('href') for elem in card.find_elements(By.CLASS_NAME, 'jcs-JobTitle')), None)
                    try:
                        parsed_url = urlparse(job['url'])
                        query_params = parse_qs(parsed_url.query)
                        job['job_id'] = query_params.get('jk', [None])[0]                            
                    except Exception as e:
                        logging.info(f"Error parsing job URL for {job.get('title', 'Unknown title')}: {e}")
                        job['job_id'] = None
                except:
                    logging.info(f"Error getting job_url for {job.get('title', 'Unknown title')}: {e}")
                    job['url'] = None
                    job['job_id'] = None
                jobs.append(job)
            
            except Exception as e:
                logging.info(f"Error processing job card: {e}")
                continue

        offset += 10
        sleep(random.uniform(2, 4))
                
    driver.quit()
    
    return jobs

def get_indeed_job_description(url):
    """Get job description from Indeed job posting using Selenium"""
    driver = setup_chrome_driver()
    try:
        #print(f"Loading job URL: {url}")
        driver.get(url)
        # Wait for job description to load (up to 10 seconds)
        try:
            wait = WebDriverWait(driver, 30)
            description_divs = driver.find_elements(By.ID, "jobDescriptionText")
            if description_divs:  # Check if we got anything back
                if isinstance(description_divs, list):  # If it's a list
                    description_div = description_divs[0]
                else:  # If it's a single WebElement
                    description_div = description_divs
                # Get the text content
                description = description_div.text.strip()
                return description
        except Exception as e:
            logging.info(f"Error finding job description: {e}")
            return None
    except Exception as e:
        logging.info(f"Error loading page: {e}")
        return None
    finally:
        driver.quit()

def get_fitness_rating(description):
    with open(resume_path, 'r') as file:
        resume_text = file.read()
    prompt = f"""Here is my resume and a job description. On a scale of 0-100, analyze how good of a fit I am for this role using the following scoring system:
Base score (0-60): Match between job requirements and my demonstrated experience
Bonus points (up to 40):

+20 points if the role heavily involves my core expertise areas (AWS infrastructure, Linux systems administration, high availability and disaster recovery, or infrastructure automation)
+10 points if the role's seniority level matches my experience (subtract points if significantly junior or if requiring different experience level)
+10 points if remote work is possible (for non-remote roles, only award these points if the location is specified as acceptable to me)

Deductions:

-15 points if it's primarily a software development role
-15 points if it's sales related or a management/vice president/director level role
-15 points if the experience requirements are significantly mismatched with my background

Please provide only a numerical score in the output, no other details or reasoning needed.

        Resume:
        {resume_text}

        Job Description:
        {description}
        """
    try:
        client = anthropic.Client(api_key=anthropic_api_key)
        message = client.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
    except Exception as e:
        logging.info(f"Error connecting to Claude for fitness score: {e}")
        return None
    try:
        fitness=int(str(message.content[0].text))
    except Exception as e:
        logging.info(f"Response for fitness score isn't only a number: {e}")
        return None
    return fitness

def get_cover_letter(company, title, description):
    with open(resume_path, 'r') as file:
        resume_text = file.read()
    prompt = f"""
Generate a cover letter for the {title} role at {company}, customized based on my resume and the job description. The letter should:

Be professional but conversational in tone
Prioritize highlighting my experience with:

AWS and cloud engineering
Migration of production services to cloud environments
Relevant technical achievements

Address any experience gaps or requirement mismatches directly but positively
Include 3-4 bullet points maximum, focusing on technical achievements that best match the role's requirements.  Use dashes instead of bullet point characters.
Keep to 20 lines or less for single-page fit, with 1.25-inch side margins for PDF compatibility
Omit generic statements about company mission/excitement
Subtly incorporate a propular 80s song lyric into the letter where it fits well, but leave out the commentary at the bottom telling me about where you put it.

Use this format, replacing each section with appropriate content:
- Current date in Month DD, YYYY format
- Complete business letter header with my name, address, recipient's name, title, company name and address
- Begin with "Dear Hiring Manager," unless a specific recipient name is provided
- Opening paragraph introducing myself and stating my interest (2-3 sentences)
- Experience paragraph with relevant bullet points (3-4 bullets maximum)
- Closing paragraph requesting an interview (1-2 sentences)
- Professional signature line starting with "Sincerely," followed by "Ryan J Alder"

Resume:
{resume_text}

Job Description:
{description}
        """
    try:
        client = anthropic.Client(api_key=anthropic_api_key)
        message = client.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
    except Exception as e:
        logging.info(f"Error connecting to Claude for cover letter: {e}")
        return None
    cover_letter=str(message.content[0].text)
    # Clean up unecessary AI text before the letter
    #start_index = cover_letter.find("Dear")
    #cover_letter = cover_letter[start_index:]
    
    # Generate docx
    doc = Document(template_path)

    for paragraph in cover_letter.split('\n\n'):
        p = doc.add_paragraph()
        p.add_run(paragraph)
        # Add extra spacing after paragraph
        paragraph_format = p.paragraph_format
        paragraph_format.space_after = Pt(12) 
    
    cover_letter_path = f"/tmp/{company} Cover Letter.docx"
    doc.save(cover_letter_path)
    return(cover_letter_path)

# Not currently used.  Works, but was using up too many anthropic api credits
def get_company_from_description(description):
    prompt = f"""Given this job description, what is the company name?  only respond with the company name.  if no company name is found, respond with "Unknown Company".
        Job Description:
        {description}
        """
    client = anthropic.Client(api_key=anthropic_api_key)
    message = client.messages.create(
        model="claude-3-sonnet-20240229",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": prompt
        }]
    )
    company=str(message.content[0].text)
    return company

# If a job post doesn't have the salary in the normal job details, see if they say it in the description
def get_salary_from_description(description):
    patterns = [
        # $X—$Y USD or $X-$Y USD format (with em dash or regular hyphen)
        r'\$([0-9,]+)(?:—|-)\$([0-9,]+)\s+USD',

        # $X-Y/yr or $X-$Y/yr format
        r'\$([0-9,]+)(?:—|-)\$?([0-9,]+)/yr',
        r'\$([0-9,]+)K(?:—|-)\$?([0-9,]+)K/yr',  # For ranges in K format

        # $X-Y/hour or /hr format
        r'\$([0-9,]+)(?:—|-)\$?([0-9,]+)/(?:hour|hr)',

        # Single values with K notation
        r'\$([0-9,]+)K/(?:yr|year)',
        r'\$([0-9,]+)/(?:hr|hour)',

        # Ranges with 'to' or '-'
        r'\$([0-9,]+)\s+to\s+\$?([0-9,]+)(?:/(?:yr|year|hr|hour))?',

        # Annual salary format
        r'annual.*?\$([0-9,]+)(?:—|-)\$?([0-9,]+)',
        r'salary.*?\$([0-9,]+)(?:—|-)\$?([0-9,]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            # Get the matched numbers
            min_sal = match.group(1).replace(',', '')
            max_sal = match.group(2).replace(',', '') if len(match.groups()) > 1 else min_sal

            # Convert K notation if present
            min_sal = float(min_sal) * 1000 if 'K' in match.group(0) else float(min_sal)
            max_sal = float(max_sal) * 1000 if 'K' in match.group(0) else float(max_sal)

            # Convert hourly to yearly if needed (assuming 2080 hours/year)
            if '/hr' in match.group(0) or '/hour' in match.group(0):
                min_sal *= 2080
                max_sal *= 2080

            # Convert to k
            max_sal *= .001

            return max_sal

    return None

def print_metrics(metrics):
    print("\r" + " " * 80, end="\r")  # Clears the line
    print(f"{metrics['seen_count']} already seen")
    print(f"{metrics['salary_count']} with no or low salary")
    print(f"{metrics['fitness_count']} with a bad fit")
    print(f"{metrics['description_count']} failed to get description")
    print(f"{metrics['valid_count']} potential jobs sent")


def search_linkedin(event=None, context=None):
    try:
        api = Linkedin(linkedin_email, linkedin_password)
    except Exception as e:
        print(f"Error connecting to LinkedIn to get search results. Details: {e}")
        return
    jobs = api.search_jobs(keywords="cloud engineer", listed_at=86400, remote=['2'])
    if len(jobs) < 1:
        print("No search results")
        return
    print("Found", len(jobs), "LinkedIn jobs")
    # Reset metric counters to zero
    global metrics
    metrics = {key: 0 for key in metrics}
    for idx, job in enumerate(jobs):
        print(f"Processing {idx}/{len(jobs)}", end="\r")
        id = int(job['trackingUrn'].split(":")[-1])
        if awsutils.dynamodb_check_if_value_exists('linkedin_jobs', 'job_id', id):
            logging.info(f"LinkedIn job {id} already seen")
            metrics["seen_count"] += 1
            continue
        url = f"https://www.linkedin.com/jobs/view/{id}"
        logging.info(url)
        try:
            job_details = get_linkedin_job_details(id)
        except Exception as e:
            logging.info(f"Error getting job details, skipping: {e}")
            continue
        description = job_details.get('description', None)
        title = job_details.get('title', None)
        salary = int(float(job_details.get('salary') or 0))
        salary_period = job_details['salary_period'] or None
        if description is None or title is None:
            logging.info("Couldn't find job description or title")
            metrics["description_count"] += 1
            continue
        if salary_period == "YEARLY":
            highest_salary = salary / 1000
        elif salary_period == "HOURLY":
            highest_salary = salary * 2080 / 1000
        else:
            highest_salary = get_salary_from_description(description)
            if highest_salary is None:
                logging.info("No salary information found")
                awsutils.dynamodb_put_item('linkedin_jobs', 'job_id', id)
                metrics["salary_count"] += 1
                continue
        if highest_salary < 180:
            logging.info("Salary below threshold")
            awsutils.dynamodb_put_item('linkedin_jobs', 'job_id', id)
            metrics["salary_count"] += 1
        else:
            fitness=get_fitness_rating(description)
            if fitness is None:
                continue
            if fitness < 80:
                logging.info("Fitness score below threshold")
                awsutils.dynamodb_put_item('linkedin_jobs', 'job_id', id)
                metrics["fitness_count"] += 1
                continue
            company = job_details.get('company', {}).get('name') or "Unknown Company"
            email_body=f"{company} - {title}\n{url}\nsalary: {highest_salary}/yr\nfitness: {fitness}"
            logging.info(email_body)
            cover_letter_path=get_cover_letter(company, title, description)
            awsutils.send_email('Python LinkedIn Search <python@twistedslinky.org>', 'ryan@twistedslinky.org', company + " - " + title, email_body, cover_letter_path)
            awsutils.dynamodb_put_item('linkedin_jobs', 'job_id', id)
            metrics["valid_count"] += 1
    print_metrics(metrics)
    return None

def search_indeed():
    url = 'https://www.indeed.com/jobs?q=aws&l=San+Francisco%2C+CA&fromage=7&salaryType=%24185%2C000&radius=100&from=searchOnDesktopSerp'
    jobs = scrape_indeed_jobs(url)
    if not jobs:
        print("No search results")
        return
    print("Found", len(jobs), "Indeed jobs")
    # Reset metric counters to zero
    global metrics
    metrics = {key: 0 for key in metrics}
    for idx, job in enumerate(jobs):
        print(f"Processing {idx}/{len(jobs)}", end="\r")
        id = job['job_id']
        if not id:
            logging.info(f"No job id: {id}")
            continue
        if awsutils.dynamodb_check_if_value_exists('indeed_jobs', 'job_id', id):
            logging.info(f"Indeed job {id} already seen")
            metrics["seen_count"] += 1
            continue
        url = job['url']
        logging.info(url)
        description = get_indeed_job_description(url)
        title = job['title']
        highest_salary = job['highest_salary']
        if description is None:
            logging.info("Couldn't find job description")
            metrics["description_count"] += 1
            continue
        if highest_salary is None:
            logging.info("No salary information found")
            awsutils.dynamodb_put_item('indeed_jobs', 'job_id', id)
            metrics["salary_count"] += 1
            continue
        if highest_salary < 180:
            logging.info("Salary below threshold")
            awsutils.dynamodb_put_item('indeed_jobs', 'job_id', id)
            metrics["salary_count"] += 1
        else:
            fitness=get_fitness_rating(description)
            if fitness < 80:
                logging.info("Fitness score below threshold")
                awsutils.dynamodb_put_item('indeed_jobs', 'job_id', id)
                metrics["fitness_count"] += 1
                continue
            company = job_details.get('company') or "Unknown Company"
            email_body=f"{company} - {title}\n{url}\nsalary: {highest_salary}/yr\nfitness: {fitness}"
            logging.info(email_body)
            cover_letter_path=get_cover_letter(company, title, description)
            awsutils.send_email('Python Indeed Search <python@twistedslinky.org>', 'ryan@twistedslinky.org', company + " - " + title, email_body, cover_letter_path)
            awsutils.dynamodb_put_item('indeed_jobs', 'job_id', id)
            metrics["valid_count"] += 1
    print_metrics(metrics)
    return None

def search_all():
    search_linkedin()
    search_indeed()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a search on job postings and email details and cover letter to myself",formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        "website",
        choices=['linkedin','indeed','all'],
        help="Website to search, or all"
    )
    args = parser.parse_args()
    search = f"search_{args.website}()"
    eval(search)
