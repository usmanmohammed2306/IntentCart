"""Enforce the gateway response-byte limit before SDK error/body buffering."""
import httpx2

MAX_RESPONSE_BYTES = 65536


class CappedStream(httpx2.SyncByteStream):
    def __init__(self, response):
        self.response = response

    def __iter__(self):
        size = 0
        for chunk in self.response.iter_bytes(chunk_size=8192):
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise httpx2.ReadError('Gateway response exceeded the configured byte limit.')
            yield chunk

    def close(self):
        self.response.close()


class CappedTransport(httpx2.BaseTransport):
    def __init__(self, transport=None):
        self.transport = transport or httpx2.HTTPTransport(retries=0, trust_env=False)

    def handle_request(self, request):
        response = self.transport.handle_request(request)
        headers = {k:v for k,v in response.headers.items() if k.lower() not in ('content-encoding','content-length')}
        return httpx2.Response(response.status_code, headers=headers,
                              stream=CappedStream(response),
                              extensions=response.extensions, request=request)

    def close(self):
        self.transport.close()
