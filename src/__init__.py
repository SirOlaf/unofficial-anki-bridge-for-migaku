import json
import pathlib
import os
from typing import Optional, Any
import tempfile
import re

import anki
import anki.collection
from aqt import mw, gui_hooks
from aqt.utils import showInfo, qconnect
from aqt.operations import QueryOp
from aqt.qt import *

from . import migaku_api, migaku_manager, migaku_db


ADDON_NAME = "Anki Bridge for Migaku (Unofficial)"


config = mw.addonManager.getConfig(__name__)

config_key_note_type_mapping = "note_type_mappings"
config_key_refresh_token = "refresh_token"
config_key_pull_on_sync = "pull_on_sync"
config_key_remove_syntax = "remove_syntax"
config_key_ignored_decks_and_notes = "ignored_decks_and_notes"

def commit_config():
    assert config is not None
    mw.addonManager.writeConfig(__name__, config)

def config_try_get_note_type_mapping(migaku_deck_id: int, migaku_note_id: int):
    assert config is not None
    if config_key_note_type_mapping not in config:
        return None
    for mapping in config[config_key_note_type_mapping]:
        if mapping["migaku_deck_id"] == migaku_deck_id and mapping["migaku_note_id"] == migaku_note_id:
            return mapping
    return None
def config_put_note_type_mapping(mapping):
    assert config is not None
    if config_key_note_type_mapping not in config:
        config[config_key_note_type_mapping] = []

    new_mappings = []
    replaced_old = False
    for old in config[config_key_note_type_mapping]:
        if old["migaku_deck_id"] == mapping["migaku_deck_id"] and old["migaku_note_id"] == mapping["migaku_note_id"]:
            new_mappings.append(mapping)
            replaced_old = True
        else:
            new_mappings.append(old)
    if not replaced_old:
        new_mappings.append(mapping)
    config[config_key_note_type_mapping] = new_mappings
    commit_config()
def config_delete_note_type_mapping(migaku_deck_id: int, migaku_note_id: int):
    assert config is not None
    new_mappings = []
    for old in config.get(config_key_note_type_mapping, []):
        if old["migaku_deck_id"] != migaku_deck_id or old["migaku_note_id"] != migaku_note_id:
            new_mappings.append(old)
    config[config_key_note_type_mapping] = new_mappings
    commit_config()

def config_get_ignored_decks_and_notes() -> list[Any]:
    assert config is not None
    return config.get(config_key_ignored_decks_and_notes, [])
def config_put_ignored_deck_and_note(pair: Any):
    assert config is not None
    cur_pairs = config_get_ignored_decks_and_notes()
    if pair not in cur_pairs:
        cur_pairs.append(pair)
    config[config_key_ignored_decks_and_notes] = cur_pairs
    commit_config()
def config_delete_ignored_deck_and_note(pair: Any):
    assert config is not None
    new_pairs = []
    for old in config_get_ignored_decks_and_notes():
        if old != pair:
            new_pairs.append(old)
    config[config_key_ignored_decks_and_notes] = new_pairs
    commit_config()


def config_try_get_refresh_token() -> Optional[str]:
    assert config is not None
    return config.get(config_key_refresh_token, None)

def config_put_refresh_token(refresh_token: str):
    assert config is not None
    config[config_key_refresh_token] = refresh_token
    commit_config()

def config_get_pull_on_sync() -> bool:
    assert config is not None
    return config.get(config_key_pull_on_sync, False)

def config_put_pull_on_sync(value: bool):
    assert config is not None
    config[config_key_pull_on_sync] = value
    commit_config()

def config_get_remove_syntax() -> bool:
    assert config is not None
    return config.get(config_key_remove_syntax, False)

def config_put_remove_syntax(value: bool):
    assert config is not None
    config[config_key_remove_syntax] = value
    commit_config()



migaku = migaku_manager.MigakuManager(migaku_api.MigakuSession(
    auth_token=None,
    early_access=True,
), srs_db_path=str(pathlib.Path(os.path.abspath(os.path.dirname(__file__))).joinpath("user_files", "migaku.db")))


