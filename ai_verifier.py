# ai_verifier.py

import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS 
from googlesearch import search as google_search # Backup Engine
from thefuzz import fuzz 
import re
import urllib3
import time

from app import app, db, Job 

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_text_from_url(url):
    """
    Visits a URL and extracts all visible text.
    """
    try:
        print(f"   🔗 Reading: {url[:60]}...")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=10, verify=False)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            for script in soup(["script", "style", "nav", "footer"]):
                script.extract()
            clean_text = soup.get_text(separator=' ', strip=True).lower()
            print(f"      ✅ Success! ({len(clean_text)} characters)")
            return clean_text
        else:
            print(f"      ❌ Failed (Status: {response.status_code})")
            return ""
    except Exception as e:
        print(f"      ❌ Connection Error: {e}")
        return ""

def perform_search(query):
    """
    Tries DuckDuckGo first. If it fails, switches to Google.
    Returns a list of URLs.
    """
    urls = []
    
    # 1. Try DuckDuckGo
    try:
        print(f"   🔎 Trying DuckDuckGo for: '{query}'")
        results = DDGS().text(query, max_results=5)
        if results:
            for r in results:
                urls.append(r['href'])
            print(f"      ✅ DuckDuckGo found {len(urls)} links.")
            return urls
    except Exception as e:
        print(f"      ⚠️ DuckDuckGo Error: {e}")

    # 2. Try Google (Backup)
    if not urls:
        print("   ⚠️  DuckDuckGo failed/empty. Switching to Google...")
        try:
            # sleep_interval prevents blocking
            results = google_search(query, num_results=5, sleep_interval=2)
            urls = list(results)
            print(f"      ✅ Google found {len(urls)} links.")
        except Exception as e:
            print(f"      ❌ Google Search Error: {e}")
            
    return urls

def verify_and_approve_job(job_id):
    
    with app.app_context():
        print(f"\n🕵️‍♂️ AI Agent STARTING: Fact-checking Job ID {job_id}...")
        
        job = Job.query.get(job_id)
        if not job: return

        web_knowledge_text = ""
        
        # --- STEP 1: GENERATE QUERY ---
        # "SarkariExam" is preferred, but we keep it slightly broad to ensure hits
        query = f"{job.company} {job.title} recruitment sarkari"
        
        # --- STEP 2: GET URLS (Dual Engine) ---
        found_urls = perform_search(query)
        
        if not found_urls:
            print("   ❌ CRITICAL: Both search engines returned 0 results.")
            job.status = 'Rejected'
            db.session.commit()
            return

        # --- STEP 3: READ URLS ---
        for url in found_urls:
            # Skip unreadable formats
            if "youtube.com" in url or ".pdf" in url: continue

            # Logic: Read everything we find until we have enough text
            # We prioritize SarkariExam if it appears in the list
            if "sarkariexam" in url:
                print("   🎯 FOUND SARKARIEXAM LINK!")
                web_knowledge_text += get_text_from_url(url)
                break # Found the best source
            
            # Otherwise, read trusted sites
            elif "sarkari" in url or "gov.in" in url or "jagran" in url:
                 web_knowledge_text += get_text_from_url(url)
            
            # Fallback: Read generic sites if knowledge is empty
            elif len(web_knowledge_text) < 500:
                 web_knowledge_text += get_text_from_url(url)

        # --- STEP 4: VERIFY ---
        print("   🧠 Analyzing Content...")
        
        if len(web_knowledge_text) < 100:
            print("   ❌ No readable text extracted. Rejecting.")
            job.status = 'Rejected'
            db.session.commit()
            return

        # MATCHING
        company_score = fuzz.partial_ratio(job.company.lower(), web_knowledge_text)
        title_score = fuzz.partial_ratio(job.title.lower(), web_knowledge_text)
        
        # KEYWORDS (Recruitment, Apply, Online)
        keyword_score = 0
        keywords = ["recruitment", "apply", "notification", "vacancy", "online form"]
        for k in keywords:
            if k in web_knowledge_text:
                keyword_score = 100
                break

        # CALCULATION
        final_confidence = (company_score * 0.4) + (title_score * 0.4) + (keyword_score * 0.2)
        
        print(f"   📊 Scores -> Company: {company_score} | Title: {title_score} | Context: {keyword_score}")
        print(f"   🎯 Confidence: {int(final_confidence)}%")

        job.ai_confidence = int(final_confidence)
        
        if final_confidence >= 50:
            job.status = 'Approved'
            print("   ✅ STATUS: APPROVED (Live)")
        else:
            job.status = 'Rejected'
            print("   ❌ STATUS: REJECTED (Hidden)")

        db.session.commit()