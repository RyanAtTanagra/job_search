import argparse
import logging
from time import sleep, time

from config import load_config, load_secrets
from models import DescriptionResult
from scrapers import SCRAPERS
from salary import get_salary_from_text, get_salary_from_description
from ai import get_company_from_description, get_fitness_rating, get_cover_letter
from db import batch_check_seen, check_if_seen, mark_as_seen
from notifications import send_email
from browser import setup_ulimits, BrowserSession


def print_metrics_realtime(metrics, current_idx, total_jobs):
    """Print metrics in real-time, updating the same lines."""
    print(f"\033[2K\rProcessing {current_idx}/{total_jobs}")
    print(f"\033[2K\r{metrics['seen_count']} already seen")
    print(f"\033[2K\r{metrics['skipped_count']} skipped (no job id)")
    print(f"\033[2K\r{metrics['salary_count']} with no or low salary")
    print(f"\033[2K\r{metrics['fitness_count']} with a bad fit")
    print(f"\033[2K\r{metrics['description_count']} failed to get description")
    print(f"\033[2K\r{metrics['valid_count']} potential jobs sent")
    print("\033[7A", end="")


def print_metrics_final(metrics):
    """Print final metrics summary."""
    for i in range(7):
        print(f"\033[2K")
    print(f"\033[7A", end="")

    print(f"{metrics['seen_count']} already seen")
    print(f"{metrics['skipped_count']} skipped (no job id)")
    print(f"{metrics['salary_count']} with no or low salary")
    print(f"{metrics['fitness_count']} with a bad fit")
    print(f"{metrics['description_count']} failed to get description")
    print(f"{metrics['valid_count']} potential jobs sent")
    print()


def _scrape_board(board, config, secrets, session):
    """Run the scraper for a board, handling remote/hybrid variants."""
    scrape_fn, _ = SCRAPERS[board]
    board_config = config['searches'][board]

    if board == "linkedin":
        # LinkedIn uses API, not Selenium — pass credentials instead of a
        # session (user_data_dir enables the browser-cookie auth fallback)
        creds = (secrets['linkedin_email'], secrets['linkedin_password'])
        user_data_dir = config['browser'].get('user_data_dir')
        if 'remote' in board_config and 'hybrid' in board_config:
            jobs_remote = scrape_fn(board_config['remote'], *creds,
                                    user_data_dir=user_data_dir) or []
            jobs_hybrid = scrape_fn(board_config['hybrid'], *creds,
                                    user_data_dir=user_data_dir) or []
            return jobs_remote + jobs_hybrid
        return scrape_fn(board_config['url'], *creds, user_data_dir=user_data_dir)

    if 'remote' in board_config and 'hybrid' in board_config:
        jobs_remote = scrape_fn(board_config['remote'], session) or []
        jobs_hybrid = scrape_fn(board_config['hybrid'], session) or []
        return jobs_remote + jobs_hybrid
    return scrape_fn(board_config['url'], session)


def _get_description(board, job, config, secrets, session):
    """Get job description, handling LinkedIn's special API case."""
    _, get_desc_fn = SCRAPERS[board]

    if board == "linkedin":
        sleep(1)
        job_details = get_desc_fn(
            job.id, secrets['linkedin_email'], secrets['linkedin_password'],
            user_data_dir=config['browser'].get('user_data_dir')
        )
        if job_details is None:
            job.description = None
        else:
            job.description = job_details.get('description', None)
            job.title = job_details.get('title', None)
            salary = int(float(job_details.get('salary') or 0))
            salary_period = job_details.get('salary_period') or None
            job.salary_text = f"{salary} {salary_period}"
            job.highest_salary = get_salary_from_text(job.salary_text) if job.salary_text else None
    else:
        result = get_desc_fn(job.url, session)
        if isinstance(result, DescriptionResult):
            job.description = result.description
            if result.salary:
                job.highest_salary = result.salary
        else:
            job.description = result


