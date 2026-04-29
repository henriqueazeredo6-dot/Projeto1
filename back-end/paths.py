from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
ENV_FILE = BASE_DIR / ".env"
TOKENS_DIR = BASE_DIR / ".tokens"


def project_path(*parts: str) -> Path:
    return BASE_DIR.joinpath(*parts)
