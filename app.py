from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
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
import pypdf
from dotenv import load_dotenv

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = "careerway_secret_key"
# Use environment variable for DB path if available, else default to local sqlite
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///careerway.db')
app.config['UPLOAD_FOLDER'] = 'static/resumes'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

FEEDBACK_UPLOAD_FOLDER = 'static/uploads/feedback'
os.makedirs(FEEDBACK_UPLOAD_FOLDER, exist_ok=True)

# --- GEMINI CONFIG ---
load_dotenv()
# IMPORTANT: Model updated to current stable flash model
GEMINI_MODEL = 'gemini-1.5-flash' 
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# --- EMAIL CONFIG ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USERNAME'] = 'your_email@gmail.com' 
app.config['MAIL_PASSWORD'] = 'xxxx xxxx xxxx xxxx'  
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True

mail = Mail(app)
db = SQLAlchemy(app)

# ===========================
#         DATABASE MODELS
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
    skills = db.Column(db.String(500))
    degree = db.Column(db.String(100))
    specialization = db.Column(db.String(100))
    passing_year = db.Column(db.String(10))
    experience = db.Column(db.String(20))
    target_role = db.Column(db.String(100))
    work_mode = db.Column(db.String(20))
    portfolio = db.Column(db.String(200))
    resume_filename = db.Column(db.String(200))
    is_flagged = db.Column(db.Boolean, default=False)
    my_applications = db.relationship('Application', backref='student', lazy=True)

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
    last_date = db.Column(db.String(50)) 
    application_start_date = db.Column(db.String(50)) 
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

class StudyLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.String(20), nullable=False) 
    status = db.Column(db.String(20), default='Completed')
    topic_covered = db.Column(db.String(100))

# Create tables automatically on Render
with app.app_context():
    db.create_all()

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

def parse_date_str(date_str):
    if not date_str or date_str in ["Check Notice", "Not Specified"]: return None
    try:
        clean_date = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_str)
        return datetime.strptime(clean_date, "%d %B %Y")
    except: return None

# --- SMART MATCHING LOGIC ---
def get_recommendations(user):
    if not user.skills: return []
    user_skills = [s.strip().lower() for s in user.skills.split(',')]
    user_role = user.target_role.lower() if user.target_role else ""
    user_city = user.location.lower() if user.location else ""
    is_fresher = True if user.experience == "Fresher" else False
    all_jobs = Job.query.filter(or_(Job.status=='Active', Job.status=='Approved')).all()
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
            score += min(common * 10, 30)
            if common > 0: reasons.append(f"{common} Shared Skills")
        if user_city and user_city in job.location.lower():
            score += 15
            reasons.append("Location Match")
        if is_fresher:
            if any(x in job.title.lower() for x in ["senior", "manager", "lead"]): score -= 20
            else: score += 15
        if score > 35:
            scored_jobs.append({"job": job, "score": int(min(score, 99)), "reason": ", ".join(reasons[:2]) if reasons else "Profile Match"})
    scored_jobs.sort(key=lambda x: x['score'], reverse=True)
    return scored_jobs[:6]