def _valid_job_id(job_id):
    if not job_id:
        return False
    if isinstance(job_id, str) and len(job_id) > 2048:
        return False
    return True


def search_board(board, config, secrets, progress=False):
    """Search a job board, score jobs, and email good matches."""
    if progress:
        print(f"Searching {board} (scraping is silent — this can take a few minutes per board)...", flush=True)
    if board == "linkedin":
        _search_board(board, config, secrets, progress, session=None)
        return

    browser_config = config['browser']
    with BrowserSession(
        headless=not config.get('_head', False),
        debug=config.get('_debug', False),
        user_data_dir=browser_config.get('user_data_dir'),
        reconnect_seconds=browser_config.get('reconnect_seconds', 10),
    ) as session:
        _search_board(board, config, secrets, progress, session)


def _search_board(board, config, secrets, progress, session):
    dry_run = config.get('_dry_run', False)

    jobs = _scrape_board(board, config, secrets, session)
    if not jobs:
        print(f"No {board} search results")
        return

    print("Found", len(jobs), board, "jobs")

    if dry_run:
        # Print first few jobs, try fetching one description, then return
        missing_ids = sum(1 for job in jobs if not _valid_job_id(job.id))
        if missing_ids:
            print(f"  WARNING: {missing_ids}/{len(jobs)} jobs have no usable job id (would be skipped)")
        for i, job in enumerate(jobs[:5]):
            print(f"  [{i+1}] {job.title or 'No title'} | {job.company or 'No company'} | salary: {job.highest_salary or 'N/A'}")
            print(f"      id={job.id}")
            print(f"      url={job.url}")
        if jobs:
            print(f"\nFetching description for first job...")
            _get_description(board, jobs[0], config, secrets, session)
            if jobs[0].description:
                desc_preview = jobs[0].description[:200].replace('\n', ' ')
                print(f"  Description: {desc_preview}...")
                if jobs[0].highest_salary:
                    print(f"  Salary from description: {jobs[0].highest_salary}")
            else:
                print(f"  Could not fetch description")
        return

    thresholds = config['thresholds']
    email_config = config['email']
    api_key = secrets['anthropic_api_key']
    mail_to = email_config['to']
    from_domain = email_config['from_domain']

    metrics = {
        "seen_count": 0,
        "skipped_count": 0,
        "description_count": 0,
        "salary_count": 0,
        "fitness_count": 0,
        "valid_count": 0,
    }

    # One batched lookup instead of a DynamoDB query per job
    seen_ids = batch_check_seen(
        f"{board}_jobs", 'job_id',
        [job.id for job in jobs if _valid_job_id(job.id)]
    )

    def _mark_seen(job_id):
        # Track locally too so a duplicate later in this run (remote+hybrid
        # overlap) is treated as seen
        mark_as_seen(f"{board}_jobs", 'job_id', job_id)
        seen_ids.add(job_id)

    for idx, job in enumerate(jobs):
        if progress:
            print_metrics_realtime(metrics, idx, len(jobs))

        if not _valid_job_id(job.id):
            logging.info(f"Invalid job id: {job.id}")
            metrics["skipped_count"] += 1
            continue

        if job.id in seen_ids:
            logging.info(f"{board} job {job.id} already seen")
            metrics["seen_count"] += 1
            continue

        # If the listing card already showed a below-threshold salary, skip
        # the (expensive) description fetch entirely
        if job.highest_salary and job.highest_salary < thresholds['annual_salary']:
            logging.info(f"Card salary below threshold: {job.highest_salary}")
            _mark_seen(job.id)
            metrics["salary_count"] += 1
            continue

        logging.info(job.url)
        sleep(1)

        _get_description(board, job, config, secrets, session)

        if job.description is None:
            logging.info("Couldn't find job description")
            metrics["description_count"] += 1
            continue

        if job.description == "private":
            logging.info("Couldn't find job description, possibly private, emailing URL")
            email_body = f"Private {board} listing:\n{job.url}"
            send_email(
                f"Python {board} Search <python@{from_domain}>",
                mail_to, f"Private {board} listing", email_body
            )
            _mark_seen(job.id)
            metrics["description_count"] += 1
            continue

        if not job.highest_salary:
            job.highest_salary = get_salary_from_description(job.description)

        if job.highest_salary is None:
            logging.info("No salary information found")
            _mark_seen(job.id)
            metrics["salary_count"] += 1
            continue

        if job.highest_salary < thresholds['annual_salary']:
            logging.info(f"Salary below threshold: {job.highest_salary}")
            _mark_seen(job.id)
            metrics["salary_count"] += 1
        else:
            if not job.company:
                job.company = get_company_from_description(
                    job.description, api_key, config['ai']['model']
                )

            # LinkedIn spam dedup: check company+title combo
            if board == "linkedin" and job.company:
                job_id2 = f"{job.company}_{job.title}".lower().strip()
                if check_if_seen(f"{board}_spam", 'job_id', job_id2):
                    logging.info(f"{board} job {job_id2} already seen")
                    metrics["seen_count"] += 1
                    continue
                else:
                    mark_as_seen(f"{board}_spam", 'job_id', job_id2)

            job.fitness = get_fitness_rating(
                job.description, job.company, job.title, config, api_key
            )

            if job.fitness is None:
                # API error — leave unmarked so it's retried next run
                logging.warning(f"No fitness score for {job.url}, will retry next run")
                continue

            if job.fitness < thresholds['fitness_score']:
                logging.info(f"Fitness score below threshold: {job.fitness}")
                _mark_seen(job.id)
                metrics["fitness_count"] += 1
                continue

            email_body = (f"{job.company} - {job.title}\n{job.url}\n"
                          f"salary: {job.highest_salary}/yr\nfitness: {job.fitness}")
            logging.info(email_body)

            cover_letter_path = get_cover_letter(
                job.company, job.title, job.description, config, api_key
            )
            send_email(
                f"Python {board} Search <python@{from_domain}>",
                mail_to, f"{job.company} - {job.title}",
                email_body, cover_letter_path
            )
            _mark_seen(job.id)
            metrics["valid_count"] += 1

    print_metrics_final(metrics)


