import hashlib
import hmac
import time
from urllib.parse import urlencode

import requests


class BinanceError(Exception):
    def __init__(self, status, body):
        super().__init__(f"{status}: {body}")
        self.status, self.body = status, body

class Binance:
    def __init__(self, base, key="", secret=""):
        self.base, self.key, self.secret = base, key, secret
        self.s = requests.Session()
        self.offset = 0
        if key:
            self.s.headers["X-MBX-APIKEY"] = key

    def sync_time(self):
        t = requests.get(self.base + "/fapi/v1/time", timeout=10).json()["serverTime"]
        self.offset = t - int(time.time() * 1000)

    def get(self, path, **params):
        return self._do("GET", path, params, False)

    def signed(self, method, path, **params):
        return self._do(method, path, params, True)

    def _do(self, method, path, params, signed):
        params = {k: v for k, v in params.items() if v is not None}
        if signed:
            params["timestamp"] = int(time.time() * 1000) + self.offset
            params["recvWindow"] = 5000
            q = urlencode(params)
            sig = hmac.new(self.secret.encode(), q.encode(), hashlib.sha256).hexdigest()
            r = self.s.request(method, f"{self.base}{path}?{q}&signature={sig}", timeout=10)
        else:
            r = self.s.request(method, self.base + path, params=params, timeout=10)
        if r.status_code >= 400:
            raise BinanceError(r.status_code, r.text)
        return r.json()