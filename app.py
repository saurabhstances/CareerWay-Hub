from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from sqlalchemy import or_
import random
import string
import os
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import threading
import time
import schedule
import urllib3
import google.generativeai as genai
from thefuzz import fuzz, process
import json
import re
from functools import wraps
from flask import request, abort, session, render_template, redirect, url_for
from datetime import datetime
import pypdf
from dotenv import load_dotenv

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = "careerway_secret_key"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///careerway.db'
app.config['UPLOAD_FOLDER'] = 'static/resumes'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

UPLOAD_FOLDER = 'static/uploads/feedback'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# --- GEMINI CONFIG ---
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# --- EMAIL CONFIG ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USERNAME'] = 'your_email@gmail.com' # CHANGE THIS
app.config['MAIL_PASSWORD'] = 'xxxx xxxx xxxx xxxx'  # CHANGE THIS
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True

mail = Mail(app)
db = SQLAlchemy(app)
with app.app_context():
    db.create_all()

# ===========================
#        DATABASE MODELS
# ===========================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    mobile = db.Column(db.String(15))
    location = db.Column(db.String(100))
    # --- PRO PROFILE FIELDS ---
    skills = db.Column(db.String(500))
    degree = db.Column(db.String(100))
    specialization = db.Column(db.String(100))
    passing_year = db.Column(db.String(10))
    experience = db.Column(db.String(20))
    target_role = db.Column(db.String(100))
    work_mode = db.Column(db.String(20))
    portfolio = db.Column(db.String(200))
    resume_filename = db.Column(db.String(200))
    
    my_applications = db.relationship('Application', backref='student', lazy=True)
    is_flagged = db.Column(db.Boolean, default=False)
    
class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    company = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(100), nullable=False)
    salary = db.Column(db.String(50))
    skills = db.Column(db.String(500))
    job_type = db.Column(db.String(20))
    work_mode = db.Column(db.String(20))
    experience_req = db.Column(db.String(50))
    
    # --- DATES ---
    last_date = db.Column(db.String(50)) 
    application_start_date = db.Column(db.String(50)) 
    
    # --- SMART COLUMNS ---
    application_fee = db.Column(db.String(100))
    min_qualification = db.Column(db.String(100))
    age_limit = db.Column(db.String(50))
    category = db.Column(db.String(50), default='General')
    
    description = db.Column(db.Text)
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)
    recruiter_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    source_link = db.Column(db.String(500))
    status = db.Column(db.String(20), default='Active')
    ai_confidence = db.Column(db.Integer, default=0)
    applications = db.relationship('Application', backref='job', lazy=True)

class Application(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date_applied = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='Applied')
    cover_letter = db.Column(db.Text)

class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50))
    file_filename = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    uploader_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    uploader_name = db.Column(db.String(100))

# --- STUDY LOG MODEL ---
class StudyLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.String(20), nullable=False) # Format YYYY-MM-DD
    status = db.Column(db.String(20), default='Completed')
    topic_covered = db.Column(db.String(100))


    def __repr__(self):
        return f'<Feedback {self.category} - {self.id}>'

# --- HELPERS ---
def generate_unique_username(full_name):
    base_name = "".join(e for e in full_name if e.isalnum()).lower()
    candidate = base_name
    while User.query.filter_by(username=candidate).first():
        candidate = base_name + str(random.randint(100, 999))
    return candidate

def calculate_profile_score(user):
    score = 0
    if user.name: score += 10
    if user.email: score += 10
    if user.mobile: score += 15
    if user.location: score += 10
    if user.skills: score += 20
    if user.degree: score += 10
    if user.resume_filename: score += 25
    return min(score, 100)

def send_job_alert_email(job_list):
    with app.app_context():
        users = User.query.filter_by(role='Student').all()
        emails = [u.email for u in users]
        if not emails or not job_list: return
        try:
            msg = Message(f"🚀 {len(job_list)} New Jobs Found!", sender=app.config['MAIL_USERNAME'], recipients=emails)
            body = "<h3>Fresh Jobs:</h3><ul>"
            for job in job_list:
                body += f"<li><b>{job['title']}</b> - {job['company']} <br> <a href='{job['link']}'>View Job</a></li>"
            body += "</ul>"
            msg.html = body
            mail.send(msg)
        except Exception as e: print(f"Email Error: {e}")

def run_scheduler():
    from auto_scraper import fetch_latest_jobs
    try:
        new_jobs = fetch_latest_jobs()
        if new_jobs: pass 
    except: pass
    schedule.every(6).hours.do(lambda: fetch_latest_jobs())
    while True:
        schedule.run_pending()
        time.sleep(60)

