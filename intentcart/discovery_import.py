"""No-network Channel3 export review. Offers never supply compatibility facts."""
import re
from urllib.parse import urlsplit

def review(payload,catalog):
    if type(payload) is not dict or set(payload)!={'source','items'} or payload['source']!='channel3':raise ValueError('Supply a Channel3 discovery export.')
    if type(payload['items']) is not list or not 1<=len(payload['items'])<=40:raise ValueError('Supply one to forty reviewed discovery items.')
    products={p['id']:p for p in catalog['products']};seen=set();rows=[]
    for item in payload['items']:
        keys={'offer_id','merchant','url','name','product_id','variant','price_cents','observed_on'}
        if type(item) is not dict or set(item)!=keys:raise ValueError('Discovery item fields are incomplete or unsupported.')
        for key in ('offer_id','merchant','name','product_id','variant'):
            if type(item[key]) is not str or not 0<len(item[key])<=200:raise ValueError('Invalid discovery identity.')
        url=urlsplit(item['url'])
        if url.scheme!='https' or not url.hostname or url.username or url.password:raise ValueError('Review an HTTPS merchant URL without embedded credentials.')
        if type(item['price_cents']) is not int or not 0<=item['price_cents']<=300000:raise ValueError('Invalid discovery price.')
        from .workbench import freshness
        if freshness(item,3650)['status']!='current':raise ValueError('Discovery needs a valid non-future observation date.')
        product=products.get(item['product_id'])
        if not product or product.get('variant',product['id'])!=item['variant']:raise ValueError('Explicit source-to-product and exact-variant matching is required.')
        identity=(item['merchant'].casefold(),item['offer_id'])
        if identity in seen:raise ValueError('Duplicate merchant offer identity.')
        seen.add(identity);rows.append({**item,'review_required':True,'compatibility_facts_imported':False,'checkout_supported':False})
    return {'schema':'intentcart-discovery-review/1','items':rows,'provider_calls':0,'notice':'Offline normalization of an existing export. No URL fetched, API call made, inventory verified, compatibility fact imported or offer applied.'}