def setupMigakuAuthDialog() -> bool:
    win = QDialog()
    main_layout = QVBoxLayout(win)
    form_layout = QFormLayout(win)
    form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

    main_layout.addWidget(QLabel(f"{ADDON_NAME} login"))

    email_box = QLineEdit()
    email_box.setPlaceholderText("Enter your email")
    form_layout.addRow(QLabel("Email:"), email_box)

    password_box = QLineEdit()
    password_box.setPlaceholderText("Enter your password")
    password_box.setEchoMode(QLineEdit.EchoMode.Password)
    form_layout.addRow(QLabel("Password:"), password_box)

    main_layout.addLayout(form_layout)

    success = False
    def on_login_button():
        nonlocal success, win, email_box, password_box
        auth = migaku_api.FirebaseAuthToken.try_from_email_password(email=email_box.text(), password=password_box.text())
        if auth is None:
            QMessageBox.warning(
                win,
                "Error",
                "Invalid email or password."
            )
        else:
            config_put_refresh_token(auth.refresh_token)
            migaku.set_auth(auth)
            win.close()
            success = True

    login_button = QPushButton("Login")
    login_button.clicked.connect(on_login_button)
    main_layout.addWidget(login_button)

    win.setLayout(main_layout)
    win.exec()
    return success


def askInitialAuthSetup() -> bool:
    msg = QMessageBox(mw)
    msg.setIcon(QMessageBox.Icon.Information)
    msg.setWindowTitle(ADDON_NAME)
    msg.setText(f"{ADDON_NAME} needs access to Migaku's api using your account. Do you want to set this up now?")
    yes_button = msg.addButton("Yes", QMessageBox.ButtonRole.AcceptRole)
    msg.addButton("No", QMessageBox.ButtonRole.RejectRole)
    msg.exec()

    if msg.clickedButton() == yes_button:
        if setupMigakuAuthDialog():
            QMessageBox.information(mw, "Done", f"{ADDON_NAME} now has api access.")
            return True
        else:
            QMessageBox.critical(mw, "Failure", f"{ADDON_NAME} has been unable to get api access.")
            return False
    else:
        return False

def ensure_migaku_auth(silent: bool = False) -> bool:
    if not migaku.has_auth():
        refresh_token = config_try_get_refresh_token()
        if refresh_token:
            migaku.set_auth(migaku_api.FirebaseAuthToken(refresh_token))
            return True
        else:
            if silent: return False
            return askInitialAuthSetup()
    else:
        return True


def askInitialMmDbDownload() -> bool:
    if not ensure_migaku_auth():
        return False

    msg = QMessageBox(mw)
    msg.setIcon(QMessageBox.Icon.Information)
    msg.setWindowTitle(ADDON_NAME)
    msg.setText(f"{ADDON_NAME} requires a local version of the Migaku Memory database to function. Download it now?")

    yes_button = msg.addButton("Yes", QMessageBox.ButtonRole.AcceptRole)
    msg.addButton("No", QMessageBox.ButtonRole.RejectRole)
    msg.exec()

    if msg.clickedButton() == yes_button:
        migaku.force_download_db()
        QMessageBox.information(mw, "Done", "Initial database download has been completed.")
        return True
    else:
        return False

def ensureLocalMmDb(silent: bool = False) -> bool:
    if not migaku.has_db():
        if silent: return False
        return askInitialMmDbDownload()
    else:
        return True

def ensure_migaku_setup(silent: bool = False) -> bool:
    return ensure_migaku_auth(silent=silent) and ensureLocalMmDb(silent=silent)


