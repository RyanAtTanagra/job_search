import logging

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from models import Job, DescriptionResult
from browser import load_page
from salary import get_salary_from_text


def scrape(url, headless=True, debug=False, user_data_dir=None):
    """Scrape Monster job listings. Returns list of Job objects."""
    jobs = []
    driver = None

    try:
        logging.info(f"Scraping Monster page: {url}")
        driver = load_page(url, headless=headless, debug=debug,
                           load_more=True, user_data_dir=user_data_dir)
        try:
            job_cards = driver.find_elements(By.CSS_SELECTOR, "article[data-testid='JobCard']")
            if not job_cards:
                return jobs
            logging.info(f"Found {len(job_cards)} Monster jobs")
        except Exception as e:
            logging.info(f"Error finding job cards: {e}")
            return jobs

        for card in job_cards:
            try:
                job = Job(
                    id=card.find_element(By.CSS_SELECTOR, "button[data-job-id]").get_attribute("data-job-id"),
                    url=card.find_element(By.CSS_SELECTOR, "a[data-testid='jobTitle']").get_attribute('href'),
                    title=(card.find_element(By.CSS_SELECTOR, "a[data-testid='jobTitle']").get_attribute('textContent') or '').strip(),
                    company=(card.find_element(By.CSS_SELECTOR, "span[data-testid='company']").get_attribute('textContent') or '').strip()
                )
                logging.info(job.url)

                salary_block = (card.find_elements(By.CSS_SELECTOR, "div[data-tagtype-testid='payTag']") or [None])[0]
                job.salary_text = (salary_block.get_attribute('textContent') or '').strip() if salary_block else None
                job.highest_salary = get_salary_from_text(job.salary_text) if job.salary_text else None

                jobs.append(job)

            except Exception as e:
                logging.info(f"Error processing job card: {e}")
                continue

    except Exception as e:
        logging.info(f"Error scraping Monster: {e}")

    finally:
        if driver:
            driver.quit()

    return jobs


def get_job_description(url, headless=True, debug=False, user_data_dir=None):
    """Get the full job description from a Monster job page."""
    driver = None
    try:
        driver = load_page(url, headless=headless, debug=debug,
                           skip_cloudflare_detection=True, user_data_dir=user_data_dir)
        try:
            json_data = driver.execute_script(
                'return JSON.parse(document.getElementById("__NEXT_DATA__").textContent)'
            )
            description = json_data['props']['pageProps']['jobViewResultsData']['jobPosting']['description']
            driver.execute_script("document.body.innerHTML = arguments[0];", description)
            description_text = (driver.find_element(By.TAG_NAME, "body").get_attribute('textContent') or '').strip()
            if description_text:
                return DescriptionResult(description=description_text.strip())
        except Exception as e:
            logging.info(f"Error finding description div: {e}")
            return DescriptionResult()

    except Exception as e:
        logging.info(f"Error loading page: {e}")
        return DescriptionResult()

    finally:
        if driver:
            driver.quit()

    return DescriptionResult()
