from . import linkedin, indeed, upwork, insight, ziprecruiter, cybercoders, dice, monster, kforce

# Maps board name -> (scrape_function, get_description_function)
# Replaces the old globals() dispatch pattern
SCRAPERS = {
    "linkedin": (linkedin.scrape, linkedin.get_job_details),
    "indeed": (indeed.scrape, indeed.get_job_description),
    "upwork": (upwork.scrape, upwork.get_job_description),
    "insight": (insight.scrape, insight.get_job_description),
    "ziprecruiter": (ziprecruiter.scrape, ziprecruiter.get_job_description),
    "cybercoders": (cybercoders.scrape, cybercoders.get_job_description),
    "dice": (dice.scrape, dice.get_job_description),
    "monster": (monster.scrape, monster.get_job_description),
    "kforce": (kforce.scrape, kforce.get_job_description),
}
