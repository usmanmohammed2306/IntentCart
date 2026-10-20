import os
from pathlib import Path

def load_env():
    path = Path('.env')
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

load_env()
PUBLIC_URL = os.getenv('PUBLIC_URL', 'http://127.0.0.1:4000').rstrip('/')
DATABASE_PATH = os.getenv('DATABASE_PATH', 'var/intentcart.sqlite3')
CLIENT_ID = os.getenv('PAYPAL_CLIENT_ID', '')
CLIENT_SECRET = os.getenv('PAYPAL_CLIENT_SECRET', '')
COOKIE_SECURE = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
CHANNEL3_KEY = os.getenv('CHANNEL3_API_KEY', '')
CALL_LIMIT = int(os.getenv('EXTERNAL_CALL_LIMIT', '0'))
MAX_QUESTIONS = 4
ASTRO_URL = os.getenv('ASTRO_GATEWAY_URL','')
ASTRO_KEY = os.getenv('ASTRO_GATEWAY_API_KEY','')
ASTRO_MODEL = os.getenv('MODEL_DEFAULT','claude-haiku-4-5')
ASTRO_CREDIT_ONLY = os.getenv('ASTRO_CREDIT_ONLY_CONFIRMED','false')=='true'
ASTRO_BUDGET = int(os.getenv('ASTRO_BUDGET_MICROUSD','0'))
ASTRO_INPUT_RATE = int(os.getenv('ASTRO_INPUT_MICROUSD_PER_MILLION','0'))
ASTRO_OUTPUT_RATE = int(os.getenv('ASTRO_OUTPUT_MICROUSD_PER_MILLION','0'))
