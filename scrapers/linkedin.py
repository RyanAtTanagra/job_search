import logging
from time import time

from requests.cookies import RequestsCookieJar

from models import Job
from browser import BrowserSession
from utils.linkedin_api import Linkedin

# One authenticated client per set of credentials, reused for the whole run
_api_cache = {}


def _cookies_from_browser(user_data_dir):
    """Pull a LinkedIn session out of the script's Chrome profile.

    Password auth from a script gets blocked by LinkedIn's CHALLENGE flow, but
    a session established in a real browser works: log into linkedin.com in
    the profile browser (see README "Browser Profile"), then this lifts the
    li_at/JSESSIONID cookies for the API client. Returns None if the profile
    isn't logged in.
    """
    logging.warning("Extracting LinkedIn session cookies from Chrome profile")
    with BrowserSession(headless=True, user_data_dir=user_data_dir) as session:
        driver = session.load_page(
            "https://www.linkedin.com/feed/", skip_cloudflare_detection=True
        )
        if not driver:
            return None
        cookies = driver.get_cookies()

    names = {c['name'] for c in cookies}
    if 'li_at' not in names or 'JSESSIONID' not in names:
        return None

    # Chrome reports JSESSIONID as a session cookie (no expiry), but the
    # linkedin_api jar validity check requires a future expiry on it —
    # without one the jar is considered expired on every run. Borrow li_at's
    # expiry (or 30 days) for any cookie that lacks its own.
    li_at_expiry = next(
        (c.get('expiry') for c in cookies if c['name'] == 'li_at' and c.get('expiry')),
        int(time() + 30 * 86400)
    )
    jar = RequestsCookieJar()
    for c in cookies:
        jar.set(
            c['name'], c['value'],
            domain=c.get('domain'), path=c.get('path', '/'),
            expires=c.get('expiry') or li_at_expiry,
        )
    return jar


def _get_api(linkedin_email, linkedin_password, user_data_dir=None):
    key = (linkedin_email, linkedin_password)
    if key in _api_cache:
        return _api_cache[key]

    api = None
    try:
        api = Linkedin(linkedin_email, linkedin_password)
    except Exception as e:
        # Expired cookie jars raise LinkedinSessionExpired and fresh password
        # auth usually hits LinkedIn's CHALLENGE flow — fall back to the
        # session cookies from the Chrome profile
        logging.warning(
            f"LinkedIn auth failed ({type(e).__name__}: {e}), "
            f"trying session cookies from the browser profile"
        )
        jar = _cookies_from_browser(user_data_dir)
        if jar is None:
            raise Exception(
                "LinkedIn login required: open Chrome with the script's profile "
                "(see README 'Browser Profile'), log into linkedin.com, then rerun"
            )
        api = Linkedin(linkedin_email, linkedin_password, cookies=jar)
        # Persist the jar so future runs skip the browser hop
        try:
            api.client._cookie_repository.save(jar, linkedin_email)
        except Exception as save_err:
            logging.warning(f"Couldn't cache LinkedIn cookies: {save_err}")

    _api_cache[key] = api
    return api


def scrape(search_params, linkedin_email, linkedin_password, user_data_dir=None):
    """Search LinkedIn jobs via API. Returns list of Job objects."""
    jobs = []
    try:
        api = _get_api(linkedin_email, linkedin_password, user_data_dir)
    except Exception as e:
        print(f"Error connecting to LinkedIn to get search results. Details: {type(e).__name__}: {e}")
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


def get_job_details(job_id, linkedin_email, linkedin_password, user_data_dir=None):
    """Get job details via LinkedIn API. Returns raw API dict (not DescriptionResult).

    The dict may contain: description, title, salary, salary_period.
    LinkedIn is handled specially in search_board because the API returns
    richer data than a simple description.
    """
    try:
        api = _get_api(linkedin_email, linkedin_password, user_data_dir)
    except Exception as e:
        logging.warning(f"Error connecting to LinkedIn to get job description: {e}")
        return None

    return api.get_job_description(job_id)
