import re
import logging
import functools

import anthropic
from docx import Document
from docx.shared import Pt

# Company names appear early in postings; no need to send the whole description
COMPANY_EXTRACT_CHARS = 1500
# Cap description size for scoring — long tails are EEO/benefits boilerplate
FITNESS_DESCRIPTION_CHARS = 12000

_clients = {}


def _get_client(api_key):
    if api_key not in _clients:
        _clients[api_key] = anthropic.Anthropic(api_key=api_key)
    return _clients[api_key]


@functools.lru_cache(maxsize=4)
def _read_resume(resume_path):
    with open(resume_path, 'r') as file:
        return file.read()


def _call_claude(api_key, model, prompt, max_tokens=1000, system=None):
    """Shared helper for Claude API calls."""
    client = _get_client(api_key)
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system is not None:
        kwargs["system"] = system
    message = client.messages.create(**kwargs)
    usage = message.usage
    logging.info(
        f"Claude usage: input={usage.input_tokens} output={usage.output_tokens} "
        f"cache_write={getattr(usage, 'cache_creation_input_tokens', 0)} "
        f"cache_read={getattr(usage, 'cache_read_input_tokens', 0)}"
    )
    return str(message.content[0].text)


def get_company_from_description(description, api_key, model):
    """Extract the company name from a job description using Claude."""
    prompt = f"""Extract only the company name from this job description.

        Rules:
        - Respond with ONLY the company name, nothing else
        - No explanations, no parentheses, no additional text
        - If no company name is found, respond with exactly: Unknown Company

        Job Description:
            {description[:COMPANY_EXTRACT_CHARS]}
        """
    try:
        return _call_claude(api_key, model, prompt, max_tokens=50)
    except Exception as e:
        logging.warning(f"Error connecting to Claude to get company name: {e}")
        return None


def _fitness_system_block(resume_text, location):
    """Static scoring instructions + resume, identical for every job in a run.

    Marked with cache_control so repeat calls within the cache TTL bill this
    portion at ~10% of the normal input rate. Note: if the rubric + resume is
    below the model's minimum cacheable prefix (4096 tokens for Haiku 4.5),
    it silently won't cache — harmless, no premium is paid. Check the
    cache_read value in the debug log to verify.
    """
    text = f"""You score job descriptions against my resume. For each job description you receive, analyze on a scale of 0-100 how good of a fit I am for the role using the following scoring system:

        Base score (0-60): Match between job's core requirements (not "nice to have" or optional skills) and my demonstrated experience

Bonus points (up to 40):

    +20 points if ALL these conditions are met:
        - Role's primary responsibilities (not "nice to have") heavily involve infrastructure operations/maintenance
- Role involves AWS infrastructure, Linux systems administration, or disaster recovery as core duties
- Role is NOT classified as software engineering
- Infrastructure skills are listed in required/core skills, not just "nice to have"

+10 points if the role's seniority level matches my experience (subtract points if significantly junior or if requiring different experience level)
+10 points if role is fully remote OR is within 25 miles of {location}

Deductions:

    -20 points if ANY of these are true:
        - Role requires building new features or applications as primary duty
    - Role focuses on product development or customer-facing features

-15 points if:
    - Role has significant software engineering requirements but includes some infrastructure work
    - Core requirements emphasize coding/development over infrastructure operations
    - Experience requirements focus on software development years over infrastructure experience

-10 points if:
    - Role requires occasional coding but is primarily infrastructure-focused
    - Infrastructure skills are only listed in "nice to have" sections

-15 points if:
    - It's sales/solutions related or a management/vice president/director level role
    - Experience requirements are significantly mismatched with my background

Please provide only a numerical score in the output, no other details or reasoning needed.

Resume:
    {resume_text}
"""
    return [{
        "type": "text",
        "text": text,
        "cache_control": {"type": "ephemeral"},
    }]


def get_fitness_rating(description, company, title, config, api_key):
    """Score a job's fitness against the user's resume (0-100).

    Returns 0 for quick-filter matches (bad title, company, or too many
    software indicators). Otherwise calls Claude for a detailed score.
    """
    filters = config['filters']

    # Check title first (fastest)
    for keyword in filters['poor_fit_titles']:
        if keyword in title.lower():
            logging.info(f"Job filtered out due to title containing '{keyword}'")
            return 0

    # Check company name
    if company:
        for poor_company in filters['poor_fit_companies']:
            if poor_company in company.lower():
                logging.info(f"Job filtered out due to company {poor_company}")
                return 0

    # Count software development indicators
    software_indicator_count = sum(
        1 for indicator in filters['software_role_indicators']
        if indicator in description.lower()
    )
    if software_indicator_count >= 3:
        logging.info(f"Job filtered out due to {software_indicator_count} software development indicators")
        return 0

    # Call Claude for detailed fitness score
    resume_text = _read_resume(config['user']['resume_path'])
    location = config['user']['location']
    model = config['ai']['model']
    max_tokens = config['ai']['max_tokens']

    prompt = f"""Job Description:
    {description[:FITNESS_DESCRIPTION_CHARS]}
"""
    try:
        response = _call_claude(
            api_key, model, prompt, max_tokens,
            system=_fitness_system_block(resume_text, location)
        )
    except Exception as e:
        logging.warning(f"Error connecting to Claude for fitness score: {e}")
        return None

    # Tolerate outputs like "85." or "Score: 85" — a strict int() parse used
    # to fail these, leaving jobs unmarked and re-scored on every future run
    match = re.search(r'\d{1,3}', response)
    if not match:
        logging.warning(f"No score found in fitness response: {response!r}")
        return None
    return max(0, min(100, int(match.group())))


def get_cover_letter(company, title, description, config, api_key):
    """Generate a tailored cover letter as a .docx file. Returns the file path."""
    resume_text = _read_resume(config['user']['resume_path'])

    user_name = config['user']['name']
    model = config['ai']['model']
    max_tokens = config['ai']['max_tokens']

    prompt = f"""
Generate a cover letter for the {title} role at {company}, customized based on my resume and the job description. If the company name is "Unknown Company", see if you can figure out the actual company name from the description.  The letter should:

    Style: Professional yet conversational, max 20 lines, 1.25" margins

Prioritize highlighting my experience with:
    AWS and cloud engineering
Migration of production services to cloud environments
Relevant technical achievements

Include:
    1. Brief intro (2-3 sentences)
2. Experience section with 3-4 dashes showing achievements matching role
3. Short closing requesting interview
4. "Sincerely," + "{user_name}"

Skip:
    - Generic company praise
- Mission statements
- Non-technical details

Address any experience gaps or requirement mismatches directly but positively

Resume:
    {resume_text}

Job Description:
    {description}
        """
    try:
        cover_letter = _call_claude(api_key, model, prompt, max_tokens)
    except Exception as e:
        logging.warning(f"Error connecting to Claude for cover letter: {e}")
        return None

    # Generate docx from template
    doc = Document(config['user']['template_path'])

    for paragraph in cover_letter.split('\n\n'):
        p = doc.add_paragraph()
        run = p.add_run(paragraph)
        run.font.name = 'Calibri'
        run.font.size = Pt(11)
        paragraph_format = p.paragraph_format
        paragraph_format.space_after = Pt(12)

    # Sanitize company name for file path
    safe_company = re.sub(r'[^\w\s-]', '', company)[:100]
    cover_letter_path = f"/tmp/{safe_company} Cover Letter.docx"
    doc.save(cover_letter_path)
    return cover_letter_path
