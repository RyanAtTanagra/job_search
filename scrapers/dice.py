import logging
from time import sleep

from selenium.webdriver.common.by import By

from models import Job, DescriptionResult
from browser import load_page
from salary import get_salary_from_text


def scrape(base_url, headless=True, debug=False, user_data_dir=None):
    """Scrape Dice job listings. Returns list of Job objects."""
    jobs = []
    current_page = 1
    driver = None

    try:
        while True:
            page_url = f"{base_url}&page={current_page}"
            logging.info(f"Scraping Dice page {current_page}: {page_url}")
            driver = load_page(page_url, headless=headless, debug=debug,
                               user_data_dir=user_data_dir)

            # Try newer CSS elements first
            job_cards = driver.find_elements(By.CSS_SELECTOR, "div[data-id]")
            logging.info(f"Found {len(job_cards)} Dice jobs")

            # Fall back to older elements
            if not job_cards:
                try:
                    job_cards = driver.find_elements(By.CSS_SELECTOR, "dhi-search-card")
                    if not job_cards:
                        break
                    logging.info(f"Found {len(job_cards)} Dice jobs")
                except Exception as e:
                    logging.info(f"Error finding job cards: {e}")
                    break

            for card in job_cards:
                try:
                    job_id = card.get_attribute('data-id')
                    title_link = card.find_element(
                        By.CSS_SELECTOR, "a[data-testid='job-search-job-detail-link']"
                    )
                    # Dice hides text from .text but textContent works
                    title = (title_link.get_attribute('textContent') or '').strip()
                    company_element = card.find_element(
                        By.CSS_SELECTOR, "a[href*='company-profile'] p"
                    )
                    company = (company_element.get_attribute('textContent') or '').strip()
                    url = title_link.get_attribute('href')

                    job = Job(
                        id=f"{company}_{title}".lower().strip(),
                        url=url,
                        title=title,
                        company=company
                    )
                    jobs.append(job)

                except Exception as e:
                    print(f"Error processing job card: {e}")
                    continue

            driver.quit()
            driver = None

            if len(job_cards) < 20:
                break

            current_page += 1

    except Exception as e:
        logging.info(f"Error scraping Dice: {e}")

    finally:
        if driver:
            driver.quit()

    return jobs


def get_job_description(url, headless=True, debug=False, user_data_dir=None):
    """Get the full job description from a Dice job page."""
    driver = None
    try:
        driver = load_page(url, headless=headless, debug=debug,
                           skip_cloudflare_detection=True, user_data_dir=user_data_dir)
        if not driver:
            return DescriptionResult()

        sleep(2)  # Wait for dynamic content to render

        # Salary
        highest_salary = None
        try:
            salary_element = driver.find_element(By.CSS_SELECTOR, "div[data-cy='payDetails'] span")
            salary_text = (salary_element.get_attribute('textContent') or '').strip()
            highest_salary = get_salary_from_text(salary_text) if salary_text else None
        except Exception:
            logging.info("Error finding salary div")

        # Description — Dice uses CSS module hashes in class names
        description = None
        try:
            description_element = driver.find_element(
                By.CSS_SELECTOR, '[class*="jobDescription"]'
            )
            description = (driver.execute_script(
                'return arguments[0].textContent', description_element
            ) or '').strip()
        except Exception:
            pass

        return DescriptionResult(description=description, salary=highest_salary)

    except Exception as e:
        logging.info(f"Error loading page: {e}")
        return DescriptionResult()

    finally:
        if driver:
            driver.quit()
