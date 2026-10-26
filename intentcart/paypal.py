"""Sandbox-only Orders v2 adapter. Secrets never leave the server."""
import time
import threading
import httpx
from decimal import Decimal
from . import config
from . import paypal_limits

BASE = 'https://api-m.sandbox.paypal.com'

class ProviderError(Exception):
    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain

class PayPal:
    def __init__(self):
        self.token = None
        self.until = 0
        self.lock = threading.Lock()

    def access_token(self):
        if not (config.CLIENT_ID and config.CLIENT_SECRET):
            raise ProviderError('Connect PayPal sandbox credentials to enable checkout.')
        with self.lock:
            if self.token and self.until > time.time():
                return self.token
            try:
                paypal_limits.reserve('POST','/v1/oauth2/token')
                response = httpx.post(BASE + '/v1/oauth2/token', auth=(config.CLIENT_ID, config.CLIENT_SECRET),
                                      data={'grant_type': 'client_credentials'}, timeout=15)
                response.raise_for_status()
                payload = response.json()
                token = payload['access_token']
                expires = int(payload.get('expires_in', 60))
                if not isinstance(token, str) or not token:
                    raise ValueError('Missing token')
            except paypal_limits.LimitError as exc:
                raise ProviderError(str(exc)) from exc
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
                raise ProviderError('PayPal sandbox authentication is unavailable.') from exc
            self.token = token
            self.until = time.time() + max(0, expires - 60)
            return self.token

    def request(self, method, path, body=None, request_id=None):
        headers = {'Authorization': 'Bearer ' + self.access_token(), 'Content-Type': 'application/json',
                   'Prefer': 'return=representation'}
        if request_id:
            headers['PayPal-Request-Id'] = request_id
        try:
            paypal_limits.reserve(method,path,body,request_id)
            response = httpx.request(method, BASE + path, headers=headers, json=body, timeout=20)
            if response.status_code >= 400:
                raise ProviderError('PayPal could not complete this sandbox request. Reconcile its status before retrying.',
                                    uncertain=response.status_code >= 500)
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError('Invalid response object')
            paypal_limits.observe(method,path,payload)
            return payload
        except paypal_limits.LimitError as exc:
            raise ProviderError(str(exc)) from exc
        except (httpx.HTTPError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
            raise ProviderError('PayPal response was interrupted. Your request is saved; check its status before retrying.', uncertain=True) from exc

    def create(self, quote, request_id):
        amount = f"{quote['total_cents'] / 100:.2f}"
        return self.request('POST', '/v2/checkout/orders', {
            'intent': 'CAPTURE', 'purchase_units': [{'reference_id': quote['id'],
            'custom_id': quote['id'], 'description': 'IntentCart fictional workstation bundle — sandbox only' if quote.get('kind')=='mission' else 'IntentCart fictional backpack — sandbox only',
            'amount': {'currency_code': 'USD', 'value': amount}}],
            'payment_source': {'paypal': {'experience_context': {'shipping_preference': 'NO_SHIPPING',
            'user_action': 'PAY_NOW', 'brand_name': 'IntentCart Sandbox'}}}}, request_id)

    def get(self, order_id):
        return self.request('GET', '/v2/checkout/orders/' + order_id)

    def capture(self, order_id, request_id):
        return self.request('POST', '/v2/checkout/orders/' + order_id + '/capture', {}, request_id)

    def refund(self, capture_id, request_id):
        return self.request('POST', '/v2/payments/captures/' + capture_id + '/refund', {}, request_id)

def verify_capture(payload, quote, order_id):
    if not isinstance(payload, dict) or payload.get('id') != order_id:
        raise ProviderError('Payment order identity did not match the approved quote.')
    units = payload.get('purchase_units', [])
    if not isinstance(units, list) or len(units) != 1 or not isinstance(units[0], dict) or units[0].get('reference_id') != quote['id']:
        raise ProviderError('Payment reference did not match the approved quote.')
    payments = units[0].get('payments', {})
    captures = payments.get('captures', []) if isinstance(payments, dict) else None
    if not isinstance(captures, list) or len(captures) > 1 or (captures and (not isinstance(captures[0], dict) or not isinstance(captures[0].get('status'), str))):
        raise ProviderError('PayPal returned an unsupported capture response. Operator review is required.')
    if not captures:
        if payload.get('status') == 'COMPLETED':
            raise ProviderError('Completed order has no verifiable capture. Operator review is required.')
        return None
    if captures[0].get('status') not in ('COMPLETED', 'REFUNDED'):
        return None
    if payload.get('status') != 'COMPLETED':
        raise ProviderError('Captured payment has a contradictory order status. Operator review is required.')
    capture = captures[0]
    amount = capture.get('amount', {})
    try:
        valid = amount.get('currency_code') == 'USD' and Decimal(amount.get('value', '0')) * 100 == quote['total_cents']
    except Exception:
        valid = False
    if not valid or not capture.get('id'):
        raise ProviderError('Captured amount did not match the approved quote. Operator review is required.')
    return capture

provider = PayPal()