# --- SMART MATCHING LOGIC ---
def get_recommendations(user):
    if not user.skills: return []
    
    user_skills = [s.strip().lower() for s in user.skills.split(',')]
    user_role = user.target_role.lower() if user.target_role else ""
    user_city = user.location.lower() if user.location else ""
    is_fresher = True if user.experience == "Fresher" else False
    
    all_jobs = Job.query.filter_by(status='Active').all() + Job.query.filter_by(status='Approved').all()
    scored_jobs = []
    
    for job in all_jobs:
        score = 0
        reasons = []
        
        if user_role:
            role_sim = fuzz.token_set_ratio(user_role, job.title.lower())
            score += role_sim * 0.4
            if role_sim > 70: reasons.append("Role Match")

        if job.skills:
            job_skills = [s.strip().lower() for s in job.skills.split(',')]
            common = sum(1 for s in user_skills if any(s in js for js in job_skills))
            skill_score = min(common * 10, 30)
            score += skill_score
            if common > 0: reasons.append(f"{common} Shared Skills")

        if user_city and user_city in job.location.lower():
            score += 15
            reasons.append("Location Match")
            
        job_title_lower = job.title.lower()
        if is_fresher:
            if "senior" in job_title_lower or "manager" in job_title_lower or "lead" in job_title_lower:
                score -= 20 
            else:
                score += 15 
        
        if "bank" in user.skills.lower() and job.category == "Bank": score += 10
        if "police" in user.skills.lower() and job.category == "Defence/Police": score += 10

        if score > 35:
            scored_jobs.append({
                "job": job,
                "score": int(min(score, 99)),
                "reason": ", ".join(reasons[:2]) if reasons else "Profile Match"
            })
            
    scored_jobs.sort(key=lambda x: x['score'], reverse=True)
    return scored_jobs[:6]

# ===========================
#        AUTH ROUTES
# ===========================

@app.route('/')
def home(): return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_input = request.form['email']
        password = request.form['password']
        user = User.query.filter(or_(User.email == user_input, User.username == user_input)).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['user_name'] = user.name
            session['user_role'] = user.role
            if user.role == 'Recruiter': return redirect(url_for('recruiter_dashboard'))
            if user.skills is None: return redirect(url_for('complete_profile'))
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid Credentials", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']
        auto_username = generate_unique_username(name)
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        
        new_user = User(name=name, email=email, password=hashed_password, role=role, username=auto_username)
        try:
            db.session.add(new_user)
            db.session.commit()
            session['user_id'] = new_user.id
            session['user_name'] = new_user.name
            session['user_role'] = new_user.role
            flash(f"Account Created! Welcome, {name}.", "success")
            if role == 'Recruiter': return redirect(url_for('recruiter_dashboard'))
            return redirect(url_for('dashboard'))
        except Exception as e: 
            print(f"Register Error: {e}") 
            flash("Error: Email already exists.", "danger")
    return render_template('register.html')

# ===========================
#      DASHBOARD & CORE
# ===========================

def parse_date_str(date_str):
    if not date_str or date_str in ["Check Notice", "Not Specified"]: return None
    try:
        clean_date = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_str)
        return datetime.strptime(clean_date, "%d %B %Y")
    except: return None

@app.route('/dashboard')
def dashboard():
    # 1. --- LOGGED IN CHECK ---
    is_logged_in = 'user_id' in session
    user_id = session.get('user_id')
    user = User.query.get(user_id) if is_logged_in else None
    
    # Redirect if recruiter (security)
    if is_logged_in and session.get('user_role') == 'Recruiter':
        return redirect(url_for('recruiter_dashboard'))
    
    page = request.args.get('page', 1, type=int)
    
    # 2. --- JOBS DATA (Shared for User & Guest) ---
    govt_jobs_pagination = Job.query.filter_by(job_type='Govt').order_by(Job.id.desc()).paginate(page=page, per_page=20, error_out=False)
    private_jobs = Job.query.filter_by(job_type='Private', status='Active').order_by(Job.date_posted.desc()).all()
    
    # Distance Logic
    user_city = user.location.lower().strip() if (user and user.location) else ""
    for job in private_jobs:
        job_city = job.location.lower().strip()
        if user_city and (user_city in job_city or job_city in user_city):
            job.distance = round(random.uniform(0.5, 4.8), 1)
        else:
            job.distance = round(random.uniform(10.5, 45.0), 1)

    today = datetime.now()
    for job in govt_jobs_pagination.items:
        job.is_expiring = False
        job.is_new = False
        if job.last_date:
            ld = parse_date_str(job.last_date)
            if ld and 0 <= (ld - today).days <= 7: job.is_expiring = True
        if job.application_start_date:
            sd = parse_date_str(job.application_start_date)
            if sd and 0 <= (today - sd).days <= 5: job.is_new = True

    # 3. --- PERSONALIZED DATA (Conditioned on Login) ---
    recommendations = get_recommendations(user) if is_logged_in else []
    applied_ids = []
    my_apps = []
    top_candidates = []
    
    # Default Stats for Guest
    stats = {
        'total': 0, 'interviews': 0, 'score': 0, 'pending': 0, 'streak': 0, 'dates': []
    }

    if is_logged_in:
        # Streak Calculation
        logs = StudyLog.query.filter_by(user_id=user.id).all()
        completed_dates = list(set([log.date for log in logs]))
        current_streak = len(completed_dates)

        my_apps = Application.query.filter_by(student_id=user.id).all()
        applied_ids = [app.job_id for app in my_apps]
        
        stats = {
            'total': len(my_apps),
            'interviews': Application.query.filter_by(student_id=user_id, status='Shortlisted').count(),
            'score': calculate_profile_score(user),
            'pending': Application.query.filter_by(student_id=user_id, status='Applied').count(),
            'streak': current_streak,
            'dates': completed_dates
        }

        # Leaderboard Logic (Only for logged in users to save processing)
        all_students = User.query.filter_by(role='Student').all()
        leaderboard_data = []
        for student in all_students:
            p_score = calculate_profile_score(student)
            student_logs = StudyLog.query.filter_by(user_id=student.id).all()
            s_streak = len(set([log.date for log in student_logs]))
            total_points = p_score + (s_streak * 10)
            
            leaderboard_data.append({
                'name': "You" if student.id == user_id else student.name.split()[0],
                'is_me': student.id == user_id,
                'points': total_points,
                'streak': s_streak,
                'is_pro': True if s_streak >= 5 or p_score >= 90 else False 
            })
        leaderboard_data.sort(key=lambda x: x['points'], reverse=True)
        top_candidates = leaderboard_data[:5]

    todays_byte = {"word": "Ubiquitous", "meaning": "Present everywhere.", "gk": "USB was invented by Ajay Bhatt.", "color": "primary"}
    
    # 4. --- RENDER ---
    return render_template('dashboard.html', 
                            is_logged_in=is_logged_in,  # IMPORTANT: Pass this to hide features
                            private_jobs=private_jobs, 
                            govt_jobs=govt_jobs_pagination, 
                            recommendations=recommendations,
                            my_apps=my_apps, 
                            applied_ids=applied_ids, 
                            stats=stats, 
                            user_name=session.get('user_name', 'Guest'), 
                            daily_byte=todays_byte,
                            top_candidates=top_candidates)

