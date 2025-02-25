import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException,TimeoutException
from docx import Document
from docx.shared import Pt
import re
import os
import resource
import anthropic
import argparse
import random
from time import sleep,time
from utils import awsutils
from utils.linkedin_api import Linkedin
import logging
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qs, urljoin, urlencode
#from bs4 import BeautifulSoup
from typing import Optional
from dataclasses import dataclass, field

# Modify ulimits because some sites return a lot of jobs and we run out of file descriptors
soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE, (1024, hard))

# Annual salary threshold
salary_threshold = 180

# Hourly threshold
hourly_threshold = 80

# Job fitness score threshold
fitness_threshold = 75

# Search URLs and terms
linkedin_search_keywords = "cloud engineer"
indeed_search_url = 'https://www.indeed.com/jobs?q=aws&l=San+Francisco%2C+CA&fromage=7&salaryType=%24185%2C000&radius=100&from=searchOnDesktopSerp'
upwork_search_url = 'https://www.upwork.com/nx/search/jobs/?q=aws%20cloud&sort=recency&per_page=50&&user_location_match=1'
insight_global_search_url = 'https://jobs.insightglobal.com/jobs/find_a_job/?rd=Distance&remote=true&miles=False&srch=AWS+Cloud+Engineer'
ziprecruiter_search_url = 'https://www.ziprecruiter.com/jobs-search?search=aws+cloud+engineer&location=Grass+Valley%2C+CA&refine_by_location_type=only_remote&radius=5000&days=7&refine_by_employment=employment_type%3Aall&refine_by_salary=180000&refine_by_salary_ceil=295000'
cybercoders_search_url = 'https://www.cybercoders.com/search/cloud?days=7&locationtype=3&sortType=relevance'
dice_search_url = 'https://www.dice.com/jobs?q=aws%20cloud%20engineer&countryCode=US&radius=30&radiusUnit=mi&pageSize=100&filters.postedDate=SEVEN&filters.workplaceTypes=Remote&language=en'
weworkremotely_search_url = 'https://weworkremotely.com/remote-jobs/search?search_uuid=&term=&sort=past_week&categories%5B%5D=6&region%5B%5D=1'
monster_search_url = 'https://www.monster.com/jobs/search?q=Aws+Cloud&where=San+Francisco%2C+CA&page=1&recency=last+week&rd=100'
kforce_search_url = 'https://www.kforce.com/find-work/search-jobs/#/?t=cloud'

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
    "vice president ",
    "senior manager",
    "sr. manager"
]

poor_fit_companies = [
    "geico",
    "atlassian",
    "oracle",
    "nvidia",
    "apple",
    "microsoft",
    "peraton" # Always requires active security clearance
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

@dataclass
class Job:
    id: str
    url: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    description: Optional[str] = None
    salary_text: Optional[str] = None
    highest_salary: Optional[float] = None
    fitness: Optional[float] = None
    source: Optional[str] = None  # e.g., "LinkedIn", "Indeed"

# Used for general web scrapers
def setup_chrome_driver():
    options = uc.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--enable-javascript')
    options.add_argument('--disable-blink-features=AutomationControlled')  # Hide automation
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--enable-cookies')
    # Add some randomness to appear more human
    import random
    random_width = random.randint(1200, 1600)
    random_height = random.randint(800, 1000)
    options.add_argument(f'--window-size={random_width},{random_height}')
    # To use my existing logged in sessions
    options.add_argument('--user-data-dir=/Users/link/Library/Application Support/Google/Chrome')
    options.add_argument('--profile-directory=Default')
    # Add a realistic user agent
    options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
    options.add_argument('--lang=en-US,en;q=0.9')
    options.add_argument('--enable-cookies')
    driver = uc.Chrome(options=options, version_main=133)
    # Execute stealth JS
    driver.execute_script("""
    Object.defineProperty(navigator, 'webdriver', {
      get: () => undefined
    });
    """)
    return driver

def load_page(url, skip_cloudflare_detection=False, load_more=False):
    try:
        driver = setup_chrome_driver()
    except Exception as e:
        print(f"Error loading Chrome: {e}")
        return None
    driver.get(url)
    wait = WebDriverWait(driver, 10)
    domain = urlparse(url).netloc.replace('www.', '')
    if skip_cloudflare_detection == False:
        try:
            logging.info("Checking for Cloudflare verification")
            # First, try to detect if we're on a verification page
            verification_indicators = [
                "Just a moment...",
                "Additional Verification Required", 
                "challenge-form",
                "/cdn-cgi/challenge-platform"
            ]
            
            is_verification_page = any(indicator in driver.page_source for indicator in verification_indicators)

            if is_verification_page:
                logging.info("Found a verification indicator")
                '''
                # Try the sign-in bypass first
                try:
                    # Look for any sign-in link on the page
                    sign_in_selectors = [
                        ".link-signin a", 
                        ".link-signin--mobile",
                        "a[href*='login']",
                        "a[href*='signin']",
                        "a.sign-in-link"
                    ]
                    sign_in_clicked = False
                    for selector in sign_in_selectors:
                        if sign_in_clicked:
                            break
        
                        signin_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        if signin_elements:
                            try:
                                logging.info(f"Found sign-in element with selector: {selector}. Clicking it...")
                                driver.execute_script("arguments[0].click();", signin_elements[0])
                                sign_in_clicked = True
            
                                # Wait for page to change after login
                                sleep(2)
            
                                # Check if verification page is gone
                                if not any(indicator in driver.page_source for indicator in verification_indicators):
                                    logging.info("Successfully bypassed verification using sign-in")
                                    driver.get(url)
                                    break
                                else:
                                    # If we're still on verification page, this click didn't work
                                    sign_in_clicked = False
                            except Exception as e:  # ADD THIS EXCEPT BLOCK
                                logging.info(f"Error clicking sign-in element: {e}")
                                sign_in_clicked = False
                    
                except Exception as e:
                    logging.info(f"Sign-in bypass failed: {e}")
                '''
                # If sign-in bypass didn't work, try the traditional Cloudflare handling
                if any(indicator in driver.page_source for indicator in verification_indicators):
                    logging.info("Found verification indicator on the page")
                    # Look for multiple possible selectors that might indicate the challenge
                    try:
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
                        logging.info(f"Error handling verification iframe: {e}")
                        driver.switch_to.default_content()
            
        except Exception as e:
            logging.info(f"Error handling verification or none found: {e}")

    if load_more:
        try:
            # Scroll down and load more if needed
            while True:
                last_height = driver.execute_script("return document.body.scrollHeight")
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                sleep(1)

                # Try clicking "Load More" buttons first
                button_clicked = False
                load_more_buttons = [
                        (By.CLASS_NAME, "btn-line-darkCerulean"),  # Kforce button
                        (By.ID, "job-search-load-more")  # Monster button
                        ]
                for by, value in load_more_buttons:
                    try:
                        load_more_button = wait.until(
                                EC.element_to_be_clickable((by, value))
                                )
                        driver.execute_script("arguments[0].scrollIntoView();", load_more_button)
                        load_more_button.click()
                        sleep(1)

                        # Scroll again after clicking the button to trigger dynamic loading
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                        sleep(1)

                        button_clicked = True
                        break  # If one button is clicked, don't check the other in this loop iteration
                    except (TimeoutException, NoSuchElementException):
                        continue  # Try the next button if this one isn't found

                new_height = driver.execute_script("return document.body.scrollHeight")

                # Only exit if height hasn't changed AND no button was clicked
                if new_height == last_height and not button_clicked:
                    break

                logging.info(f"Scrolling from {last_height} to {new_height}")
        except:
            logging.info("Couldn't find load more jbuttons")
    try:
        job_selectors = [
                ".job_seen_beacon",
                "article.job-tile",
                ".paging-container",
                "div.job_result_two_pane",
                ".result-box",
                "dhi-search-card",
                "section.jobs article ul",
                ".job-details-description",
                "article[data-testid='JobCard']",
                "#__NEXT_DATA__",
                "ul.data-jobs li",
                ".data-job-desc",
                "#react-job-wrapper",
                "div.page-meta",
                "h1.col-xs-12.col-sm-8",
                ".page-box-shadow.fake-tab-content",
                ".result",
                ".detailpage-desc",
                ".job_result_two_pane",
                "div.job_description",
                "article.job-tile",
                "div[data-test='job-description']",
                ".visitor-page-container"
                ]

        wait.until(
                EC.presence_of_element_located((
                    By.CSS_SELECTOR, ", ".join(job_selectors)
                    ))
                )

    except Exception:
        logging.info("Page loaded but job info not found!")

    if debug:
        with open(f"{domain}_debug.html", "w", encoding="utf-8") as file:
            file.write(driver.page_source)
    return driver

def get_company_from_description(description):
    prompt = f"""Given this job description, what is the company name?  only respond with the company name.  if no company name is found, respond with "Unknown Company".
        Job Description:
            {description}
        """
    client = anthropic.Client(api_key=anthropic_api_key)
    message = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": prompt
                }]
            )
    company=str(message.content[0].text)
    return company

