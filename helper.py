from bs4 import BeautifulSoup
import re
import pandas as pd

# Reads a CSV and extracts the 'Title Link' column, optionally limiting number of rows
def read_urls_from_csv(file_path: str, limit: int | None = None) -> list[str]:
    """
    Reads URLs from the 'Title Link' column of a CSV file.

    Args:
        file_path (str): Path to the CSV file.
        limit (int | None): Optional maximum number of URLs to return. 
            If None, returns all URLs.

    Returns:
        list[str]: A list of cleaned, non-null URL strings.
    """
    df = pd.read_csv(file_path)
    total_rows = len(df)
    cleaned_urls = df['Title Link'].dropna().astype(str).str.strip()
    print(f"Total rows in CSV: {total_rows}")
    return cleaned_urls.head(limit).tolist() if limit is not None else cleaned_urls.tolist()

# Parses HTML content from an FDA page and extracts structured standard information
def extract_fda_standard_data(html: str) -> dict:
    """
    Extracts structured FDA standard data from the given HTML page content.

    Parses fields such as recognition numbers, standard details, 
    regulatory citations, guidance documents, and contact info from FDA pages.

    Args:
        html (str): Raw HTML content of an FDA standard detail page.

    Returns:
        dict: A dictionary containing structured data with keys like:
            - FR_Recognition_List_Number
            - Date_of_Entry
            - FR_Recognition_Number
            - Standard
            - Scope_Abstract
            - Extent_of_Recognition
            - Rationale_for_Recognition
            - Transition_Period
            - Public_Law_CFR_Procode
            - FDA_Guidance_Publications
            - FDA_Technical_Contacts
            - Standards_Development_Organization
            - FDA_Specialty_Task_Group
    """
    soup = BeautifulSoup(html, "lxml")
    
    # Initialize with all expected fields set to None
    data = {
        "FR_Recognition_List_Number": None,
        "Date_of_Entry": None,
        "FR_Recognition_Number": None,
        "Standard": None,
        "Scope_Abstract": None,
        "Extent_of_Recognition": None,
        "Rationale_for_Recognition": None,
        "Transition_Period": None,
        "Public_Law_CFR_Procode": None,
        "FDA_Guidance_Publications": None,
        "FDA_Technical_Contacts": None,
        "Standards_Development_Organization": {
            "Acronym": None,
            "Name": None,
            "Website": None
        },
        "FDA_Specialty_Task_Group": None
    }

    # Extract FR Recognition List Number
    fr_info = soup.find(string="FR Recognition List Number")
    if fr_info:
        td = fr_info.find_parent("td").find_next_sibling("td")
        data["FR_Recognition_List_Number"] = td.text.strip()

    # Extract Date of Entry
    date_info = soup.find(string="Date of Entry")
    if date_info:
        data["Date_of_Entry"] = date_info.find_next("span").text.strip()

    # Extract FR Recognition Number
    fr_number = soup.find(string="FR Recognition Number")
    if fr_number:
        td = fr_number.find_parent("td").find_next_sibling("td")
        data["FR_Recognition_Number"] = td.text.strip()

    # Extract Standard details: Organization, Number/Edition, and Title
    standard_table = soup.find("td", string="Standard")
    if standard_table:
        full_text = standard_table.find_next("table").get_text(separator=" ").replace('\u00a0', '').strip()
        lines = [l.strip() for l in full_text.splitlines() if l.strip()]
        data["Standard"] = " - ".join(lines) if lines else None
        
    

    # Extract Scope/Abstract section
    scope = soup.find("span", string="Scope/Abstract")
    if scope:
        abstract = scope.find_next("table").get_text(" ", strip=True)
        data["Scope_Abstract"] = abstract

    # Extract Extent of Recognition
    extent = soup.find("span", string="Extent of Recognition")
    if extent:
        data["Extent_of_Recognition"] = extent.find_next("table").get_text(strip=True)

    # Extract Rationale for Recognition
    rationale = soup.find("span", string="Rationale for Recognition")
    if rationale:
        data["Rationale_for_Recognition"] = rationale.find_next("table").get_text(" ", strip=True)

    # Extract Transition Period
    transition = soup.find("span", string="Transition Period")
    if transition:
        tp_text = transition.find_next("table").get_text(" ", strip=True)
        data["Transition_Period"] = tp_text

    # Helper to split product code into text and optional footnote number
    def extract_product_code_parts(code_text):
        match = re.match(r"^([A-Z]{3,4})(\d+)?$", code_text)
        if match:
            return {"code": match.group(1), "footnote_number": match.group(2) or None}
        return {"code": code_text, "footnote_number": ""}

    # Convert relative FDA links to absolute URLs
    def make_absolute_url(href):
        return f"https://www.accessdata.fda.gov{href}" if href and href.startswith("/") else href

    # Extract CFR & Procode table data (device regulations)
    cfr_section = soup.find("span", string=re.compile("Public Law"))
    if cfr_section:
        table = cfr_section.find_next("table")
        if table:
            rows = table.find_all("tr")
            if len(rows) > 1 and len(rows[0].find_all("td")) >= 3:
                procode_entries = []
                for row in rows[1:]:
                    tds = row.find_all("td")
                    if len(tds) < 4:
                        continue
                    code_text = tds[3].text.strip()
                    code_info = extract_product_code_parts(code_text)
                    code_href = make_absolute_url(tds[3].find("a")["href"]) if tds[3].find("a") else None
                    
                    reg_text = tds[0].text.strip()
                    reg_url = make_absolute_url(tds[0].find("a")["href"]) if tds[0].find("a") else None
                    regulation_number = {
                        "text": reg_text,
                        "url": reg_url
                    } if reg_text and reg_text.upper() != "N/A" else None

                    
                    procode_entries.append({
                        "Regulation_Number": regulation_number,
                        "Device_Name": tds[1].text.strip(),
                        "Device_Class": tds[2].text.strip(),
                        "Product_Code": {
                            "code": code_info["code"],
                            "footnote_number": code_info["footnote_number"] if code_info["footnote_number"] else None,
                            "url": code_href
                        }
                    })
                if procode_entries:
                    data["Public_Law_CFR_Procode"] = procode_entries
            else:
                raw_text = table.get_text(" ", strip=True)
                if raw_text:
                    data["Public_Law_CFR_Procode"] = raw_text

    # Extract FDA Guidance and/or Supportive Publications
    guidance_section = soup.find("span", string=re.compile("Relevant FDA Guidance"))
    if guidance_section:
        table = guidance_section.find_next("table")
        if table:
            lines = [line.strip() for line in table.get_text(separator="\n").split("\n") if line.strip()]
            guidance_items = [line for line in lines if re.match(r"^\d+\.\s", line)]
            if guidance_items:
                data["FDA_Guidance_Publications"] = guidance_items

    # Extract FDA Technical Contacts (with de-duplication on email)
    contact_section = soup.find("span", string=re.compile(r"FDA Technical Contact[s]?", re.IGNORECASE))
    contacts = []
    seen_emails = set()

    if contact_section:
        parent = contact_section.find_parent("tr")
        contact_tables = parent.find_all_next("table", limit=3)
        for contact_table in contact_tables:
            td_tags = contact_table.find_all("td")
            contact_info = {}
            for td in td_tags:
                lines = [line.strip() for line in td.stripped_strings if line.strip()]
                if len(lines) >= 4:
                    contact_info = {"Name": lines[0], "Office": lines[1], "Phone": lines[2], "Email": lines[3]}
                elif len(lines) == 3:
                    contact_info = {"Name": lines[0], "Office": lines[1], "Phone": "", "Email": lines[2]}
                elif len(lines) == 2 and "@" in lines[1]:
                    contact_info = {"Name": lines[0], "Office": "", "Phone": "", "Email": lines[1]}
                if contact_info.get("Email") and contact_info["Email"] not in seen_emails:
                    seen_emails.add(contact_info["Email"])
                    contacts.append(contact_info)

    if contacts:
        data["FDA_Technical_Contacts"] = contacts

    # Extract Standards Development Organization info
    sdo = soup.find("span", string="Standards Development Organization")
    if sdo:
        row = sdo.find_next("table").find("tr")
        tds = row.find_all("td")
        data["Standards_Development_Organization"] = {
            "Acronym": tds[0].text.strip(),
            "Name": tds[1].text.strip(),
            "Website": tds[2].find("a")["href"] if tds[2].find("a") else ""
        }

    # Extract FDA Specialty Task Group (STG)
    stg = soup.find("span", string="FDA Specialty Task Group (STG)")
    if stg:
        data["FDA_Specialty_Task_Group"] = stg.find_next("table").get_text(strip=True)

    return data
