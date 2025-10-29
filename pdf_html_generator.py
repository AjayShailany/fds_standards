# pdf_html_generator.py
import os, re, logging, unicodedata, random, time
from typing import List
import pandas as pd
from fpdf import FPDF
import boto3, requests
from botocore.exceptions import ClientError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_S3_BUCKET, validate_s3_config
from models import FdaStandard
from helper import extract_fda_standard_data
from fda_db_operations import FDADatabaseOperations

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# 1. Session factory (retry + random UA)
# ------------------------------------------------------------------
def get_session():
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=2, status_forcelist=[500, 502, 503, 504, 429])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/119.0 Safari/537.36",
]

# ------------------------------------------------------------------
# 2. PDF – Helvetica + UTF-8 + NO LINKS
# ------------------------------------------------------------------
class BrandedPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(True, margin=15)
        self.set_font("Helvetica", size=10)

    def footer(self):
        self.set_y(-15)
        self.set_fill_color(44, 132, 172)
        self.rect(0, self.get_y(), self.w, 20, 'F')
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", style='I', size=8)
        self.set_xy(10, self.get_y() + 5)
        self.cell(0, 5, 'Powered by Lexim AI, Inc.', align='L')
        self.set_xy(-40, self.get_y())
        self.cell(0, 5, f'Page {self.page_no()} / {{nb}}', align='R')

    def section_title(self, title: str):
        if self.get_y() + 15 > self.h - 15:
            self.add_page()
        self.ln(3)
        self.set_fill_color(230, 240, 248)
        self.set_text_color(44, 132, 172)
        self.set_font("Helvetica", style='B', size=11)
        self.cell(0, 8, self._clean(title), 0, 1, 'L', fill=True)
        self.ln(1)

    def section_body(self, label: str, value: str):
        if not value or value == "N/A":
            return
        value = self._clean(value)
        max_width = 130
        words = value.split()
        lines = 1
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            if self.get_string_width(test) > max_width:
                lines += 1
                current = word
            else:
                current = test
        height = max(lines * 6, 8)
        if self.get_y() + height > self.h - 15:
            self.add_page()
        self.set_font("Helvetica", style='B', size=8)
        self.set_text_color(0, 0, 0)
        y = self.get_y()
        self.cell(60, 6, f"{label}:", 0, 0, 'R')
        self.set_font("Helvetica", size=8)
        self.set_xy(70, y)
        self.multi_cell(130, 6, value)
        self.set_draw_color(200, 210, 220)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2)

    def draw_table_header(self, headers: List[str], widths: List[int], aligns: List[str]):
        self.set_font("Helvetica", style='B', size=8)
        self.set_fill_color(180, 210, 230)
        self.set_text_color(0, 0, 0)
        for i, h in enumerate(headers):
            self.cell(widths[i], 8, self._clean(h), 1, 0, aligns[i], fill=True)
        self.ln()

    def draw_table_row(self, cols: List[str], widths: List[int], aligns: List[str]):
        self.set_font("Helvetica", size=8)
        self.set_text_color(0, 0, 0)
        row_h = 8
        for col, w in zip(cols, widths):
            lines = 1
            words = self._clean(col).split()
            current = ""
            for word in words:
                test = f"{current} {word}".strip()
                if self.get_string_width(test) > w - 4:
                    lines += 1
                    current = word
                else:
                    current = test
            row_h = max(row_h, lines * 6)
        if self.get_y() + row_h > self.h - 15:
            self.add_page()
            self.draw_table_header(["Name","Office","Phone","Email"], widths, aligns)
        x0, y0 = self.get_x(), self.get_y()
        for c, w, a in zip(cols, widths, aligns):
            self.set_xy(x0, y0)
            self.multi_cell(w, 6, self._clean(c), 1, a)
            x0 += w
        self.set_y(y0 + row_h)

    def _clean(self, text: str) -> str:
        if not text:
            return "N/A"
        # Replace non-ASCII with ?
        return re.sub(r'[^\x00-\x7F]+', '?', str(text))