def get_fitness_rating(description, company, title):
    # Check title first as it's fastest
    for keyword in poor_fit_titles:
        if keyword in title.lower():
            logging.info(f"Job filtered out due to title containing '{keyword}'")
            return 0  # Return 0 for poor fit jobs

    # Check company name if we can identify it
    for poor_company in poor_fit_companies:
        if poor_company in company.lower():
            logging.info(f"Job filtered out due to company {poor_company}")
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
                model="claude-3-5-haiku-20241022",
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
                model="claude-3-5-haiku-20241022",
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
        run = p.add_run(paragraph)
        run.font.name = 'Calibri'
        run.font.size = Pt(11)
        # Add extra spacing after paragraph
        paragraph_format = p.paragraph_format
        paragraph_format.space_after = Pt(12) 

    cover_letter_path = f"/tmp/{company.replace('/', '')} Cover Letter.docx"
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

def scrape_indeed_jobs(base_url):
    jobs = []
    offset = 0

    try:
        while True:
            # Construct the paginated URL
            paginated_url = f"{base_url}&start={offset}"
            logging.info(f"Scraping Indeed page with offset {offset}: {paginated_url}")

            driver = load_page(paginated_url)
            if not driver:
                logging.info("Failed to load page. Skipping...")
                break

            # Find job cards
            try:
                job_cards = driver.find_elements(By.CLASS_NAME, "job_seen_beacon")
                if not job_cards:
                    logging.info("No job listings found, stopping pagination.")
                    break
                logging.info(f"Found {len(job_cards)} Indeed jobs")
            except Exception as e:
                logging.info(f"Error finding job cards: {e}")
                break

            # Process each job listing
            for card in job_cards:
                try:
                    job = {}

                    job['title'] = next((elem.text.strip() for elem in card.find_elements(By.CSS_SELECTOR, 'span[id^="jobTitle"]')), None)
                    job['company'] = next((elem.text.strip() for elem in card.find_elements(By.CSS_SELECTOR, '[data-testid="company-name"]')), None)
                    job['description'] = next((elem.text.strip() for elem in card.find_elements(By.CSS_SELECTOR, '[data-testid="jobsnippet_footer"]')), None)

                    # Salary processing
                    job['salary_text'] = next((elem.text.strip() for elem in card.find_elements(By.CSS_SELECTOR, '.metadata.salary-snippet-container')), None)
                    job['highest_salary'] = get_salary_from_text(job['salary_text']) if job['salary_text'] else None

                    try:
                        job['url'] = next((elem.get_attribute('href') for elem in card.find_elements(By.CLASS_NAME, 'jcs-JobTitle')), None)
                        if job['url']:
                            parsed_url = urlparse(job['url'])
                            query_params = parse_qs(parsed_url.query)
                            job['job_id'] = query_params.get('jk', [None])[0]
                        else:
                            job['job_id'] = None
                    except Exception as e:
                        logging.info(f"Error parsing job URL for {job.get('title', 'Unknown title')}: {e}")
                        job['job_id'] = None

                    jobs.append(job)

                except Exception as e:
                    logging.info(f"Error processing job card: {e}")
                    continue

            driver.quit()

            offset += 10
            if offset >= 200:  # Prevent infinite scraping loops
                logging.info("Reached pagination limit, stopping.")
                break

            sleep(random.uniform(2, 4))

    except Exception as e:
        logging.info(f"Error scraping Indeed: {e}")

    finally:
        if driver:
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
            driver.quit()
            return None
    except Exception as e:
        logging.info(f"Error loading page: {e}")
        return None
    finally:
        driver.quit()

def scrape_upwork_jobs(base_url):
    jobs = []
    current_page = 1
    try:
        while True:
            # Construct the URL for the current page
            page_url = f"{base_url}&page={current_page}"

            logging.info(f"Scraping Upwork page {current_page}: {page_url}")
            driver = load_page(page_url)
            try:
                job_cards = driver.find_elements(By.CSS_SELECTOR, 'article.job-tile')
                if not job_cards:
                    break
                logging.info(f"Found {len(job_cards)} Upwork jobs")
            except Exception as e:
                logging.info(f"Error finding job cards: {e}")
                break

            # Process each job listing
            for card in job_cards:
                try:
                    title_elem = card.find_element(By.CSS_SELECTOR, 'h2.job-tile-title a')
                    job_url = urljoin('https://www.upwork.com', title_elem.get_attribute('href'))
                    job_id_match = re.search(r'_~(\d+)', job_url)
 
                    job = Job(
                            id = int(job_id_match.group(1)) if job_id_match else None,
                            url = job_url,
                            title = title_elem.text.strip(),
                            company = "Unkown Company"
                    )

                    # Extract payment information
                    price_elem = card.find_element(By.CSS_SELECTOR, '[data-test="job-type-label"]')
                    job.salary_text = price_elem.text.strip() if price_elem else None
                    logging.info(f"Price text: {job.salary_text}")
                    job.highest_salary = get_salary_from_text(job.salary_text) or None

                    jobs.append(job)
                    logging.info(job.url)

                except Exception as e:
                    logging.error(f"Error processing job card: {e}")
                    continue

            driver.quit()

            if len(job_cards) == 0:
                break

            current_page += 1

            if current_page > 20:  # Sanity check
                break

    except Exception as e:
        logging.error(f"Error scraping Upwork jobs: {e}")
        return []
    
    finally:
        driver.quit()

    return jobs

