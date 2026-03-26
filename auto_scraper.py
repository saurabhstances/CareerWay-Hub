import requests
from bs4 import BeautifulSoup
from app import app, db, Job
import urllib3
import time
from datetime import datetime

# Import the mechanical hand
try:
    from ai_scraper import scrape_job_smartly
except ImportError:
    print("❌ Critical: Could not import ai_scraper.py")
    def scrape_job_smartly(url): return None

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 1. SARKARI SCRAPER (GOVERNMENT JOBS ONLY)
# ==========================================
def fetch_govt_jobs():
    TARGET_URL = "https://www.sarkariexam.com/"
    count = 0
    
    with app.app_context():
        print(f"\n🤖 Auto-Bot (Govt): Connecting to {TARGET_URL}...")
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            response = requests.get(TARGET_URL, headers=headers, verify=False, timeout=20)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            target_section = None
            for header in soup.find_all(['h2', 'h3', 'span', 'strong']):
                if "Top Online Form" in header.get_text(strip=True):
                    target_section = header.find_parent('div') 
                    print("   🎯 Govt Target Locked: 'Top Online Form'")
                    break
            
            if not target_section: return 0

            links = target_section.find_all('a', href=True)
            jobs_to_scrape = links[:15]
            jobs_to_scrape.reverse() 

            for link in jobs_to_scrape:
                title = link.get_text(strip=True)
                url = link['href']
                if "View All" in title or len(title) < 5: continue
                
                if Job.query.filter_by(title=title).first(): continue

                print(f"   ✨ Govt Extracting: {title[:40]}...")
                job_data = scrape_job_smartly(url)
                
                if job_data:
                    job = Job(
                        title=title,
                        company=job_data['company'],
                        location=job_data['location'],
                        salary=job_data['salary'],
                        skills=job_data['skills'],
                        description=job_data['description'], 
                        last_date=job_data['last_date'],
                        application_start_date=job_data['start_date'],
                        job_type='Govt',
                        category='Govt / PSU', 
                        source_link=job_data['source_link'], 
                        status='Approved',
                        ai_confidence=100,
                        recruiter_id=1
                    )
                    db.session.add(job)
                    db.session.commit()
                    count += 1
                    time.sleep(2)

            print(f"   ✅ Govt Finished! Added {count} new jobs.")
            return count

        except Exception as e:
            print(f"   ❌ Govt Global Error: {e}")
            return 0

# --- MASTER CONTROLLER ---
def fetch_latest_jobs():
    # Only fetches Govt jobs now
    return fetch_govt_jobs()