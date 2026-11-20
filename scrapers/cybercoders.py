import logging
from time import sleep

from selenium.webdriver.common.by import By

from models import Job, DescriptionResult
from salary import get_salary_from_text


def scrape(base_url, session):
    """Scrape CyberCoders job listings. Returns list of Job objects."""
    jobs = []
    current_page = 1

    try:
        while True:
            page_url = f"{base_url}&page={current_page}"
            logging.info(f"Scraping CyberCoders page {current_page}: {page_url}")
            driver = session.load_page(page_url)
            if not driver:
                break
            try:
                job_cards = driver.find_elements(By.CLASS_NAME, "result-box")
                if not job_cards:
                    break
                logging.info(f"Found {len(job_cards)} CyberCoders jobs")
            except Exception as e:
                logging.info(f"Error finding job cards: {e}")
                break

            for card in job_cards:
                try:
                    card.click()
                    sleep(1)

                    job_link = driver.find_element(By.CSS_SELECTOR, ".job-details-header a")
                    job_url = job_link.get_attribute("href")
                    job = Job(
                        id=job_url.split('/')[-1],
                        url=job_url,
                        title=(job_link.get_attribute('textContent') or '').strip()
                    )

                    salary_block = driver.find_element(
                        By.CSS_SELECTOR, ".job-details-header .info-block.tertiary"
                    )
                    job.salary_text = (salary_block.get_attribute('textContent') or '').strip() if salary_block else None
                    job.highest_salary = get_salary_from_text(job.salary_text) if job.salary_text else None
                    job.company = "Unknown Company"

                    jobs.append(job)

                except Exception as e:
                    logging.info(f"Error processing job card: {e}")
                    continue

            if len(job_cards) == 0:
                break

            current_page += 1
            if current_page > 50:
                break

    except Exception as e:
        logging.warning(f"Error scraping CyberCoders: {e}")

    return jobs


def get_job_description(url, session):
    """Get the full job description from a CyberCoders job page."""
    try:
        driver = session.load_page(url, skip_cloudflare_detection=True)
        if not driver:
            return DescriptionResult()
        try:
            desc_div = driver.find_element(By.CLASS_NAME, "job-details-description")
            if desc_div:
                desc_text = (desc_div.get_attribute('textContent') or '').strip()
                return DescriptionResult(description=desc_text if desc_text else None)
        except Exception as e:
            logging.info(f"Error finding description div: {e}")
            return DescriptionResult()

    except Exception as e:
        logging.info(f"Error loading page: {e}")
        return DescriptionResult()

    return DescriptionResult()