def get_upwork_job_description(url):
    try:
        driver = load_page(url, skip_cloudflare_detection=True)

        # First check to see if it's a private listing
        private_check = driver.find_element(By.XPATH, "//h4[text()='This job is a private listing.']")
        if private_check:
            driver.quit()
            return "private"

        description_element = driver.find_element(By.CSS_SELECTOR, "p.text-body-sm")
        if description_element:
            description = description_element.text.strip()
            driver.quit()
            return description

        driver.quit()
        return None

    except Exception as e:
        logging.error(f"Error extracting job description: {e}")
        return None

    finally:
        driver.quit()

def scrape_insight_global(base_url):
    jobs = []
    current_page = 1

    try:
        while True:
            # Construct the URL for the current page
            page_url = base_url.replace('/find_a_job/', f'/find_a_job/{current_page}/')

            logging.info(f"Scraping insight global page {current_page}: {page_url}")
            driver = load_page(page_url)
            try:
                # First check if we have valid pagination
                pagination = driver.find_element(By.CLASS_NAME, "paging-container")

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
                    title_elem = listing.find_element(By.CLASS_NAME, "job-title").find_element(By.TAG_NAME, "a")
                    job_url = title_elem.get_attribute("href")
                    job_id_match = re.search(r'job-(\d+)', job_url)
                    job = Job(
                            id = job_id_match.group(1) if job_id_match else None,
                            url = job_url,
                            title = title_elem.text.strip()
                            )
                    # Get job info section
                    info_parts = [p.strip() for p in listing.find_element(By.CLASS_NAME, "job-info").text.split("|")]

                    job.salary_text = info_parts[3].strip() if len(info_parts) > 3 else ""
                    job.highest_salary = get_salary_from_text(job.salary_text) or None

                    job.company = "Unknown Company"  # Default since all jobs are from Insight Global

                    jobs.append(job)

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

                driver.quit()    
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
        driver = load_page(url, skip_cloudflare_detection=True)
        try:
            # Get all description divs
            desc_sections = driver.find_element(By.CLASS_NAME, "detailpage-desc")

            # Combine all description sections into one string
            description_parts = []
            for section in desc_sections:
                text = section.text.strip()
                if text:  # Only add non-empty sections
                    description_parts.append(text)

            description = "\n\n".join(description_parts)
            return description
        except Exception as e:
            logging.info(f"Error finding description div: {e}")
            return None

    except Exception as e:
        logging.info(f"Error loading page: {e}")
        return None

    finally:
        driver.quit()

    return None

def scrape_ziprecruiter(base_url):
    jobs = []
    current_page = 1

    try:
        while True:
            page_url = f"{base_url}&page={current_page}"
            logging.info(f"Scraping Ziprecruiter page {current_page}...")

            driver = load_page(page_url)

            # Find all job result containers
            job_cards = driver.find_elements(By.CLASS_NAME, "job_result_two_pane")
            logging.info(f"Found {len(job_cards)} jobs")

            # If no jobs found, we've reached the end
            if not job_cards:
                break

            for card in job_cards:
                try:
                    # Find job link which contains title and URL
                    job_link = card.find_element(By.TAG_NAME, "h2").find_element(By.TAG_NAME, "a")
                    company_elem = card.find_element(By.XPATH, ".//a[@data-testid='job-card-company']")
                    company = company_elem.text.strip() if company_elem else None
                    title = job_link.text.strip()

                    job = Job(
                        # Zip Recruiter is annoying and doesn't show the unique job id in the search results, so we'll fake one with company+title
                        id = f"{company}_{title}".lower().strip(),
                        url = job_link.get_attribute("href"),
                        company = company,
                        title = title
                    )
                    
                    # Find salary info
                    try:
                        salary_elem = card.find_element(By.CSS_SELECTOR, "div.flex.items-center")
                        job.salary_text = salary_elem.text.strip() if salary_elem else None
                    except Exception as e:
                        job.salary_text = None
                    job.highest_salary = get_salary_from_text(job.salary_text) or None

                    # Add job details to list
                    jobs.append(job)

                except Exception as e:
                    logging.info(f"Error parsing job listing: {str(e)}")
                    continue

            # Check for next page button
            next_button = driver.find_element(By.XPATH, "//a[@title='Next Page']")
            if not next_button:
                break

            driver.quit()
            current_page += 1
            # Sanity check
            if current_page > 50:
                break

    except Exception as e:
        logging.info(f"Error scraping ZipRecruiter: {str(e)}")

    finally:
        driver.quit()

    return jobs

def get_ziprecruiter_job_description(url):
    try:
        driver = load_page(url)
    
        try:
            job_desc_div = driver.find_element(By.CLASS_NAME, "job_description")
            if not job_desc_div:
                return None

            # Get all text elements within the description div
            #desc_elements = job_desc_div.find_all(string=True, recursive=True)
            #for element in desc_elements:
            #    text = element.strip()
            #    if text:  # Only add non-empty strings
            #        description += text + "\n"

            #return description.strip()
            return job_desc_div.text

        except Exception as e:
            logging.info(f"Error finding description div: {e}")
            return None

    except Exception as e:
        print(f"Error scraping job description: {str(e)}")
        return None

    finally:
        driver.quit()

    return None

def scrape_cybercoders(base_url):
    jobs = []
    current_page = 1

    try:
        while True:
            # Construct the URL for the current page
            page_url = f"{base_url}&page={current_page}"

            logging.info(f"Scraping CyberCoders page {current_page}: {page_url}")
            driver = load_page(page_url)
            try:
                job_cards = driver.find_elements(By.CLASS_NAME, "result-box")
                if not job_cards:
                    break
                logging.info(f"Found {len(job_cards)} CyberCoders jobs")
            except Exception as e:
                logging.info(f"Error finding job cards: {e}")
                break

            # Process each job listing
            for card in job_cards:
                try:
                    # Click the job card to load details
                    card.click()
                    sleep(1)  # Wait for details to load

                    job_link = driver.find_element(By.CSS_SELECTOR, ".job-details-header a")
                    job_url = job_link.get_attribute("href")
                    job = Job(
                            id = job_url.split('/')[-1],
                            url = job_url,
                            title = job_link.text.strip()
                            )

                    # Get salary text
                    salary_block = driver.find_element(By.CSS_SELECTOR, ".job-details-header .info-block.tertiary")
                    job.salary_text = salary_block.text if salary_block else None
                    job.highest_salary = get_salary_from_text(job.salary_text) or None

                    job.company = "Unknown Company"  # Default since all jobs are from CyberCoders

                    jobs.append(job)

                except Exception as e:
                    logging.info(f"Error processing job card: {e}")
                    continue

            driver.quit()

            if len(job_cards) == 0:
                break

            current_page += 1

            if current_page > 50:  # Sanity check
                break

    except Exception as e:
        logging.info(f"Error scraping CyberCoders: {e}")

    finally:
        driver.quit()

    return jobs

