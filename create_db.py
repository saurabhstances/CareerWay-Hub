import sqlite3

conn = sqlite3.connect('careerway.db')
cur = conn.cursor()

cur.execute("""
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    email TEXT UNIQUE,
    password TEXT,
    role TEXT
)
""")

cur.execute("""
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    location TEXT,
    skills TEXT,
    description TEXT,
    salary TEXT,
    recruiter_id INTEGER
)
""")

conn.commit()
conn.close()

print("Database created successfully")
