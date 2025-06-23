from collections import namedtuple, OrderedDict
import dataclasses
from typing import Any

import sqlite3

from .common import get_timestamp_ms


DbResSyncTimes = namedtuple("DbResSyncTimes", ["last_pull", "last_push"])

@dataclasses.dataclass
class DbRowCard:
    id: int
    mod: int
    serverMod: int
    del_: int
    deckId: int
    cardTypeId: int
    created: int
    primaryField: str
    secondaryField: str
    fields: str
    words: str
    due: int
    balancedDue: int
    interval: float
    factor: float
    lastReview: int
    reviewCount: int
    passCount: int
    failCount: int
    lapseCount: int
    pos: int
    lessonId: int
    seedMod: int
    notes: int
    seedDel: int
    suspended: int
    isSample: int
    replacementCardId: int

@dataclasses.dataclass
class DbRowCardType:
    id: int
    mod: int
    serverMod: int
    del_: int
    lang: str
    name: str
    config: str

@dataclasses.dataclass
class DbRowDeck:
    id: int
    mod: int
    serverMod: int
    del_: int
    lang: str
    name: str
    icon: str
    lastRecalc: int
    newBatchMax: int
    newBatchSize: int
    newGraduateCount: int
    factorMon: float
    factorTue: float
    factorWed: float
    factorThu: float
    factorFri: float
    factorSat: float
    factorSun: float
    retention10: float
    retention35: float
    retention100: float
    retention350: float
    retention1000: float
    intervalFactor10: float
    intervalFactor35: float
    intervalFactor100: float
    intervalFactor350: float
    intervalFactor1000: float
    learningMaterialId: int
    seedMod: int
    seedDel: int
    courseType: str

@dataclasses.dataclass
class DbRowCardWordRelation:
    mod: int
    serverMod: int
    del_: int
    seedMod: int
    seedDel: int
    cardId: int
    dictForm: str
    secondary: str
    partOfSpeech: str
    language: str
    isTargetWord: int
    occurrences: int

@dataclasses.dataclass
class DbRowWordList:
    dictForm: str
    secondary: str
    partOfSpeech: str
    language: str
    mod: int
    serverMod: int
    del_: int
    knownStatus: str
    hasCard: int
    tracked: int


def _dict_to_ordered_row_by_dataclass(j, t) -> list[tuple[str, Any]]:
    fields = []
    for f in dataclasses.fields(t):
        name = f.name[:-1] if f.name.endswith("_") else f.name
        fields.append((name, j[name]))
    return fields


class MigakuDb:
    def __init__(self, db_con: sqlite3.Connection):
        self._handle = db_con
        self._cursor = self._handle.cursor()

    def _commit(self):
        self._handle.commit()

    def fetch_last_sync_times(self) -> DbResSyncTimes:
        res = dict(self._cursor.execute("SELECT id, last_sync FROM local_data"))
        return DbResSyncTimes(last_pull=res["pullSync"], last_push=res["pushSync"])

    def update_sync_times(self, pull_time: int, push_time: int):
        self._cursor.execute('UPDATE local_data SET last_sync = ? WHERE id = "pullSync"', [pull_time])
        self._cursor.execute('UPDATE local_data SET last_sync = ? WHERE id = "pushSync"', [push_time])
        self._commit()

    def _do_dict_put(self, table: str, value: Any, t: type):
        fields = _dict_to_ordered_row_by_dataclass(value, t)
        questionmarks = ", ".join(["?"] * len(fields))
        self._cursor.execute(f'INSERT OR REPLACE INTO {table} VALUES({questionmarks})', [x[1] for x in fields])
        self._commit() # TODO: Maybe put this somewhere else


    def put_card(self, card_json: Any):
        self._do_dict_put("card", card_json, DbRowCard)

    def put_card_word_relation(self, relation: Any):
        self._do_dict_put("CardWordRelation", relation, DbRowCardWordRelation)

    def put_word_status(self, word: Any):
        self._do_dict_put("WordList", word, DbRowWordList)

    def fetch_available_langcodes(self) -> set[str]:
        res = self._cursor.execute("SELECT lang FROM card_type ORDER BY id")
        return list(OrderedDict.fromkeys([x[0] for x in res.fetchall()]))

    def fetch_note_types_for_language(self, langcode: str) -> list[DbRowCardType]:
        res = self._cursor.execute("SELECT * FROM card_type WHERE lang=? ORDER BY id", [langcode])
        result = []
        for r in res:
            result.append(DbRowCardType(*r))
        return result

    def fetch_decks_for_language(self, langcode: str) -> list[DbRowDeck]:
        res = self._cursor.execute("SELECT * FROM deck WHERE lang=? ORDER BY id", [langcode])
        result = []
        for r in res:
            result.append(DbRowDeck(*r))
        return result

    def fetch_note_type_by_id(self, id: int) -> list[DbRowCardType]:
        res = self._cursor.execute("SELECT * FROM card_type WHERE id=?", [id])
        return DbRowCardType(*res.fetchone())

    def apply_sync_changeset(self, j: Any):
        for group, value in j.items():
            # Would prefer a match statement but anki's python might be too old
            if group == "cards":
                for card in value:
                    self.put_card(card)
            elif group == "cardWordRelations":
                for relation in value:
                    self.put_card_word_relation(relation)
            elif group == "words":
                for word in value:
                    self.put_word_status(word)
            elif group in ["decks", "cardTypes", "vacations", "reviews", "reviewHistory"]:
                pass # TODO: These MIGHT be relevant one day, but definitely not now
            elif group in ["config", "keyValue", "learningMaterials", "lesson"]:
                pass # These are not relevant for us
            else:
                if value:
                    raise ValueError(f"Unimplemented change type: {group}")