@app.route('/email_matches', methods=['POST'])
def email_matches():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    
    recs = get_recommendations(user)
    if not recs:
        flash("No matches found to email.", "warning")
        return redirect(url_for('dashboard'))
        
    try:
        msg = Message(f"🔥 Your Top Job Matches from CareerWay", sender=app.config['MAIL_USERNAME'], recipients=[user.email])
        body = f"<h3>Hi {user.name}, here are jobs matching your skills:</h3><ul>"
        for item in recs:
            job = item['job']
            body += f"<li><b>{job.title}</b> ({item['score']}% Match)<br>Link: {job.source_link}<br>Deadline: {job.last_date}</li><br>"
        body += "</ul><p>Apply now via CareerWay Dashboard.</p>"
        msg.html = body
        mail.send(msg)
        flash(f"Sent {len(recs)} matches to {user.email}!", "success")
    except Exception as e:
        print(f"Email Error: {e}")
        flash("Could not send email. Check server logs.", "danger")
        
    return redirect(url_for('dashboard'))

@app.route('/auto_fetch_sarkari', methods=['POST'])
def auto_fetch_sarkari():
    from auto_scraper import fetch_latest_jobs
    try:
        new_count = fetch_latest_jobs()
        if new_count > 0:
            flash(f"Success! Bot found {new_count} new Govt & Private jobs.", "success")
        else:
            flash("Scraper ran successfully, but no new jobs were found.", "info")
    except Exception as e:
        print(f"Scraper Error: {e}")
        flash("An error occurred while fetching jobs.", "danger")
    return redirect(url_for('dashboard'))

@app.route('/complete_profile', methods=['GET', 'POST'])
def complete_profile():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    
    if request.method == 'POST':
        user.mobile = request.form.get('mobile')
        user.location = request.form.get('location')
        user.skills = request.form.get('skills')
        user.degree = request.form.get('degree')
        user.passing_year = request.form.get('year')
        
        user.specialization = request.form.get('specialization')
        user.experience = request.form.get('experience')
        user.target_role = request.form.get('target_role')
        user.work_mode = request.form.get('work_mode')
        user.portfolio = request.form.get('portfolio')
        
        if 'resume' in request.files:
            file = request.files['resume']
            if file.filename != '':
                filename = secure_filename(file.filename)
                unique_filename = f"resume_{user.username}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                user.resume_filename = unique_filename
        db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template('student_profile.html', user=user)

