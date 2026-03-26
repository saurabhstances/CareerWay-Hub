import requests
from bs4 import BeautifulSoup
import re

def clean_html(soup_element):
    """
    Cleans the HTML: removes ads, scripts, and internal links.
    """
    if not soup_element: return ""
    
    # 1. Remove Junk Tags
    for tag in soup_element(["script", "style", "iframe", "ins", "button", "input", "form"]):
        tag.decompose()
        
    # 2. Remove "Google Ads" or empty divs
    for div in soup_element.find_all("div"):
        if "ad" in str(div.get("class", [])).lower() or "adsbygoogle" in str(div):
            div.decompose()

    # 3. Fix Links: Make sure they open in new tab
    for a in soup_element.find_all("a"):
        a['target'] = "_blank"
        # Optional: Remove links if you don't want them leaving your site
        # if "sarkariexam" in a.get('href', ''): a.replace_with(a.get_text())

    # 4. Format Tables for your Dashboard
    for table in soup_element.find_all("table"):
        table['class'] = "table table-bordered table-striped"
        
    # 5. Convert their Headers (h2) to your Blue Headers (h3)
    for header in soup_element.find_all(["h1", "h2", "h4"]):
        new_tag = soup_element.new_tag("h3")
        new_tag.string = header.get_text()
        header.replace_with(new_tag)

    return str(soup_element)

def scrape_job_direct(url):
    print(f"⚡ Direct Scraping: {url}...")
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10, verify=False)
        
        if response.status_code != 200: return None
        
        soup = BeautifulSoup(response.text, 'html.parser')

        # --- EXTRACT META DATA ---
        # Try to find the title
        title = soup.find('h1')
        job_title = title.get_text(strip=True) if title else "Govt Job"
        
        # --- EXTRACT MAIN CONTENT ---
        # SarkariExam usually puts everything inside '.post-content' or '#post-content'
        content = soup.find('div', class_='post-content') or soup.find('div', id='post-content') or soup.find('article')
        
        if not content:
            # Fallback: Try finding the first table and its parent
            first_table = soup.find('table')
            if first_table: content = first_table.parent
        
        if not content:
            print("   ❌ Could not find content block.")
            return None

        # --- CLEAN THE CONTENT ---
        clean_html_str = clean_html(content)
        
        # --- EXTRACT DATES & FEES (Simple Search) ---
        # We search the raw text for these keywords to fill your DB columns
        text_lower = content.get_text().lower()
        
        # Simple extraction for Fees
        fees = "Check Notice"
        if "fee" in text_lower:
            # Find a line with 'fee' and numbers
            fees_match = re.search(r'fee.*?(\d+)', text_lower)
            if fees_match: fees = "See Details"

        # Simple extraction for Last Date
        last_date = "Check Notice"
        date_match = re.search(r'last date.*?(\d{1,2}\s+[a-zA-Z]+\s+\d{4})', text_lower, re.IGNORECASE)
        if date_match:
            last_date = date_match.group(1)

        return {
            "title": job_title,
            "company": "Govt Org", # Generic default
            "location": "India",
            "salary": "As Per Rules",
            "skills": fees,
            "last_date": last_date,
            "description": clean_html_str, # The full, formatted HTML
            "source_link": url
        }

    except Exception as e:
        print(f"   ❌ Error: {e}")
        return None