# scraper.py
import logging
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import pandas as pd
from config import FDA_BASE_URL, HEADERS, COLUMNS

logger = logging.getLogger(__name__)

def fetch_page(start: int = 1, session: requests.Session | None = None) -> str:
    if session is None:
        session = requests.Session()
        session.headers.update(HEADERS)
    params = {"standardsearch": "1", "start_search": str(start), "pagenum": 500}
    resp = session.get(FDA_BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.text

def extract_table_rows(soup: BeautifulSoup, header_template=None):
    table = soup.find("table", {"id": "stds-results-table"})
    if not table:
        return [], header_template
    rows, carry = [], [None] * 4
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        texts = [td.get_text(strip=True) for td in tds]
        if header_template is None and any("Date" in t for t in texts):
            header_template = texts
            continue
        if header_template and texts == header_template:
            continue
        if len(tds) >= 7:
            a = tds[6].find("a")
            rows.append({
                "date_of_entry": texts[0],
                "specialty_task_group_area": texts[1],
                "recognition_number": texts[2],
                "extent_of_recognition": texts[3],
                "standards_developing_organization": texts[4],
                "standard_designation_number_and_date": texts[5],
                "standard_title": a.get_text(strip=True) if a else texts[6],
                "title_link": urljoin(FDA_BASE_URL, a["href"]) if a else ""
            })
            carry = texts[:4]
        elif len(tds) == 3:   # continuation row
            a = tds[2].find("a")
            rows.append({
                "date_of_entry": carry[0],
                "specialty_task_group_area": carry[1],
                "recognition_number": carry[2],
                "extent_of_recognition": carry[3],
                "standards_developing_organization": texts[0],
                "standard_designation_number_and_date": texts[1],
                "standard_title": a.get_text(strip=True) if a else texts[2],
                "title_link": urljoin(FDA_BASE_URL, a["href"]) if a else ""
            })
    return rows, header_template

def scrape_fda_standards() -> pd.DataFrame:
    logger.info("Starting FDA standards scrape")
    all_rows, start, header_template = [], 1, None
    sess = requests.Session()
    sess.headers.update(HEADERS)
    while True:
        logger.info(f"Page start={start}")
        try:
            html = fetch_page(start, sess)
            soup = BeautifulSoup(html, "html.parser")
            page_rows, header_template = extract_table_rows(soup, header_template)
            if not page_rows:
                break
            all_rows.extend(page_rows)
            if len(page_rows) < 500:
                break
            start += 500
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Scrape error at {start}: {e}")
            break
    sess.close()
    df = pd.DataFrame(all_rows, columns=COLUMNS).fillna("").astype(str)
    logger.info(f"Scraped {len(df)} standards")
    return df