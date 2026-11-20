import logging
import random
from time import sleep
from urllib.parse import urlparse, parse_qs

from selenium.webdriver.common.by import By

from models import Job, DescriptionResult


def scrape(base_url, session):
    """Scrape Indeed job listings. Returns list of Job objects."""
    jobs = []
    offset = 0

    try:
        while True:
            paginated_url = f"{base_url}&start={offset}"
            logging.info(f"Scraping Indeed page with offset {offset}: {paginated_url}")

            driver = session.load_page(paginated_url)
            if not driver:
                logging.info("Failed to load page. Skipping...")
                break

            try:
                job_cards = driver.find_elements(By.CLASS_NAME, "job_seen_beacon")
                if not job_cards:
                    logging.info("No job listings found, stopping pagination.")
                    break
                logging.info(f"Found {len(job_cards)} Indeed jobs")
            except Exception as e:
                logging.info(f"Error finding job cards: {e}")
                break

            for card in job_cards:
                try:
                    job_url = next(
                        (elem.get_attribute('href')
                         for elem in card.find_elements(By.CLASS_NAME, 'jcs-JobTitle')),
                        None
                    )
                    if job_url:
                        parsed_url = urlparse(job_url)
                        query_params = parse_qs(parsed_url.query)
                        job_id = query_params.get('jk', [None])[0]
                    else:
                        job_id = None

                    # Fallback: cards without a jcs-JobTitle link usually still
                    # carry the job key as a data-jk attribute
                    if not job_id:
                        job_id = next(
                            (elem.get_attribute('data-jk')
                             for elem in card.find_elements(By.CSS_SELECTOR, '[data-jk]')
                             if elem.get_attribute('data-jk')),
                            None
                        )
                        if job_id and not job_url:
                            job_url = f"https://www.indeed.com/viewjob?jk={job_id}"

                    job = Job(
                        id=job_id,
                        url=job_url,
                        title=next(
                            ((elem.get_attribute('textContent') or '').strip()
                             for elem in card.find_elements(By.CSS_SELECTOR, 'span[id^="jobTitle"]')),
                            None
                        ),
                        company=next(
                            ((elem.get_attribute('textContent') or '').strip()
                             for elem in card.find_elements(By.CSS_SELECTOR, '[data-testid="company-name"]')),
                            None
                        ),
                        description=next(
                            ((elem.get_attribute('textContent') or '').strip()
                             for elem in card.find_elements(By.CSS_SELECTOR, '[data-testid="jobsnippet_footer"]')),
                            None
                        ),
                        salary_text=next(
                            ((elem.get_attribute('textContent') or '').strip()
                             for elem in card.find_elements(By.CSS_SELECTOR, '.metadata.salary-snippet-container')),
                            None
                        ),
                    )

                    jobs.append(job)

                except Exception as e:
                    logging.info(f"Error processing job card: {e}")
                    continue

            offset += 10
            if offset >= 200:
                logging.info("Reached pagination limit, stopping.")
                break

            sleep(random.uniform(2, 4))

    except Exception as e:
        logging.warning(f"Error scraping Indeed: {e}")

    return jobs


def get_job_description(url, session):
    """Get the full job description from an Indeed job page."""
    try:
        driver = session.load_page(url)
        if not driver:
            return DescriptionResult()
        try:
            description_divs = driver.find_elements(By.ID, "jobDescriptionText")
            if description_divs:
                description_div = description_divs[0] if isinstance(description_divs, list) else description_divs
                return DescriptionResult(description=(description_div.get_attribute('textContent') or '').strip())
        except Exception as e:
            logging.info(f"Error finding job description: {e}")
            return DescriptionResult()
    except Exception as e:
        logging.info(f"Error loading page: {e}")
        return DescriptionResult()

    return DescriptionResult()
