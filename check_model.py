import google.generativeai as genai

# PASTE YOUR KEY HERE
GEMINI_API_KEY = "AIzaSyDE0fIQBbanplAwfvoeaDjp2LKGiOYe_tk"
genai.configure(api_key=GEMINI_API_KEY)

print("🔍 Checking available models...")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"✅ Found: {m.name}")
except Exception as e:
    print(f"❌ Error: {e}")