"""Explicit local, stateless public-preview and gated production profiles.

A readiness result checks declared configuration and current storage, not the
host's billing, failover, security certification or future persistence.
"""
import base64
import hashlib
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit
from fastapi.responses import JSONResponse

MODES = {'local','public-preview','production'}


def mode():
    return os.getenv('INTENTCART_MODE','local')


def configuration(config):
    profile = mode()
    issues = []
    url = urlsplit(config.PUBLIC_URL)
    if profile not in MODES:
        issues.append('Unknown release profile.')
    if profile in ('public-preview','production'):
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):
            issues.append('Public profiles require one exact HTTPS origin.')
        if not config.COOKIE_SECURE:
            issues.append('Public profiles require secure session cookies.')
    if profile == 'public-preview':
        if config.CALL_LIMIT != 0 or config.ASTRO_BUDGET != 0 or any((config.CLIENT_ID,config.CLIENT_SECRET,config.ASTRO_KEY,config.CHANNEL3_KEY)):
            issues.append('Stateless public previews cannot hold provider credentials or positive spending caps.')
    if profile == 'production':
        authentication=os.getenv('INTENTCART_AUTH','basic')
        termination=os.getenv('INTENTCART_TLS_TERMINATION','')
        if termination not in ('','astropods') or (termination=='astropods' and (authentication!='astropods' or not (url.hostname or '').endswith('.agents.astropods.ai'))):issues.append('Managed TLS termination requires verified Astropods identity and its assigned HTTPS hostname.')
        if authentication=='astropods':
            try:
                from .astro_auth import authorizer
                authorizer()
            except Exception:issues.append('Astropods production requires a valid deployed authorization identity.')
        elif authentication=='basic':
            if len(os.getenv('INTENTCART_ACCESS_PASSWORD','').encode())<32:issues.append('Production requires a private access password of at least32 bytes.')
        else:issues.append('Unknown production authentication policy.')
        root = Path(config.DATABASE_PATH).resolve().parent
        if os.getenv('INTENTCART_STORAGE_ACK') != 'durable' or not (root/'.intentcart-volume').is_file():
            issues.append('Production requires an operator-confirmed durable volume and installation marker.')
        if config.CALL_LIMIT > 0 and os.getenv('INTENTCART_PUBLIC_INFERENCE_APPROVED') != 'true':
            issues.append('A separate public inference allocation must be explicitly approved.')
        if not config.ASTRO_KEY or not config.ASTRO_URL or config.CALL_LIMIT <= 0 or config.ASTRO_BUDGET <= 0:
            issues.append('An AI production profile requires its own configured positive model allocation.')
        if not config.ASTRO_CREDIT_ONLY or min(config.ASTRO_INPUT_RATE,config.ASTRO_OUTPUT_RATE) <= 0:
            issues.append('Production inference requires confirmed credit-only access and reviewed rates.')
    return {'profile':profile,'configuration_ready':not issues,'issues':issues}


def validate(config):
    result = configuration(config)
    if not result['configuration_ready']:
        raise RuntimeError('Release configuration rejected: '+' '.join(result['issues']))


def access(request, config):
    if mode() == 'local':
        return None
    if request.url.path in ('/healthz','/readyz') and request.client and request.client.host in ('127.0.0.1','::1'):return None
    origin = urlsplit(config.PUBLIC_URL)
    if request.url.hostname != origin.hostname:
        return JSONResponse({'detail':'Host is not allowed.'},status_code=400)
    if mode() == 'public-preview':
        # Read-only preview cannot create owned tasks, quotes, imports or usage.
        if request.method not in ('GET','HEAD','OPTIONS'):
            return JSONResponse({'detail':'This is a read-only public preview.'},status_code=403)
        return None
    if request.url.path in ('/healthz','/readyz'):
        return None
    # The managed frontend terminates TLS before its private HTTP upstream.
    # This explicit profile still requires exact Host and signed platform identity.
    managed_tls=(os.getenv('INTENTCART_AUTH','basic')=='astropods' and os.getenv('INTENTCART_TLS_TERMINATION')=='astropods' and (origin.hostname or '').endswith('.agents.astropods.ai'))
    if request.url.scheme != 'https' and not managed_tls:
        return JSONResponse({'detail':'HTTPS is required.'},status_code=400)
    if os.getenv('INTENTCART_AUTH','basic')=='astropods':
        return JSONResponse({'detail':'Sign in through Astropods.'},status_code=401)
    header = request.headers.get('authorization','')
    valid = False
    try:
        kind, value = header.split(' ',1)
        decoded = base64.b64decode(value,validate=True).decode('utf-8') if kind.lower() == 'basic' else ''
        user, password = decoded.split(':',1)
        expected = os.getenv('INTENTCART_ACCESS_PASSWORD','')
        valid = len(expected.encode()) >= 32 and secrets.compare_digest(user.encode(),b'intentcart') and secrets.compare_digest(password.encode(),expected.encode())
    except (ValueError,UnicodeError):
        pass
    if not valid:
        return JSONResponse({'detail':'Sign in to this private launch.'},status_code=401,headers={'WWW-Authenticate':'Basic realm="IntentCart", charset="UTF-8"','Cache-Control':'no-store'})
    return None


def cache_policy(request, response, web_root):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Vary'] = 'Cookie, Authorization'
    if mode()=='production' and (request.url.scheme=='https' or (os.getenv('INTENTCART_TLS_TERMINATION')=='astropods' and request.scope.get('intentcart_auth_subject'))):response.headers['Strict-Transport-Security']='max-age=31536000'
    name = request.url.path.removeprefix('/static/')
    if request.url.path.startswith('/static/'):
        path = (web_root/name).resolve()
        if path.is_relative_to(web_root.resolve()) and path.is_file():
            expected = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            if request.query_params.get('v') == expected:
                response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
                if 'Vary' in response.headers:del response.headers['Vary']
            else:
                response.headers['Cache-Control'] = 'public, max-age=0, must-revalidate'
    return response


async def access_async(request,config):
    denied=access(request,config)
    if denied is not None and denied.status_code==401 and mode()=='production' and os.getenv('INTENTCART_AUTH','basic')=='astropods':
        from .astro_auth import access as authorize
        return await authorize(request)
    return denied
