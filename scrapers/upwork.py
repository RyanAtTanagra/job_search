import re
import logging
from urllib.parse import urljoin

from selenium.webdriver.common.by import By

from models import Job, DescriptionResult
from salary import get_salary_from_text


def scrape(base_url, session):
    """Scrape Upwork job listings. Returns list of Job objects."""
    jobs = []
    current_page = 1

    try:
        while True:
            page_url = f"{base_url}&page={current_page}"
            logging.info(f"Scraping Upwork page {current_page}: {page_url}")
            driver = session.load_page(page_url)
            if not driver:
                break
            try:
                job_cards = driver.find_elements(By.CSS_SELECTOR, 'article.job-tile')
                if not job_cards:
                    break
                logging.info(f"Found {len(job_cards)} Upwork jobs")
            except Exception as e:
                logging.info(f"Error finding job cards: {e}")
                break

            for card in job_cards:
                try:
                    title_elem = card.find_element(By.CSS_SELECTOR, 'h2.job-tile-title a')
                    job_url = urljoin('https://www.upwork.com', title_elem.get_attribute('href'))
                    job_id_match = re.search(r'_~(\d+)', job_url)

                    job = Job(
                        id=int(job_id_match.group(1)) if job_id_match else None,
                        url=job_url,
                        title=(title_elem.get_attribute('textContent') or '').strip(),
                        company="Unknown Company"
                    )

                    price_elem = card.find_element(By.CSS_SELECTOR, '[data-test="job-type-label"]')
                    job.salary_text = (price_elem.get_attribute('textContent') or '').strip() if price_elem else None
                    job.highest_salary = get_salary_from_text(job.salary_text) if job.salary_text else None

                    jobs.append(job)
                    logging.info(job.url)

                except Exception as e:
                    logging.error(f"Error processing job card: {e}")
                    continue

            if len(job_cards) == 0:
                break

            current_page += 1
            if current_page > 20:
                break

    except Exception as e:
        logging.error(f"Error scraping Upwork jobs: {e}")

    return jobs


def get_job_description(url, session):
    """Get the full job description from an Upwork job page."""
    try:
        driver = session.load_page(url, skip_cloudflare_detection=True)
        if not driver:
            return DescriptionResult()

        # Check for private listing
        try:
            private_check = driver.find_element(
                By.XPATH, "//h4[contains(text(), 'This job is a private listing')]"
            )
            if private_check:
                logging.info("Found private listing")
                return DescriptionResult(description="private")
        except Exception:
            pass

        description_element = driver.find_element(By.CSS_SELECTOR, "p.text-body-sm")
        if description_element:
            return DescriptionResult(description=(description_element.get_attribute('textContent') or '').strip())

        return DescriptionResult()

    except Exception as e:
        logging.error(f"Error extracting job description: {e}")
        return DescriptionResult()
