import os
import base64
import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class KalshiClient:
    def __init__(self, api_key_id="", private_key_path="", env="demo"):
        self.api_key_id = api_key_id or ""
        self.private_key_path = private_key_path or ""
        self.env = env

        if env == "production":
            self.base_url = "https://external-api.kalshi.com/trade-api/v2"
        else:
            self.base_url = "https://external-api.demo.kalshi.co/trade-api/v2"

        self._private_key = None

    def _load_private_key(self):
        if self._private_key is not None:
            return self._private_key

        private_key_text = os.getenv("KALSHI_PRIVATE_KEY", "")

        if private_key_text:
            key_bytes = private_key_text.replace("\\n", "\n").encode("utf-8")
        else:
            if not self.private_key_path:
                raise RuntimeError("No Kalshi private key configured.")

            p = Path(self.private_key_path)

            if not p.exists():
                raise RuntimeError(f"Private key file not found: {p}")

            with p.open("rb") as f:
                key_bytes = f.read()

        self._private_key = serialization.load_pem_private_key(
            key_bytes,
            password=None,
            backend=default_backend(),
        )

        return self._private_key

    def _signature(self, timestamp, method, path):
        private_key = self._load_private_key()
        path_without_query = path.split("?")[0]

        message = (
            f"{timestamp}{method.upper()}{path_without_query}"
        ).encode("utf-8")

        if isinstance(private_key, Ed25519PrivateKey):
            signature = private_key.sign(message)
        else:
            signature = private_key.sign(
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH,
                ),
                hashes.SHA256(),
            )

        return base64.b64encode(signature).decode("utf-8")

    def _headers(self, method, endpoint):
        if not self.api_key_id:
            raise RuntimeError("KALSHI_API_KEY_ID is not configured.")

        timestamp = str(
            int(datetime.datetime.now().timestamp() * 1000)
        )

        sign_path = urlparse(
            self.base_url + endpoint
        ).path

        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": self._signature(
                timestamp,
                method,
                sign_path,
            ),
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }

    def public_get(self, endpoint, params=None):
        response = requests.get(
            self.base_url + endpoint,
            params=params,
            timeout=15,
        )

        response.raise_for_status()
        return response.json()

    def auth_get(self, endpoint, params=None):
        response = requests.get(
            self.base_url + endpoint,
            headers=self._headers("GET", endpoint),
            params=params,
            timeout=15,
        )

        response.raise_for_status()
        return response.json()

    def auth_post(self, endpoint, payload):
        response = requests.post(
            self.base_url + endpoint,
            headers=self._headers("POST", endpoint),
            json=payload,
            timeout=15,
        )

        if not response.ok:
            raise RuntimeError(
                f"Kalshi error {response.status_code}: "
                f"{response.text}"
            )

        return response.json()

    def get_markets(self, limit=100, status="open"):
        return self.public_get(
            "/markets",
            params={
                "limit": limit,
                "status": status,
            },
        )

    def get_market(self, ticker):
        return self.public_get(
            f"/markets/{ticker}"
        )

    def get_orderbook(self, ticker, depth=20):
        return self.public_get(
            f"/markets/{ticker}/orderbook",
            params={"depth": depth},
        )

    def get_balance(self):
        return self.auth_get(
            "/portfolio/balance"
        )

    def get_positions(self):
        return self.auth_get(
            "/portfolio/positions"
        )

    def create_order(
        self,
        ticker,
        price,
        count,
        client_order_id,
    ):
        payload = {
            "ticker": ticker,
            "client_order_id": client_order_id,
            "side": "bid",
            "count": str(count),
            "price": f"{price:.4f}",
            "time_in_force": "good_till_canceled",
            "self_trade_prevention_type": "taker_at_cross",
            "post_only": False,
            "cancel_order_on_pause": True,
            "reduce_only": False,
            "subaccount": 0,
            "exchange_index": 0,
        }

        return self.auth_post(
            "/portfolio/events/orders",
            payload,
        )
