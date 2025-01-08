import undetected_chromedriver as uc
from selenium import webdriver
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
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qs, urljoin, urlencode
from bs4 import BeautifulSoup

# Annual salary threshold
salary_threshold = 180

# Hourly threshold
hourly_threshold = 100

# Job fitness score threshold
fitness_threshold = 80

# Resume text used for fitness scoring and cover letter generation
resume_path = "Ryan J Alder Resume.txt"

# Template used for cover letter
template_path = "Ryan J Alder Header Template.docx"

metrics = {
    "seen_count": 0,
    "description_count": 0,
    "salary_count": 0,
    "fitness_count": 0,
    "valid_count": 0,
    }

load_dotenv()
anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
if not anthropic_api_key:
    raise ValueError("Anthropic API key is not set in the .env file!")

linkedin_email = os.getenv("LINKEDIN_EMAIL")
linkedin_password = os.getenv("LINKEDIN_PASSWORD")
if not linkedin_email or not linkedin_password:
    raise ValueError("LinkedIn email or password is not set in the .env file!")

logging.basicConfig(level=logging.INFO, filename='job_processing.log')
logging.getLogger("botocore").setLevel(logging.WARNING)
#warnings.filterwarnings("ignore", category=DeprecationWarning)

# Used for Indeed and Upwork scrapers
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

def scrape_upwork_jobs(url):
    """
    Scrape Upwork jobs from the search results page
    """
    driver = setup_chrome_driver()
    jobs = []
    current_url = url
    try:
        while current_url:
            driver.get(current_url)
            # Wait for job listings to load
            driver.implicitly_wait(10)

            soup = BeautifulSoup(driver.page_source, 'html.parser')
            with open("upwork.html", "w", encoding="utf-8") as file:
                file.write(driver.page_source)

            # Find all job listings
            for job_element in soup.find_all('article', class_='job-tile'):
                try:
                    # Extract job title and URL
                    title_element = job_element.find('h2', class_='job-tile-title')
                    title = title_element.get_text(strip=True) if title_element else None
                    url_element = title_element.find('a') if title_element else None
                    job_url = urljoin('https://www.upwork.com', url_element['href']) if url_element else None
                    job_id = int(re.search(r'_~(\d+)', job_url).group(1))

                    # Extract payment information
                    info_list = job_element.find('ul', class_='job-tile-info-list')
                    price_element = info_list.find('li', attrs={'data-test': 'job-type-label'}) if info_list else None
                    price_text = price_element.get_text(strip=True) if price_element else None

                    # Parse price information
                    try:
                        if 'Hourly' in price_text:
                            amounts = re.findall(r'\$(\d+(?:\.\d{2})?)', price_text)
                            if len(amounts) == 2:
                                price_type = 'hourly'
                                min_amount = float(amounts[0])
                                max_amount = float(amounts[1])
                            elif len(amounts) == 1:
                                price_type = 'hourly'
                                min_amount = float(amounts[0])
                                max_amount = float(amounts[0])
                        elif 'Fixed price' in price_text:
                            fixed_price_element = info_list.find('li', attrs={'data-test': 'is-fixed-price'})
                            if fixed_price_element:
                                amount = re.search(r'\$(\d+(?:\.\d{2})?)', fixed_price_element.get_text(strip=True))
                            if amount:
                                price_type = 'fixed'
                                min_amount = float(amount.group(1))
                                max_amount = float(amount.group(1))
                        else:
                            price_type, min_amount, max_amount = None, None, None
                    except Exception as e:
                        logging.error(f"Error parsing price: {e}")
                        price_type, min_amount, max_amount = None, None, None

                    # Extract and parse duration if available
                    duration_element = info_list.find('li', attrs={'data-test': 'duration-label'}) if info_list else None
                    duration_text = duration_element.get_text(strip=True) if duration_element else None

                    job_info = {
                        'job_id': job_id,
                        'title': title,
                        'url': job_url,
                        'payment_type': price_type,
                        'min_amount': min_amount,
                        'max_amount': max_amount,
                        'original_price_text': price_text
                    }

                    # If it's a fixed price job with duration, calculate estimated hourly rate
                    if price_type == 'fixed' and duration_text:
                        min_months, max_months, min_hours, max_hours = parse_duration_hours(duration_text)
                        if all(x is not None for x in [min_months, max_months, min_hours, max_hours]):
                            # Calculate average monthly hours
                            avg_hours_per_month = (min_hours + max_hours) / 2 * 4  # 4 weeks per month
                            avg_months = (min_months + max_months) / 2
                            total_hours = avg_hours_per_month * avg_months
                            estimated_hourly_rate = min_amount / total_hours if total_hours > 0 else None

                            job_info.update({
                                'estimated_hourly_rate': round(estimated_hourly_rate, 2) if estimated_hourly_rate else None,
                                'duration_months': f"{min_months} to {max_months}",
                                'hours_per_week': f"{min_hours} to {max_hours}"
                            })

                    jobs.append(job_info)

                except Exception as e:
                    logging.error(f"Error processing job listing: {e}")
                    continue

            # Get next page URL
            try:
                next_button = soup.find('button', {'data-test': 'next-page'})
                if not next_button or 'disabled' in next_button.attrs:
                    logging.info("No next_button")
                    break
                    
                next_page = next_button.get('data-ev-page_index')
                if not next_page:
                    print("No next_page")
                    break
                    
                # Parse the current URL and update page number
                parsed_url = urlparse(current_url)
                query_params = parse_qs(parsed_url.query)
                query_params['page'] = next_page
                new_query = urlencode(query_params, doseq=True)
                current_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}?{new_query}"
                
                # Optional: Add a slight delay between pages to be nice to the server
                sleep(2)
                
            except Exception as e:
                logging.error(f"Error getting next page URL: {e}")
                break

        return jobs

    except Exception as e:
        logging.error(f"Error scraping Upwork jobs: {e}")
        return []