def get_cybercoders_job_description(url):
    try:
        driver = load_page(url, skip_cloudflare_detection=True)

        try:
            desc_div = driver.find_element(By.CLASS_NAME, "job-details-description")
            if desc_div:
                return desc_div.text if desc_div.text.strip() else None
        except Exception as e:
            logging.info(f"Error finding description div: {e}")
            return None

    except Exception as e:
        logging.info(f"Error loading page: {e}")
        return None

    finally:
        driver.quit()

    return None

def scrape_dice_jobs(base_url):
    try:
        driver = setup_chrome_driver()
    except Exception as e:
        print(f"Error loading Chrome: {e}")
        return None
    jobs = []
    current_page = 1
    while True:
        # Construct the URL for the current page
        page_url = f"{base_url}&page={current_page}"

        # Navigate to the page
        logging.info(f"Scraping Dice page {current_page}: {page_url}")
        driver.get(page_url)
        wait = WebDriverWait(driver, 10)
        with open("dice_last.html", "w", encoding="utf-8") as file:
            file.write(driver.page_source)
        try:
            job_cards = wait.until(EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, "dhi-search-card")))
        except:
            logging.info("No job cards")
            break

        # Break if no jobs found
        if len(job_cards) == 0:
            break

        # Process each job card
        for card in job_cards:
            try:
                # Find the title link element which contains both title and URL
                title_link = card.find_element(By.CSS_SELECTOR, "a[data-cy='card-title-link']")

                # Get company element
                company_element = card.find_element(By.CSS_SELECTOR, "a[data-cy='search-result-company-name']")

                # Extract job details
                job_id = title_link.get_attribute('id').strip('()').strip(',').strip()
                job_url = f"https://www.dice.com/job-detail/{job_id}"
                title = title_link.text.strip().strip('()').strip(',').strip()
                company = company_element.text.strip()
                # Different job_id because Dice is so fucking noisy due to companies spamming the same position over and over
                spam_job_id = f"{company}_{title}".lower().strip()

                jobs.append({
                    'job_id': spam_job_id,
                    'url': job_url,
                    'company': company,
                    'title': title,
                    })

            except Exception as e:
                print(f"Error processing job card: {e}")
                continue

        # Increment page counter
        current_page += 1
        sleep(2)

    driver.quit()

    return jobs

def get_dice_job_description(url):
    try:
        driver = setup_chrome_driver()
    except Exception as e:
        print(f"Error loading Chrome: {e}")
        return None

    try:
        driver.get(url)
        wait = WebDriverWait(driver, 10)
        try:
            salary_element = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-cy='payDetails'] span"))
                    )
            salary_text = salary_element.text
            logging.info(f"Found salary_text: {salary_text}")
            # Standardize format and remove currency
            salary_clean = salary_text.replace('USD', '').replace('$', '').strip()

            # Remove various forms of annual/hourly indicators
            salary_clean = salary_clean.replace('per year', '').replace('/year', '').replace('/yr', '').replace('yearly', '')
            salary_clean = salary_clean.replace('per hour', '').replace('/hour', '').replace('/hr', '').replace('hourly', '')

            # Handle "Up to X" pattern
            if salary_clean.lower().startswith('up to'):
                salary_clean = salary_clean.lower().replace('up to', '').strip()
                salary_val = salary_clean

            # Split range and get higher value
            if ' - ' in salary_clean:
                salary_val = salary_clean.split(' - ')[1]
            elif '-' in salary_clean:  # Add this case
                salary_val = salary_clean.split('-')[1]
            else:
                salary_val = salary_clean

            # Convert to float (remove commas)
            salary_val = float(salary_val.replace(',', ''))

            # Convert to thousands
            highest_salary = salary_val / 1000

            # Check if it's hourly based on explicit indicators or amount
            is_hourly = any(term in salary_text.lower() for term in ['/hr', '/hour', 'per hour', 'hourly'])

            # If no explicit hourly indicator, check if the amount suggests hourly rate
            # Assuming anything less than $200 is likely an hourly rate
            if not is_hourly and highest_salary < 0.2:  # $200 in thousands
                is_hourly = True

            # Convert hourly to annual salary
            if is_hourly:
                highest_salary = highest_salary * 2080

        except:
            highest_salary = None

        try:
            expand_button = wait.until(
                    EC.presence_of_element_located((By.ID, "descriptionToggle"))
                    )
            if "Read Full Job Description" in expand_button.text:
                # Try scrolling to button first to ensure it's in view
                driver.execute_script("arguments[0].scrollIntoView(true);", expand_button)
                sleep(0.5)  # Brief pause to let scroll complete
                try:
                    expand_button.click()
                except:
                    # If direct click fails, try JavaScript click
                    driver.execute_script("arguments[0].click();", expand_button) 
        except:
            # If expand button isn't found, assume description is already expanded
            # or doesn't need expanding - continue with rest of script
            pass 

        try:
            description_element = wait.until(
                    EC.presence_of_element_located((By.ID, "jobDescription"))
                    )
            description = description_element.text
        except:
            description = None

        driver.quit()
        return highest_salary, description

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        driver.quit()
        return None, None

    finally:
        if driver:
            try:
                driver.quit()
            except Exception as e:
                logging.error(f"Error closing driver: {e}")

def scrape_wwr_jobs(url):
    try:
        driver = setup_chrome_driver()
    except Exception as e:
        print(f"Error loading Chrome: {e}")
        return None
    jobs = []

    # Navigate to the page
    logging.info(f"Scraping WWR page {url}")
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 10)
        with open("wwr_last.html", "w", encoding="utf-8") as file:
            file.write(driver.page_source)
        jobs_section = wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "section.jobs article ul")
            ))
        job_cards = jobs_section.find_elements(By.CSS_SELECTOR, "li:not(.feature--ad):not(.view-all)")

        # Break if no jobs found
        if len(job_cards) == 0:
            return None
    except:
        logging.info("Error loading job cards")
        driver.quit()
        return None

    # Process each job card
    for card in job_cards:
        try:
            job_link = card.find_element(By.CSS_SELECTOR, "a:has(span.title)")
            # Extract job URL and ID
            job_url = job_link.get_attribute("href")
            job_id = job_url.split("/")[-1].strip() if job_url else None

            # Extract company and title
            company = card.find_element(By.CSS_SELECTOR, "span.company").text
            title = card.find_element(By.CSS_SELECTOR, "span.title").text

            jobs.append({
                "company": company,
                "title": title,
                "url": job_url,
                "job_id": job_id
                })

        except Exception as e:
            print(f"Error processing job card: {e}")
            continue

    driver.quit()

    return jobs

