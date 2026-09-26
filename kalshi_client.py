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

   def
