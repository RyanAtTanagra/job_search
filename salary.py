import re
import logging


def get_salary_from_text(salary_text):
    """Parse salary text and return the highest annual salary in dollars."""
    logging.info(f"salary_text: {salary_text}")
    cleaned_text = salary_text.replace('$', '').replace(',', '')
    salary_numbers = re.findall(r'\d+\.?\d*', cleaned_text)
    if not salary_numbers:
        return None
    highest_salary = float(salary_numbers[-1])

    is_in_thousands = "k" in cleaned_text.lower()

    is_explicitly_annual = any(
        term in cleaned_text.lower()
        for term in ["annual", "year", "per annum", "/year", "/yr"]
    )

    # If not explicitly annual and number is below 200, assume it's hourly
    if not is_in_thousands and not is_explicitly_annual and highest_salary < 200:
        highest_salary *= 2080  # Convert hourly wage to annual salary

    # If salary is in thousands (e.g. "150K"), convert to dollars
    if is_in_thousands:
        highest_salary *= 1000

    return highest_salary


def get_salary_from_description(description):
    """Extract salary from a job description using regex patterns."""
    patterns = [
        # Specific formats first
        r'\$([0-9,]+)K(?:—|-)\$?([0-9,]+)K/yr',
        r'\$([0-9,]+)K/(?:yr|year)',
        r'\$(\d+)[-—](\d+),\d{3}/yr',
        r'\$([0-9,]+)K(?:—|-)\$?([0-9,]+)K/Annum',
        r'\$([0-9,.]+)K(?:—|-)\s*\$?([0-9,.]+)K',
        r'\$([0-9,.]+)(?:\.\d+)?\s*(?:—|-)\s*\$([0-9,.]+)(?:\.\d+)?',
        r'\$([0-9,.]+)(?:\.\d+)?\s*(?:—|-{1,2})\s*\$([0-9,.]+)(?:\.\d+)?(?:\s+annually)?',
        r'\$([0-9,]+)(?:/year|/yr)(?:.*?)to\s+\$([0-9,]+)(?:/year|/yr)',

        # Hourly patterns
        r'\$([0-9,.]+)(?:\s+USD)?(?:\s+per\s+|\/)(?:hour|hr)',

        # Special cases
        r'(?:up to)\s*\$([0-9,]+)(?:\s+per\s+(?:month|year|hr|hour))?',

        # Standard ranges
        r'\$([0-9,]+)(?:,\d{3})*\s*-\s*\$([0-9,]+)(?:,\d{3})*',
        r'\$([0-9,]+)(?:—|-)\$([0-9,]+)\s+USD',
        r'\$([0-9,]+)(?:—|-)\$?([0-9,]+)/yr',
        r'\$([0-9,]+)\s+to\s+\$?([0-9,]+)(?:/(?:yr|year|hr|hour))?',
        r'between\s+\$([0-9,.]+)\s+and\s+\$([0-9,.]+)(?:\s+annually)?',

        # Keyword-based patterns last
        r'annual.*?\$([0-9,]+)(?:—|-)\$?([0-9,]+)',
        r'salary.*?\$([0-9,]+)(?:—|-)\$?([0-9,]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            return get_salary_from_text(match.group(0))

    return None