def get_wwr_job_description(url):
    try:
        driver = setup_chrome_driver()
    except Exception as e:
        print(f"Error loading Chrome: {e}")
        return None

    try:
        driver.get(url)
        wait = WebDriverWait(driver, 10)
        sleep(5)

        try:
            desc_div = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "div#job-listing-show-container")
                ))
            return desc_div.text if desc_div.text.strip() else None
        except Exception as e:
            logging.info(f"Error finding description div: {e}")
            return None

    except Exception as e:
        logging.info(f"Error loading page: {e}")
        return None

    finally:
        driver.quit()

    return None

def scrape_monster(url):
    jobs = []

    try:
        while True:
            logging.info(f"Scraping Monster page: {url}")
            driver = load_page(url, load_more=True)
            try:
                job_cards = driver.find_elements(By.CSS_SELECTOR, "article[data-testid='JobCard']")
                if not job_cards:
                    break
                logging.info(f"Found {len(job_cards)} Monster jobs")
            except Exception as e:
                logging.info(f"Error finding job cards: {e}")
                break

            # Process each job listing
            for card in job_cards:
                try:
                    job = Job(
                            id = card.find_element(By.CSS_SELECTOR, "button[data-job-id]").get_attribute("data-job-id"),
                            url = card.find_element(By.CSS_SELECTOR, "a[data-testid='jobTitle']").get_attribute('href'),
                            title = card.find_element(By.CSS_SELECTOR, "a[data-testid='jobTitle']").text,
                            company = card.find_element(By.CSS_SELECTOR, "span[data-testid='company']").text
                            )
                    logging.info(job.url)
                    # Get salary text
                    salary_block = (card.find_elements(By.CSS_SELECTOR, "div[data-tagtype-testid='payTag']") or [None])[0]
                    job.salary_text = salary_block.text if salary_block else None
                    job.highest_salary = get_salary_from_text(job.salary_text) if job.salary_text else None

                    jobs.append(job)

                except Exception as e:
                    logging.info(f"Error processing job card: {e}")
                    continue

            try:
                load_more = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.ID, "job-search-load-more"))
                )
                driver.execute_script("arguments[0].scrollIntoView();", load_more)
                sleep(1)  # Small delay to let the page settle
                load_more.click()
                sleep(1)  # Wait for new results to load
            except Exception as e:
                # No more results to load
                break

    except Exception as e:
        logging.info(f"Error scraping Monster: {e}")

    finally:
        driver.quit()

    return jobs

def get_monster_job_description(url):
    try:
        driver = load_page(url, skip_cloudflare_detection=True)

        try:
            json_data = driver.execute_script('return JSON.parse(document.getElementById("__NEXT_DATA__").textContent)')
            description = json_data['props']['pageProps']['jobViewResultsData']['jobPosting']['description']
            driver.execute_script("document.body.innerHTML = arguments[0];", description)
            description_text = driver.find_element(By.TAG_NAME, "body").text

            if description_text:
                return description_text.strip()
        except Exception as e:
            logging.info(f"Error finding description div: {e}")
            return None

    except Exception as e:
        logging.info(f"Error loading page: {e}")
        return None

    finally:
        driver.quit()

def scrape_kforce(url):
    jobs = []

    try:
        logging.info(f"Scraping Kforce page: {url}")
        driver = load_page(url, load_more=True)
        try:
            job_cards = driver.find_elements(By.CSS_SELECTOR, "ul.data-jobs li")
            logging.info(f"Found {len(job_cards)} Kforce jobs")
        except Exception as e:
            logging.info(f"Error finding job cards: {e}")
            return

        # Process each job listing
        for card in job_cards:
            try:
                job_link = card.find_element(By.CSS_SELECTOR, "h2 a.linkForJob")
                job = Job(
                    id = job_link.get_attribute("href").split("/detail/")[1].rstrip("/") if "/detail/" in job_link.get_attribute("href") else None,
                    url = job_link.get_attribute("href"),
                    title = job_link.text.strip(),
                    company = "Kforce"
                )

                jobs.append(job)

            except Exception as e:
                logging.info(f"Error processing job card: {e}")
                continue

    except Exception as e:
        logging.info(f"Error scraping Kforce: {e}")

    finally:
        if driver:
            driver.quit()

    return jobs

def get_kforce_job_description(url):
    try:
        driver = load_page(url, skip_cloudflare_detection=True, load_more=False)
        sleep(2)

        try:
            try:
                salary_block = driver.find_element(By.XPATH, "//span[contains(@class, 'c-orange') and contains(text(), 'Compensation:')]/parent::h4")
            except NoSuchElementException:
                salary_block = None
            salary_text = salary_block.text if salary_block else None
            highest_salary = get_salary_from_text(salary_text) if salary_text else None

            description = driver.find_element(By.CSS_SELECTOR, "div.data-job-desc").text if driver.find_elements(By.CSS_SELECTOR, "div.data-job-desc") else None

            return highest_salary, description
        
        except Exception as e:
            logging.info(f"Error finding description div: {e}")
            return None,None

    except Exception as e:
        logging.info(f"Error loading page: {e}")
        return None,None

    finally:
        if driver:
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

def get_salary_from_text(salary_text):
    cleaned_text = salary_text.replace('$', '').replace(',', '')
    # Get all the numbers, and take the last one
    salary_numbers = re.findall(r'\d+', cleaned_text)  # Extract all numbers
    highest_salary = float(salary_numbers[-1])
    
    # If 'hour' exists in the salary, flag it as hourly to be converted to salary
    is_hourly = any(term in cleaned_text.lower() for term in ["hour", "hr", "hourly"])
    if is_hourly:
        highest_salary *= 2080

    # Check if K/k is in the text (meaning the salary is already in thousands)
    is_in_thousands = 'k' in cleaned_text.lower()
    
    # Only divide by 1000 if not already expressed in thousands
    if not is_in_thousands:
        highest_salary /= 1000
        
    return highest_salary