def mapCardTypesDialog() -> None:
    if not ensure_migaku_setup():
        return

    col = mw.col
    assert col is not None
    assert migaku.db is not None

    migaku_languages = migaku.db.fetch_available_langcodes()
    migaku_decks: list[migaku_db.DbRowDeck] = []
    migaku_note_types: list[migaku_db.DbRowCardType] = []

    anki_decks = col.decks.all_names_and_ids()
    anki_note_types = col.models.all()

    win = QDialog()
    main_layout = QVBoxLayout(win)

    migaku_deck_combo: Optional[QComboBox] = None
    anki_deck_combo: Optional[QComboBox] = None
    source_note_kind_combo: Optional[QComboBox] = None
    dest_note_kind_combo: Optional[QComboBox] = None
    scroll_content_widget: Optional[QWidget] = None
    fields_layout: Optional[QGridLayout] = None
    ignore_combo_checkbox: Optional[QCheckBox] = None

    save_button = QPushButton("Save")
    mapping_status_label = QLabel("")

    changed_mapping = False
    def save_mapping():
        nonlocal fields_layout, anki_note_types, migaku_note_types, source_note_kind_combo, dest_note_kind_combo, changed_mapping

        selected_migaku_deck = migaku_decks[migaku_deck_combo.currentIndex()]
        selected_anki_deck = anki_decks[anki_deck_combo.currentIndex()]

        selected_anki_note_type = anki_note_types[dest_note_kind_combo.currentIndex()]
        selected_migaku_note_type = migaku_note_types[source_note_kind_combo.currentIndex()]

        this_pair = {
            "migaku_deck_id": selected_migaku_deck.id,
            "migaku_note_id": selected_migaku_note_type.id,
        }
        existing_ignored_pairs = config_get_ignored_decks_and_notes()
        existing_mapping = config_try_get_note_type_mapping(migaku_deck_id=selected_migaku_deck.id, migaku_note_id=selected_migaku_note_type.id)
        should_continue = True
        if this_pair in existing_ignored_pairs or (existing_mapping and (existing_mapping["anki_deck_id"] == selected_anki_deck.id or existing_mapping["anki_note_id"] != selected_anki_note_type["id"])):
            msg = QMessageBox(win)
            msg.setText("You are about to replace a mapping. Do you want to proceed?")
            yes_button = msg.addButton("Yes", QMessageBox.ButtonRole.AcceptRole)
            msg.addButton("No", QMessageBox.ButtonRole.RejectRole)
            msg.exec()
            if msg.clickedButton() != yes_button:
                should_continue = False
        if not should_continue:
            return

        if ignore_combo_checkbox is not None and ignore_combo_checkbox.isChecked():
            config_put_ignored_deck_and_note(this_pair)
            config_delete_note_type_mapping(migaku_deck_id=this_pair["migaku_deck_id"], migaku_note_id=this_pair["migaku_note_id"])
        else:
            indices = []
            for i in range(fields_layout.rowCount()):
                x = fields_layout.itemAtPosition(i, 0)
                if x is None: continue
                w = x.widget()
                if isinstance(w, QComboBox):
                    indices.append(max(w.currentIndex() - 1, -1))
            assert len(indices) == len(selected_anki_note_type["flds"])

            mapping_config = {
                "anki_note_id": selected_anki_note_type["id"],
                "migaku_note_id": selected_migaku_note_type.id,
                "anki_deck_id": selected_anki_deck.id,
                "migaku_deck_id": selected_migaku_deck.id,
                "anki_fields": [x["name"] for x in selected_anki_note_type["flds"]],
                "migaku_fields": [x["name"] for x in json.loads(selected_migaku_note_type.config)["fields"]],
                "mapped_migaku_indices": indices
            }
            config_put_note_type_mapping(mapping_config)
            config_delete_ignored_deck_and_note(this_pair["migaku_deck_id"])
        mapping_status_label.setText("Saved")
        save_button.setEnabled(False)
        changed_mapping = False

    def update_fields_display():
        nonlocal source_note_kind_combo, fields_layout, changed_mapping
        if changed_mapping:
            msg = QMessageBox(win)
            msg.setText("You are about to discard your changes. Do you want to save the current mapping?")
            yes_button = msg.addButton("Yes", QMessageBox.ButtonRole.AcceptRole)
            msg.addButton("No", QMessageBox.ButtonRole.RejectRole)
            msg.exec()
            if msg.clickedButton() == yes_button:
                save_mapping()
            changed_mapping = False

        assert fields_layout is not None
        while fields_layout.count():
            x = fields_layout.takeAt(0)
            if w := x.widget():
                w.deleteLater()
        source_note_type_index = source_note_kind_combo.currentIndex()
        selected_mm_note_type = migaku_note_types[source_note_type_index]
        raw_mm_config = json.loads(selected_mm_note_type.config)
        selected_anki_note_type = anki_note_types[dest_note_kind_combo.currentIndex()]
        selected_anki_deck = anki_decks[anki_deck_combo.currentIndex()]
        selected_migaku_deck = migaku_decks[migaku_deck_combo.currentIndex()]

        this_pair = {
            "migaku_deck_id": selected_migaku_deck.id,
            "migaku_note_id": selected_mm_note_type.id,
        }
        ignored_pairs = config_get_ignored_decks_and_notes()
        existing_mapping = config_try_get_note_type_mapping(migaku_deck_id=selected_migaku_deck.id, migaku_note_id=selected_mm_note_type.id)
        if this_pair in ignored_pairs:
            mapping_status_label.setText("This deck + card type combination is ignored")
            if ignore_combo_checkbox is not None:
                ignore_combo_checkbox.setChecked(True)
        else:
            if not existing_mapping:
                save_button.setEnabled(True)
                mapping_status_label.setText("This is a new mapping")
            else:
                if existing_mapping["anki_deck_id"] == selected_anki_deck.id and existing_mapping["anki_note_id"] == selected_anki_note_type["id"]:
                    mapping_status_label.setText("This is an existing mapping")
                else:
                    mapping_status_label.setText("There is a mapping to different anki note type or deck already")
                    save_button.setEnabled(True)

        for i, f in enumerate(selected_anki_note_type["flds"], start=1):
            combo = QComboBox()
            combo.addItems([""] + [x["name"] for x in raw_mm_config["fields"]])
            if existing_mapping and existing_mapping["anki_deck_id"] == selected_anki_deck.id and existing_mapping["anki_note_id"] == selected_anki_note_type["id"]:
                combo.setCurrentIndex(max(existing_mapping["mapped_migaku_indices"][i - 1] + 1, 0))
            else:
                combo.setCurrentIndex(i)
            def on_update_mapping():
                nonlocal changed_mapping
                changed_mapping = True
                save_button.setEnabled(True)
            combo.currentIndexChanged.connect(on_update_mapping)

            fields_layout.addWidget(combo, i, 0)
            fields_layout.addWidget(QLabel(f["name"]), i, 1)


    def create_deck_selection_ui():
        nonlocal source_note_kind_combo, dest_note_kind_combo, migaku_deck_combo, anki_deck_combo, ignore_combo_checkbox, fields_layout

        grid = QGridLayout()
        lang_selection_combo_box = QComboBox()
        lang_selection_combo_box.addItems(migaku_languages)

        migaku_deck_combo = QComboBox()
        anki_deck_combo = QComboBox()
        anki_deck_combo.addItems([x.name for x in anki_decks])

        source_note_kind_combo = QComboBox()
        source_note_kind_combo.addItems([])

        def on_selection_change():
            if ignore_combo_checkbox is not None:
                ignore_combo_checkbox.setChecked(False)
            update_fields_display()

        dest_note_kind_combo = QComboBox()
        dest_note_kind_combo.addItems([x["name"] for x in anki_note_types])

        grid.addWidget(QLabel("<b>Language:</b>"), 0, 0)
        grid.addWidget(lang_selection_combo_box, 0, 1)

        grid.addWidget(QLabel("<b>MM Deck:</b>"), 1, 0)
        grid.addWidget(migaku_deck_combo, 1, 1)
        grid.addWidget(QLabel("<b>Anki Deck:"), 1, 2)
        grid.addWidget(anki_deck_combo, 1, 3)

        grid.addWidget(QLabel("<b>MM Card type:</b>"), 2, 0)
        grid.addWidget(source_note_kind_combo, 2, 1)
        grid.addWidget(QLabel("<b>Anki  Note type:</b>"), 2, 2)
        grid.addWidget(dest_note_kind_combo, 2, 3)

        grid.addWidget(QLabel("Ignore deck+card type combo"), 3, 0)
        ignore_combo_checkbox = QCheckBox()
        def on_toggle_ignore():
            nonlocal scroll_content_widget, ignore_combo_checkbox
            assert ignore_combo_checkbox is not None
            if scroll_content_widget is None: return
            if ignore_combo_checkbox.isChecked():
                scroll_content_widget.setEnabled(False)
            else:
                scroll_content_widget.setEnabled(True)
        ignore_combo_checkbox.toggled.connect(on_toggle_ignore)
        grid.addWidget(ignore_combo_checkbox, 3, 1)

        main_layout.addLayout(grid)

        def on_lang_changed():
            nonlocal migaku_note_types, migaku_decks, source_note_kind_combo
            ignore_combo_checkbox.setChecked(False)

            migaku_decks = [x for x in migaku.db.fetch_decks_for_language(lang_selection_combo_box.currentText()) if x.del_ == 0]
            migaku_deck_combo.clear()
            migaku_deck_combo.addItems([x.name for x in migaku_decks])

            migaku_note_types = [x for x in migaku.db.fetch_note_types_for_language(lang_selection_combo_box.currentText()) if x.del_ == 0]
            source_note_kind_combo.clear()
            source_note_kind_combo.addItems([x.name for x in migaku_note_types])
        lang_selection_combo_box.currentIndexChanged.connect(on_lang_changed)
        on_lang_changed() # initial contents

        migaku_deck_combo.currentIndexChanged.connect(on_selection_change)
        source_note_kind_combo.currentIndexChanged.connect(on_selection_change)
        dest_note_kind_combo.currentIndexChanged.connect(on_selection_change)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(line)

    def create_field_mapping_area():
        nonlocal scroll_content_widget, fields_layout

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content_widget = QWidget()
        fields_layout = QGridLayout(scroll_content_widget)
        fields_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll_area.setWidget(scroll_content_widget)
        main_layout.addWidget(scroll_area)

    create_deck_selection_ui()
    create_field_mapping_area()

    update_fields_display()

    save_button.clicked.connect(save_mapping)
    main_layout.addWidget(save_button, alignment=Qt.AlignmentFlag.AlignRight)
    main_layout.addWidget(mapping_status_label, alignment=Qt.AlignmentFlag.AlignLeft)

    win.setLayout(main_layout)
    win.exec()


