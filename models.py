from dataclasses import dataclass
from typing import Optional


@dataclass
class Job:
    id: str
    url: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    description: Optional[str] = None
    salary_text: Optional[str] = None
    highest_salary: Optional[float] = None
    fitness: Optional[float] = None
    source: Optional[str] = None


@dataclass
class DescriptionResult:
    """Normalized return type for all get_job_description functions."""
    description: Optional[str] = None
    salary: Optional[float] = None
