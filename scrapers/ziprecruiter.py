import hashlib
import logging

from selenium.webdriver.common.by import By

from models import Job, DescriptionResult
from salary import get_salary_from_text


def scrape(base_url, session):
    """Scrape ZipRecruiter job listings. Returns list of Job objects."""
    jobs = []
    current_page = 1

    try:
        while True:
            page_url = f"{base_url}&page={current_page}"
            logging.info(f"Scraping Ziprecruiter page {current_page}...")

            driver = session.load_page(page_url)
            if not driver:
                logging.info("Failed to load page")
                break

            job_cards = driver.find_elements(
                By.CSS_SELECTOR, ".job_result_two_pane, .job_result_two_pane_v2"
            )
            logging.info(f"Found {len(job_cards)} jobs")

            if not job_cards:
                break

            for card in job_cards:
                try:
                    article = card.find_element(By.TAG_NAME, "article")
                    article_id = article.get_attribute("id")
                    if not article_id:
                        continue

                    job_id = (article_id.replace("job-card-", "")
                              if article_id.startswith("job-card-") else article_id)

                    # Title
                    try:
                        title_button = card.find_element(By.CSS_SELECTOR, "button[type='button'] h2")
                        title = title_button.get_attribute("aria-label") or (title_button.get_attribute('textContent') or '').strip()
                        title = title.replace("NEW!", "").strip()
                    except Exception:
                        title = None

                    # Company
                    try:
                        company_elem = card.find_element(
                            By.CSS_SELECTOR, "a[data-testid='job-card-company']"
                        )
                        company = (company_elem.get_attribute('textContent') or '').strip()
                    except Exception:
                        company = None

                    # URL
                    job_url = None
                    try:
                        apply_link = card.find_element(By.CSS_SELECTOR, "a[aria-label='Apply']")
                        job_url = apply_link.get_attribute('href')
                    except Exception:
                        if company and title and job_id:
                            company_slug = (company.lower().replace(' ', '-')
                                            .replace(',', '').replace('.', '').replace('&', 'and'))
                            title_slug = (title.lower().replace(' ', '-')
                                          .replace(',', '').replace('.', ''))
                            company_hash = hashlib.md5(company_slug.encode()).hexdigest()[:8]
                            title_hash = hashlib.md5(title_slug.encode()).hexdigest()[:8]
                            job_url = (f"https://www.ziprecruiter.com/jobs/"
                                       f"{company_slug}-{company_hash}/"
                                       f"{title_slug}-{title_hash}?lvk={job_id}")

                    if company and title:
                        formatted_id = f"{company}_{title}".lower().strip()
                    else:
                        formatted_id = job_id

                    job = Job(
                        id=formatted_id,
                        url=job_url,
                        company=company,
                        title=title
                    )

                    # Salary — find the <p> element containing a dollar sign
                    job.salary_text = None
                    for p_elem in card.find_elements(By.TAG_NAME, "p"):
                        text = (p_elem.get_attribute('textContent') or '').strip()
                        if '$' in text:
                            job.salary_text = text
                            break

                    job.highest_salary = get_salary_from_text(job.salary_text) if job.salary_text else None
                    jobs.append(job)

                except Exception as e:
                    logging.info(f"Error parsing job listing: {str(e)}")
                    continue

            # Check for next page
            try:
                next_button = driver.find_element(By.CSS_SELECTOR, "[title='Next Page']")
                if not (next_button and next_button.is_enabled()
                        and "opacity-[.45]" not in next_button.get_attribute("class")):
                    logging.info("No more pages available")
                    break
            except Exception:
                logging.info("No pagination found")
                break

            current_page += 1
            if current_page > 50:
                break

    except Exception as e:
        logging.warning(f"Error scraping ZipRecruiter: {str(e)}")

    return jobs


def get_job_description(url, session):
    """Get the full job description from a ZipRecruiter job page."""
    try:
        driver = session.load_page(url)
        if not driver:
            return DescriptionResult()

        try:
            # ZipRecruiter shows job details in a right-pane SPA; description
            # follows the "Job description" heading
            desc_div = driver.find_element(
                By.XPATH,
                "//h2[contains(text(),'Job description')]/following-sibling::div[1]"
            )
            if not desc_div:
                return DescriptionResult()
            return DescriptionResult(description=(desc_div.get_attribute('textContent') or '').strip())
        except Exception as e:
            logging.info(f"Error finding description div: {e}")
            return DescriptionResult()

    except Exception as e:
        logging.info(f"Error scraping job description: {str(e)}")
        return DescriptionResult()
