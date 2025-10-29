import os
from urllib.parse import quote_plus
from dotenv import load_dotenv
import logging
load_dotenv(override=True)

# Database configuration
DB_NAME = os.getenv("DB_NAME", "lexim_gpt_dev")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", 3306))

# S3 configuration
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

# FDA scraping constants
FDA_BASE_URL = "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfStandards/results.cfm"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# Local paths
DEFAULT_DOWNLOAD_DIR = "downloads"
PDF_OUTPUT_PATH = os.path.join(DEFAULT_DOWNLOAD_DIR, "pdfs")
HTML_OUTPUT_PATH = os.path.join(DEFAULT_DOWNLOAD_DIR, "html")
COLUMNS = [
    "date_of_entry", "specialty_task_group_area", "recognition_number",
    "extent_of_recognition", "standards_developing_organization",
    "standard_designation_number_and_date", "standard_title", "title_link"
]

def setup_directories(download_dir: str):
    """Ensure download directories exist."""
    pdf_path = os.path.join(download_dir, "PDFS")
    html_path = os.path.join(download_dir, "HTML")
    os.makedirs(pdf_path, exist_ok=True)
    os.makedirs(html_path, exist_ok=True)
    return pdf_path, html_path

def validate_s3_config():
    """Validate S3 configuration."""
    missing = []
    if not AWS_ACCESS_KEY_ID:
        missing.append("AWS_ACCESS_KEY_ID")
    if not AWS_SECRET_ACCESS_KEY:
        missing.append("AWS_SECRET_ACCESS_KEY")
    if not AWS_S3_BUCKET:
        missing.append("AWS_S3_BUCKET")
    if missing:
        logging.error(f"Missing S3 config: {', '.join(missing)}")
        return False
    return True