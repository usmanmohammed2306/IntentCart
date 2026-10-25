"""Strict signed-identity guard around Astropods' official authorization SDK."""
from functools import lru_cache
import math,os,re,time
from urllib.parse import urlsplit
import httpx
import jwt
from fastapi.responses import JSONResponse


def transport(url,**kwargs):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname!='astropods.com' or parsed.path!='/api/v1/deployments/authorize' or parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.port not in (None,443):raise ValueError('Untrusted authorization endpoint')
    return httpx.get(url,**kwargs,follow_redirects=False,trust_env=False)


@lru_cache(maxsize=1)
def authorizer():
    from astropods_adapter_core.auth import Authorizer,decode_deploy_token
    token=os.environ.get('ASTRO_AUTHZ_TOKEN','')
    if not token or os.environ.get('ASTRO_AUTH_DEV_USER_ID'):raise ValueError('A deployed identity is required; development identities are forbidden')
    try:claims=decode_deploy_token(token)
    except Exception:raise ValueError('Invalid deployed authorization identity') from None
    issuer=urlsplit(claims.issuer)
    if issuer.scheme!='https' or issuer.hostname!='astropods.com' or issuer.path not in ('','/') or issuer.username or issuer.password or issuer.query or issuer.fragment or issuer.port not in (None,443):raise ValueError('Untrusted authorization issuer')
    if 'custom' in claims.anyone_adapters:raise ValueError('This invited launch cannot use an anonymous or outage-fallback grant')
    result=Authorizer(identity_token=token,adapter='custom',cache_ttl_seconds=30,timeout_seconds=5,verify_identity=True,http_get=transport)
    if result.dev_mode:raise ValueError('Development authorization is forbidden')
    return result


async def access(request):
    # The SDK can fall back to a bare identity header. This application instead
    # requires signed, expiring ALB claims before its authorization step.
    token=request.headers.get('x-amzn-oidc-data','')
    if not token or len(token)>16384:return JSONResponse({'detail':'Sign in through Astropods.'},status_code=401)
    try:
        header=jwt.get_unverified_header(token);exp=header.get('exp');kid=header.get('kid');signer=header.get('signer')
        if isinstance(exp,str) and re.fullmatch(r'[0-9]{1,15}',exp):exp=int(exp)
        if header.get('alg')!='ES256' or type(exp) not in (int,float) or not math.isfinite(exp) or exp<=time.time():raise ValueError('Missing or expired signed claims')
        if not isinstance(kid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',kid):raise ValueError('Invalid key identifier')
        if not isinstance(signer,str) or not re.fullmatch(r'arn:aws:elasticloadbalancing:[a-z0-9-]+:[0-9]{12}:loadbalancer/app/[A-Za-z0-9-]+/[A-Za-z0-9]+',signer):raise ValueError('Invalid platform signer')
        from astropods_adapter_core.auth import guard_async
        outcome=await guard_async(authorizer(),request.headers)
    except (ValueError,TypeError,KeyError,jwt.InvalidTokenError):return JSONResponse({'detail':'Sign-in could not be verified.'},status_code=401)
    except Exception:return JSONResponse({'detail':'Sign-in verification is temporarily unavailable.'},status_code=503)
    if outcome.status!=200:return JSONResponse({'detail':'Sign-in is unavailable.' if outcome.status==503 else 'This account cannot open this private launch.'},status_code=outcome.status)
    principal=outcome.principal
    if not principal or principal.source!='alb' or not isinstance(principal.user_id,str) or not 0<len(principal.user_id)<=200 or principal.claims.get('sub')!=principal.user_id:return JSONResponse({'detail':'Verified sign-in is required.'},status_code=401)
    request.scope['intentcart_auth_subject']=principal.user_id
    return None