def _mm_sync_task(migaku: migaku_manager.MigakuManager, col: anki.collection.Collection, silent: bool) -> int:
    sync_new_card_count = 0
    new_notes = []
    should_add_to_anki = False

    def get_ext(p: str):
        _, ext = os.path.splitext(p)
        return ext

    def fetch_media(path: str) -> Optional[str]:
        data = migaku.session.try_fetch_srs_media(path)
        if data is None: return None
        tmp_path = None
        with tempfile.NamedTemporaryFile(delete=False, suffix=get_ext(path)) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        new_filename = mw.col.media.add_file(tmp_path)
        pathlib.Path(tmp_path).unlink(missing_ok=True)
        return new_filename

    def report_error(message: str):
        nonlocal silent
        if silent:
            raise ValueError(message)
        else:
            QMessageBox.critical(mw, ADDON_NAME, message)

    def sync_callback(incoming_changes) -> bool:
        nonlocal sync_new_card_count, new_notes, should_add_to_anki
        new_cards = []
        for card in incoming_changes["cards"]:
            if card["lessonId"] is not None:
                continue
            for i in range(len(new_cards) - 1, -1, -1):
                if new_cards[i]["id"] == card["id"]:
                    del new_cards[i] # only keep the most recent version
            if not card["del"]:
                new_cards.append(card)

        ignored_pairs = config_get_ignored_decks_and_notes()
        for card in new_cards:
            this_pair = {
                "migaku_deck_id": card["deckId"],
                "migaku_note_id": card["cardTypeId"],
            }
            if this_pair in ignored_pairs:
                # Ignored pairs get skipped
                continue
            if card["mod"] != card["created"]:
                # If the modification time is not the creation time we are not interested for now
                continue
            migaku_deck_id = card["deckId"]
            migaku_note_type = migaku.db.fetch_note_type_by_id(card["cardTypeId"])
            migaku_deck_info = migaku.db.fetch_deck_by_id(migaku_deck_id)
            used_mapping = config_try_get_note_type_mapping(migaku_deck_id=migaku_deck_id, migaku_note_id=card["cardTypeId"])
            if used_mapping is None:
                report_error(f"MM import failed. Please create a mapping for the \"{migaku_note_type.name} ({migaku_note_type.lang})\" note type from MM's \"{migaku_deck_info.name}\" deck.")
                return False

            anki_note_type = col.models.get(used_mapping["anki_note_id"])
            assert anki_note_type is not None # TODO: More reliable handling
            anki_note_type_fields = anki_note_type["flds"]
            migaku_note_type_fields = json.loads(migaku_note_type.config)["fields"]

            new_note = col.new_note(anki_note_type)
            new_note.add_tag("anki_bridge_for_migaku")

            migaku_field_def_map = {x["name"]: x for x in migaku_note_type_fields}
            anki_field_def_map = {x["name"]: x for x in anki_note_type_fields}
            migaku_card_fields = [card["primaryField"], card["secondaryField"]] + card["fields"].split("\x1f")
            for i in range(len(used_mapping["mapped_migaku_indices"])):
                if i == -1:
                    continue

                migaku_idx = used_mapping["mapped_migaku_indices"][i]
                migaku_field_def = migaku_field_def_map[used_mapping["migaku_fields"][migaku_idx]]
                anki_field_name = anki_field_def_map[used_mapping["anki_fields"][i]]["name"]
                migaku_field_type = migaku_field_def["type"]
                if migaku_field_type == "SYNTAX":
                    field_str: str = migaku_card_fields[migaku_idx]
                    # TODO: This could be translated into ruby text
                    if config_get_remove_syntax():
                        new_note[anki_field_name] = re.sub(r"\[.*?\]", "", field_str).replace("{", "").replace("}", "")
                    else:
                        new_note[anki_field_name] = field_str
                elif migaku_field_type == "TEXT":
                    new_note[anki_field_name] = migaku_card_fields[migaku_idx]
                elif migaku_field_type == "IMAGE":
                    new_filename = fetch_media(migaku_card_fields[migaku_idx][5:])
                    if new_filename is not None:
                        new_note[anki_field_name] = f'<img src="{new_filename}">'
                    else:
                        new_note[anki_field_name] = ""
                elif migaku_field_type in ["AUDIO", "AUDIO_LONG"]:
                    new_filename = fetch_media(migaku_card_fields[migaku_idx][5:])
                    if new_filename is not None:
                        new_note[anki_field_name] = f'[sound:{new_filename}]'
                    else:
                        new_note[anki_field_name] = ""
                else:
                    report_error(f"Import failed. The \"{migaku_field_type}\" field type isn't implemented, please report this bug.")
                    return False
            new_notes.append((used_mapping["anki_deck_id"], new_note))

        sync_new_card_count = len(new_notes)
        if len(new_notes) == 0:
            if not silent:
                QMessageBox.information(mw, ADDON_NAME, f"There are no new cards.")
        else:
            if not silent:
                msg = QMessageBox(mw)
                msg.setIcon(QMessageBox.Icon.Information)
                msg.setWindowTitle("Information")
                if len(new_notes) == 1:
                    msg.setText("Found 1 new card since last pull. Do you want to proceed?")
                else:
                    msg.setText(f"Found {len(new_notes)} new cards since last pull. Do you want to proceed?")
                continue_button = msg.addButton("Continue", QMessageBox.ButtonRole.DestructiveRole)
                msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
                msg.exec()
                if msg.clickedButton() != continue_button:
                    return False
        should_add_to_anki = True
        return True
    migaku.do_sync(sync_callback)

    if should_add_to_anki:
        for new_note in new_notes:
            col.add_note(new_note[1], new_note[0])

    return sync_new_card_count


