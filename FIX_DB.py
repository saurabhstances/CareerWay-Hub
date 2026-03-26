import os
from app import app, db

# 1. Force Delete the Database File
db_path = os.path.join(os.getcwd(), 'careerway.db')
if os.path.exists(db_path):
    try:
        os.remove(db_path)
        print("✅ Old Database DELETED successfully.")
    except Exception as e:
        print(f"❌ Could not delete DB. Close VS Code and try again. Error: {e}")
else:
    print("ℹ️ No old database found (Clean slate).")

# 2. Create New Tables
try:
    with app.app_context():
        db.create_all()
        print("✅ New Database & Tables CREATED successfully.")
        print("🚀 You can now run 'python app.py' and Register.")
except Exception as e:
    print(f"❌ Error creating tables: {e}")