import sys
import os

# Add the current directory to sys.path so we can import app modules
sys.path.insert(0, os.path.abspath("."))

from app.database import fetch_rows

sql = "SELECT * FROM attendances LIMIT 5"
rows = fetch_rows(sql, {})

print("ROWS FOUND:", len(rows))
for r in rows:
    print(r)
