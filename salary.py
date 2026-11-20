import re
import logging

# Normalized annual values outside this range are treated as noise
# (sign-on bonuses, stipends, meal allowances, regex misfires)
PLAUSIBLE_ANNUAL_MIN = 20000
PLAUSIBLE_ANNUAL_MAX = 900000


def get_salary_from_text(salary_text, assume_hourly=True):
    """Parse salary text and return the highest annual salary in dollars.

    assume_hourly: when True (listing-card text, which is trusted to be a
    salary), a bare number under 200 is treated as an hourly rate. Description
    snippets pass False so only explicit hourly context triggers conversion.
    """
    logging.info(f"salary_text: {salary_text}")
    cleaned_text = salary_text.replace('$', '').replace(',', '')
    # 401(k) mentions would otherwise be parsed as a salary number with a
    # "thousands" suffix (401 -> 401,000)
    cleaned_text = re.sub(r'401\s*\(?k\)?', '', cleaned_text, flags=re.IGNORECASE)

    salary_numbers = re.findall(r'\d+\.?\d*', cleaned_text)
    if not salary_numbers:
        return None
    highest_salary = max(float(n) for n in salary_numbers)

    lower = cleaned_text.lower()

    # "150K" style — the k must be attached to a number, not just anywhere
    # in the text ("week", "401k", ...)
    is_in_thousands = re.search(r'\d(?:\.\d+)?\s*k\b', lower) is not None

    is_explicitly_annual = any(
        term in lower
        for term in ["annual", "year", "per annum", "/year", "/yr", "yearly"]
    )

    is_monthly = any(term in lower for term in ["month", "/mo"])

    is_hourly = any(term in lower for term in ["hour", "/hr", " hr", "hourly"])

    if is_in_thousands:
        highest_salary *= 1000
    elif is_monthly and highest_salary < 50000:
        highest_salary *= 12
    elif is_hourly and highest_salary < 500:
        highest_salary *= 2080  # Convert hourly wage to annual salary
    elif assume_hourly and not is_explicitly_annual and highest_salary < 200:
        highest_salary *= 2080

    return highest_salary


# Patterns for salary-looking snippets in free-form description text.
# All matches from all patterns are collected; implausible values are
# discarded and the highest survivor wins, so ordering doesn't matter.
SALARY_PATTERNS = [
    # $ ranges: "$150,000 - $180,000", "$150K—$170K/yr", "$80 to $104/hr",
    # "between $140,000 and $175,000 annually"
    r'\$[0-9][0-9,.]*\s?K?\s*(?:—|–|--|-|to|and)\s*\$?[0-9][0-9,.]*\s?K?'
    r'(?:\s*(?:/|\bper\s+)(?:yr|year|annum|hour|hr|month|mo))?(?:\s+(?:annually|USD|a year|an hour))?',

    # Single $ values with an explicit period: "$150,000/yr", "$85.50 per hour",
    # "$12,500 per month", "$150K/year"
    r'\$[0-9][0-9,.]*\s?K?\s*(?:/|\bper\s+)\s*(?:yr|year|annum|hour|hr|month|mo)',
    r'\$[0-9][0-9,.]*\s?K?\s+(?:USD\s+)?(?:annually|a year|an hour|hourly|yearly)',

    # "up to" amounts — require a K suffix, a unit, or a 4+ digit figure so
    # "up to $150 gift card" can't become a salary
    r'up to\s+\$?[0-9][0-9,]{3,}[0-9,.]*\s?K?(?:\s*(?:/|\bper\s+)(?:yr|year|hour|hr|month|mo))?',
    r'up to\s+\$?[0-9][0-9,.]*\s?K\b',
    r'up to\s+\$[0-9,.]+\s*(?:/|\bper\s+)(?:yr|year|hour|hr|month|mo)',

    # $-less formats: "USD 150,000", "150,000 - 180,000 per year",
    # "150k-180k"
    r'USD\s?[0-9][0-9,.]*\s?K?(?:\s*(?:—|–|-|to)\s*(?:USD\s?)?[0-9][0-9,.]*\s?K?)?',
    r'[0-9]{2,3},[0-9]{3}\s*(?:—|–|-|to)\s*[0-9]{2,3},[0-9]{3}'
    r'(?:\s*(?:/|\bper\s+)(?:yr|year|annum)|\s+annually|\s+a year)?',
    r'\b[0-9]{2,3}\s?[kK]\s*(?:—|–|-|to)\s*[0-9]{2,3}\s?[kK]\b',

    # Keyword context as a last resort: "salary range ... $175,000"
    r'(?:salary|compensation|pay)\s?(?:range|rate)?[^.\n]{0,40}?'
    r'\$[0-9][0-9,.]*\s?K?(?:\s*(?:—|–|-|to)\s*\$?[0-9][0-9,.]*\s?K?)?',
]


def get_salary_from_description(description):
    """Extract salary from a job description.

    Collects every salary-looking match, normalizes each to an annual value,
    drops implausible ones (bonuses, stipends), and returns the highest —
    or None if nothing plausible was found.
    """
    candidates = []
    for pattern in SALARY_PATTERNS:
        for match in re.finditer(pattern, description, re.IGNORECASE):
            value = get_salary_from_text(match.group(0), assume_hourly=False)
            if value and PLAUSIBLE_ANNUAL_MIN <= value <= PLAUSIBLE_ANNUAL_MAX:
                candidates.append(value)

    return max(candidates) if candidates else None