@app.route('/job/<int:job_id>')
def view_job(job_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    job = Job.query.get_or_404(job_id)
    user = User.query.get(session['user_id'])
    has_applied = False
    if Application.query.filter_by(job_id=job.id, student_id=user.id).first(): has_applied = True
    return render_template('job_details.html', job=job, has_applied=has_applied)

# --- APPLY PROCESS (EMAIL REMOVED AS REQUESTED) ---
@app.route('/apply_process/<int:job_id>', methods=['GET', 'POST'])
def apply_process(job_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    job = Job.query.get_or_404(job_id)
    user = User.query.get(session['user_id'])
    existing = Application.query.filter_by(job_id=job.id, student_id=user.id).first()
    
    if existing:
        flash("Already applied.", "info")
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        cover_letter = request.form.get('cover_letter')
        new_app = Application(job_id=job.id, student_id=user.id, cover_letter=cover_letter, status='Applied')
        db.session.add(new_app)
        db.session.commit()
        flash("Application Sent!", "success")
        return redirect(url_for('dashboard'))
        
    return render_template('Apply_Job.html', job=job, user=user)

@app.route('/recruiter_dashboard')
def recruiter_dashboard():
    if 'user_id' not in session or session.get('user_role') != 'Recruiter': return redirect(url_for('login'))
    my_jobs = Job.query.filter_by(recruiter_id=session['user_id']).order_by(Job.date_posted.desc()).all()
    stats = {job.id: Application.query.filter_by(job_id=job.id).count() for job in my_jobs}
    return render_template('recruiter_dashboard.html', jobs=my_jobs, stats=stats, user_name=session.get('user_name'))

@app.route('/post_job', methods=['GET', 'POST'])
def post_job():
    if 'user_id' not in session or session.get('user_role') != 'Recruiter': return redirect(url_for('login'))
    if request.method == 'POST':
        new_job = Job(
            title=request.form['title'], company=request.form['company'], location=request.form['location'],
            salary=request.form['salary'], skills=request.form['skills'], job_type='Private',
            work_mode=request.form['work_mode'], experience_req=request.form['experience'],
            description=request.form['description'], recruiter_id=session['user_id'], status='Active'
        )
        db.session.add(new_job)
        db.session.commit()
        flash("Job Posted!", "success")
        return redirect(url_for('recruiter_dashboard'))
    return render_template('post_job.html')

@app.route('/job_applicants/<int:job_id>')
def job_applicants(job_id):
    if 'user_id' not in session or session.get('user_role') != 'Recruiter': 
        return redirect(url_for('login'))
    
    job = Job.query.get_or_404(job_id)
    if job.recruiter_id != session['user_id']: 
        return redirect(url_for('recruiter_dashboard'))
    
    ranked_applicants = []
    job_skills = job.skills.lower() if job.skills else ""
    
    for application in job.applications:
        student = application.student
        student_skills = student.skills.lower() if student.skills else ""
        
        match_score = fuzz.token_set_ratio(job_skills, student_skills)
        if job.experience_req == student.experience: match_score += 10
        if job.location and student.location and job.location.lower() in student.location.lower(): match_score += 5
        
        match_score = min(match_score, 100)
        ranked_applicants.append({"app": application, "student": student, "score": match_score})
    
    ranked_applicants.sort(key=lambda x: x['score'], reverse=True)
    return render_template('applicants_list.html', job=job, applicants=ranked_applicants, user_name=session.get('user_name'))

# --- UPDATE STATUS (EMAIL REMOVED) ---
@app.route('/update_status/<int:app_id>/<string:status>')
def update_status(app_id, status):
    if 'user_id' not in session or session.get('user_role') != 'Recruiter': return redirect(url_for('login'))
    application = Application.query.get_or_404(app_id)
    application.status = status
    db.session.commit()
    return redirect(url_for('job_applicants', job_id=application.job.id))

@app.route('/library')
def library():
    if 'user_id' not in session: return redirect(url_for('login'))
    resources = Resource.query.order_by(Resource.uploaded_at.desc()).all()
    govt_papers = [r for r in resources if r.category == 'Govt Papers']
    coding_notes = [r for r in resources if r.category == 'Coding Notes']
    syllabus = [r for r in resources if r.category == 'Syllabus']
    return render_template('library.html', govt_papers=govt_papers, coding_notes=coding_notes, syllabus=syllabus, user_name=session.get('user_name'))

@app.route('/upload_resource', methods=['GET', 'POST'])
def upload_resource():
    if 'user_id' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        file = request.files['file']
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            unique_filename = f"book_{int(time.time())}_{filename}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
            new_res = Resource(title=request.form['title'], category=request.form['category'], file_filename=unique_filename, description="Community Upload", uploader_id=session['user_id'], uploader_name=session['user_name'])
            db.session.add(new_res)
            db.session.commit()
            return redirect(url_for('library'))
    return render_template('upload_resource.html')

@app.route('/download/<filename>')
def download_file(filename):
    if 'user_id' not in session: return redirect(url_for('login'))
    return redirect(url_for('static', filename='resumes/' + filename))

@app.route('/resume_builder', methods=['GET', 'POST'])
def resume_builder():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    
    if request.method == 'POST':
        # Passes beautifully formatted form data directly to the preview!
        form_data = request.form
        return render_template('resume_preview.html', user=user, data=form_data)
        
    return render_template('resume_form.html', user=user)

@app.route('/ai_job_matcher')
def ai_job_matcher():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    return render_template('job_matches.html', user=user)

@app.route('/api/perform_match', methods=['POST'])
def api_perform_match():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    user = User.query.get(session['user_id'])
    jobs = Job.query.filter(or_(Job.status=='Approved', Job.status=='Active')).limit(15).all()
    jobs_data = [{"id": j.id, "title": j.title, "company": j.company, "skills": j.skills} for j in jobs]
    prompt = f"Rank top 3 jobs for {user.skills} from: {jobs_data}. Return JSON list."
    try:
        res = genai.GenerativeModel('gemini-2.5-flash').generate_content(prompt) 
        matches = json.loads(res.text.replace('```json', '').replace('```', '').strip())
        final = []
        for m in matches:
            job = next((j for j in jobs if j.id == int(m.get('job_id', 0))), None)
            if job: final.append({"title": job.title, "company": job.company, "score": m['match_score'], "reason": m['reason'], "link": url_for('view_job', job_id=job.id)})
        return jsonify({"matches": final})
    except: return jsonify({"matches": []})

@app.route('/submit_govt_job', methods=['GET', 'POST'])
def submit_govt_job():
    if 'user_id' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        pass  
    return render_template('add_job.html')

# --- 1. UPGRADED SMART CHAT BOT WITH STRICT STRUCTURE ---
@app.route('/ask_botg', methods=['POST'])
def ask_botg():
    if 'user_id' not in session: 
        return {"reply": "Please login to chat with me! 🤖"}
        
    try:
        user = User.query.get(session['user_id'])
        user_message = request.json.get('message', '')
        language = request.json.get('language', 'English')
        
        # Safely handle empty skills
        user_skills = user.skills if user.skills else 'None listed'
        
        my_apps = Application.query.filter_by(student_id=user.id).all()
        applied_jobs = [app.job.title for app in my_apps]
        
        all_jobs = Job.query.filter_by(status='Active').all()
        job_catalog = ""
        for j in all_jobs:
            job_catalog += f"ID:{j.id} | Title:{j.title} | Company:{j.company} | Type:{j.job_type} | Salary:{j.salary} | Location:{j.location}\n"

        prompt = f"""
        You are 'BotG', the highly professional AI career assistant for CareerWay AI.
        User: {user.name}. Skills: {user_skills}.
        Applied to: {', '.join(applied_jobs) if applied_jobs else 'None'}.

        LIVE JOB CATALOG:
        {job_catalog}

        USER MESSAGE: "{user_message}"
        LANGUAGE: "{language}" (You MUST translate your final answer to this language)

        CRITICAL STRICT RULES - READ CAREFULLY:
        1. NO PARAGRAPHS. You are strictly forbidden from writing walls of text.
        2. ALWAYS use HTML bullet points (<ul><li>...</li></ul>) when answering questions or giving advice.
        3. If the user asks for a job (e.g., "python jobs"), search the LIVE JOB CATALOG. Output EVERY matching job using EXACTLY this HTML card format:
           <div style="background:#F8FAFC; padding:15px; border-radius:10px; margin-bottom:12px; border:1px solid #CBD5E1; color:#1F2937; box-shadow: 0 2px 5px rgba(0,0,0,0.05);">
             <strong style="color:#4F46E5; font-size:1.1rem;">[Job Title]</strong><br>
             <span style="font-size:0.85rem; color:#6B7280;">🏢 [Company] &nbsp;|&nbsp; 📍 [Location]</span><br>
             <span style="font-size:0.9rem; color:#10B981; font-weight:bold; display:block; margin:5px 0;">💰 [Salary]</span>
             <a href="/job/[ID]" style="display:inline-block; padding:8px 15px; background:#4F46E5; color:white; border-radius:6px; text-decoration:none; font-size:0.85rem; font-weight:bold; transition:0.2s;">View & Apply</a>
           </div>
        4. NEVER use markdown symbols like `**`, `*`, or `#`. Only use raw HTML tags (<b>, <ul>, <li>, <br>).
        5. If no jobs match, reply with a short <ul> list explaining that no jobs were found.
        """
        
        model = genai.GenerativeModel('gemini-2.5-flash')
        bot_reply = model.generate_content(prompt).text.strip()
        
        # Clean up any accidental markdown blocks the AI might add
        bot_reply = bot_reply.replace('```html', '').replace('```', '')
        
        return {"reply": bot_reply}
        
    except Exception as e:
        print(f"!!! BotG Error !!! -> {str(e)}")
        return {"reply": f"<b style='color:red;'>System Error:</b> {str(e)}"}


# --- 2. NEW REAL-TIME TRANSLATION API ---
@app.route('/api/translate_chat', methods=['POST'])
def translate_chat():
    data = request.get_json()
    text = data.get('text', '')
    target_lang = data.get('language', 'English')
    
    if not text: return jsonify({'text': ''})
    
    prompt = f"""
    Translate the following HTML text into {target_lang}. 
    CRITICAL: Keep ALL HTML tags (like <div>, <b>, <a>, <br>, <ul>, <li>, <span>, <strong>) completely intact and untranslated. Only translate the human readable text inside the tags.
    
    Text to translate:
    {text}
    """
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        res = model.generate_content(prompt).text.strip()
        res = res.replace('```html', '').replace('```', '')
        return jsonify({'text': res})
    except Exception as e:
        print(f"Translate Error: {e}")
        return jsonify({'text': text}) 
    
@app.route('/interview_prep')
def interview_prep():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    
    my_apps = Application.query.filter_by(student_id=user.id).all()
    
    logs = StudyLog.query.filter_by(user_id=user.id).all()
    streak = len([log.date for log in logs])
    stats = {'streak': streak}
    
    return render_template('interview_prep.html', 
                           user_name=session.get('user_name'), 
                           user=user, 
                           my_apps=my_apps,
                           stats=stats)

@app.route('/api/interview_bot', methods=['POST'])
def interview_bot():
    try:
        data = request.get_json()
        role = data.get('role', 'Software Engineer')
        topic = data.get('topic', 'General HR')
        answer = data.get('answer', '')

        prompt = f"""
        You are an expert AI Interview Coach conducting a mock interview for a '{role}' role.
        The current interview focus is '{topic}'.
        
        The user just provided this answer: "{answer}"
        
        Evaluate their answer, give brief constructive feedback, and ask the NEXT interview question.
        If they say "I am ready" or "Start", skip feedback and just ask the first question.
        
        CRITICAL: Return ONLY a valid JSON object. No intro text. Format exactly like this:
        {{
            "rating": 8,
            "feedback": "Your answer was good because...",
            "next_question": "Tell me about a time when..."
        }}
        """
        
        model = genai.GenerativeModel('gemini-2.5-flash') 
        response = model.generate_content(prompt)
        
        raw_text = response.text.strip()
        
        # BULLETPROOF FIX: Use Regex to extract ONLY the JSON part
        match = re.search(r'\{[\s\S]*\}', raw_text)
        
        if match:
            clean_json = match.group(0)
            return jsonify(json.loads(clean_json))
        else:
            raise ValueError("No JSON found in AI response")
            
    except Exception as e: 
        print(f"!!! INTERVIEW BOT ERROR !!! -> {str(e)}")
        return jsonify({
            "rating": "N/A",
            "feedback": "System adjusting connection...",
            "next_question": "Let's continue. Could you elaborate on your last point?"
        })

# --- AI ROADMAP & DAILY TASK APIs ---

@app.route('/api/generate_roadmap', methods=['POST'])
def generate_roadmap():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    user = User.query.get(session['user_id'])
    
    target_role = user.target_role if user.target_role else "Software Engineer"
    current_skills = user.skills if user.skills else "None"
    
    prompt = f"""
    Create a 4-Week Learning Roadmap for a student wanting to become a '{target_role}'.
    Current Skills: {current_skills}.
    
    Return ONLY a JSON array like this (no markdown):
    [
        {{"week": "Week 1", "topic": "Basics", "details": "Learn variables, loops..."}},
        {{"week": "Week 2", "topic": "Advanced", "details": "Learn OOP, Databases..."}}
    ]
    Make it specific to {target_role}.
    """
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash') 
        response = model.generate_content(prompt)
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        roadmap = json.loads(clean_json)
        return jsonify({"roadmap": roadmap, "role": target_role})
    except Exception as e:
        print(f"Roadmap Error: {e}")
        return jsonify({"error": "AI could not generate roadmap"}), 500

@app.route('/api/get_daily_task', methods=['POST'])
def get_daily_task():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    user = User.query.get(session['user_id'])
    role = user.target_role if user.target_role else "General Govt Exams"
    
    prompt = f"""
    Act as a strict Study Coach for a student preparing for '{role}'.
    Generate a JSON response for TODAY's Daily Task.
    Format:
    {{
        "topic": "Specific Topic Name",
        "hours": "2.5 Hours",
        "syllabus_focus": "One sentence on what sub-topics to cover.",
        "mental_tip": "A short, unique mental health exercise to deal with anxiety/stress.",
        "quiz_question": "A multiple choice question related to the topic.",
        "options": ["Option A", "Option B", "Option C", "Option D"],
        "correct_answer": "Option A"
    }}
    Return ONLY JSON.
    """
    try:
        model = genai.GenerativeModel('gemini-2.5-flash') 
        res = model.generate_content(prompt)
        data = json.loads(res.text.replace('```json', '').replace('```', '').strip())
        return jsonify(data)
    except:
        return jsonify({"error": "AI Brain Busy"})

@app.route('/api/mark_complete', methods=['POST'])
def mark_complete():
    if 'user_id' not in session: return jsonify({"error": "Auth needed"})
    today = datetime.now().strftime("%Y-%m-%d")
    
    existing = StudyLog.query.filter_by(user_id=session['user_id'], date=today).first()
    if not existing:
        new_log = StudyLog(user_id=session['user_id'], date=today, topic_covered="Daily AI Task")
        db.session.add(new_log)
        db.session.commit()
        return jsonify({"status": "success", "streak": "Updated"})
    return jsonify({"status": "already_done"})

# --- 🔥 AI COVER LETTER GENERATOR ---
@app.route('/api/write_cover_letter', methods=['POST'])
def write_cover_letter():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    job_id = data.get('job_id')
    
    user = User.query.get(session['user_id'])
    job = Job.query.get_or_404(job_id)
    
    prompt = f"""
    Write a short, professional Cover Letter for a student named {user.name} applying for the role of '{job.title}' at '{job.company}'.
    
    Candidate Details:
    - Degree: {user.degree}
    - Skills: {user.skills}
    - Experience: {user.experience}
    
    Job Requirements:
    - Skills Needed: {job.skills}
    - Location: {job.location}
    
    Instructions:
    1. Keep it under 150 words.
    2. Mention specifically how the candidate's skills match the job requirements.
    3. Be enthusiastic but formal.
    4. Return ONLY the body of the letter (no subject line, no placeholders like [Your Name]).
    """
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash') 
        response = model.generate_content(prompt)
        return jsonify({"letter": response.text.replace('**', '').strip()})
    except Exception as e:
        return jsonify({"error": "AI is busy writing. Try again."})
    
# --- STRICT RESUME SMART WRITE ---
@app.route('/api/enhance_resume_text', methods=['POST'])
def enhance_resume_text():
    data = request.get_json()
    raw_text = data.get('text', '')
    text_type = data.get('type', 'projects')

    if not raw_text:
        return jsonify({'error': 'No text provided'}), 400

    try:
        prompt = f"""
        You are an expert Human Resume Writer helping a college student. 
        Rewrite the following rough notes about their {text_type} into 2 or 3 highly professional bullet points.
        
        CRITICAL STRICT RULES:
        1. NO MARKDOWN: Never use asterisks (**), bold text, italics, or hashtags. Output plain text only.
        2. SOUND HUMAN: Use natural, clear, and professional language. Avoid robotic, overly complex vocabulary.
        3. EXACT NAMES: Keep the exact project or company names provided.
        4. BULLET FORMAT: Start each point with a standard bullet symbol (•) and a simple, strong action verb. Do not add intro/outro text.
        
        Raw notes from user: {raw_text}
        """
        
        model = genai.GenerativeModel('gemini-2.5-flash') 
        response = model.generate_content(prompt) 
        enhanced_text = response.text.strip()
        
        return jsonify({'enhanced_text': enhanced_text})
        
    except Exception as e:
        print(f"!!! GEMINI API ERROR !!! -> {str(e)}")
        return jsonify({'error': f'Failed to generate text. Error: {str(e)}'}), 500

# --- 🔥 AI RESUME ATS SCANNER ---
@app.route('/api/scan_resume', methods=['POST'])
def scan_resume():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"}), 401
    user = User.query.get(session['user_id'])
    
    if not user.resume_filename:
        return jsonify({"error": "No resume uploaded! Go to Profile to upload one."})
    
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], user.resume_filename)
    
    if not os.path.exists(file_path):
        return jsonify({"error": "Resume file not found on server."})

    try:
        reader = pypdf.PdfReader(file_path)
        resume_text = ""
        for page in reader.pages:
            resume_text += page.extract_text()
    except Exception as e:
        return jsonify({"error": "Could not read PDF. Make sure it's a valid file."})

    target_role = user.target_role if user.target_role else "Software Engineer"
    
    prompt = f"""
    Act as an expert ATS (Applicant Tracking System) Scanner.
    Target Role: {target_role}
    
    Resume Text:
    {resume_text[:3000]} (truncated)
    
    Analyze this resume and provide a JSON response ONLY:
    {{
        "score": 85,
        "summary": "One sentence summary of the resume quality.",
        "missing_keywords": ["Python", "Docker", "Team Leadership"],
        "formatting_issues": ["Fonts are okay", "Avoid tables"]
    }}
    Be strict but helpful.
    """
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash') 
        res = model.generate_content(prompt)
        data = json.loads(res.text.replace('```json', '').replace('```', '').strip())
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": "AI Brain busy. Try again."})

