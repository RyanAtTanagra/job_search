import os
import yaml
from dotenv import load_dotenv

load_dotenv()


def load_config(config_path="config.yaml"):
    """Load configuration from YAML file."""
    with open(config_path) as f:
        config = yaml.safe_load(f)

    required_sections = ["thresholds", "ai", "user", "email", "searches", "filters", "browser"]
    missing = [s for s in required_sections if s not in config]
    if missing:
        raise ValueError(f"Missing required config sections: {', '.join(missing)}")

    return config


def load_secrets():
    """Load secrets from environment variables."""
    secrets = {
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY"),
        "linkedin_email": os.getenv("LINKEDIN_EMAIL"),
        "linkedin_password": os.getenv("LINKEDIN_PASSWORD"),
    }
    missing = [k for k, v in secrets.items() if not v]
    if missing:
        raise ValueError(f"Missing required secrets in .env: {', '.join(missing)}")

    return secrets
