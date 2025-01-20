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
from time import sleep,time
from utils import awsutils
from utils.linkedin_api import Linkedin
import logging
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qs, urljoin, urlencode
from bs4 import BeautifulSoup

DEBUG = 1

# Annual salary threshold
salary_threshold = 180

# Hourly threshold
hourly_threshold = 80

# Job fitness score threshold
fitness_threshold = 80

# Search URLs and terms
linkedin_search_keywords = "cloud engineer"
indeed_search_url = 'https://www.indeed.com/jobs?q=aws&l=San+Francisco%2C+CA&fromage=7&salaryType=%24185%2C000&radius=100&from=searchOnDesktopSerp'
upwork_search_url = 'https://www.upwork.com/nx/search/jobs/?q=aws%20cloud&sort=recency&per_page=50'
insight_global_search_url = 'https://jobs.insightglobal.com/jobs/find_a_job/?rd=Distance&remote=true&miles=False&srch=AWS+Cloud+Engineer'
ziprecruiter_search_url = 'https://www.ziprecruiter.com/jobs-search?search=aws+cloud+engineer&location=Grass+Valley%2C+CA&refine_by_location_type=only_remote&radius=5000&days=3&refine_by_employment=employment_type%3Aall&refine_by_salary=180000&refine_by_salary_ceil=295000'

# Constants for job filtering
poor_fit_titles = [
    "software engineer",
    "software architect",
    "software develop",
    "frontend engineer",
    "backend engineer",
    "front end engineer",
    "back end engineer",
    "full stack engineer",
    "fullstack engineer",
    "protocol engineer",
    "blockchain engineer",
    "machine learning engineer",
    "ML engineer",
    "security engineer",
    "solution",
    "account executive",
    "client executive",
    "sales",
    "product manager",
    "program manager",
    "data architect",
    "data engineer",
    "data scientist",
    "marketing manager",
    "director",
    "vp of ",
    "vice president of ",
    "senior manager",
    "sr. manager"
]

poor_fit_companies = [
    "geico",
    "atlassian",
    "oracle",
    "nvidia"
]

software_role_indicatiors = [
    "angular",
    "react",
    "java ",  # space after to avoid matching javascript
    "c++",
    "rust",
    "golang",
    "front end",
    "frontend",
    "back end",
    "backend",
    "full stack",
    "fullstack",
    "ui/ux",
    "user interface",
    "mobile app",
    "android",
    "ios development"
]

# Where to send the emails
mail_to = "ryan@twistedslinky.org"

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

# Used for general web scrapers
def setup_chrome_driver():
    options = uc.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--enable-javascript')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--enable-cookies')
    
    # Add a realistic user agent
    options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
    
    driver = uc.Chrome(options=options, version_main=131)
    return driver

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

