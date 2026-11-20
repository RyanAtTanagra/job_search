import re
import logging

from selenium.webdriver.common.by import By

from models import Job, DescriptionResult
from salary import get_salary_from_text


def scrape(base_url, session):
    """Scrape Insight Global job listings. Returns list of Job objects."""
    jobs = []
    current_page = 1

    try:
        while True:
            page_url = base_url.replace('/find_a_job/', f'/find_a_job/{current_page}/')
            logging.info(f"Scraping insight global page {current_page}: {page_url}")
            driver = session.load_page(page_url)
            if not driver:
                break
            try:
                pagination = driver.find_element(By.CLASS_NAME, "paging-container")
                result_text = pagination.find_element(By.CLASS_NAME, "h").text
                if " of " in result_text:
                    match = re.search(r'of (\d+)', result_text)
                    if match:
                        total_jobs = int(match.group(1))
                        if len(jobs) >= total_jobs:
                            logging.info(f"Reached end of listings (processed {len(jobs)} of {total_jobs} jobs)")
                            break

                job_listings = driver.find_elements(By.CLASS_NAME, "result")
                if not job_listings:
                    logging.info("No job listings found on page")
                    break
            except Exception:
                logging.info(f"Problem getting content for page: {current_page}")
                break

            for listing in job_listings:
                try:
                    title_elem = listing.find_element(By.CLASS_NAME, "job-title").find_element(By.TAG_NAME, "a")
                    job_url = title_elem.get_attribute("href")
                    job_id_match = re.search(r'job-(\d+)', job_url)
                    job = Job(
                        id=job_id_match.group(1) if job_id_match else None,
                        url=job_url,
                        title=(title_elem.get_attribute('textContent') or '').strip()
                    )
                    info_text = listing.find_element(By.CLASS_NAME, "job-info").get_attribute('textContent') or ''
                    info_parts = [
                        p.strip()
                        for p in info_text.split("|")
                    ]
                    raw_salary = info_parts[3].strip() if len(info_parts) > 3 else ""
                    # The salary text is followed by embedded JSON; take only the first line
                    job.salary_text = raw_salary.split("\n")[0].strip()
                    job.highest_salary = get_salary_from_text(job.salary_text) if job.salary_text else None
                    job.company = "Unknown Company"

                    jobs.append(job)

                except Exception as e:
                    logging.info(f"Error processing job listing: {str(e)}")
                    continue

            # Check for next page
            try:
                pagination = driver.find_element(By.CLASS_NAME, "paging-container")
                active_page = pagination.find_element(By.CLASS_NAME, "active")
                next_page = active_page.find_element(By.XPATH, "following-sibling::li[1]/a")
                if not next_page.get_attribute("href"):
                    logging.info("No link to next page found")
                    break
                current_page += 1
            except Exception:
                logging.info("No more pages available")
                break

    except Exception as e:
        logging.warning(f"Error scraping Insight Global: {str(e)}")

    return jobs


def get_job_description(url, session):
    """Get the full job description from an Insight Global job page."""
    try:
        driver = session.load_page(url, skip_cloudflare_detection=True)
        if not driver:
            return DescriptionResult()
        try:
            desc_sections = driver.find_elements(By.CLASS_NAME, "detailpage-desc")
            description_parts = []
            for section in desc_sections:
                text = (section.get_attribute('textContent') or '').strip()
                if text:
                    description_parts.append(text)
            return DescriptionResult(description="\n\n".join(description_parts))
        except Exception as e:
            logging.info(f"Error finding description div: {e}")
            return DescriptionResult()

    except Exception as e:
        logging.info(f"Error loading page: {e}")
        return DescriptionResult()