if __name__ == "__main__":
    start_time = time()

    parser = argparse.ArgumentParser(
        description="Search job boards, score against resume, and email matches",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "website",
        choices=list(SCRAPERS.keys()) + ['all', 'selenium'],
        help="Website to search, or 'all', or 'selenium' for browser-based boards"
    )
    parser.add_argument("--cron", action="store_true",
                        help="Suppress progress output for cron jobs")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging")
    parser.add_argument("--head", action="store_true",
                        help="Run Chrome in the foreground")
    parser.add_argument("--config", default="config.yaml",
                        help="Path to config file (default: config.yaml)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Test scraping only: skip DB, AI, and email")
    args = parser.parse_args()

    config = load_config(args.config)
    secrets = load_secrets()

    # Store runtime flags in config for easy passing
    config['_head'] = args.head
    config['_debug'] = args.debug
    config['_dry_run'] = args.dry_run

    progress = not args.cron

    logging.basicConfig(
        level=logging.INFO if args.debug else logging.WARN,
        filename="debug.log",
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    setup_ulimits(config['browser'].get('ulimit_nofile', 2048))

    selenium_boards = config.get('selenium_boards', [])

    if args.website == "all":
        search_board("linkedin", config, secrets, progress)
        print("\n")
        for board in selenium_boards:
            search_board(board, config, secrets, progress)
            print("\n")
    elif args.website == "selenium":
        for board in selenium_boards:
            search_board(board, config, secrets, progress)
            print("\n")
    else:
        search_board(args.website, config, secrets, progress)

    end_time = time()
    elapsed_time = end_time - start_time
    print(f"\nScript completed in {elapsed_time:.2f} seconds")
