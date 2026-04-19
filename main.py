import argparse
import logging
from time import sleep, time

from config import load_config, load_secrets
from models import DescriptionResult
from scrapers import SCRAPERS
from salary import get_salary_from_text, get_salary_from_description
from ai import get_company_from_description, get_fitness_rating, get_cover_letter
from db import check_if_seen, mark_as_seen
from notifications import send_email
from browser import setup_ulimits


def print_metrics_realtime(metrics, current_idx, total_jobs):
    """Print metrics in real-time, updating the same lines."""
    print(f"\033[2K\rProcessing {current_idx}/{total_jobs}")
    print(f"\033[2K\r{metrics['seen_count']} already seen")
    print(f"\033[2K\r{metrics['salary_count']} with no or low salary")
    print(f"\033[2K\r{metrics['fitness_count']} with a bad fit")
    print(f"\033[2K\r{metrics['description_count']} failed to get description")
    print(f"\033[2K\r{metrics['valid_count']} potential jobs sent")
    print("\033[6A", end="")


def print_metrics_final(metrics):
    """Print final metrics summary."""
    for i in range(6):
        print(f"\033[2K")
    print(f"\033[6A", end="")

    print(f"{metrics['seen_count']} already seen")
    print(f"{metrics['salary_count']} with no or low salary")
    print(f"{metrics['fitness_count']} with a bad fit")
    print(f"{metrics['description_count']} failed to get description")
    print(f"{metrics['valid_count']} potential jobs sent")
    print()


def _scrape_board(board, config, secrets):
    """Run the scraper for a board, handling remote/hybrid variants."""
    scrape_fn, _ = SCRAPERS[board]
    board_config = config['searches'][board]
    browser_config = config['browser']
    headless_flag = not config.get('_head', False)
    debug_flag = config.get('_debug', False)
    user_data_dir = browser_config.get('user_data_dir')

    if board == "linkedin":
        # LinkedIn uses API, not Selenium — pass credentials instead of browser args
        if 'remote' in board_config and 'hybrid' in board_config:
            jobs_remote = scrape_fn(
                board_config['remote'],
                secrets['linkedin_email'], secrets['linkedin_password']
            ) or []
            jobs_hybrid = scrape_fn(
                board_config['hybrid'],
                secrets['linkedin_email'], secrets['linkedin_password']
            ) or []
            return jobs_remote + jobs_hybrid
        else:
            return scrape_fn(
                board_config['url'],
                secrets['linkedin_email'], secrets['linkedin_password']
            )
    else:
        # Selenium-based scrapers
        if 'remote' in board_config and 'hybrid' in board_config:
            jobs_remote = scrape_fn(
                board_config['remote'],
                headless=headless_flag, debug=debug_flag,
                user_data_dir=user_data_dir
            ) or []
            jobs_hybrid = scrape_fn(
                board_config['hybrid'],
                headless=headless_flag, debug=debug_flag,
                user_data_dir=user_data_dir
            ) or []
            return jobs_remote + jobs_hybrid
        else:
            return scrape_fn(
                board_config['url'],
                headless=headless_flag, debug=debug_flag,
                user_data_dir=user_data_dir
            )


def _get_description(board, job, config, secrets):
    """Get job description, handling LinkedIn's special API case."""
    _, get_desc_fn = SCRAPERS[board]
    browser_config = config['browser']
    headless_flag = not config.get('_head', False)
    debug_flag = config.get('_debug', False)
    user_data_dir = browser_config.get('user_data_dir')

    if board == "linkedin":
        sleep(1)
        job_details = get_desc_fn(
            job.id, secrets['linkedin_email'], secrets['linkedin_password']
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
        result = get_desc_fn(
            job.url,
            headless=headless_flag, debug=debug_flag,
            user_data_dir=user_data_dir
        )
        if isinstance(result, DescriptionResult):
            job.description = result.description
            if result.salary:
                job.highest_salary = result.salary
        else:
            job.description = result


def search_board(board, config, secrets, progress=False):
    """Search a job board, score jobs, and email good matches."""
    dry_run = config.get('_dry_run', False)

    jobs = _scrape_board(board, config, secrets)
    if not jobs:
        print(f"No {board} search results")
        return

    print("Found", len(jobs), board, "jobs")

    if dry_run:
        # Print first few jobs, try fetching one description, then return
        for i, job in enumerate(jobs[:5]):
            print(f"  [{i+1}] {job.title or 'No title'} | {job.company or 'No company'} | salary: {job.highest_salary or 'N/A'}")
            print(f"      id={job.id}")
            print(f"      url={job.url}")
        if jobs:
            print(f"\nFetching description for first job...")
            _get_description(board, jobs[0], config, secrets)
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
        "description_count": 0,
        "salary_count": 0,
        "fitness_count": 0,
        "valid_count": 0,
    }

    for idx, job in enumerate(jobs):
        if progress:
            print_metrics_realtime(metrics, idx, len(jobs))

        if not job.id:
            logging.info(f"No job id: {job.id}")
            continue
        if isinstance(job.id, str) and len(job.id) > 2048:
            logging.info(f"Job id too long: {job.id}")
            continue

        if check_if_seen(f"{board}_jobs", 'job_id', job.id):
            logging.info(f"{board} job {job.id} already seen")
            metrics["seen_count"] += 1
            continue

        logging.info(job.url)
        sleep(1)

        _get_description(board, job, config, secrets)

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
            mark_as_seen(f"{board}_jobs", 'job_id', job.id)
            metrics["description_count"] += 1
            continue

        if not job.highest_salary:
            job.highest_salary = get_salary_from_description(job.description)

        if job.highest_salary is None:
            logging.info("No salary information found")
            mark_as_seen(f"{board}_jobs", 'job_id', job.id)
            metrics["salary_count"] += 1
            continue

        if job.highest_salary < thresholds['annual_salary']:
            logging.info(f"Salary below threshold: {job.highest_salary}")
            mark_as_seen(f"{board}_jobs", 'job_id', job.id)
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
                continue

            if job.fitness < thresholds['fitness_score']:
                logging.info(f"Fitness score below threshold: {job.fitness}")
                mark_as_seen(f"{board}_jobs", 'job_id', job.id)
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
            mark_as_seen(f"{board}_jobs", 'job_id', job.id)
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