def get_upwork_job_description(url):
    try:
        driver = setup_chrome_driver()
        driver.get(url)
        driver.implicitly_wait(10)  # Wait for content to load

        # Find the description
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        # First check to see if it's a private listing
        private_check = soup.find('h4', string='This job is a private listing.')
        if private_check:
            return "private"
        description_element = soup.find('p', class_='text-body-sm')

        if description_element:
            description = description_element.get_text(strip=True)
            driver.quit()
            return description

        driver.quit()
        return None

    except Exception as e:
        logging.error(f"Error extracting job description: {e}")
        driver.quit()
        return None

def parse_duration_hours(duration_text):
    """
    Parse the duration and hours per week from text like "3 to 6 months, 30+ hrs/week"
    Returns (min_months, max_months, min_hours, max_hours)
    """
    try:
        # Extract months
        months_match = re.search(r'(\d+)(?:\s+to\s+(\d+))?\s+months?', duration_text)
        if months_match:
            min_months = int(months_match.group(1))
            max_months = int(months_match.group(2)) if months_match.group(2) else min_months
        else:
            min_months = max_months = None
            
        # Extract hours
        hours_match = re.search(r'(\d+)\+?\s*hrs/week|Less than (\d+)\s*hrs/week', duration_text)
        if hours_match:
            if hours_match.group(1):  # matches "30+ hrs/week"
                min_hours = int(hours_match.group(1))
                max_hours = 40  # assume 40 as max for "X+" format
            else:  # matches "Less than X hrs/week"
                min_hours = 1
                max_hours = int(hours_match.group(2))
        else:
            min_hours = max_hours = None
            
        return min_months, max_months, min_hours, max_hours
    except Exception as e:
        logging.error(f"Error parsing duration: {e}")
        return None, None, None, None

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

+20 points if the role heavily involves my core expertise areas (AWS infrastructure, Linux systems administration, high availability and disaster recovery, or infrastructure automation). Note: Infrastructure development/programming roles do not qualify for this bonus.
+10 points if the role's seniority level matches my experience (subtract points if significantly junior or if requiring different experience level)
+10 points if remote work is possible (for non-remote roles, only award these points if the location is specified as acceptable to me)

Deductions:

-20 points if it's primarily a software engineering focus
-15 points if the role has significant software engineering requirements but includes some infrastructure work
-10 points if the role requires occasional coding but is primarily infrastructure-focused
-15 points if it's sales/solutions related or a management/vice president/director level role
-15 points if the experience requirements are significantly mismatched with my background
-10 points if the company is GEICO, Atlassian, Oracle, or NVidia

Indicators of software engineering focus include:
- Job title contains "Software Engineer" or "Developer"
- Primary responsibilities include writing new features or applications
- Multiple programming languages listed as requirements (rather than just scripting)
- Focus on APIs, services, or application development
- Requirements for computer science fundamentals (data structures, algorithms)
- Focus on building/developing infrastructure (rather than operating/maintaining it)
- Requirements for specific programming languages beyond Python/Shell
- Emphasis on protocol/software development
- Requirements for blockchain/crypto development experience

Indicators of a sales/solutions related role:
- Job title contains "sales" or "solution"

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
Generate a cover letter for the {title} role at {company}, customized based on my resume and the job description. If the company name is "Unknown Company", see if you can figure out the actual company name from the description.  The letter should:

Be professional but conversational in tone
Prioritize highlighting my experience with:

AWS and cloud engineering
Migration of production services to cloud environments
Relevant technical achievements

