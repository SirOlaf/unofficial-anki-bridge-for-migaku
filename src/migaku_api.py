import time
import requests
import gzip
from typing import Optional

from .common import get_timestamp_ms


MIGAKU_API_KEY = "AIzaSyDZvwYKYTsQoZkf3oKsfIQ4ykuy2GZAiH8"

class FirebaseAuthToken:
    def __init__(self, refresh_token: str):
        self.refresh_token = refresh_token
        self._expires_at_ms = 0
        self._auth_token = ""

    def _refresh(self):
        url = f"https://securetoken.googleapis.com/v1/token?key={MIGAKU_API_KEY}"
        resp = requests.post(url, json={
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        })
        j = resp.json()
        self._auth_token = j["access_token"]
        self._expires_at_ms = get_timestamp_ms() + (int(j["expires_in"]) - 5000)

    @staticmethod
    def try_from_email_password(email: str, password: str) -> Optional["FirebaseAuthToken"]:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={MIGAKU_API_KEY}"
        resp = requests.post(url, json={
            "email": email,
            "password": password,
            "returnSecureToken": True,
        })
        if resp.status_code != 200:
            return None
        j = resp.json()
        res = FirebaseAuthToken(j["refreshToken"])
        res._expires_at_ms = get_timestamp_ms() + (int(j["expiresIn"]) - 5000)
        res._auth_token = j["idToken"]
        return res

    def get(self) -> str:
        if get_timestamp_ms() > self._expires_at_ms:
            self._refresh()
        return self._auth_token


class MigakuSession:
    def __init__(self, auth_token: Optional[FirebaseAuthToken], early_access=True):
        self.early_access = early_access
        self._auth_token = auth_token

    def _get_sync_server_url(self) -> str:
        if self.early_access:
            return "https://srs-sync-server-testing-437922001437.us-central1.run.app/"
        else:
            raise ValueError("Only the early access endpoint is implemented right now")

    def _fetch_srs_download_url(self):
        if self._auth_token is None: raise ValueError("Missing auth token")
        resp = requests.get(
            "https://srs-db-presigned-url-service-api.migaku.com/db-force-sync-download-url",
            headers={"Authorization": "Bearer " + self._auth_token.get()},
        )
        return resp.text

    def force_download_srs_db(self):
        url = self._fetch_srs_download_url()
        resp = requests.get(url)
        compressed_db = resp.content
        return gzip.decompress(compressed_db)

    def try_fetch_srs_media(self, path: str) -> Optional[bytes]:
        if self._auth_token is None: raise ValueError("Missing auth token")
        resp = requests.get(
            f"https://file-sync-worker-api.migaku.com/data/{path}",
            headers={"Authorization": "Bearer " + self._auth_token.get()},
        )
        if resp.status_code != 200:
            return None
        return resp.content

    def push_sync(self, words):
        if self._auth_token is None: raise ValueError("Missing auth token")
        data = {
            "decks": [],
            "cardTypes": [],
            "cards": [],
            "cardWordRelations": [],
            "vacations": [],
            "reviews": [],
            "words": words,
            "config": None,
            "keyValue": [],
            "learningMaterials": [],
            "lessons": [],
            "reviewHistory": [],
        }
        resp = requests.put(
            f"{self._get_sync_server_url()}/sync?clientSessionId={get_timestamp_ms()}",
            headers={"Authorization": "Bearer " + self._auth_token.get()},
            json=data,
        )
        if resp.status_code != 200:
            raise ValueError(f"Bad response ({resp.status_code}): {resp.text}")

    def pull_sync(self, since_timestamp_ms):
        if self._auth_token is None: raise ValueError("Missing auth token")
        resp = requests.get(
            f"{self._get_sync_server_url()}/sync?timestamp={since_timestamp_ms}",
            headers={"Authorization": "Bearer " + self._auth_token.get()},
        )
        return resp.json()