def pull_new_cards_from_mm(silent: bool = False) -> None:
    if not ensure_migaku_setup(silent=silent):
        return

    col = mw.col
    assert col is not None

    if silent:
        def on_success(new_card_count):
            if new_card_count > 0:
                mw.onRefreshTimer()

        op = QueryOp(
            parent=mw,
            op=lambda col: _mm_sync_task(migaku=migaku, col=col, silent=True),
            success=on_success
        )
        op.with_progress().run_in_background()
    else:
        new_card_count = _mm_sync_task(migaku=migaku, col=col, silent=False)
        if new_card_count > 0:
            mw.onRefreshTimer()


def sync_hook() -> None:
    if not config_get_pull_on_sync():
        return
    pull_new_cards_from_mm(silent=True)


def forceDownloadMmDb() -> None:
    msg = QMessageBox(mw)
    msg.setIcon(QMessageBox.Icon.Critical)
    msg.setWindowTitle("Force MM database reset")
    msg.setText("This will trigger a full database download from Migaku. Doing so will overwrite the local database.")

    continue_button = msg.addButton("Continue", QMessageBox.ButtonRole.DestructiveRole)
    msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    msg.exec()

    if msg.clickedButton() == continue_button:
        migaku.force_download_db()
        QMessageBox.information(mw, "Done", "The database has been downloaded.")

