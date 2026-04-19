import logging
from models import Job
from utils.linkedin_api import Linkedin


def scrape(search_params, linkedin_email, linkedin_password):
    """Search LinkedIn jobs via API. Returns list of Job objects."""
    jobs = []
    try:
        api = Linkedin(linkedin_email, linkedin_password)
    except Exception as e:
        print(f"Error connecting to LinkedIn to get search results. Details: {e}")
        return None

    job_cards = api.search_jobs(**search_params)
    if len(job_cards) < 1:
        print("No search results")
        return None

    logging.info(f"Found {len(job_cards)} LinkedIn jobs")
    for card in job_cards:
        try:
            job_id = int(card['trackingUrn'].split(":")[-1])
            job = Job(
                id=job_id,
                url=f"https://www.linkedin.com/jobs/view/{job_id}"
            )
            jobs.append(job)
        except Exception as e:
            logging.info(f"Error processing job card: {e}")
            continue

    return jobs


def get_job_details(job_id, linkedin_email, linkedin_password):
    """Get job details via LinkedIn API. Returns raw API dict (not DescriptionResult).

    The dict may contain: description, title, salary, salary_period.
    LinkedIn is handled specially in search_board because the API returns
    richer data than a simple description.
    """
    try:
        api = Linkedin(linkedin_email, linkedin_password)
    except Exception as e:
        logging.info(f"Error connecting to LinkedIn to get job description")
        return None

    return api.get_job_description(job_id)
