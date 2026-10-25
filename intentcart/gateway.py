"""Optional Astropods goal interpretation; never a fact or payment authority.

Protocol checked against docs.astropods.com/ai-gateway/chat on October 11.
Live connectivity is a separate gate. No request occurs with a zero call cap,
missing reviewed pricing, missing credit-only confirmation or missing keys.
"""
import json
import math
from urllib.parse import urlsplit
import httpx
from .missions import Goal

class GatewayError(Exception):
    pass

def action_json(raw):
    """Accept one complete JSON value or one whole JSON fence, never extract prose.

    Some compatible gateways wrap JSON despite the output instruction. Removing
    that single transport wrapper grants no tool authority; strict schema and
    state-dependent validation still run afterward. Mixed text stays invalid.
    """
    if not isinstance(raw, str) or len(raw) > 12000:
        raise ValueError('Invalid action size.')
    text = raw.strip()
    if text.startswith('```json\n') and text.endswith('\n```'):
        text = text[len('```json\n'):-len('\n```')]
    elif text.startswith('```\n') and text.endswith('\n```'):
        text = text[len('```\n'):-len('\n```')]
    # Reject arrays/scalars and multiple values before handing off to Pydantic.
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError('Model action must be a single JSON object.')
    return text

def request_body(text, model):
    return {'model':model,'max_tokens':512,'temperature':0,
            'messages':[{'role':'system','content':
                'Return only a JSON object matching this goal schema. Use defaults for unspecified fields. '
                'Do not invent laptop capabilities. Laptop names are fictional profiles. '
                'Never grant driver permission: allow_driver must be false. '
                'No extra keys, facts, products, tools, code or payment actions. Schema: '+json.dumps(Goal.model_json_schema())},
                {'role':'user','content':text}]}

def reservation(body, input_rate, output_rate):
    """Conservative local budget reservation using operator-reviewed price caps.

    Rates are USD micro-units per million tokens. UTF-8 bytes plus 1024 envelope
    tokens bound the small text prompt conservatively; hidden provider charges
    are not established. Enable only under a confirmed credit-only account cap.
    """
    if type(input_rate) is not int or type(output_rate) is not int or min(input_rate,output_rate)<=0:
        raise GatewayError('Reviewed positive token-price ceilings are required.')
    return math.ceil(((len(json.dumps(body,ensure_ascii=False).encode())+1024)*input_rate+512*output_rate)/1_000_000)

def parse(payload):
    try:
        raw=payload['choices'][0]['message']['content']
        if not isinstance(raw,str) or len(raw)>12000: raise ValueError('Unexpected model output')
        goal=Goal.model_validate_json(raw)
        goal=goal.model_copy(update={'allow_driver':False})
        usage=payload.get('usage',{})
        if not isinstance(usage,dict): usage={}
        usage={k:v for k,v in usage.items() if k in ('prompt_tokens','completion_tokens','total_tokens') and type(v) is int and v>=0}
    except (KeyError,IndexError,TypeError,ValueError) as exc:
        raise GatewayError('Model returned an invalid goal. Review the local form instead; no plan changed.') from exc
    return {'suggestions':goal.model_dump(),'mode':'Astropods structured model proposal',
            'review_required':True,'usage':usage,
            'notice':'Review all fields. Model output supplies no product facts or payment consent; driver permission is reset to false.'}

def raw_call(base_url,key,body):
    """OpenAI SDK transport for Astropods, with zero retries and bounded reads."""
    from openai import OpenAI, DefaultHttpxClient, APIError, omit
    import httpx2
    from .sdk_transport import CappedTransport
    url=urlsplit(base_url)
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise GatewayError('The server-configured gateway must be an HTTPS host without credentials or query parameters.')
    try:
        transport=DefaultHttpxClient(timeout=20, follow_redirects=False, trust_env=False, transport=CappedTransport())
        with OpenAI(api_key=key, base_url=base_url.rstrip('/')+'/v1', max_retries=0,
                    organization='', project='', default_headers={'OpenAI-Organization':omit,'OpenAI-Project':omit},
                    timeout=20, http_client=transport) as client:
            with client.chat.completions.with_streaming_response.create(**body) as response:
                content=bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content)>65536:
                        raise GatewayError('Gateway output exceeded the response limit.')
        payload=json.loads(content)
        if not isinstance(payload,dict):
            raise GatewayError('Gateway returned an invalid response envelope.')
        return payload
    except (APIError, httpx2.HTTPError, ValueError) as exc:
        raise GatewayError('Astropods interpretation is unavailable. No retry was sent; your reviewed task remains unchanged.') from exc

def call(base_url,key,body):
    return parse(raw_call(base_url,key,body))
