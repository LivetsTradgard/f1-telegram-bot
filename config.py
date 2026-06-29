import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')

if not TOKEN:
    exit(1)

API_URL = "https://api.jolpi.ca/ergast/f1"
DB_PATH = "f1_users.db"