Address any experience gaps or requirement mismatches directly but positively
Include 3-4 bullet points maximum, focusing on technical achievements that best match the role's requirements.  Use dashes instead of bullet point characters.
Keep to 20 lines or less for single-page fit, with 1.25-inch side margins for PDF compatibility
Omit generic statements about company mission/excitement

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
        job_details = get_linkedin_job_details(id)
        if job_details is None:
            logging.info(f"Error getting job details, skipping")
            continue
        description = job_details.get('description', None)
        title = job_details.get('title', None)
        salary = int(float(job_details.get('salary') or 0))
        salary_period = job_details.get('salary_period') or None
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
        if highest_salary < salary_threshold:
            logging.info("Salary below threshold")
            awsutils.dynamodb_put_item('linkedin_jobs', 'job_id', id)
            metrics["salary_count"] += 1
        else:
            fitness=get_fitness_rating(description)
            if fitness is None:
                continue
            if fitness < fitness_threshold:
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
        print("No Indeed search results")
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
        if highest_salary < salary_threshold:
            logging.info("Salary below threshold")
            awsutils.dynamodb_put_item('indeed_jobs', 'job_id', id)
            metrics["salary_count"] += 1
        else:
            fitness=get_fitness_rating(description)
            if fitness is None:
                continue
            if fitness < fitness_threshold:
                logging.info("Fitness score below threshold")
                awsutils.dynamodb_put_item('indeed_jobs', 'job_id', id)
                metrics["fitness_count"] += 1
                continue
            company = job['company'] or "Unknown Company"
            email_body=f"{company} - {title}\n{url}\nsalary: {highest_salary}/yr\nfitness: {fitness}"
            logging.info(email_body)
            cover_letter_path=get_cover_letter(company, title, description)
            awsutils.send_email('Python Indeed Search <python@twistedslinky.org>', 'ryan@twistedslinky.org', company + " - " + title, email_body, cover_letter_path)
            awsutils.dynamodb_put_item('indeed_jobs', 'job_id', id)
            metrics["valid_count"] += 1
    print_metrics(metrics)
    return None

def search_upwork():
    url = 'https://www.upwork.com/nx/search/jobs/?contractor_tier=3&q=aws%20cloud&sort=recency'
    jobs = scrape_upwork_jobs(url)
    if not jobs:
        print("No Upwork search results")
        return
    print("Found", len(jobs), "Upwork jobs")
    # Reset metric counters to zero
    global metrics
    metrics = {key: 0 for key in metrics}
    for idx, job in enumerate(jobs):
        print(f"Processing {idx}/{len(jobs)}", end="\r")
        id = job['job_id']
        if not id:
            logging.info(f"No job id: {id}")
            continue
        if awsutils.dynamodb_check_if_value_exists('upwork_jobs', 'job_id', id):
            logging.info(f"Upwork job {id} already seen")
            metrics["seen_count"] += 1
            continue
        url = job['url']
        logging.info(url)
        description = get_upwork_job_description(url)
        title = job['title']
        highest_rate = job['max_amount']
        if description in (None, "private"):
            logging.info("Couldn't find job description, possibly private, emailing URL")
            email_body=f"Private Upwork listing:\n{url}"
            awsutils.send_email('Python Upwork Search <python@twistedslinky.org>', 'ryan@twistedslinky.org', 'Private Upwork listing', email_body)
            awsutils.dynamodb_put_item('upwork_jobs', 'job_id', id)
            metrics["description_count"] += 1
            continue
        if highest_rate is None:
            logging.info("No rate information found")
            awsutils.dynamodb_put_item('upwork_jobs', 'job_id', id)
            metrics["salary_count"] += 1
            continue
        if highest_rate < hourly_threshold:
            logging.info("Rate below threshold")
            awsutils.dynamodb_put_item('upwork_jobs', 'job_id', id)
            metrics["salary_count"] += 1
        else:
            fitness=get_fitness_rating(description)
            if fitness is None:
                continue
            if fitness < fitness_threshold:
                logging.info("Fitness score below threshold")
                awsutils.dynamodb_put_item('upwork_jobs', 'job_id', id)
                metrics["fitness_count"] += 1
                continue
            company = "Unknown Company"
            email_body=f"{company} - {title}\n{url}\nrate: {highest_rate}/hr\nfitness: {fitness}"
            logging.info(email_body)
            cover_letter_path=get_cover_letter(company, title, description)
            awsutils.send_email('Python Upwork Search <python@twistedslinky.org>', 'ryan@twistedslinky.org', company + " - " + title, email_body, cover_letter_path)
            awsutils.dynamodb_put_item('upwork_jobs', 'job_id', id)
            metrics["valid_count"] += 1
    print_metrics(metrics)
    return None

def search_all():
    search_linkedin()
    print("\n")
    search_indeed()
    print("\n")
    search_upwork()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a search on job postings and email details and cover letter to myself",formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        "website",
        choices=['linkedin','indeed','upwork', 'all'],
        help="Website to search, or all"
    )
    args = parser.parse_args()
    search = f"search_{args.website}()"
    eval(search)