@app.route('/delete_job/<int:job_id>')
def delete_job(job_id):
    if 'user_id' not in session or session.get('user_role') != 'Recruiter': 
        return redirect(url_for('login'))
    
    job = Job.query.get_or_404(job_id)
    
    if job.recruiter_id != session['user_id']:
        flash("You are not authorized to delete this job.", "danger")
        return redirect(url_for('recruiter_dashboard'))
    
    try:
        Application.query.filter_by(job_id=job.id).delete()
        db.session.delete(job)
        db.session.commit()
        flash("Job listing deleted successfully.", "success")
    except Exception as e:
        db.session.rollback()
        print(f"Delete Error: {e}")
        flash("An error occurred while deleting the job.", "danger")
        
    return redirect(url_for('recruiter_dashboard'))

# --- 🔥 AI RECRUITER: SMART APPLICANT RANKING 🔥 ---
@app.route('/api/rank_applicants/<int:job_id>', methods=['POST'])
def ai_rank_applicants(job_id):
    if 'user_id' not in session or session.get('user_role') != 'Recruiter': 
        return jsonify({"error": "Unauthorized"}), 401
    
    job = Job.query.get_or_404(job_id)
    applications = Application.query.filter_by(job_id=job.id).all()
    
    if len(applications) == 0:
        return jsonify({"error": "No applications received yet!"})
        
    # Gather candidate data
    candidates_data = []
    for app in applications:
        st = app.student
        candidates_data.append({
            "id": st.id,
            "name": st.name,
            "skills": st.skills or "None",
            "experience": st.experience or "Fresher",
            "degree": st.degree or "Not specified"
        })
        
    prompt = f"""
    You are an expert AI Tech Recruiter for CareerWay.
    
    Job Title: {job.title}
    Required Skills: {job.skills}
    Experience Needed: {job.experience_req}
    
    Here is the list of candidates who applied (in JSON format):
    {json.dumps(candidates_data)}
    
    Analyze the candidates against the job requirements. Rank the top 3 best matches.
    Return ONLY a valid JSON array of objects with this exact format (no markdown, no backticks):
    [
        {{"name": "Candidate Name", "score": 95, "reason": "1-sentence specific reason why they are a great fit."}}
    ]
    """
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        res = model.generate_content(prompt)
        clean_json = res.text.replace('```json', '').replace('```', '').strip()
        rankings = json.loads(clean_json)
        return jsonify({"rankings": rankings})
    except Exception as e:
        print("Ranking Error:", e)
        return jsonify({"error": "AI servers are busy. Please try again."}), 500