def show_settings() -> None:
    win = QDialog(mw)
    win.setWindowTitle(ADDON_NAME)

    grid = QGridLayout()
    grid.setAlignment(Qt.AlignmentFlag.AlignTop)

    grid.addWidget(QLabel("Pull MM cards at Anki sync"), 0, 0)
    auto_pull_mm_checkbox = QCheckBox()
    def on_toggle_auto_pull():
        nonlocal auto_pull_mm_checkbox
        config_put_pull_on_sync(auto_pull_mm_checkbox.isChecked())
    auto_pull_mm_checkbox.toggled.connect(on_toggle_auto_pull)
    auto_pull_mm_checkbox.setChecked(config_get_pull_on_sync())
    grid.addWidget(auto_pull_mm_checkbox, 0, 1)

    grid.addWidget(QLabel("Remove Migaku Syntax"), 1, 0)
    remove_migaku_syntax_checkbox = QCheckBox()
    def on_toggle_remove_migaku_syntax():
        nonlocal remove_migaku_syntax_checkbox
        config_put_remove_syntax(remove_migaku_syntax_checkbox.isChecked())
    remove_migaku_syntax_checkbox.toggled.connect(on_toggle_remove_migaku_syntax)
    remove_migaku_syntax_checkbox.setChecked(config_get_remove_syntax())
    grid.addWidget(remove_migaku_syntax_checkbox, 1, 1)

    win.setLayout(grid)
    win.exec()


# TODO: Hooks on note type modifications. The stored mappings MUST be updated

my_menu = mw.form.menuTools.addMenu(ADDON_NAME)
assert my_menu is not None

gui_hooks.sync_will_start.append(sync_hook)

map_card_types_action = QAction("Map card types", mw)
qconnect(map_card_types_action.triggered, mapCardTypesDialog)
my_menu.addAction(map_card_types_action)

pull_new_action = QAction("Pull new cards from MM", mw)
qconnect(pull_new_action.triggered, pull_new_cards_from_mm)
my_menu.addAction(pull_new_action)

forceDbAction = QAction("Force download MM database", mw)
qconnect(forceDbAction.triggered, forceDownloadMmDb)
my_menu.addAction(forceDbAction)

settings_action = QAction("Settings", mw)
qconnect(settings_action.triggered, show_settings)
my_menu.addAction(settings_action)

ensure_migaku_setup()
