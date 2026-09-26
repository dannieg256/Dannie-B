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
        self.env = (env or "demo").lower()

        if self.env == "production":
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

            path = Path(self.private_key_path)

            if not path.exists():
                raise RuntimeError(
                    f"Private key file not found: {path}"
                )

            with path.open("rb") as f:
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
            raise RuntimeError(
                "KALSHI_API_KEY_ID is not configured."
            )

        timestamp = str(
            int(
                datetime.datetime.now(
                    datetime.timezone.utc
                ).timestamp()
                * 1000
            )
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
            "Accept": "application/json",
        }

    def public_get(self, endpoint, params=None):
        response = requests.get(
            self.base_url + endpoint,
            params=params,
            timeout=20,
        )

        if not response.ok:
            raise RuntimeError(
                f"Kalshi public API error "
                f"{response.status_code}: {response.text}"
            )

        return response.json()

    def auth_get(self, endpoint, params=None):
        response = requests.get(
            self.base_url + endpoint,
            headers=self._headers("GET", endpoint),
            params=params,
            timeout=20,
        )

        if not response.ok:
            raise RuntimeError(
                f"Kalshi authenticated API error "
                f"{response.status_code}: {response.text}"
            )

        return response.json()

    def auth_post(self, endpoint, payload):
        response = requests.post(
            self.base_url + endpoint,
            headers=self._headers("POST", endpoint),
            json=payload,
            timeout=20,
        )

        if not response.ok:
            raise RuntimeError(
                f"Kalshi error "
                f"{response.status_code}: {response.text}"
            )

        return response.json()

    @staticmethod
    def _to_float(value):
        if value is None or value == "":
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _legacy_cents_to_dollars(value):
        if value is None or value == "":
            return None

        try:
            return float(value) / 100.0
        except (TypeError, ValueError):
            return None

    def _read_market_price(
        self,
        market,
        dollar_field,
        legacy_field,
    ):
        value = self._to_float(
            market.get(dollar_field)
        )

        if value is not None:
            return value

        legacy = market.get(
            legacy_field
        )

        if legacy is not None:
            return self._legacy_cents_to_dollars(
                legacy
            )

        return None

    def _parse_orderbook(self, response):
        yes_bid = None
        yes_ask = None
        no_bid = None
        no_ask = None

        fp = response.get(
            "orderbook_fp"
        ) or {}

        yes_levels = (
            fp.get("yes_dollars")
            or []
        )

        no_levels = (
            fp.get("no_dollars")
            or []
        )

        if yes_levels:
            prices = []

            for level in yes_levels:
                if (
                    isinstance(level, (list, tuple))
                    and len(level) >= 1
                ):
                    price = self._to_float(level[0])

                    if price is not None:
                        prices.append(price)

            if prices:
                yes_bid = max(prices)

        if no_levels:
            prices = []

            for level in no_levels:
                if (
                    isinstance(level, (list, tuple))
                    and len(level) >= 1
                ):
                    price = self._to_float(level[0])

                    if price is not None:
                        prices.append(price)

            if prices:
                no_bid = max(prices)

        if no_bid is not None:
            yes_ask = 1.0 - no_bid

        if yes_bid is not None:
            no_ask = 1.0 - yes_bid

        old = response.get(
            "orderbook"
        ) or {}

        if yes_bid is None:
            old_yes = old.get("yes") or []

            if isinstance(old_yes, list):
                prices = []

                for level in old_yes:
                    if (
                        isinstance(level, (list, tuple))
                        and len(level) >= 1
                    ):
                        price = self._legacy_cents_to_dollars(
                            level[0]
                        )

                        if price is not None:
                            prices.append(price)

                if prices:
                    yes_bid = max(prices)

        if no_bid is None:
            old_no = old.get("no") or []

            if isinstance(old_no, list):
                prices = []

                for level in old_no:
                    if (
                        isinstance(level, (list, tuple))
                        and len(level) >= 1
                    ):
                        price = self._legacy_cents_to_dollars(
                            level[0]
                        )

                        if price is not None:
                            prices.append(price)

                if prices:
                    no_bid = max(prices)

        if yes_ask is None and no_bid is not None:
            yes_ask = 1.0 - no_bid

        if no_ask is None and yes_bid is not None:
            no_ask = 1.0 - yes_bid

        return {
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "no_bid": no_bid,
            "no_ask": no_ask,
        }

    def get_markets(
        self,
        limit=100,
        status="open",
    ):
        all_markets = []
        cursor = None

        for _ in range(5):

            params = {
                "limit": 100,
                "status": status,
                "mve_filter": "exclude",
            }

            if cursor:
                params["cursor"] = cursor

            result = self.public_get(
                "/markets",
                params=params,
            )

            markets = result.get(
                "markets",
                [],
            )

            for market in markets:

                if not isinstance(market, dict):
                    continue

                ticker = market.get("ticker")

                if not ticker:
                    continue

                yes_bid = self._read_market_price(
                    market,
                    "yes_bid_dollars",
                    "yes_bid",
                )

                yes_ask = self._read_market_price(
                    market,
                    "yes_ask_dollars",
                    "yes_ask",
                )

                if yes_bid is None or yes_bid <= 0:
                    continue

                if yes_ask is None or yes_ask <= 0:
                    continue

                if yes_bid >= 1 or yes_ask >= 1:
                    continue

                if yes_bid > yes_ask:
                    continue

                volume = self._to_float(
                    market.get("volume_fp")
                )

                if volume is None:
                    volume = self._to_float(
                        market.get("volume")
                    )

                if volume is None:
                    volume = 0.0

                market["yes_bid_dollars"] = (
                    f"{yes_bid:.4f}"
                )

                market["yes_ask_dollars"] = (
                    f"{yes_ask:.4f}"
                )

                market["volume_fp"] = str(
                    volume
                )

                all_markets.append(
                    market
                )

                if len(all_markets) >= limit:
                    return {
                        "markets": all_markets,
                        "cursor": cursor,
                    }

            cursor = result.get(
                "cursor"
            )

            if not cursor:
                break

        return {
            "markets": all_markets,
            "cursor": cursor,
        }

    def get_market(self, ticker):
        result = self.public_get(
            f"/markets/{ticker}"
        )

        market = result.get(
            "market",
            {},
        )

        if not market:
            return result

        yes_bid = self._read_market_price(
            market,
            "yes_bid_dollars",
            "yes_bid",
        )

        yes_ask = self._read_market_price(
            market,
            "yes_ask_dollars",
            "yes_ask",
        )

        try:
            orderbook = self.get_orderbook(
                ticker,
                depth=20,
            )

            parsed = self._parse_orderbook(
                orderbook
            )

            if parsed["yes_bid"] is not None:
                yes_bid = parsed["yes_bid"]

            if parsed["yes_ask"] is not None:
                yes_ask = parsed["yes_ask"]

            if parsed["no_bid"] is not None:
                market["no_bid_dollars"] = (
                    f"{parsed['no_bid']:.4f}"
                )

            if parsed["no_ask"] is not None:
                market["no_ask_dollars"] = (
                    f"{parsed['no_ask']:.4f}"
                )

        except Exception:
            pass

        if yes_bid is not None:
            market["yes_bid_dollars"] = (
                f"{float(yes_bid):.4f}"
            )

        if yes_ask is not None:
            market["yes_ask_dollars"] = (
                f"{float(yes_ask):.4f}"
            )

        result["market"] = market

        return result

    def get_orderbook(
        self,
        ticker,
        depth=20,
    ):
        return self.public_get(
            f"/markets/{ticker}/orderbook",
            params={
                "depth": depth,
            },
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
        price = float(price)
        count = int(count)

        if not 0.01 <= price <= 0.99:
            raise ValueError(
                "Order price must be between $0.01 and $0.99."
            )

        if count < 1:
            raise ValueError(
                "Order count must be at least 1."
            )

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