# --- USER FEEDBACK ROUTE ---
@app.route('/feedback', methods=['GET', 'POST'])
def feedback():
    # Guests can provide feedback too, but we track user_id if logged in
    is_logged_in = 'user_id' in session
    
    if request.method == 'POST':
        category = request.form.get('category')
        rating = request.form.get('rating')
        message = request.form.get('message')
        
        # --- 🔥 NEW: Handle File Upload 🔥 ---
        file = request.files.get('screenshot')
        filename = None
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(UPLOAD_FOLDER, filename))
        
        # Log it to your terminal
        print(f"🚀 Feedback: {category} | Rating: {rating} | Msg: {message} | File: {filename}")

        # --- 🔥 Updated Thank You Message 🔥 ---
        flash("Thank you for your valuable feedback from the CareerWay Team.", "success")
        return redirect(url_for('feedback')) # Redirect back to show the alert on the feedback page
        
    return render_template('feedback.html', 
                           user_name=session.get('user_name', 'Guest'), 
                           is_logged_in=is_logged_in)

ADMIN_ACCESS_TOKEN = "CARRY1234"

# 🔥 2. SESSION PROTECTION DECORATOR
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if the session has the admin flag
        if not session.get('is_admin_authenticated'):
            # If not logged in, pretend the page doesn't exist
            abort(404)
        return f(*args, **kwargs)
    return decorated_function