# ===========================
#         AUTH ROUTES
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
        flash("Invalid Credentials", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name, email, password, role = request.form['name'], request.form['email'], request.form['password'], request.form['role']
        auto_username = generate_unique_username(name)
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(name=name, email=email, password=hashed_password, role=role, username=auto_username)
        try:
            db.session.add(new_user)
            db.session.commit()
            session.update({'user_id': new_user.id, 'user_name': new_user.name, 'user_role': new_user.role})
            flash(f"Account Created! Welcome, {name}.", "success")
            return redirect(url_for('recruiter_dashboard') if role == 'Recruiter' else url_for('dashboard'))
        except: flash("Error: Email already exists.", "danger")
    return render_template('register.html')

# ===========================
#      DASHBOARD & CORE
# ===========================

@app.route('/dashboard')
def dashboard():
    is_logged_in = 'user_id' in session
    user = User.query.get(session.get('user_id')) if is_logged_in else None
    if is_logged_in and session.get('user_role') == 'Recruiter': return redirect(url_for('recruiter_dashboard'))
    
    page = request.args.get('page', 1, type=int)
    govt_jobs_pagination = Job.query.filter_by(job_type='Govt').order_by(Job.id.desc()).paginate(page=page, per_page=20, error_out=False)
    private_jobs = Job.query.filter_by(job_type='Private', status='Active').order_by(Job.date_posted.desc()).all()
    
    user_city = user.location.lower().strip() if (user and user.location) else ""
    for job in private_jobs:
        job.distance = round(random.uniform(0.5, 4.8), 1) if user_city and user_city in job.location.lower() else round(random.uniform(10.5, 45.0), 1)

    today = datetime.now()
    for job in govt_jobs_pagination.items:
        job.is_expiring = job.is_new = False
        if job.last_date:
            ld = parse_date_str(job.last_date)
            if ld and 0 <= (ld - today).days <= 7: job.is_expiring = True
        if job.application_start_date:
            sd = parse_date_str(job.application_start_date)
            if sd and 0 <= (today - sd).days <= 5: job.is_new = True

    stats = {'total': 0, 'interviews': 0, 'score': 0, 'pending': 0, 'streak': 0, 'dates': []}
    recommendations = top_candidates = applied_ids = my_apps = []

    if is_logged_in:
        recommendations = get_recommendations(user)
        my_apps = Application.query.filter_by(student_id=user.id).all()
        applied_ids = [app.job_id for app in my_apps]
        logs = StudyLog.query.filter_by(user_id=user.id).all()
        completed_dates = list(set([log.date for log in logs]))
        stats.update({'total': len(my_apps), 'interviews': Application.query.filter_by(student_id=user.id, status='Shortlisted').count(),
                      'score': calculate_profile_score(user), 'pending': Application.query.filter_by(student_id=user.id, status='Applied').count(),
                      'streak': len(completed_dates), 'dates': completed_dates})
        
        all_students = User.query.filter_by(role='Student').all()
        leaderboard = []
        for s in all_students:
            s_score = calculate_profile_score(s)
            s_streak = len(set([l.date for l in StudyLog.query.filter_by(user_id=s.id).all()]))
            leaderboard.append({'name': "You" if s.id == user.id else s.name.split()[0], 'points': s_score + (s_streak * 10), 'streak': s_streak})
        leaderboard.sort(key=lambda x: x['points'], reverse=True)
        top_candidates = leaderboard[:5]

    return render_template('dashboard.html', is_logged_in=is_logged_in, private_jobs=private_jobs, govt_jobs=govt_jobs_pagination, 
                           recommendations=recommendations, my_apps=my_apps, applied_ids=applied_ids, stats=stats, 
                           user_name=session.get('user_name', 'Guest'), daily_byte={"word": "Ubiquitous", "meaning": "Present everywhere."}, 
                           top_candidates=top_candidates)

@app.route('/complete_profile', methods=['GET', 'POST'])
def complete_profile():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        for field in ['mobile', 'location', 'skills', 'degree', 'passing_year', 'specialization', 'experience', 'target_role', 'work_mode', 'portfolio']:
            setattr(user, field, request.form.get(field))
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
    
    # Use .get() instead of .get_or_404() temporarily to see if it's a data issue
    job = Job.query.get(job_id)
    
    if job is None:
        return "Job not found in database. Please run the scraper first!", 404
        
    user = User.query.get(session['user_id'])
    has_applied = Application.query.filter_by(job_id=job.id, student_id=user.id).first() is not None
    
    return render_template('Job_details.html', job=job, has_applied=has_applied)

@app.route('/apply_process/<int:job_id>', methods=['GET', 'POST'])
def apply_process(job_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    job, user = Job.query.get_or_404(job_id), User.query.get(session['user_id'])
    if Application.query.filter_by(job_id=job.id, student_id=user.id).first():
        flash("Already applied.", "info"); return redirect(url_for('dashboard'))
    if request.method == 'POST':
        db.session.add(Application(job_id=job.id, student_id=user.id, cover_letter=request.form.get('cover_letter'), status='Applied'))
        db.session.commit(); flash("Application Sent!", "success"); return redirect(url_for('dashboard'))
    # FIX: Corrected Template Case Sensitivity
    return render_template('Apply_Job.html', job=job, user=user)

@app.route('/interview_prep')
def interview_prep():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    streak = len(set([log.date for log in StudyLog.query.filter_by(user_id=user.id).all()]))
    # FIX: Corrected Template Case Sensitivity
    return render_template('interview_prep.html', user_name=session.get('user_name'), user=user, 
                           my_apps=Application.query.filter_by(student_id=user.id).all(), stats={'streak': streak})

@app.route('/api/interview_bot', methods=['POST'])
def interview_bot():
    try:
        data = request.get_json()
        prompt = f"Role: {data.get('role')}, Topic: {data.get('topic')}, User Answer: '{data.get('answer')}'. Evaluate and give next question in JSON {{rating, feedback, next_question}}."
        res = genai.GenerativeModel(GEMINI_MODEL).generate_content(prompt)
        match = re.search(r'\{[\s\S]*\}', res.text)
        return jsonify(json.loads(match.group(0))) if match else jsonify({"error": "Bad AI response"})
    except: return jsonify({"rating": "N/A", "feedback": "System adjusting...", "next_question": "Tell me more?"})

# --- RECRUITER & ADMIN ROUTES ---

@app.route('/recruiter_dashboard')
def recruiter_dashboard():
    if session.get('user_role') != 'Recruiter': return redirect(url_for('login'))
    my_jobs = Job.query.filter_by(recruiter_id=session['user_id']).order_by(Job.date_posted.desc()).all()
    stats = {job.id: Application.query.filter_by(job_id=job.id).count() for job in my_jobs}
    return render_template('recruiter_dashboard.html', jobs=my_jobs, stats=stats, user_name=session.get('user_name'))

ADMIN_ACCESS_TOKEN = "CARRY1234"
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_admin_authenticated'): abort(404)
        return f(*args, **kwargs)
    return decorated

@app.route('/gateway')
def admin_gateway():
    if request.args.get('token') == ADMIN_ACCESS_TOKEN: return render_template('admin_login.html')
    abort(404)

@app.route('/process_admin', methods=['POST'])
def process_admin():
    if request.form.get('admin_id') == "Saurabh_Admin" and request.form.get('admin_pwd') == "Carry1234":
        session.update({'permanent': True, 'is_admin_authenticated': True})
        return redirect(url_for('admin_dashboard'))
    return "Forbidden", 403

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    recruiters, students = User.query.filter_by(role='Recruiter').all(), User.query.filter_by(role='Student').all()
    # FIX: Corrected Template Case Sensitivity
    return render_template('admin_dashboard.html', recruiters=recruiters, students=students, 
                           stats={'total_recruiters': len(recruiters), 'total_students': len(students)})

if __name__ == '__main__':
    # Scheduler logic (runs only on main process)
    if not os.environ.get("WERKZEUG_RUN_MAIN") and os.environ.get('RENDER') is None:
        from auto_scraper import fetch_latest_jobs
        schedule.every(6).hours.do(fetch_latest_jobs)
        def run_sched():
            while True: schedule.run_pending(); time.sleep(60)
        threading.Thread(target=run_sched, daemon=True).start()
    
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