# ------------------------------------------------------------------
# 3. HTML generator (unchanged)
# ------------------------------------------------------------------
def generate_html(data: dict, filename: str, out_dir: str) -> str | None:
    try:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, filename)
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>FDA Standard {data.get('FR_Recognition_Number','')}</title>
<style>
  body {{font-family: Arial, Helvetica, sans-serif; margin:40px;}}
  h1,h2 {{color:#2c84ac;}}
  .section {{margin:15px 0;padding:10px;background:#f0f8ff;border-left:4px solid #2c84ac;}}
  .label {{font-weight:bold;display:inline-block;width:180px;}}
  table {{border-collapse:collapse;width:100%;margin:10px 0;}}
  th,td {{border:1px solid #ccc;padding:8px;text-align:left;}}
  th {{background:#d0e8f7;}}
  .footer {{margin-top:50px;text-align:center;color:#666;font-size:0.8em;}}
</style></head><body>
<h1>FDA Recognized Standard</h1>"""
        fields = [
            ("Standard", data.get("Standard")),
            ("Date of Entry", data.get("Date_of_Entry")),
            ("Recognition List #", data.get("FR_Recognition_List_Number")),
            ("FR Recognition #", data.get("FR_Recognition_Number")),
            ("Scope", data.get("Scope_Abstract")),
            ("Extent", data.get("Extent_of_Recognition")),
            ("Rationale", data.get("Rationale_for_Recognition")),
            ("Transition Period", data.get("Transition_Period")),
            ("Specialty Task Group", data.get("FDA_Specialty_Task_Group")),
        ]
        html += "<div class='section'>"
        for l, v in fields:
            if v: html += f"<p><span class='label'>{l}:</span> {v}</p>"
        html += "</div>"
        org = data.get("Standards_Development_Organization")
        if org:
            html += "<div class='section'><h2>Standards Organization</h2>"
            if org.get("Acronym"): html += f"<p><span class='label'>Acronym:</span> {org['Acronym']}</p>"
            if org.get("Name"): html += f"<p><span class='label'>Name:</span> {org['Name']}</p>"
            if org.get("Website"): html += f"<p><span class='label'>Website:</span> <a href='{org['Website']}'>{org['Website']}</a></p>"
            html += "</div>"
        contacts = data.get("FDA_Technical_Contacts")
        if contacts:
            html += "<div class='section'><h2>Technical Contacts</h2><table><tr><th>Name</th><th>Office</th><th>Phone</th><th>Email</th></tr>"
            for c in contacts:
                html += f"<tr><td>{c.get('Name','')}</td><td>{c.get('Office','')}</td><td>{c.get('Phone','')}</td><td>{c.get('Email','')}</td></tr>"
            html += "</table></div>"
        procodes = data.get("Public_Law_CFR_Procode")
        if procodes and isinstance(procodes, list):
            html += "<div class='section'><h2>CFR & Product Codes</h2><table><tr><th>Device</th><th>Class</th><th>Regulation</th><th>Product Code</th></tr>"
            for e in procodes:
                reg = e.get("Regulation_Number",{}).get("text","N/A") if e.get("Regulation_Number") else "N/A"
                code = e.get("Product_Code",{}).get("code","N/A") if e.get("Product_Code") else "N/A"
                html += f"<tr><td>{e.get('Device_Name','')}</td><td>{e.get('Device_Class','')}</td><td>{reg}</td><td>{code}</td></tr>"
            html += "</table></div>"
        html += "<div class='footer'>Powered by Lexim AI, Inc.</div></body></html>"
        with open(path, "w", encoding="utf-8") as f: f.write(html)
        logger.info(f"HTML -> {path}")
        return path
    except Exception as e:
        logger.error(f"HTML error {filename}: {e}")
        return None

# ------------------------------------------------------------------
# 4. S3 uploader
# ------------------------------------------------------------------
class S3Uploader:
    def __init__(self):
        if not validate_s3_config():
            raise ValueError("S3 config missing")
        self.s3 = boto3.client('s3',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY)
        self.bucket = AWS_S3_BUCKET

    def upload(self, path: str, key: str, ctype: str) -> bool:
        if not os.path.exists(path): return False
        try:
            self.s3.upload_file(Filename=path, Bucket=self.bucket, Key=key,
                                ExtraArgs={'ContentType': ctype})
            logger.info(f"S3 upload: {key}")
            return True
        except ClientError as e:
            logger.error(f"S3 error {key}: {e}")
            return False

    def exists(self, key: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404': return False
            raise

# ------------------------------------------------------------------
# 5. Processor
# ------------------------------------------------------------------
class FDAStandardsProcessor:
    def __init__(self, pdf_dir: str, html_dir: str, s3_prefix: str = "FDA_STANDARDS/"):
        self.pdf_dir = pdf_dir
        self.html_dir = html_dir
        self.s3_prefix = s3_prefix.rstrip("/") + "/"
        os.makedirs(pdf_dir, exist_ok=True)
        os.makedirs(html_dir, exist_ok=True)
        self.s3 = S3Uploader() if validate_s3_config() else None
        self.db = FDADatabaseOperations()

    def _filename(self, rec_num: str, title: str) -> tuple[str, str]:
        safe = unicodedata.normalize("NFKD", title).encode('ascii','ignore').decode()
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', safe).strip()[:100]
        base = f"{rec_num}_{safe}"
        return f"{base}.pdf", f"{base}.html"

    def generate_pdf(self, std: FdaStandard, pdf_fn: str) -> str | None:
        try:
            path = os.path.join(self.pdf_dir, pdf_fn)
            pdf = BrandedPDF()
            pdf.alias_nb_pages()
            pdf.add_page()

            pdf.section_title("Standard Info")
            pdf.section_body("Standard", std.Standard)
            pdf.section_body("Date of Entry", std.Date_of_Entry)
            pdf.section_body("Recognition List #", std.FR_Recognition_List_Number)
            pdf.section_body("FR Recognition #", std.FR_Recognition_Number)
            pdf.section_body("Scope Abstract", std.Scope_Abstract)
            pdf.section_body("Extent of Recognition", std.Extent_of_Recognition)
            pdf.section_body("Rationale", std.Rationale_for_Recognition)
            if std.Transition_Period: pdf.section_body("Transition Period", std.Transition_Period)
            if std.FDA_Specialty_Task_Group: pdf.section_body("FDA Specialty Task Group", std.FDA_Specialty_Task_Group)

            org = std.Standards_Development_Organization
            if org and (org.Acronym or org.Name or org.Website):
                pdf.section_title("Standards Development Organization")
                pdf.section_body("Acronym", org.Acronym)
                pdf.section_body("Name", org.Name)
                pdf.section_body("Website", str(org.Website) if org.Website else "N/A")

            if std.FDA_Technical_Contacts:
                pdf.section_title("FDA Technical Contacts")
                pdf.draw_table_header(["Name","Office","Phone","Email"],[45,60,25,60],['L']*4)
                for c in std.FDA_Technical_Contacts:
                    pdf.draw_table_row([c.Name or "", c.Office or "", c.Phone or "", c.Email or ""],[45,60,25,60],['L']*4)

            if isinstance(std.Public_Law_CFR_Procode, list):
                pdf.section_title("CFR Procode Entries")
                pdf.draw_table_header(["Device Name","Class","Regulation No","Product Code"],[120,20,25,25],['L','C','C','C'])
                for e in std.Public_Law_CFR_Procode:
                    reg = e.Regulation_Number.text if e.Regulation_Number else "N/A"
                    code = e.Product_Code.code if e.Product_Code else "N/A"
                    pdf.draw_table_row([e.Device_Name or "", e.Device_Class or "", reg, code],
                                       [120,20,25,25],['L','C','C','C'])

            pdf.output(path)
            logger.info(f"PDF -> {path}")
            return path
        except Exception as e:
            logger.error(f"PDF generation failed for {pdf_fn}: {e}")
            return None

    def process_unprocessed(self, df: pd.DataFrame):
        session = get_session()
        for idx, row in df.iterrows():
            url = row["title_link"]
            pdf_fn, html_fn = self._filename(row["recognition_number"], row["standard_title"])

            if self.s3 and self.s3.exists(f"{self.s3_prefix}PDF/{pdf_fn}") and self.s3.exists(f"{self.s3_prefix}HTML/{html_fn}"):
                logger.info(f"Skip (S3): {url}")
                time.sleep(0.5)
                continue

            delay = random.uniform(2.0, 5.0)
            logger.info(f"[{idx+1}/{len(df)}] Wait {delay:.1f}s → {url}")
            time.sleep(delay)

            try:
                headers = {"User-Agent": random.choice(USER_AGENTS)}
                resp = session.get(url, headers=headers, timeout=20)

                if "abuse-detection-apology" in resp.url or resp.status_code == 404:
                    logger.warning(f"FDA blocked: {url}")
                    self.db.update_s3_paths(url, "BLOCKED", "BLOCKED")
                    continue

                if resp.status_code == 403:
                    raw = {"url": url}
                    m = re.search(r"standard__identification_no=(\d+)", url)
                    raw["standard_identification_no"] = int(m.group(1)) if m else None
                    std = FdaStandard(**raw)
                else:
                    resp.raise_for_status()
                    raw = extract_fda_standard_data(resp.text)
                    raw["url"] = url
                    m = re.search(r"standard__identification_no=(\d+)", url)
                    raw["standard_identification_no"] = int(m.group(1)) if m else None
                    std = FdaStandard(**raw)

                pdf_path = self.generate_pdf(std, pdf_fn)
                html_path = generate_html(std.model_dump(), html_fn, self.html_dir)

                uploaded = True
                if self.s3:
                    if pdf_path and not self.s3.upload(pdf_path, f"{self.s3_prefix}PDF/{pdf_fn}", "application/pdf"):
                        uploaded = False
                    if html_path and not self.s3.upload(html_path, f"{self.s3_prefix}HTML/{html_fn}", "text/html"):
                        uploaded = False
                    if uploaded:
                        self.db.update_s3_paths(url, pdf_fn if pdf_path else "FAILED", html_fn)
                        for p in (pdf_path, html_path):
                            if p and os.path.exists(p):
                                try: os.remove(p)
                                except: pass
                    else:
                        logger.warning(f"Upload failed for {url}")
                else:
                    logger.info(f"Local only: {pdf_fn}, {html_fn}")

            except Exception as e:
                logger.error(f"Failed {url}: {e}")
                self.db.update_s3_paths(url, "FAILED", "FAILED")

    def run(self):
        unproc = self.db.get_unprocessed_standards()
        if unproc.empty:
            logger.info("No unprocessed standards")
            return
        self.process_unprocessed(unproc)














# # pdf_html_generator.py
# import os, re, logging, unicodedata, random, time
# from typing import List
# import pandas as pd
# from fpdf import FPDF
# import boto3, requests
# from botocore.exceptions import ClientError
# from requests.adapters import HTTPAdapter
# from urllib3.util.retry import Retry

# from config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_S3_BUCKET, validate_s3_config
# from models import FdaStandard
# from helper import extract_fda_standard_data
# from fda_db_operations import FDADatabaseOperations

# logger = logging.getLogger(__name__)

# # ------------------------------------------------------------------
# # 1. Session factory (retry + random UA)
# # ------------------------------------------------------------------
# def get_session():
#     session = requests.Session()
#     retry = Retry(total=3, backoff_factor=2, status_forcelist=[500, 502, 503, 504, 429])
#     adapter = HTTPAdapter(max_retries=retry)
#     session.mount("http://", adapter)
#     session.mount("https://", adapter)
#     return session

# USER_AGENTS = [
#     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
#     "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
#     "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/119.0 Safari/537.36",
# ]

# # ------------------------------------------------------------------
# # 2. PDF – Helvetica only + NO DRY_RUN
# # ------------------------------------------------------------------
# class BrandedPDF(FPDF):
#     def __init__(self):
#         super().__init__()
#         self.set_font("Helvetica", size=10)

#     def footer(self):
#         self.set_y(-15)
#         self.set_fill_color(44, 132, 172)
#         self.rect(0, self.get_y(), self.w, 20, 'F')
#         self.set_text_color(255, 255, 255)
#         self.set_font("Helvetica", style='I', size=8)
#         self.set_xy(10, self.get_y() + 5)
#         self.cell(0, 5, 'Powered by Lexim AI, Inc.', align='L')
#         self.set_xy(-40, self.get_y())
#         self.cell(0, 5, f'Page {self.page_no()} / {{nb}}', align='R')

#     def section_title(self, title: str):
#         if self.get_y() + 15 > self.h - self.b_margin:
#             self.add_page()
#         self.ln(3)
#         self.set_fill_color(230, 240, 248)
#         self.set_text_color(44, 132, 172)
#         self.set_font("Helvetica", style='B', size=11)
#         self.cell(0, 8, title, 0, 1, 'L', fill=True)
#         self.ln(1)

#     def section_body(self, label: str, value: str):
#         if not value or value == "N/A":
#             return
#         # Estimate height using get_string_width
#         max_width = 130
#         words = str(value).split()
#         lines = 1
#         current = ""
#         for word in words:
#             test = f"{current} {word}".strip()
#             if self.get_string_width(test) > max_width:
#                 lines += 1
#                 current = word
#             else:
#                 current = test
#         height = max(lines * 6, 8)
#         if self.get_y() + height > self.h - self.b_margin:
#             self.add_page()
#         self.set_font("Helvetica", style='B', size=8)
#         self.set_text_color(0, 0, 0)
#         y = self.get_y()
#         self.cell(60, 6, f"{label}:", 0, 0, 'R')
#         self.set_font("Helvetica", size=8)
#         self.set_xy(70, y)
#         self.multi_cell(130, 6, str(value))
#         self.set_draw_color(200, 210, 220)
#         self.line(10, self.get_y(), 200, self.get_y())
#         self.ln(2)

#     def draw_table_header(self, headers: List[str], widths: List[int], aligns: List[str]):
#         self.set_font("Helvetica", style='B', size=8)
#         self.set_fill_color(180, 210, 230)
#         self.set_text_color(0, 0, 0)
#         for i, h in enumerate(headers):
#             self.cell(widths[i], 8, h, 1, 0, aligns[i], fill=True)
#         self.ln()

#     def draw_table_row(self, cols: List[str], widths: List[int], aligns: List[str], links: List[str] = None):
#         self.set_font("Helvetica", size=8)
#         self.set_text_color(0, 0, 0)
#         # Estimate max row height
#         row_h = 8
#         for col, w in zip(cols, widths):
#             lines = 1
#             words = str(col).split()
#             current = ""
#             for word in words:
#                 test = f"{current} {word}".strip()
#                 if self.get_string_width(test) > w - 4:
#                     lines += 1
#                     current = word
#                 else:
#                     current = test
#             row_h = max(row_h, lines * 6)
#         if self.get_y() + row_h > self.h - self.b_margin:
#             self.add_page()
#             # Re-draw header on new page
#             header_map = {
#                 ("Name","Office","Phone","Email"): [45,60,25,60],
#                 ("Device Name","Class","Regulation No","Product Code"): [120,20,25,25]
#             }
#             for h, w in header_map.items():
#                 if len(h) == len(widths):
#                     self.draw_table_header(list(h), w, aligns)
#                     break
#         x0, y0 = self.get_x(), self.get_y()
#         for i, (c, w, a) in enumerate(zip(cols, widths, aligns)):
#             self.set_xy(x0, y0)
#             if links and links[i]:
#                 self.set_text_color(0, 0, 255)
#                 self.multi_cell(w, 6, str(c), 1, a, link=links[i])
#                 self.set_text_color(0, 0, 0)
#             else:
#                 self.multi_cell(w, 6, str(c), 1, a)
#             x0 += w
#         self.set_y(y0 + row_h)

# # ------------------------------------------------------------------
# # 3. HTML generator
# # ------------------------------------------------------------------
# def generate_html(data: dict, filename: str, out_dir: str) -> str | None:
#     try:
#         os.makedirs(out_dir, exist_ok=True)
#         path = os.path.join(out_dir, filename)
#         html = f"""<!DOCTYPE html>
# <html><head><meta charset="utf-8"><title>FDA Standard {data.get('FR_Recognition_Number','')}</title>
# <style>
#   body {{font-family: Arial, Helvetica, sans-serif; margin:40px;}}
#   h1,h2 {{color:#2c84ac;}}
#   .section {{margin:15px 0;padding:10px;background:#f0f8ff;border-left:4px solid #2c84ac;}}
#   .label {{font-weight:bold;display:inline-block;width:180px;}}
#   table {{border-collapse:collapse;width:100%;margin:10px 0;}}
#   th,td {{border:1px solid #ccc;padding:8px;text-align:left;}}
#   th {{background:#d0e8f7;}}
#   .footer {{margin-top:50px;text-align:center;color:#666;font-size:0.8em;}}
# </style></head><body>
# <h1>FDA Recognized Standard</h1>"""
#         fields = [
#             ("Standard", data.get("Standard")),
#             ("Date of Entry", data.get("Date_of_Entry")),
#             ("Recognition List #", data.get("FR_Recognition_List_Number")),
#             ("FR Recognition #", data.get("FR_Recognition_Number")),
#             ("Scope", data.get("Scope_Abstract")),
#             ("Extent", data.get("Extent_of_Recognition")),
#             ("Rationale", data.get("Rationale_for_Recognition")),
#             ("Transition Period", data.get("Transition_Period")),
#             ("Specialty Task Group", data.get("FDA_Specialty_Task_Group")),
#         ]
#         html += "<div class='section'>"
#         for l, v in fields:
#             if v: html += f"<p><span class='label'>{l}:</span> {v}</p>"
#         html += "</div>"
#         org = data.get("Standards_Development_Organization")
#         if org:
#             html += "<div class='section'><h2>Standards Organization</h2>"
#             if org.get("Acronym"): html += f"<p><span class='label'>Acronym:</span> {org['Acronym']}</p>"
#             if org.get("Name"): html += f"<p><span class='label'>Name:</span> {org['Name']}</p>"
#             if org.get("Website"): html += f"<p><span class='label'>Website:</span> <a href='{org['Website']}'>{org['Website']}</a></p>"
#             html += "</div>"
#         contacts = data.get("FDA_Technical_Contacts")
#         if contacts:
#             html += "<div class='section'><h2>Technical Contacts</h2><table><tr><th>Name</th><th>Office</th><th>Phone</th><th>Email</th></tr>"
#             for c in contacts:
#                 html += f"<tr><td>{c.get('Name','')}</td><td>{c.get('Office','')}</td><td>{c.get('Phone','')}</td><td>{c.get('Email','')}</td></tr>"
#             html += "</table></div>"
#         procodes = data.get("Public_Law_CFR_Procode")
#         if procodes and isinstance(procodes, list):
#             html += "<div class='section'><h2>CFR & Product Codes</h2><table><tr><th>Device</th><th>Class</th><th>Regulation</th><th>Product Code</th></tr>"
#             for e in procodes:
#                 reg = e.get("Regulation_Number",{}).get("text","N/A") if e.get("Regulation_Number") else "N/A"
#                 code = e.get("Product_Code",{}).get("code","N/A") if e.get("Product_Code") else "N/A"
#                 html += f"<tr><td>{e.get('Device_Name','')}</td><td>{e.get('Device_Class','')}</td><td>{reg}</td><td>{code}</td></tr>"
#             html += "</table></div>"
#         html += "<div class='footer'>Powered by Lexim AI, Inc.</div></body></html>"
#         with open(path, "w", encoding="utf-8") as f: f.write(html)
#         logger.info(f"HTML -> {path}")
#         return path
#     except Exception as e:
#         logger.error(f"HTML error {filename}: {e}")
#         return None

# # ------------------------------------------------------------------
# # 4. S3 uploader
# # ------------------------------------------------------------------
# class S3Uploader:
#     def __init__(self):
#         if not validate_s3_config():
#             raise ValueError("S3 config missing")
#         self.s3 = boto3.client('s3',
#             aws_access_key_id=AWS_ACCESS_KEY_ID,
#             aws_secret_access_key=AWS_SECRET_ACCESS_KEY)
#         self.bucket = AWS_S3_BUCKET

#     def upload(self, path: str, key: str, ctype: str) -> bool:
#         if not os.path.exists(path): return False
#         try:
#             self.s3.upload_file(Filename=path, Bucket=self.bucket, Key=key,
#                                 ExtraArgs={'ContentType': ctype})
#             logger.info(f"S3 upload: {key}")
#             return True
#         except ClientError as e:
#             logger.error(f"S3 error {key}: {e}")
#             return False

#     def exists(self, key: str) -> bool:
#         try:
#             self.s3.head_object(Bucket=self.bucket, Key=key)
#             return True
#         except ClientError as e:
#             if e.response['Error']['Code'] == '404': return False
#             raise

# # ------------------------------------------------------------------
# # 5. Processor
# # ------------------------------------------------------------------
# class FDAStandardsProcessor:
#     def __init__(self, pdf_dir: str, html_dir: str, s3_prefix: str = "FDA_STANDARDS/"):
#         self.pdf_dir = pdf_dir
#         self.html_dir = html_dir
#         self.s3_prefix = s3_prefix.rstrip("/") + "/"
#         os.makedirs(pdf_dir, exist_ok=True)
#         os.makedirs(html_dir, exist_ok=True)
#         self.s3 = S3Uploader() if validate_s3_config() else None
#         self.db = FDADatabaseOperations()

#     # ------------------------------------------------------------------
#     # Helper: safe filename
#     # ------------------------------------------------------------------
#     def _filename(self, rec_num: str, title: str) -> tuple[str, str]:
#         safe = unicodedata.normalize("NFKD", title).encode('ascii','ignore').decode()
#         safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', safe).strip()[:100]
#         base = f"{rec_num}_{safe}"
#         return f"{base}.pdf", f"{base}.html"

#     # ------------------------------------------------------------------
#     # PDF generation (with safe fallbacks)
#     # ------------------------------------------------------------------
#     def generate_pdf(self, std: FdaStandard, pdf_fn: str) -> str | None:
#         try:
#             path = os.path.join(self.pdf_dir, pdf_fn)
#             pdf = BrandedPDF()
#             pdf.alias_nb_pages()
#             pdf.add_page()
#             pdf.section_title("Standard Info")
#             pdf.section_body("Standard", std.Standard or "N/A")
#             pdf.section_body("Date of Entry", std.Date_of_Entry or "N/A")
#             pdf.section_body("Recognition List #", std.FR_Recognition_List_Number or "N/A")
#             pdf.section_body("FR Recognition #", std.FR_Recognition_Number or "N/A")
#             pdf.section_body("Scope Abstract", std.Scope_Abstract or "N/A")
#             pdf.section_body("Extent of Recognition", std.Extent_of_Recognition or "N/A")
#             pdf.section_body("Rationale", std.Rationale_for_Recognition or "N/A")
#             if std.Transition_Period: pdf.section_body("Transition Period", std.Transition_Period)
#             if std.FDA_Specialty_Task_Group: pdf.section_body("FDA Specialty Task Group", std.FDA_Specialty_Task_Group)

#             org = std.Standards_Development_Organization
#             if org and (org.Acronym or org.Name or org.Website):
#                 pdf.section_title("Standards Development Organization")
#                 pdf.section_body("Acronym", org.Acronym or "N/A")
#                 pdf.section_body("Name", org.Name or "N/A")
#                 pdf.section_body("Website", str(org.Website) if org.Website else "N/A")

#             if std.FDA_Technical_Contacts:
#                 pdf.section_title("FDA Technical Contacts")
#                 pdf.draw_table_header(["Name","Office","Phone","Email"],[45,60,25,60],['L']*4)
#                 for c in std.FDA_Technical_Contacts:
#                     pdf.draw_table_row([c.Name, c.Office, c.Phone, c.Email],[45,60,25,60],['L']*4)

#             if isinstance(std.Public_Law_CFR_Procode, list):
#                 pdf.section_title("CFR Procode Entries")
#                 pdf.draw_table_header(["Device Name","Class","Regulation No","Product Code"],[120,20,25,25],['L','C','C','C'])
#                 for e in std.Public_Law_CFR_Procode:
#                     reg = e.Regulation_Number.text if e.Regulation_Number else "N/A"
#                     code = e.Product_Code.code if e.Product_Code else "N/A"
#                     reg_url = e.Regulation_Number.url if e.Regulation_Number and e.Regulation_Number.url else None
#                     code_url = e.Product_Code.url if e.Product_Code and e.Product_Code.url else None
#                     pdf.draw_table_row([e.Device_Name, e.Device_Class, reg, code],
#                                        [120,20,25,25],['L','C','C','C'],
#                                        links=[None,None,reg_url,code_url])

#             pdf.output(path)
#             logger.info(f"PDF -> {path}")
#             return path
#         except Exception as e:
#             logger.error(f"PDF generation failed for {pdf_fn}: {e}")
#             return None  # Allow HTML to continue

#     # ------------------------------------------------------------------
#     # MAIN: process unprocessed rows
#     # ------------------------------------------------------------------
#     def process_unprocessed(self, df: pd.DataFrame):
#         session = get_session()
#         for idx, row in df.iterrows():
#             url = row["title_link"]
#             pdf_fn, html_fn = self._filename(row["recognition_number"], row["standard_title"])

#             # Skip if already in S3
#             if self.s3 and self.s3.exists(f"{self.s3_prefix}PDF/{pdf_fn}") and self.s3.exists(f"{self.s3_prefix}HTML/{html_fn}"):
#                 logger.info(f"Skip (S3): {url}")
#                 time.sleep(0.5)
#                 continue

#             # Random delay 2‑5 s
#             delay = random.uniform(2.0, 5.0)
#             logger.info(f"[{idx+1}/{len(df)}] Wait {delay:.1f}s → {url}")
#             time.sleep(delay)

#             try:
#                 headers = {"User-Agent": random.choice(USER_AGENTS)}
#                 resp = session.get(url, headers=headers, timeout=20)

#                 # FDA abuse‑detection page
#                 if "abuse-detection-apology" in resp.url or resp.status_code == 404:
#                     logger.warning(f"FDA blocked (abuse): {url}")
#                     self.db.update_s3_paths(url, "BLOCKED", "BLOCKED")
#                     continue

#                 if resp.status_code == 403:
#                     logger.warning(f"403 → fallback {url}")
#                     raw = {"url": url}
#                     m = re.search(r"standard__identification_no=(\d+)", url)
#                     raw["standard_identification_no"] = int(m.group(1)) if m else None
#                     std = FdaStandard(**raw)
#                 else:
#                     resp.raise_for_status()
#                     raw = extract_fda_standard_data(resp.text)
#                     raw["url"] = url
#                     m = re.search(r"standard__identification_no=(\d+)", url)
#                     raw["standard_identification_no"] = int(m.group(1)) if m else None
#                     std = FdaStandard(**raw)

#                 # Generate files
#                 pdf_path = self.generate_pdf(std, pdf_fn)
#                 html_path = generate_html(std.model_dump(), html_fn, self.html_dir)

#                 # Upload only if file exists
#                 uploaded = True
#                 if self.s3:
#                     if pdf_path and not self.s3.upload(pdf_path, f"{self.s3_prefix}PDF/{pdf_fn}", "application/pdf"):
#                         uploaded = False
#                     if html_path and not self.s3.upload(html_path, f"{self.s3_prefix}HTML/{html_fn}", "text/html"):
#                         uploaded = False
#                     if uploaded:
#                         # Update DB only if at least HTML uploaded
#                         self.db.update_s3_paths(url, pdf_fn if pdf_path else "FAILED", html_fn)
#                         # Clean up local files
#                         for p in (pdf_path, html_path):
#                             if p and os.path.exists(p):
#                                 try: os.remove(p)
#                                 except: pass
#                     else:
#                         logger.warning(f"Upload failed for {url}")
#                 else:
#                     logger.info(f"Local only: {pdf_fn}, {html_fn}")

#             except Exception as e:
#                 logger.error(f"Failed {url}: {e}")
#                 self.db.update_s3_paths(url, "FAILED", "FAILED")

#     # ------------------------------------------------------------------
#     # Public entry point
#     # ------------------------------------------------------------------
#     def run(self):
#         unproc = self.db.get_unprocessed_standards()
#         if unproc.empty:
#             logger.info("No unprocessed standards")
#             return
#         self.process_unprocessed(unproc)