# 🔥 3. THE SECRET GATEWAY (Entry Point)
# URL: http://127.0.0.1:5000/gateway?token=CARRY1234
@app.route('/gateway')
def admin_gateway():
    user_token = request.args.get('token')
    
    if user_token == ADMIN_ACCESS_TOKEN:
        return render_template('admin_login.html')
    
    # Incorrect or missing token results in "Not Found"
    abort(404)

# 🔥 4. AUTHENTICATION PROCESS
@app.route('/process_admin', methods=['POST'])
def process_admin():
    admin_id = request.form.get('admin_id')
    admin_pwd = request.form.get('admin_pwd')
    
    if admin_id == "Saurabh_Admin" and admin_pwd == "Carry1234":
        # Create a permanent secure session
        session.permanent = True 
        session['is_admin_authenticated'] = True
        return redirect(url_for('admin_dashboard'))
    
    return "Invalid Credentials", 403

# 🔥 5. PROTECTED ADMIN DASHBOARD
@app.route('/admin/dashboard')
@admin_required # Your secret access key protection
def admin_dashboard():
    # 1. Fetch Feedback (Matches your form fields)
    
    
    # 2. Fetch Users by Role
    recruiters = User.query.filter_by(role='Recruiter').all()
    students = User.query.filter_by(role='Student').all()
    
    # 3. System Statistics for Stat Cards
    stats = {
        'total_recruiters': len(recruiters),
        'total_students': len(students),
        'fraud_alerts': User.query.filter_by(role='Recruiter', is_flagged=True).count()
    }
    
    return render_template('admin_dashboard.html', 
                           recruiters=recruiters, 
                           students=students,
                           stats=stats)

# 🔥 6. LOGOUT AND KILL SESSION
@app.route('/admin/logout')
def admin_logout():
    # Remove only admin credentials from the session
    session.pop('is_admin_authenticated', None)
    # Clear entire session for maximum security
    session.clear() 
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        t = threading.Thread(target=run_scheduler)
        t.daemon = True
        t.start()
    app.run(host='0.0.0.0', port=5000, debug=True)
