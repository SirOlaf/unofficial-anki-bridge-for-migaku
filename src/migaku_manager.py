import sqlite3
import json
import pathlib
from typing import Any, Literal, Callable, Optional

from .common import get_timestamp_ms
from .migaku_api import MigakuSession, FirebaseAuthToken
from .migaku_db import MigakuDb


class MigakuManager:
    def __init__(self, session: MigakuSession, srs_db_path: str = "migakusrs.db"):
        self._session = session
        self._srs_db_path = pathlib.Path(srs_db_path)
        self.db: Optional[MigakuDb] = None
        self._local_word_changes: list[dict[str, Any]] = []
        if self._srs_db_path.exists():
            self._open_db()

    def force_download_db(self):
        self._srs_db_path.absolute().parent.mkdir(parents=True, exist_ok=True)
        self._srs_db_path.write_bytes(self._session.force_download_srs_db())
        self._open_db()

    def set_auth(self, token: FirebaseAuthToken):
        self._session._auth_token = token

    def has_auth(self):
        return self._session._auth_token is not None

    def _open_db(self):
        assert self._srs_db_path.exists()
        assert self.db is None
        self.db = MigakuDb(sqlite3.connect(self._srs_db_path, check_same_thread=False))

    def has_db(self) -> bool:
        return self.db is not None

    # TODO: Implementation of the push side
    # def set_local_word_status(self, language: str, dict_form: str, secondary: str, status: Literal["UNKNOWN", "KNOWN", "IGNORED", "LEARNING"], has_card: bool, tracked: bool):
    #     self._local_word_changes.append({
    #         "dictForm": dict_form,
    #         "secondary": secondary,
    #         "partOfSpeech": "",
    #         "language": language,
    #         "mod": get_timestamp_ms(),
    #         "serverMod": -1, # In push mode we should set it to -1 and later update it through sync
    #         "del": 0,
    #         "knownStatus": status,
    #         "hasCard": has_card,
    #         "tracked": tracked
    #     })

    def do_sync(self, changeset_cb: Optional[Callable[[Any], bool]] = None):
        if not self.has_db():
            if self._srs_db_path.exists():
                # TODO: Better errors
                raise ValueError("The db file exists but it wasn't opened")
            self.force_download_db()
            self._open_db()
        assert self.db is not None

        timestamp = get_timestamp_ms()
        last_sync_times = self.db.fetch_last_sync_times()
        #self._session.push_sync(words=self._local_word_changes)
        changes = self._session.pull_sync(last_sync_times.last_pull)
        if changeset_cb is None or changeset_cb(changes):
            self.db.apply_sync_changeset(changes)
            self.db.update_sync_times(timestamp, timestamp)
