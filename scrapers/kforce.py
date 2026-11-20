import logging
from time import sleep

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from models import Job, DescriptionResult
from salary import get_salary_from_text


def scrape(url, session):
    """Scrape Kforce job listings. Returns list of Job objects."""
    jobs = []

    try:
        logging.info(f"Scraping Kforce page: {url}")
        driver = session.load_page(url, load_more=True)
        if not driver:
            return jobs
        try:
            job_cards = driver.find_elements(By.CSS_SELECTOR, "ul.data-jobs li")
            logging.info(f"Found {len(job_cards)} Kforce jobs")
        except Exception as e:
            logging.info(f"Error finding job cards: {e}")
            return jobs

        for card in job_cards:
            try:
                job_link = card.find_element(By.CSS_SELECTOR, "h2 a.linkForJob")
                href = job_link.get_attribute("href")
                title = (job_link.get_attribute('textContent') or '').strip()
                job = Job(
                    id=href.split("/detail/")[1].rstrip("/") if "/detail/" in href else None,
                    url=href,
                    title=title,
                    company="Kforce"
                )
                jobs.append(job)

            except Exception as e:
                logging.info(f"Error processing job card: {e}")
                continue

    except Exception as e:
        logging.warning(f"Error scraping Kforce: {e}")

    return jobs


def get_job_description(url, session):
    """Get the full job description from a Kforce job page."""
    try:
        driver = session.load_page(url, skip_cloudflare_detection=True)
        if not driver:
            return DescriptionResult()
        sleep(2)

        try:
            try:
                salary_block = driver.find_element(
                    By.XPATH,
                    "//span[contains(@class, 'c-orange') and contains(text(), 'Compensation:')]/parent::h4"
                )
            except NoSuchElementException:
                salary_block = None
            salary_text = (salary_block.get_attribute('textContent') or '').strip() if salary_block else None
            highest_salary = get_salary_from_text(salary_text) if salary_text else None

            description = None
            desc_elems = driver.find_elements(By.CSS_SELECTOR, "div.data-job-desc")
            if desc_elems:
                description = (driver.execute_script(
                    'return arguments[0].textContent', desc_elems[0]
                ) or '').strip()

            return DescriptionResult(description=description, salary=highest_salary)

        except Exception as e:
            logging.info(f"Error finding description div: {e}")
            return DescriptionResult()

    except Exception as e:
        logging.info(f"Error loading page: {e}")
        return DescriptionResult()