def get_fitness_rating(description, title):
    # Check title first as it's fastest
    for keyword in poor_fit_titles:
        if keyword in title.lower():
            logging.info(f"Job filtered out due to title containing '{keyword}'")
            return 0  # Return 0 for poor fit jobs
    
    # Check company name if we can identify it
    for company in poor_fit_companies:
        if company in description.lower():
            logging.info(f"Job filtered out due to company {company}")
            return 0


    # Count how many software development indicators are present
    software_indicator_count = sum(1 for indicator in software_role_indicatiors
                                 if indicator in description.lower())
    # If we find multiple software indicators, it's likely a dev role
    if software_indicator_count >= 3:
        logging.info(f"Job filtered out due to {software_indicator_count} software development indicators")
        return 0

    # If we passed the above tests, pass the description and our resume to anthropic for a fitness score
    with open(resume_path, 'r') as file:
        resume_text = file.read()
    prompt = f"""Here is my resume and a job description. On a scale of 0-100, analyze how good of a fit I am for this role using the following scoring system:

Base score (0-60): Match between job's core requirements (not "nice to have" or optional skills) and my demonstrated experience

Bonus points (up to 40):

+20 points if ALL these conditions are met:
- Role's primary responsibilities (not "nice to have") heavily involve infrastructure operations/maintenance
- Role involves AWS infrastructure, Linux systems administration, or disaster recovery as core duties
- Role is NOT classified as software engineering
- Infrastructure skills are listed in required/core skills, not just "nice to have"

+10 points if the role's seniority level matches my experience (subtract points if significantly junior or if requiring different experience level)
+10 points if role is fully remote OR is within 25 miles of Grass Valley, CA

Deductions:

-20 points if ANY of these are true:
    - Role requires building new features or applications as primary duty
    - Role focuses on product development or customer-facing features

-15 points if:
    - Role has significant software engineering requirements but includes some infrastructure work
    - Core requirements emphasize coding/development over infrastructure operations
    - Experience requirements focus on software development years over infrastructure experience

-10 points if:
    - Role requires occasional coding but is primarily infrastructure-focused
    - Infrastructure skills are only listed in "nice to have" sections

-15 points if:
    - It's sales/solutions related or a management/vice president/director level role
    - Experience requirements are significantly mismatched with my background

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

Style: Professional yet conversational, max 20 lines, 1.25" margins

Prioritize highlighting my experience with:
AWS and cloud engineering
Migration of production services to cloud environments
Relevant technical achievements

Include:
1. Brief intro (2-3 sentences)
2. Experience section with 3-4 dashes showing achievements matching role
3. Short closing requesting interview
4. "Sincerely," + "Ryan J Alder"

Skip:
- Generic company praise
- Mission statements
- Non-technical details

Address any experience gaps or requirement mismatches directly but positively

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
    try:
        driver = setup_chrome_driver()
    except Exception as e:
        print(f"Error loading Chrome: {e}")
        return None
    paginated_url = f"{url}&start={offset}"
    logging.info(f"Loading URL: {paginated_url}")
    driver.get(paginated_url)

    # Wait for Turnstile iframe
    wait = WebDriverWait(driver, 10)
    with open("indeed_last_html.html", "w", encoding="utf-8") as file:
        file.write(driver.page_source)
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
        if offset > 0:
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
                    job['highest_salary'] = None
                else:
                    # If there is a salary range, it's probably separated by '-'
                    if ' - ' in job['salary_text']:
                        # So grab the part after the dash (the highest value)
                        salary_part = job['salary_text'].split(' - ')[1]
                        # Split between salary value and 'a year' or 'an hour'
                        salary_parts = re.split(' a | an ', salary_part)
                    else:
                        salary_parts = re.split(' a | an ', job['salary_text'])
                    # Clean and convert to float
                    salary_clean = salary_parts[0]
                    # If 'hour' exists in the salary, flag it as hourly to be converted to salary
                    is_hourly = len(salary_parts) > 1 and 'hour' in salary_parts[1]
                    salary_clean = salary_clean.replace('$', '').replace(',', '')
                    salary_value = float(salary_clean)
                    if is_hourly:
                        salary_value = salary_value * 2080
                    job['highest_salary'] = salary_value / 1000  # Convert to thousands
                
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
        # Sanity stop, sometimes indeed keeps giving the same results on every page
        if offset >= 200:
            break
        sleep(random.uniform(2, 4))
                
    driver.quit()
    
    return jobs

def get_indeed_job_description(url):
    """Get job description from Indeed job posting using Selenium"""
    try:
        driver = setup_chrome_driver()
    except Exception as e:
        print(f"Error loading Chrome: {e}")
        return None
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

def scrape_upwork_jobs(url):
    """
    Scrape Upwork jobs from the search results page
    """
    try:
        driver = setup_chrome_driver()
    except Exception as e:
        print(f"Error loading Chrome: {e}")
        return None
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
                        #'min_amount': min_amount,
                        'max_amount': max_amount,
                        #'original_price_text': price_text
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

def scrape_insight_global(base_url):
    try:
        driver = setup_chrome_driver()
    except Exception as e:
        print(f"Error loading Chrome: {e}")
        return None
    jobs = []
    current_page = 1

    try:
        while True:
            # Construct the URL for the current page
            page_url = base_url.replace('/find_a_job/', f'/find_a_job/{current_page}/')
 
            # Navigate to the page
            logging.info(f"Scraping insight global page {current_page}: {page_url}")
            driver.get(page_url)
            with open("insight_last_html.html", "w", encoding="utf-8") as file:
                file.write(driver.page_source)

            # Wait for job listings to be present
            wait = WebDriverWait(driver, 10)
            try:
                # First check if we have valid pagination
                pagination = wait.until(EC.presence_of_element_located(
                    (By.CLASS_NAME, "paging-container")
                ))
                
                # Check if we're beyond the last page by looking for "1 - 10 of X" text
                result_text = pagination.find_element(By.CLASS_NAME, "h").text
                if " of " in result_text:
                    match = re.search(r'of (\d+)', result_text)
                    if match:
                        total_jobs = int(match.group(1))
                        # If we've processed more than total jobs, we're done
                        if len(jobs) >= total_jobs:
                            logging.info(f"Reached end of listings (processed {len(jobs)} of {total_jobs} jobs)")
                            break
                
                # Get job listings
                job_listings = driver.find_elements(By.CLASS_NAME, "result")
                if not job_listings:
                    logging.info("No job listings found on page")
                    break 
            except:
                logging.info(f"Problem getting content for page: {current_page}")
                break

            # Process each job listing
            for listing in job_listings:
                try:
                    # Get title and URL
                    title_elem = listing.find_element(By.CLASS_NAME, "job-title").find_element(By.TAG_NAME, "a")
                    title = title_elem.text.strip()
                    url = title_elem.get_attribute("href")
                    
                    # Extract job ID from URL using regex
                    job_id_match = re.search(r'job-(\d+)', url)
                    job_id = job_id_match.group(1) if job_id_match else None
                    
                    # Get job info section
                    job_info = listing.find_element(By.CLASS_NAME, "job-info")
                    info_text = job_info.text
                    info_parts = [p.strip() for p in info_text.split("|")]
                    
                    # Extract and convert compensation
                    compensation = info_parts[3].strip() if len(info_parts) > 3 else ""
                    hourly_rate_match = re.search(r'\$(\d+)\s*-\s*\$?(\d+)', compensation)
                    min_rate = float(hourly_rate_match.group(1)) if hourly_rate_match else None
                    max_rate = float(hourly_rate_match.group(2)) if hourly_rate_match else None
                    salary = max_rate * 2080 / 1000 if max_rate else None
                    
                    # Get company name if available
                    company = "Unknown Company"  # Default since all jobs are from Insight Global
                    
                    jobs.append({
                        'job_id': job_id,
                        'url': url,
                        'title': title,
                        'company': company,
                        'salary': salary
                    })
                    
                except Exception as e:
                    logging.info(f"Error processing job listing: {str(e)}")
                    continue
            
            # Check if there's a next page by looking for the navigation
            try:
                # Look for the active page number and see if there's a next page link
                pagination = driver.find_element(By.CLASS_NAME, "paging-container")
                active_page = pagination.find_element(By.CLASS_NAME, "active")
                next_page = active_page.find_element(By.XPATH, "following-sibling::li[1]/a")
                
                if not next_page.get_attribute("href"):
                    logging.info("No link to next page found")
                    break
                    
                current_page += 1
            except:
                logging.info("No more pages available")
                break
                
    except Exception as e:
        print(f"An error occurred: {str(e)}")
    
    finally:
        driver.quit()
    
    return jobs

def get_insight_global_job_description(url):
    try:
        driver = setup_chrome_driver()
    except Exception as e:
        print(f"Error loading Chrome: {e}")
        return None
    description = None
    
    try:
        driver.get(url)
        
        # Get all description divs
        wait = WebDriverWait(driver, 10)
        desc_sections = wait.until(EC.presence_of_all_elements_located(
            (By.CLASS_NAME, "detailpage-desc")
        ))
        
        # Combine all description sections into one string
        description_parts = []
        for section in desc_sections:
            text = section.text.strip()
            if text:  # Only add non-empty sections
                description_parts.append(text)
        
        description = "\n\n".join(description_parts)
                
    except Exception as e:
        print(f"Error scraping job description: {str(e)}")
        
    finally:
        driver.quit()
        
    return description

def scrape_ziprecruiter(url):
    jobs = []
    current_page = 1
    try:
        driver = setup_chrome_driver()
    except Exception as e:
        print(f"Error loading Chrome: {e}")
        return None
    logging.info(f"Scraping page {current_page}...")

    # Modify URL for pagination
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    query_params['page'] = [str(current_page)]
    new_query = urlencode(query_params, doseq=True)
    paginated_url = parsed_url._replace(query=new_query).geturl()
    logging.info(paginated_url)

    # Load the page and look for a cloudflare challenge
    driver.get(paginated_url)
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
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "job_result_two_pane")))

    except Exception as e:
        logging.info(f"Error handling verification: {e}")
    try:
        while True:
            logging.info(f"Scraping page {current_page}...")

            # Modify URL for pagination
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            query_params['page'] = [str(current_page)]
            new_query = urlencode(query_params, doseq=True)
            paginated_url = parsed_url._replace(query=new_query).geturl()
            logging.info(paginated_url)

            # Load the page
            driver.get(paginated_url)
            wait = WebDriverWait(driver, 10)
            with open("ziprecruiter_last_html.html", "w", encoding="utf-8") as file:
                file.write(driver.page_source)

            # Get page source after JavaScript execution
            html = driver.page_source
            soup = BeautifulSoup(html, 'html.parser')

            # Find all job result containers
            job_containers = soup.find_all("div", class_="job_result_two_pane")
            logging.info(f"Found {len(job_containers)} jobs")

            # If no jobs found, we've reached the end
            if not job_containers:
                break

            for job in job_containers:
                try:
                    # Find job link which contains title and URL
                    job_link = job.find("h2").find("a")
                    job_title = job_link.get_text(strip=True).replace("NEW!", "").strip()
                    job_url = job_link.get("href")
                    logging.info(job_url)
                    
                    # Find company name
                    company_elem = job.find("a", attrs={"data-testid": "job-card-company"})
                    company = company_elem.get_text(strip=True) if company_elem else None

                    # Zip Recruiter is annoying and doesn't show the unique job id in the search results, so we'll fake one with company+title
                    job_id = f"{company}_{job_title}".lower().strip()

                    # Find salary info
                    salary_elem = job.find("div", class_="flex items-center")
                    salary_text = salary_elem.get_text(strip=True) if salary_elem else None

                    if salary_text is None:
                        salary = None
                    else:
                        if ' - ' in salary_text:
                            # Grab the part after the dash (the highest value)
                            salary_part = salary_text.split(' - ')[1]
                            # Split between salary value and 'a year' or 'an hour'
                            salary_parts = re.split(' / ', salary_part)
                        else:
                            salary_parts = re.split(' / ', salary_text)
                        # Clean and convert to float
                        salary_clean = salary_parts[0].replace('K', '')
                        # If 'hr' exists in the salary, flag it as hourly to be converted to salary
                        is_hourly = len(salary_parts) > 1 and 'hr' in salary_parts[1]
                        salary_clean = salary_clean.replace('$', '').replace(',', '')
                        salary_value = float(salary_clean)
                        if is_hourly:
                            salary_value = salary_value * 2080 / 1000
                        salary = salary_value

                    logging.info(f"{job_id}\n{company} - {job_title} - {salary}")

                    # Add job details to list
                    jobs.append({
                        "job_id": job_id,
                        "url": job_url,
                        "title": job_title,
                        "company": company,
                        "salary": salary
                    })

                except Exception as e:
                    logging.info(f"Error parsing job listing: {str(e)}")
                    continue

            # Check for next page button
            next_button = soup.find("a", title="Next Page")
            if not next_button:
                break

            current_page += 1
            if current_page > 50:
                break

    except Exception as e:
        logging.info(f"Error scraping ZipRecruiter: {str(e)}")

    finally:
        driver.quit()

    return jobs

def get_ziprecruiter_job_description(url):
    try:
        driver = setup_chrome_driver()
    except Exception as e:
        print(f"Error loading Chrome: {e}")
        return None

    try:
        # Load the page
        driver.get(url)
        sleep(5)  # Wait for dynamic content to load

        # Get page source after JavaScript execution
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        # Find job description div
        job_desc_div = soup.find('div', class_='job_description')
        if not job_desc_div:
            return None

        # Get the text content of the description
        description = ""

        # Get all text elements within the description div
        desc_elements = job_desc_div.find_all(string=True, recursive=True)
        for element in desc_elements:
            text = element.strip()
            if text:  # Only add non-empty strings
                description += text + "\n"

        return description.strip()

    except Exception as e:
        print(f"Error scraping job description: {str(e)}")
        return None

    finally:
        driver.quit()

# For Upwork jobs
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

# If a job post doesn't have the salary in the normal job details, see if they say it in the description
def get_salary_from_description(description):
    patterns = [
       # Specific formats first
        r'\$([0-9,]+)K(?:—|-)\$?([0-9,]+)K/yr',  # $120K-$150K/yr
        r'\$([0-9,]+)K/(?:yr|year)',  # $120K/yr
        r'\$(\d+)[-—](\d+),\d{3}/yr',  # $120-150,000/yr
    
        # Hourly patterns
        r'\$([0-9,.]+)(?:\s+USD)?(?:\s+per\s+|\/)(?:hour|hr)',  # $20.00 USD per hour, $48/hr
    
        # Special cases
        r'(?:up to)\s*\$([0-9,]+)(?:\s+per\s+(?:month|year|hr|hour))?',  # up to $X per month/year/hour
    
        # Standard ranges
        r'\$([0-9,]+)(?:,\d{3})*\s*-\s*\$([0-9,]+)(?:,\d{3})*',  # $120,000 - $150,000
        r'\$([0-9,]+)(?:—|-)\$([0-9,]+)\s+USD',  # $120,000-$150,000 USD
        r'\$([0-9,]+)(?:—|-)\$?([0-9,]+)/yr',  # $120,000-$150,000/yr
        r'\$([0-9,]+)\s+to\s+\$?([0-9,]+)(?:/(?:yr|year|hr|hour))?',  # $120,000 to $150,000/yr
    
        # Keyword-based patterns last
        r'annual.*?\$([0-9,]+)(?:—|-)\$?([0-9,]+)',  # annual... $120,000-$150,000
        r'salary.*?\$([0-9,]+)(?:—|-)\$?([0-9,]+)',  # salary... $120,000-$150,000
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
            if '/hr' in match.group(0) or '/hour' in match.group(0) or 'per hour' in match.group(0):
                min_sal *= 2080
                max_sal *= 2080

            # Convert monthly to yearly if needed (multiply by 12 months)
            elif 'per month' in match.group(0) or '/month' in match.group(0):
                min_sal *= 12
                max_sal *= 12

            # Convert to k
            max_sal *= .001

            return max_sal

    return None

def print_metrics(metrics, progress=None):
    if progress:
        print("\r" + " " * 80, end="\r")  # Clears the progress line
    print(f"{metrics['seen_count']} already seen")
    print(f"{metrics['salary_count']} with no or low salary")
    print(f"{metrics['fitness_count']} with a bad fit")
    print(f"{metrics['description_count']} failed to get description")
    print(f"{metrics['valid_count']} potential jobs sent")

def search_linkedin(progress=None):
    try:
        api = Linkedin(linkedin_email, linkedin_password)
    except Exception as e:
        print(f"Error connecting to LinkedIn to get search results. Details: {e}")
        return
    jobs = api.search_jobs(keywords=linkedin_search_keywords, listed_at=86400, remote=['2'])
    if len(jobs) < 1:
        print("No search results")
        return
    print("Found", len(jobs), "LinkedIn jobs")
    # Reset metric counters to zero
    global metrics
    metrics = {key: 0 for key in metrics}
    for idx, job in enumerate(jobs):
        if progress:
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
            logging.info(f"Salary below threshold: {highest_salary}")
            awsutils.dynamodb_put_item('linkedin_jobs', 'job_id', id)
            metrics["salary_count"] += 1
        else:
            fitness=get_fitness_rating(description,title)
            if fitness is None:
                continue
            if fitness < fitness_threshold:
                logging.info(f"Fitness score below threshold: {fitness}")
                awsutils.dynamodb_put_item('linkedin_jobs', 'job_id', id)
                metrics["fitness_count"] += 1
                continue
            company = job_details.get('company', {}).get('name') or get_company_from_description(description)
            email_body=f"{company} - {title}\n{url}\nsalary: {highest_salary}/yr\nfitness: {fitness}"
            logging.info(email_body)
            cover_letter_path=get_cover_letter(company, title, description)
            awsutils.send_email('Python LinkedIn Search <python@twistedslinky.org>', mail_to, company + " - " + title, email_body, cover_letter_path)
            awsutils.dynamodb_put_item('linkedin_jobs', 'job_id', id)
            metrics["valid_count"] += 1
    print_metrics(metrics, progress)
    return None

def search_indeed(progress=None):
    jobs = scrape_indeed_jobs(indeed_search_url)
    if not jobs:
        print("No Indeed search results")
        return
    print("Found", len(jobs), "Indeed jobs")
    # Reset metric counters to zero
    global metrics
    metrics = {key: 0 for key in metrics}
    for idx, job in enumerate(jobs):
        if progress:
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
        if description is None:
            logging.info("Couldn't find job description")
            metrics["description_count"] += 1
            continue
        title = job['title']
        highest_salary = job['highest_salary'] or get_salary_from_description(description)
        if highest_salary is None:
            logging.info("No salary information found")
            awsutils.dynamodb_put_item('indeed_jobs', 'job_id', id)
            metrics["salary_count"] += 1
            continue
        if highest_salary < salary_threshold:
            logging.info(f"Salary below threshold: {highest_salary}")
            awsutils.dynamodb_put_item('indeed_jobs', 'job_id', id)
            metrics["salary_count"] += 1
        else:
            fitness=get_fitness_rating(description,title)
            if fitness is None:
                continue
            if fitness < fitness_threshold:
                logging.info(f"Fitness score below threshold: {fitness}")
                awsutils.dynamodb_put_item('indeed_jobs', 'job_id', id)
                metrics["fitness_count"] += 1
                continue
            company = job['company'] or get_company_from_description(description)
            email_body=f"{company} - {title}\n{url}\nsalary: {highest_salary}/yr\nfitness: {fitness}"
            logging.info(email_body)
            cover_letter_path=get_cover_letter(company, title, description)
            awsutils.send_email('Python Indeed Search <python@twistedslinky.org>', mail_to, company + " - " + title, email_body, cover_letter_path)
            awsutils.dynamodb_put_item('indeed_jobs', 'job_id', id)
            metrics["valid_count"] += 1
    print_metrics(metrics, progress)
    return None

def search_upwork(progress=None):
    jobs = scrape_upwork_jobs(upwork_search_url)
    if not jobs:
        print("No Upwork search results")
        return
    print("Found", len(jobs), "Upwork jobs")
    # Reset metric counters to zero
    global metrics
    metrics = {key: 0 for key in metrics}
    for idx, job in enumerate(jobs):
        if progress:
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
            awsutils.send_email('Python Upwork Search <python@twistedslinky.org>', mail_to, 'Private Upwork listing', email_body)
            awsutils.dynamodb_put_item('upwork_jobs', 'job_id', id)
            metrics["description_count"] += 1
            continue
        if highest_rate is None:
            logging.info("No rate information found")
            awsutils.dynamodb_put_item('upwork_jobs', 'job_id', id)
            metrics["salary_count"] += 1
            continue
        if highest_rate < hourly_threshold:
            logging.info(f"Rate below threshold: {highest_rate}")
            awsutils.dynamodb_put_item('upwork_jobs', 'job_id', id)
            metrics["salary_count"] += 1
        else:
            fitness=get_fitness_rating(description,title)
            if fitness is None:
                continue
            if fitness < fitness_threshold:
                logging.info(f"Fitness score below threshold: {fitness}")
                awsutils.dynamodb_put_item('upwork_jobs', 'job_id', id)
                metrics["fitness_count"] += 1
                continue
            company = get_company_from_description(description) or "Unknown Company"
            email_body=f"{company} - {title}\n{url}\nrate: {highest_rate}/hr\nfitness: {fitness}"
            logging.info(email_body)
            cover_letter_path=get_cover_letter(company, title, description)
            awsutils.send_email('Python Upwork Search <python@twistedslinky.org>', 'ryan@twistedslinky.org', company + " - " + title, email_body, cover_letter_path)
            awsutils.dynamodb_put_item('upwork_jobs', 'job_id', id)
            metrics["valid_count"] += 1
    print_metrics(metrics, progress)
    return None

def search_insight(progress=None):
    jobs = scrape_insight_global(insight_global_search_url)
    if not jobs:
        print("No Insight Global search results")
        return
    print("Found", len(jobs), "Insight Global jobs")
    # Reset metric counters to zero
    global metrics
    metrics = {key: 0 for key in metrics}
    for idx, job in enumerate(jobs):
        if progress:
            print(f"Processing {idx}/{len(jobs)}", end="\r")
        id = job['job_id']
        if not id:
            logging.info(f"No job id: {id}")
            continue
        if awsutils.dynamodb_check_if_value_exists('insight_global_jobs', 'job_id', id):
            logging.info(f"Insight Global job {id} already seen")
            metrics["seen_count"] += 1
            continue
        url = job['url']
        logging.info(url)
        title = job['title']
        highest_salary = job['salary']
        description = get_insight_global_job_description(url)
        if description is None:
            logging.info("Couldn't find job description")
            metrics["description_count"] += 1
            continue
        if highest_salary is None:
            logging.info("No salary information found")
            awsutils.dynamodb_put_item('insight_global_jobs', 'job_id', id)
            metrics["salary_count"] += 1
            continue
        if highest_salary < salary_threshold:
            logging.info(f"Salary below threshold: {highest_salary}")
            awsutils.dynamodb_put_item('insight_global_jobs', 'job_id', id)
            metrics["salary_count"] += 1
        else:
            fitness=get_fitness_rating(description,title)
            if fitness is None:
                continue
            if fitness < fitness_threshold:
                logging.info(f"Fitness score below threshold: {fitness}")
                awsutils.dynamodb_put_item('insight_global_jobs', 'job_id', id)
                metrics["fitness_count"] += 1
                continue
            company = job['company'] or get_company_from_description(description)
            email_body=f"{company} - {title}\n{url}\nsalary: {highest_salary}/yr\nfitness: {fitness}"
            logging.info(email_body)
            cover_letter_path=get_cover_letter(company, title, description)
            awsutils.send_email('Python Insight Global Search <python@twistedslinky.org>', mail_to, company + " - " + title, email_body, cover_letter_path)
            awsutils.dynamodb_put_item('insight_global_jobs', 'job_id', id)
            metrics["valid_count"] += 1
    print_metrics(metrics, progress)
    return None

def search_ziprecruiter(progress=None):
    jobs = scrape_ziprecruiter(ziprecruiter_search_url)
    if not jobs:
        print("No Zip Recruiter search results")
        return
    print("Found", len(jobs), "Zip Recruiter jobs")
    # Reset metric counters to zero
    global metrics
    metrics = {key: 0 for key in metrics}
    for idx, job in enumerate(jobs):
        if progress:
            print(f"Processing {idx}/{len(jobs)}", end="\r")
        id = job['job_id']
        if not id:
            logging.info(f"No job id: {id}")
            continue
        if awsutils.dynamodb_check_if_value_exists('ziprecruiter_jobs', 'job_id', id):
            logging.info(f"Zip Recruiter job {id} already seen")
            metrics["seen_count"] += 1
            continue
        url = job['url']
        logging.info(url)
        title = job['title']
        description = get_ziprecruiter_job_description(url)
        highest_salary = job['salary'] or get_salary_from_description(description)
        if description is None:
            logging.info("Couldn't find job description")
            metrics["description_count"] += 1
            continue
        if highest_salary is None:
            logging.info("No salary information found")
            awsutils.dynamodb_put_item('ziprecruiter_jobs', 'job_id', id)
            metrics["salary_count"] += 1
            continue
        if highest_salary < salary_threshold:
            logging.info(f"Salary below threshold: {highest_salary}")
            awsutils.dynamodb_put_item('ziprecruiter_jobs', 'job_id', id)
            metrics["salary_count"] += 1
        else:
            fitness=get_fitness_rating(description,title)
            if fitness is None:
                continue
            if fitness < fitness_threshold:
                logging.info(f"Fitness score below threshold: {fitness}")
                awsutils.dynamodb_put_item('ziprecruiter_jobs', 'job_id', id)
                metrics["fitness_count"] += 1
                continue
            company = job['company'] or get_company_from_description(description)
            email_body=f"{company} - {title}\n{url}\nsalary: {highest_salary}/yr\nfitness: {fitness}"
            logging.info(email_body)
            cover_letter_path=get_cover_letter(company, title, description)
            awsutils.send_email('Python Zip Recruiter Search <python@twistedslinky.org>', mail_to, company + " - " + title, email_body, cover_letter_path)
            awsutils.dynamodb_put_item('ziprecruiter_jobs', 'job_id', id)
            metrics["valid_count"] += 1
    print_metrics(metrics, progress)
    return None

if __name__ == "__main__":
    start_time = time()
    parser = argparse.ArgumentParser(description="Run a search on job postings and email details and cover letter to myself",formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        "website",
        choices=['linkedin','indeed','upwork','insight','ziprecruiter', 'all'],
        help="Website to search, or all"
    )
    parser.add_argument(
        "--cron",
        action="store_true",
        help="If set, suppress progress output for cron jobs"
    )
    args = parser.parse_args()
    # Determine if progress output should be included
    progress = not args.cron
    if args.website == "all":
        search_linkedin(progress)
        print("\n")
        search_indeed(progress)
        print("\n")
        search_upwork(progress)
        print("\n")
        search_insight(progress)
    else:
        search = f"search_{args.website}({progress})"        
        eval(search)
    end_time = time()
    elapsed_time = end_time - start_time
    print(f"\nScript completed in {elapsed_time:.2f} seconds")
