"""Print configuration presence, never its secret values."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from intentcart import config

print('IntentCart configuration')
print('PayPal sandbox:', 'configured' if config.CLIENT_ID and config.CLIENT_SECRET else 'NOT CONNECTED')
print('Channel3:', 'configured' if config.CHANNEL3_KEY else 'optional / not connected')
print('Database:', config.DATABASE_PATH)
print('Public origin:', config.PUBLIC_URL)
print('Cookie secure:', config.COOKIE_SECURE)
print('Sponsor request ceiling:',config.CALL_LIMIT)
if config.PUBLIC_URL.startswith('https://') and not config.COOKIE_SECURE:
    sys.exit('HTTPS deployment requires COOKIE_SECURE=true.')
if Path('.env').exists() and Path('.env').stat().st_mode & 0o077:
    print('Recommendation: restrict local .env permissions with chmod 600 .env.')
