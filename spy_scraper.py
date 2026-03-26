import requests
from bs4 import BeautifulSoup

URL = "https://www.sarkariresult.com/"
headers = {'User-Agent': 'Mozilla/5.0'}

response = requests.get(URL, headers=headers, verify=False)
soup = BeautifulSoup(response.text, 'html.parser')

print("\n🕵️‍♂️ LOOKING FOR SECTIONS WITH 'Top Online Form'...\n")

# Method 1: Find the text and print its parent container
target = soup.find(string="Latest Jobs")
if target:
    parent = target.find_parent('div')
    print(f"✅ Found 'Latest Jobs' inside a DIV.")
    print(f"   ID: {parent.get('id')}")
    print(f"   Class: {parent.get('class')}")
    print("-" * 30)

# Method 2: List all Divs that look like headers
print("\n🕵️‍♂️ SCANNING ALL MAJOR SECTIONS...\n")
divs = soup.find_all('div')
for div in divs:
    # We only care about divs that have an ID or Class
    if div.get('id') or div.get('class'):
        text = div.get_text(separator=' ', strip=True)[:50] # Get first 50 chars
        if "Online Form" in text:
            print(f"📦 FOUND CONTAINER:")
            print(f"   ID: {div.get('id')}")
            print(f"   Class: {div.get('class')}")
            print(f"   Starts with: '{text}...'")
            print("-" * 30)