# If a job post doesn't have the salary in the normal job details, see if they say it in the description
def get_salary_from_description(description):
    patterns = [
       # Specific formats first
        r'\$([0-9,]+)K(?:—|-)\$?([0-9,]+)K/yr',  # $120K-$150K/yr
        r'\$([0-9,]+)K/(?:yr|year)',  # $120K/yr
        r'\$(\d+)[-—](\d+),\d{3}/yr',  # $120-150,000/yr
        r'\$([0-9,]+)K(?:—|-)\$?([0-9,]+)K/Annum',  # $140K-$150K/Annum
    
        # Hourly patterns
        r'\$([0-9,.]+)(?:\s+USD)?(?:\s+per\s+|\/)(?:hour|hr)',  # $20.00 USD per hour, $48/hr
    
        # Special cases
        r'(?:up to)\s*\$([0-9,]+)(?:\s+per\s+(?:month|year|hr|hour))?',  # up to $X per month/year/hour
    
        # Standard ranges
        r'\$([0-9,]+)(?:,\d{3})*\s*-\s*\$([0-9,]+)(?:,\d{3})*',  # $120,000 - $150,000
        r'\$([0-9,]+)(?:—|-)\$([0-9,]+)\s+USD',  # $120,000-$150,000 USD
        r'\$([0-9,]+)(?:—|-)\$?([0-9,]+)/yr',  # $120,000-$150,000/yr
        r'\$([0-9,]+)\s+to\s+\$?([0-9,]+)(?:/(?:yr|year|hr|hour))?',  # $120,000 to $150,000/yr
        r'between\s+\$([0-9,]+)(?:,\d{3})*\s+and\s+\$([0-9,]+)(?:,\d{3})*',  # between $190,700 and $329,600
    
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
            company = job_details.get('company', {}).get('name') or get_company_from_description(description)
            fitness=get_fitness_rating(description, company, title)
            if fitness is None:
                continue
            if fitness < fitness_threshold:
                logging.info(f"Fitness score below threshold: {fitness}")
                awsutils.dynamodb_put_item('linkedin_jobs', 'job_id', id)
                metrics["fitness_count"] += 1
                continue
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
            company = job['company'] or get_company_from_description(description)
            fitness=get_fitness_rating(description, company, title)
            if fitness is None:
                continue
            if fitness < fitness_threshold:
                logging.info(f"Fitness score below threshold: {fitness}")
                awsutils.dynamodb_put_item('indeed_jobs', 'job_id', id)
                metrics["fitness_count"] += 1
                continue
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
        if not job.id:
            logging.info(f"No job id: {job.id}")
            continue
        if awsutils.dynamodb_check_if_value_exists('upwork_jobs', 'job_id', job.id):
            logging.info(f"Upwork job {job.id} already seen")
            metrics["seen_count"] += 1
            continue
        logging.info(job.url)
        job.description = get_upwork_job_description(job.url)
        if job.description in (None, "private"):
            logging.info("Couldn't find job description, possibly private, emailing URL")
            email_body=f"Private Upwork listing:\n{job.url}"
            awsutils.send_email('Python Upwork Search <python@twistedslinky.org>', mail_to, 'Private Upwork listing', email_body)
            awsutils.dynamodb_put_item('upwork_jobs', 'job_id', job.id)
            metrics["description_count"] += 1
            continue
        if job.highest_salary is None:
            logging.info("No rate information found")
            awsutils.dynamodb_put_item('upwork_jobs', 'job_id', job.id)
            metrics["salary_count"] += 1
            continue
        if job.highest_salary < salary_threshold:
            logging.info(f"Rate below threshold: {job.highest_salary}")
            awsutils.dynamodb_put_item('upwork_jobs', 'job_id', job.id)
            metrics["salary_count"] += 1
        else:
            job.fitness=get_fitness_rating(job.description, job.company, job.title)
            if job.fitness is None:
                continue
            if job.fitness < fitness_threshold:
                logging.info(f"Fitness score below threshold: {job.fitness}")
                awsutils.dynamodb_put_item('upwork_jobs', 'job_id', job.id)
                metrics["fitness_count"] += 1
                continue
            email_body=f"{job.company} - {job.title}\n{job.url}\nrate: {job.highest_salary}/hr\nfitness: {job.fitness}"
            logging.info(email_body)
            cover_letter_path=get_cover_letter(job.company, job.title, job.description)
            awsutils.send_email('Python Upwork Search <python@twistedslinky.org>', 'ryan@twistedslinky.org', job.company + " - " + job.title, email_body, cover_letter_path)
            awsutils.dynamodb_put_item('upwork_jobs', 'job_id', job.id)
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
        if not job.id:
            logging.info(f"No job id: {job.id}")
            continue
        if awsutils.dynamodb_check_if_value_exists('insight_global_jobs', 'job_id', job.id):
            logging.info(f"Insight Global job {job.id} already seen")
            metrics["seen_count"] += 1
            continue
        logging.info(job.url)
        job.description = get_insight_global_job_description(job.url)
        if job.description is None:
            logging.info("Couldn't find job description")
            metrics["description_count"] += 1
            continue
        if not job.highest_salary:
            job.highest_salary = get_salary_from_description(job.description)
        if job.highest_salary is None:
            logging.info("No salary information found")
            awsutils.dynamodb_put_item('insight_global_jobs', 'job_id', job.id)
            metrics["salary_count"] += 1
            continue
        if job.highest_salary < salary_threshold:
            logging.info(f"Salary below threshold: {job.highest_salary}")
            awsutils.dynamodb_put_item('insight_global_jobs', 'job_id', job.id)
            metrics["salary_count"] += 1
        else:
            if not job.company:
                job.company = get_company_from_description(job.description)
            job.fitness=get_fitness_rating(job.description, job.company, job.title)
            if job.fitness is None:
                continue
            if job.fitness < fitness_threshold:
                logging.info(f"Fitness score below threshold: {job.fitness}")
                awsutils.dynamodb_put_item('insight_global_jobs', 'job_id', job.id)
                metrics["fitness_count"] += 1
                continue
            email_body=f"{job.company} - {job.title}\n{job.url}\nsalary: {job.highest_salary}/yr\nfitness: {job.fitness}"
            logging.info(email_body)
            cover_letter_path=get_cover_letter(company, title, description)
            awsutils.send_email('Python Insight Global Search <python@twistedslinky.org>', mail_to, company + " - " + title, email_body, cover_letter_path)
            awsutils.dynamodb_put_item('insight_global_jobs', 'job_id', job.id)
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
        if not job.id:
            logging.info(f"No job id: {job.id}")
            continue
        if awsutils.dynamodb_check_if_value_exists('ziprecruiter_jobs', 'job_id', job.id):
            logging.info(f"Zip Recruiter job {job.id} already seen")
            metrics["seen_count"] += 1
            continue
        logging.info(job.url)
        job.description = get_ziprecruiter_job_description(job.url)
        if job.description is None:
            logging.info("Couldn't find job description")
            metrics["description_count"] += 1
            continue
        logging.info(f"Salary Text: {job.salary_text}")
        if not job.highest_salary:
            job.highest_salary = get_salary_from_description(job.description)
        if job.highest_salary is None:
            logging.info("No salary information found")
            awsutils.dynamodb_put_item('ziprecruiter_jobs', 'job_id', job.id)
            metrics["salary_count"] += 1
            continue
        if job.highest_salary < salary_threshold:
            logging.info(f"Salary below threshold: {job.highest_salary}")
            awsutils.dynamodb_put_item('ziprecruiter_jobs', 'job_id', job.id)
            metrics["salary_count"] += 1
        else:
            if not job.company:
                job.company = get_company_from_description(job.description)
            job.fitness=get_fitness_rating(job.description, job.company, job.title)
            if job.fitness is None:
                continue
            if job.fitness < fitness_threshold:
                logging.info(f"Fitness score below threshold: {job.fitness}")
                awsutils.dynamodb_put_item('ziprecruiter_jobs', 'job_id', job.id)
                metrics["fitness_count"] += 1
                continue
            email_body=f"{job.company} - {job.title}\n{job.url}\nsalary: {job.highest_salary}/yr\nfitness: {job.fitness}"
            logging.info(email_body)
            cover_letter_path=get_cover_letter(job.company, job.title, job.description)
            awsutils.send_email('Python Zip Recruiter Search <python@twistedslinky.org>', mail_to, job.company + " - " + job.title, email_body, cover_letter_path)
            awsutils.dynamodb_put_item('ziprecruiter_jobs', 'job_id', job.id)
            metrics["valid_count"] += 1
    print_metrics(metrics, progress)
    return None

def search_cybercoders(progress=None):
    jobs = scrape_cybercoders(cybercoders_search_url)
    if not jobs:
        print("No CyberCoders search results")
        return
    print("Found", len(jobs), "CyberCoders jobs")
    # Reset metric counters to zero
    global metrics
    metrics = {key: 0 for key in metrics}
    for idx, job in enumerate(jobs):
        if progress:
            print(f"Processing {idx}/{len(jobs)}", end="\r")
        if not job.id:
            logging.info(f"No job id: {job.id}")
            continue
        if awsutils.dynamodb_check_if_value_exists('cybercoders_jobs', 'job_id', job.id):
            logging.info(f"CyberCoders job {job.id} already seen")
            metrics["seen_count"] += 1
            continue
        logging.info(job.url)
        job.description = get_cybercoders_job_description(job.url)
        if job.description is None:
            logging.info("Couldn't find job description")
            metrics["description_count"] += 1
            continue
        if not job.highest_salary:
            job.highest_salary = get_salary_from_description(job.description)
        if job.highest_salary is None:
            logging.info("No salary information found")
            awsutils.dynamodb_put_item('cybercoders_jobs', 'job_id', job.id)
            metrics["salary_count"] += 1
            continue
        if job.highest_salary < salary_threshold:
            logging.info(f"Salary below threshold: {job.highest_salary}")
            awsutils.dynamodb_put_item('cybercoders_jobs', 'job_id', job.id)
            metrics["salary_count"] += 1
        else:
            if not job.company:
                job.company = get_company_from_description(job.description)
            job.fitness = get_fitness_rating(job.description, job.company, job.title)
            if job.fitness is None:
                continue
            if job.fitness < fitness_threshold:
                logging.info(f"Fitness score below threshold: {job.fitness}")
                awsutils.dynamodb_put_item('cybercoders_jobs', 'job_id', job.id)
                metrics["fitness_count"] += 1
                continue
            email_body=f"{job.company} - {job.title}\n{job.url}\nsalary: {job.highest_salary}/yr\nfitness: {job.fitness}"
            logging.info(email_body)
            cover_letter_path=get_cover_letter(job.company, job.title, job.description)
            awsutils.send_email('Python CyberCoders Search <python@twistedslinky.org>', mail_to, job.company + " - " + job.title, email_body, cover_letter_path)
            awsutils.dynamodb_put_item('cybercoders_jobs', 'job_id', job.id)
            metrics["valid_count"] += 1
    print_metrics(metrics, progress)
    return None

def search_dice(progress=None):
    jobs = scrape_dice_jobs(dice_search_url)
    if not jobs:
        print("No Dice search results")
        return
    print("Found", len(jobs), "Dice jobs")
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
        if awsutils.dynamodb_check_if_value_exists('dice_jobs', 'job_id', id):
            logging.info(f"Dice job {id} already seen")
            metrics["seen_count"] += 1
            continue
        url = job['url']
        logging.info(url)
        title = job['title']
        highest_salary, description = get_dice_job_description(url)
        if description is None:
            logging.info("Couldn't find job description")
            metrics["description_count"] += 1
            continue
        if highest_salary is None:
            highest_salary = get_salary_from_description(description)
        if highest_salary is None:
            logging.info("No salary information found")
            awsutils.dynamodb_put_item('dice_jobs', 'job_id', id)
            metrics["salary_count"] += 1
            continue
        if highest_salary < salary_threshold:
            logging.info(f"Salary below threshold: {highest_salary}")
            awsutils.dynamodb_put_item('dice_jobs', 'job_id', id)
            metrics["salary_count"] += 1
        else:
            company = job['company'] or get_company_from_description(description)
            fitness=get_fitness_rating(description, company, title)
            if fitness is None:
                continue
            if fitness < fitness_threshold:
                logging.info(f"Fitness score below threshold: {fitness}")
                awsutils.dynamodb_put_item('dice_jobs', 'job_id', id)
                metrics["fitness_count"] += 1
                continue
            email_body=f"{company} - {title}\n{url}\nsalary: {highest_salary}/yr\nfitness: {fitness}"
            logging.info(email_body)
            cover_letter_path=get_cover_letter(company, title, description)
            awsutils.send_email('Python Dice Search <python@twistedslinky.org>', mail_to, company + " - " + title, email_body, cover_letter_path)
            awsutils.dynamodb_put_item('dice_jobs', 'job_id', id)
            metrics["valid_count"] += 1
    print_metrics(metrics, progress)
    return None

def search_wwr(progress=None):
    jobs = scrape_wwr_jobs(weworkremotely_search_url)
    if not jobs:
        print("No WWR search results")
        return
    print("Found", len(jobs), "WWR jobs")
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
        if awsutils.dynamodb_check_if_value_exists('wwr_jobs', 'job_id', id):
            logging.info(f"WWR job {id} already seen")
            metrics["seen_count"] += 1
            continue
        url = job['url']
        logging.info(url)
        title = job['title']
        company = job['company']
        description = get_wwr_job_description(url)
        if description is None:
            logging.info("Couldn't find job description")
            metrics["description_count"] += 1
            continue
        highest_salary = get_salary_from_description(description)
        if highest_salary is None:
            logging.info("No salary information found")
            awsutils.dynamodb_put_item('wwr_jobs', 'job_id', id)
            metrics["salary_count"] += 1
            continue
        if highest_salary < salary_threshold:
            logging.info(f"Salary below threshold: {highest_salary}")
            awsutils.dynamodb_put_item('wwr_jobs', 'job_id', id)
            metrics["salary_count"] += 1
        else:
            company = job['company'] or get_company_from_description(description)
            fitness=get_fitness_rating(description, company, title)
            if fitness is None:
                continue
            if fitness < fitness_threshold:
                logging.info(f"Fitness score below threshold: {fitness}")
                awsutils.dynamodb_put_item('wwr_jobs', 'job_id', id)
                metrics["fitness_count"] += 1
                continue
            email_body=f"{company} - {title}\n{url}\nsalary: {highest_salary}/yr\nfitness: {fitness}"
            logging.info(email_body)
            cover_letter_path=get_cover_letter(company, title, description)
            awsutils.send_email('Python WeWorkRemotely Search <python@twistedslinky.org>', mail_to, company + " - " + title, email_body, cover_letter_path)
            awsutils.dynamodb_put_item('wwr_jobs', 'job_id', id)
            metrics["valid_count"] += 1
    print_metrics(metrics, progress)
    return None

def search_monster(progress=None):
    jobs = scrape_monster(monster_search_url)
    if not jobs:
        print("No Monster search results")
        return
    print("Found", len(jobs), "Monster jobs")
    # Reset metric counters to zero
    global metrics
    metrics = {key: 0 for key in metrics}
    for idx, job in enumerate(jobs):
        if progress:
            print(f"Processing {idx}/{len(jobs)}", end="\r")
        if not job.id:
            logging.info(f"No job id: {job.id}")
            continue
        job.description = get_monster_job_description(job.url)
        if awsutils.dynamodb_check_if_value_exists('monster_jobs', 'job_id', job.id):
            logging.info(f"Monster job {job.id} already seen")
            metrics["seen_count"] += 1
            continue
        logging.info(job.url)
        job.description = get_monster_job_description(job.url)
        if job.description is None:
            logging.info("Couldn't find job description")
            metrics["description_count"] += 1
            continue
        if not job.highest_salary:
            job.highest_salary = get_salary_from_description(job.description)
        if job.highest_salary is None:
            logging.info("No salary information found")
            awsutils.dynamodb_put_item('monster_jobs', 'job_id', job.id)
            metrics["salary_count"] += 1
            continue
        if job.highest_salary < salary_threshold:
            logging.info(f"Salary below threshold: {job.highest_salary}")
            awsutils.dynamodb_put_item('monster_jobs', 'job_id', job.id)
            metrics["salary_count"] += 1
        else:
            if not job.company:
                job.company = get_company_from_description(job.description)
            job.fitness = get_fitness_rating(job.description, job.company, job.title)
            if job.fitness is None:
                continue
            if job.fitness < fitness_threshold:
                logging.info(f"Fitness score below threshold: {job.fitness}")
                awsutils.dynamodb_put_item('monster_jobs', 'job_id', job.id)
                metrics["fitness_count"] += 1
                continue
            email_body=f"{job.company} - {job.title}\n{job.url}\nsalary: {job.highest_salary}/yr\nfitness: {job.fitness}"
            logging.info(email_body)
            cover_letter_path=get_cover_letter(job.company, job.title, job.description)
            awsutils.send_email('Python Monster Search <python@twistedslinky.org>', mail_to, job.company + " - " + job.title, email_body, cover_letter_path)
            awsutils.dynamodb_put_item('monster_jobs', 'job_id', job.id)
            metrics["valid_count"] += 1
    print_metrics(metrics, progress)
    return None

def search_kforce(progress=None):
    jobs = scrape_kforce(kforce_search_url)
    if not jobs:
        print("No Kforce search results")
        return
    print("Found", len(jobs), "Kforce jobs")
    # Reset metric counters to zero
    global metrics
    metrics = {key: 0 for key in metrics}
    for idx, job in enumerate(jobs):
        if progress:
            print(f"Processing {idx}/{len(jobs)}", end="\r")
        if not job.id:
            logging.info(f"No job id: {job.id}")
            continue
        if awsutils.dynamodb_check_if_value_exists('kforce_jobs', 'job_id', job.id):
            logging.info(f"Kforce job {job.id} already seen")
            metrics["seen_count"] += 1
            continue
        logging.info(job.url)
        sleep(1)
        job.highest_salary, job.description = get_kforce_job_description(job.url)
        if job.description is None:
            logging.info("Couldn't find job description")
            metrics["description_count"] += 1
            continue
        if not job.highest_salary:
            job.highest_salary = get_salary_from_description(job.description)
        if job.highest_salary is None:
            logging.info("No salary information found")
            awsutils.dynamodb_put_item('kforce_jobs', 'job_id', job.id)
            metrics["salary_count"] += 1
            continue
        if job.highest_salary < salary_threshold:
            logging.info(f"Salary below threshold: {job.highest_salary}")
            awsutils.dynamodb_put_item('kforce_jobs', 'job_id', job.id)
            metrics["salary_count"] += 1
        else:
            if not job.company:
                job.company = get_company_from_description(job.description)
            job.fitness = get_fitness_rating(job.description, job.company, job.title)
            if job.fitness is None:
                continue
            if job.fitness < fitness_threshold:
                logging.info(f"Fitness score below threshold: {job.fitness}")
                awsutils.dynamodb_put_item('kforce_jobs', 'job_id', job.id)
                metrics["fitness_count"] += 1
                continue
            email_body=f"{job.company} - {job.title}\n{job.url}\nsalary: {job.highest_salary}/yr\nfitness: {job.fitness}"
            logging.info(email_body)
            cover_letter_path=get_cover_letter(job.company, job.title, job.description)
            awsutils.send_email('Python Kforce Search <python@twistedslinky.org>', mail_to, job.company + " - " + job.title, email_body, cover_letter_path)
            awsutils.dynamodb_put_item('kforce_jobs', 'job_id', job.id)
            metrics["valid_count"] += 1
    print_metrics(metrics, progress)
    return None

if __name__ == "__main__":
    start_time = time()
    parser = argparse.ArgumentParser(description="Run a search on job postings and email details and cover letter to myself",formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        "website",
        choices=['linkedin','indeed','upwork','insight','ziprecruiter', 'cybercoders', 'dice', 'wwr', 'monster', 'kforce', 'all', 'selenium'],
        help="Website to search, or all, or those requiring selenium"
    )
    parser.add_argument("--cron", action="store_true", help="If set, suppress progress output for cron jobs")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    # Determine if progress output should be included
    progress = not args.cron
    # Log to debug.log if --debug
    global debug
    debug = args.debug
    logging.basicConfig(
        level=logging.INFO if debug else logging.WARN,
        filename="debug.log",
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    if args.website == "all":
        search_linkedin(progress)
        print("\n")
        search_indeed(progress)
        print("\n")
        search_upwork(progress)
        print("\n")
        search_insight(progress)
        print("\n")
        search_ziprecruiter(progress)
        print("\n")
        search_cybercoders(progress)
    elif args.website == "selenium":
        search_indeed(progress)
        print("\n")
        search_upwork(progress)
        print("\n")
        search_insight(progress)
        print("\n")
        search_cybercoders(progress)
        print("\n")
        search_wwr(progress)
        print("\n")
        search_ziprecruiter(progress)
        print("\n")
        search_kforce(progress)
        print("\n")
        search_monster(progress)
        print("\n")
        search_dice(progress)
    else:
        search = f"search_{args.website}({progress})"        
        eval(search)
    end_time = time()
    elapsed_time = end_time - start_time
    print(f"\nScript completed in {elapsed_time:.2f} seconds")
