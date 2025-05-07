import os
import sys
import re
import webbrowser
from datetime import datetime
import difflib
from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtGui import QPixmap, QImage, QIcon
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QListWidget, QLabel, QWidget, QPushButton,
    QFileDialog, QHBoxLayout, QLineEdit, QMessageBox, QCheckBox, QFormLayout, QMenuBar, QAction, QProgressBar,
    QMenu, QSpinBox, QPlainTextEdit, QComboBox, QDialog, QDialogButtonBox
)
from pydub import AudioSegment
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3, EasyMP3
import base64
import platform

APP_NAME = "Jam Merger"
APP_VERSION = "1.0"
APP_DATE = "2025-05-03"
APP_AUTHOR = "blatchy and GitHub Copilot"
BUG_EMAIL = "jbriggs585@gmail.com"
COFFEE_LINK = "https://buymeacoffee.com/blatchy"

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def set_ffmpeg():
    ffmpeg_path = resource_path("ffmpeg.exe")
    if os.path.exists(ffmpeg_path):
        AudioSegment.converter = ffmpeg_path

set_ffmpeg()

if platform.system() == "Windows":
    import subprocess
    import pydub.utils

    _orig_popen = subprocess.Popen

    def _popen_no_window(*args, **kwargs):
        startupinfo = kwargs.get("startupinfo")
        if not startupinfo:
            startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = startupinfo
        return _orig_popen(*args, **kwargs)

    pydub.utils.Popen = _popen_no_window

class DragDropListWidget(QListWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.InternalMove)
        self.full_paths = []

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.source() == self:
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.source() == self:
            super().dropEvent(event)
            self.update_full_paths_order()
        elif event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if file_path.lower().endswith(('.mp3', '.wav', '.flac', '.ape')):
                    parent_dir, file_name = self.extract_parent_and_file(file_path)
                    self.addItem(f"{parent_dir}/{file_name}")
                    self.full_paths.append(file_path)
            event.accept()
            self.main_window.update_file_name_preview()
            self.main_window.update_combined_metadata()
        else:
            event.ignore()

    def update_full_paths_order(self):
        reordered_paths = []
        for i in range(self.count()):
            item_text = self.item(i).text()
            for full_path in self.full_paths:
                if item_text in full_path:
                    reordered_paths.append(full_path)
                    break
        self.full_paths = reordered_paths
        self.main_window.update_file_name_preview()
        self.main_window.update_combined_metadata()

    @staticmethod
    def extract_parent_and_file(file_path):
        parent_dir = os.path.basename(os.path.dirname(file_path))
        file_name = os.path.basename(file_path)
        return parent_dir, file_name

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowIcon(QIcon(resource_path("turtle.ico")))

        self.setWindowTitle(APP_NAME)
        self.setGeometry(100, 100, 800, 700)
        self.settings = QSettings("JamMerger", "Settings")
        self.song_list = self.load_song_list()
        self.shortname_map = self.load_shortname_map()
        self.shortnames_enabled = False
        self.edit_metadata_enabled = False

        # Custom Description Settings
        self.custom_description = self.settings.value("custom_description_text", "", type=str)
        self.custom_description_enabled = self.settings.value("custom_description_enabled", False, type=bool)

        # Menu bar: Settings first, About last (rightmost)
        self.menu_bar = QMenuBar(self)
        self.settings_menu = QMenu("&Settings", self)
        self.menu_bar.addMenu(self.settings_menu)
        self.about_menu = self.menu_bar.addMenu("&About")
        self.setMenuBar(self.menu_bar)

        # Settings Actions
        self.show_progress_action = QAction("Show Progress Bar", self, checkable=True)
        self.show_progress_action.setChecked(self.settings.value("show_progress_bar", True, type=bool))
        self.show_progress_action.triggered.connect(self.toggle_progress_bar_setting)

        self.show_success_popup_action = QAction("Show Success Popup", self, checkable=True)
        self.show_success_popup_action.setChecked(self.settings.value("show_success_popup", True, type=bool))
        self.show_success_popup_action.triggered.connect(self.toggle_success_popup_setting)

        self.custom_description_action = QAction("Custom Description", self, checkable=True)
        self.custom_description_action.setChecked(self.custom_description_enabled)
        self.custom_description_action.triggered.connect(self.toggle_custom_description_dialog)

        self.settings_menu.addAction(self.show_progress_action)
        self.settings_menu.addAction(self.show_success_popup_action)
        self.settings_menu.addAction(self.custom_description_action)

        # About menu actions (rightmost)
        self.bug_action = QAction("Suggestions / Report a Bug", self)
        self.bug_action.triggered.connect(self.send_bug_email)
        self.about_menu.addAction(self.bug_action)
        self.about_action = QAction("About", self)
        self.about_action.triggered.connect(self.show_about_dialog)
        self.about_menu.addAction(self.about_action)
        self.coffee_action = QAction("Buy Me a Coffee", self)
        self.coffee_action.triggered.connect(self.open_coffee_link)
        self.about_menu.addAction(self.coffee_action)

        self.central_widget = QWidget()
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.addWidget(QLabel("Drag and drop audio files here, or use the 'Add Files' button:"))

        self.list_widget = DragDropListWidget(self)
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list_widget.setMinimumHeight(100)
        self.list_widget.setMaximumHeight(200)
        self.main_layout.addWidget(self.list_widget)

        self.album_art_label = QLabel()
        self.album_art_label.setFixedSize(100, 100)
        self.album_art_label.setStyleSheet("border: 1px solid gray;")
        self.album_art_label.setAlignment(Qt.AlignCenter)

        self.change_artwork_button = QPushButton("Change Artwork")
        self.change_artwork_button.clicked.connect(self.change_artwork)
        self.change_artwork_button.setEnabled(False)

        self.metadata_form = QFormLayout()
        self.file_name_preview_edit = QLineEdit()
        self.file_name_preview_edit.setReadOnly(True)
        self.metadata_form.addRow("Proposed File Name:", self.file_name_preview_edit)

        self.title_edit = QLineEdit()
        self.title_edit.setReadOnly(True)
        self.metadata_form.addRow("Title:", self.title_edit)
        self.artist_edit = QLineEdit()
        self.artist_edit.setReadOnly(True)
        self.metadata_form.addRow("Artist:", self.artist_edit)
        self.album_edit = QLineEdit()
        self.album_edit.setReadOnly(True)
        self.metadata_form.addRow("Album:", self.album_edit)
        self.year_edit = QLineEdit()
        self.year_edit.setReadOnly(True)
        self.metadata_form.addRow("Year:", self.year_edit)
        self.genre_edit = QLineEdit()
        self.genre_edit.setReadOnly(True)
        self.metadata_form.addRow("Genre:", self.genre_edit)
        self.album_artist_edit = QLineEdit()
        self.album_artist_edit.setReadOnly(True)
        self.metadata_form.addRow("Album Artist:", self.album_artist_edit)

        self.metadata_artwork_layout = QHBoxLayout()
        self.metadata_artwork_layout.addLayout(self.metadata_form)
        artwork_vbox = QVBoxLayout()
        artwork_vbox.addWidget(self.album_art_label)
        artwork_vbox.addWidget(self.change_artwork_button)
        self.metadata_artwork_layout.addLayout(artwork_vbox)
        self.main_layout.addLayout(self.metadata_artwork_layout)

        self.shortnames_checkbox = QCheckBox("Short Names")
        self.shortnames_checkbox.stateChanged.connect(self.toggle_shortnames)
        self.main_layout.addWidget(self.shortnames_checkbox)

        self.edit_metadata_checkbox = QCheckBox("Edit Metadata")
        self.edit_metadata_checkbox.stateChanged.connect(self.toggle_edit_metadata)
        self.main_layout.addWidget(self.edit_metadata_checkbox)

        self.omit_special_checkbox = QCheckBox("Omit Drums/Space/Rhythm Devils")
        self.omit_special_checkbox.setChecked(False)
        self.main_layout.addWidget(self.omit_special_checkbox)

        self.fade_last_checkbox = QCheckBox("Fade last song")
        self.fade_last_checkbox.setChecked(False)

        self.fade_last_spinbox = QSpinBox()
        self.fade_last_spinbox.setMinimum(0)
        self.fade_last_spinbox.setMaximum(30)
        self.fade_last_spinbox.setValue(self.settings.value("fade_last_seconds", 2, type=int))
        self.fade_last_spinbox.setSuffix(" s")
        self.fade_last_spinbox.setEnabled(self.fade_last_checkbox.isChecked())
        self.fade_last_spinbox.valueChanged.connect(self.save_fade_last_setting)

        fade_hbox = QHBoxLayout()
        fade_hbox.addWidget(self.fade_last_checkbox)
        fade_hbox.addWidget(self.fade_last_spinbox)
        fade_hbox.addStretch()
        self.main_layout.addLayout(fade_hbox)
        self.fade_last_checkbox.stateChanged.connect(
            lambda checked: self.fade_last_spinbox.setEnabled(checked)
        )

        self.omit_special_checkbox.stateChanged.connect(self.handle_omit_special_changed)
        self.handle_omit_special_changed()

        # --- Conversion checkbox and dropdown for merged files ---
        self.convert_checkbox = QCheckBox("Convert merged files to:")
        self.convert_checkbox.setChecked(False)
        self.convert_format_combo = QComboBox()
        self.convert_format_combo.addItems([
            "FLAC", "WAV", "MP3 320", "MP3 256", "MP3 128"
        ])
        self.convert_format_combo.setEnabled(False)
        convert_hbox = QHBoxLayout()
        convert_hbox.addWidget(self.convert_checkbox)
        convert_hbox.addWidget(self.convert_format_combo)
        convert_hbox.addStretch()
        self.main_layout.addLayout(convert_hbox)
        self.convert_checkbox.stateChanged.connect(
            lambda checked: self.convert_format_combo.setEnabled(checked)
        )

        self.add_files_button = QPushButton("Add Files")
        self.add_files_button.clicked.connect(self.open_file_dialog)
        self.main_layout.addWidget(self.add_files_button)

        self.clear_files_button = QPushButton("Clear Files")
        self.clear_files_button.clicked.connect(self.clear_files)
        self.main_layout.addWidget(self.clear_files_button)

        self.process_button = QPushButton("Process Files")
        self.process_button.clicked.connect(self.process_files)
        self.main_layout.addWidget(self.process_button)

        self.save_directory_button = QPushButton("Save to Directory")
        self.save_directory_button.clicked.connect(self.select_save_directory)
        self.main_layout.addWidget(self.save_directory_button)

        self.save_to_same_folder_button = QPushButton("Save to Same Folder")
        self.save_to_same_folder_button.clicked.connect(self.save_to_same_folder)
        self.main_layout.addWidget(self.save_to_same_folder_button)

        self.save_directory_label = QLabel("Save Directory: Not Selected")
        self.main_layout.addWidget(self.save_directory_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(self.show_progress_action.isChecked())
        self.main_layout.addWidget(self.progress_bar)

        self.list_widget.itemChanged.connect(self.update_file_name_preview)
        self.setCentralWidget(self.central_widget)
        self.load_last_directories()

        self.artwork_data = None
        self.artwork_mime = None

        self.metadata_widgets = [
            self.file_name_preview_edit, self.title_edit, self.artist_edit,
            self.album_edit, self.year_edit, self.genre_edit, self.album_artist_edit
        ]
        self.toggle_edit_metadata()

    def save_fade_last_setting(self):
        self.settings.setValue("fade_last_seconds", self.fade_last_spinbox.value())

    def toggle_progress_bar_setting(self):
        show = self.show_progress_action.isChecked()
        self.settings.setValue("show_progress_bar", show)
        self.progress_bar.setVisible(show)

    def toggle_success_popup_setting(self):
        show = self.show_success_popup_action.isChecked()
        self.settings.setValue("show_success_popup", show)

    def handle_omit_special_changed(self):
        pass

    def toggle_custom_description_dialog(self):
        checked = self.custom_description_action.isChecked()
        if checked:
            desc, ok = self.get_description_from_user()
            if ok:
                self.custom_description = desc
                self.custom_description_enabled = True
                self.settings.setValue("custom_description_text", desc)
                self.settings.setValue("custom_description_enabled", True)
            else:
                self.custom_description_action.setChecked(False)
        else:
            self.custom_description_enabled = False
            self.settings.setValue("custom_description_enabled", False)

    def get_description_from_user(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Custom Description")
        layout = QVBoxLayout(dialog)
        label = QLabel("Enter a custom description to be embedded as metadata in every merged file:")
        layout.addWidget(label)
        edit = QPlainTextEdit()
        edit.setPlainText(self.custom_description)
        layout.addWidget(edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        result = dialog.exec_()
        return edit.toPlainText(), result == QDialog.Accepted

    def send_bug_email(self):
        subject = f"{APP_NAME} Suggestion / Bug Report"
        body = "Please describe your suggestion or the bug you encountered:\n"
        url = f"mailto:{BUG_EMAIL}?subject={subject}&body={body}"
        webbrowser.open(url)

    def show_about_dialog(self):
        text = (
            f"<b>{APP_NAME}</b><br>"
            f"Version: {APP_VERSION}<br>"
            f"Date: {APP_DATE}<br>"
            f"Built by <b>blatchy</b> and <b>GitHub Copilot</b><br><br>"
            f"<a href='{COFFEE_LINK}'>Buy Me a Coffee</a>"
        )
        QMessageBox.about(self, f"About {APP_NAME}", text)

    def open_coffee_link(self):
        webbrowser.open(COFFEE_LINK)

    def load_song_list(self):
        song_file_path = resource_path("songs.txt")
        try:
            with open(song_file_path, "r", encoding="utf-8") as f:
                songs = [line.strip() for line in f if line.strip()]
            songs = sorted(songs, key=lambda x: -len(x))
            return songs
        except Exception as e:
            print(f"Could not load song list: {e}")
            return []

    def load_shortname_map(self):
        shortname_file_path = resource_path("shortnames.txt")
        short_map = {}
        try:
            with open(shortname_file_path, "r", encoding="utf-8") as f:
                for line in f:
                    if "=>" in line:
                        full, short = line.strip().split("=>", 1)
                        short_map[full.strip().lower()] = short.strip()
            return short_map
        except Exception as e:
            print(f"Could not load shortnames list: {e}")
            return {}

    def normalize_title(self, title):
        title = title.lower()
        title = title.replace("feeling", "feelin'")
        title = title.replace("feelin", "feelin'")
        title = re.sub(r"[^\w\s]", "", title)
        title = title.replace(" ", "")
        return title

    def extract_song_title(self, raw_title):
        cleaned = re.sub(r"^(?:\d+-)?\d+\s*", "", raw_title)
        cleaned = cleaned.replace("_", " ").replace("-", " ").strip()
        cleaned_norm = self.normalize_title(cleaned)

        norm_song_map = {self.normalize_title(song): song for song in self.song_list}
        norm_shortname_map = {self.normalize_title(full): short for full, short in self.shortname_map.items()}

        if cleaned_norm in norm_song_map:
            full_title = norm_song_map[cleaned_norm]
            short_key = self.normalize_title(full_title)
            if self.shortnames_enabled and short_key in norm_shortname_map:
                return norm_shortname_map[short_key]
            else:
                return full_title

        matches = difflib.get_close_matches(cleaned_norm, norm_song_map.keys(), n=1, cutoff=0.6)
        if matches:
            matched_key = matches[0]
            full_title = norm_song_map[matched_key]
            short_key = self.normalize_title(full_title)
            if self.shortnames_enabled and short_key in norm_shortname_map:
                return norm_shortname_map[short_key]
            else:
                return full_title

        return cleaned

    def toggle_shortnames(self):
        self.shortnames_enabled = self.shortnames_checkbox.isChecked()
        self.update_file_name_preview()
        self.update_combined_metadata()

    def toggle_edit_metadata(self):
        self.edit_metadata_enabled = self.edit_metadata_checkbox.isChecked()
        for widget in self.metadata_widgets:
            widget.setReadOnly(not self.edit_metadata_enabled)
        self.change_artwork_button.setEnabled(self.edit_metadata_enabled)
        if not self.edit_metadata_enabled:
            for widget in self.metadata_widgets:
                widget.setStyleSheet("background-color: #dddddd; color: #888888;")
            self.album_art_label.setStyleSheet("border: 1px solid gray; background-color: #dddddd;")
            self.update_file_name_preview()
            self.update_combined_metadata()
        else:
            for widget in self.metadata_widgets:
                widget.setStyleSheet("")
            self.album_art_label.setStyleSheet("border: 1px solid gray;")

    def open_file_dialog(self):
        last_dir = self.settings.value("last_add_files_dir", "")
        files, _ = QFileDialog.getOpenFileNames(self, "Select Audio Files", last_dir)
        if files:
            self.settings.setValue("last_add_files_dir", os.path.dirname(files[0]))
            for file in files:
                if file.lower().endswith(('.mp3', '.wav', '.flac', '.ape')):
                    parent_dir, file_name = DragDropListWidget.extract_parent_and_file(file)
                    self.list_widget.addItem(f"{parent_dir}/{file_name}")
                    self.list_widget.full_paths.append(file)
            self.update_file_name_preview()
            self.update_combined_metadata()

    def select_save_directory(self):
        last_dir = self.settings.value("last_save_directory", "")
        directory = QFileDialog.getExistingDirectory(self, "Select Save Directory", last_dir)
        if directory:
            self.settings.setValue("last_save_directory", directory)
            self.save_directory_label.setText(f"Save Directory: {directory}")

    def save_to_same_folder(self):
        if self.list_widget.full_paths:
            folder = os.path.dirname(self.list_widget.full_paths[0])
            self.settings.setValue("last_save_directory", folder)
            self.save_directory_label.setText(f"Save Directory: {folder}")
        else:
            QMessageBox.warning(self, "No Files", "Add audio files before using 'Save to Same Folder'.")

    def load_last_directories(self):
        last_save_directory = self.settings.value("last_save_directory", "")
        if last_save_directory:
            self.save_directory_label.setText(f"Save Directory: {last_save_directory}")

    def clear_files(self):
        self.list_widget.clear()
        self.list_widget.full_paths = []
        self.file_name_preview_edit.clear()
        self.album_art_label.clear()
        self.title_edit.clear()
        self.artist_edit.clear()
        self.album_edit.clear()
        self.year_edit.clear()
        self.genre_edit.clear()
        self.album_artist_edit.clear()
        self.artwork_data = None
        self.artwork_mime = None
        if self.edit_metadata_checkbox.isChecked():
            self.edit_metadata_checkbox.setChecked(False)
        if self.omit_special_checkbox.isChecked():
            self.omit_special_checkbox.setChecked(False)
        if self.fade_last_checkbox.isChecked():
            self.fade_last_checkbox.setChecked(False)
        self.handle_omit_special_changed()
        self.toggle_edit_metadata()

    def update_file_name_preview(self):
        if self.edit_metadata_enabled:
            return
        song_titles = []
        for i in range(self.list_widget.count()):
            item_text = self.list_widget.item(i).text()
            file_name = item_text.split("/")[-1].rsplit(".", 1)[0]
            song_title = self.extract_song_title(file_name)
            song_titles.append(song_title)
        proposed_name = " - ".join(song_titles)
        if self.list_widget.full_paths:
            date_str = self.extract_date_for_filename(self.list_widget.full_paths[0])
            proposed_name += f" ({date_str})"
        self.file_name_preview_edit.setText(proposed_name)

    def update_combined_metadata(self):
        if self.edit_metadata_enabled:
            return
        combined_titles = []
        artist, album, year, genre, album_artist = None, None, None, None, None
        for index, file_path in enumerate(self.list_widget.full_paths):
            try:
                if file_path.lower().endswith('.flac'):
                    audio_file = FLAC(file_path)
                    title = audio_file.get('title', [None])[0]
                    if index == 0:
                        artist = audio_file.get('artist', [None])[0]
                        album = audio_file.get('album', [None])[0]
                        year = audio_file.get('date', [None])[0]
                        genre = audio_file.get('genre', [None])[0]
                        album_artist = audio_file.get('albumartist', [None])[0]
                elif file_path.lower().endswith('.mp3'):
                    audio_file = MP3(file_path)
                    title = audio_file.get('TIT2', None)
                    if title:
                        title = title.text[0]
                    if index == 0:
                        artist = audio_file.get('TPE1', None)
                        if artist:
                            artist = artist.text[0]
                        album = audio_file.get('TALB', None)
                        if album:
                            album = album.text[0]
                        year = audio_file.get('TDRC', None)
                        if year:
                            year = str(year.text[0])
                        genre = audio_file.get('TCON', None)
                        if genre:
                            genre = genre.text[0]
                        album_artist = audio_file.get('TPE2', None)
                        if album_artist:
                            album_artist = album_artist.text[0]
                file_name = os.path.basename(file_path).rsplit(".", 1)[0]
                song_title = self.extract_song_title(file_name)
                combined_titles.append(song_title)
            except Exception as e:
                print(f"Error reading metadata for {file_path}: {e}")
                file_name = os.path.basename(file_path).rsplit(".", 1)[0]
                song_title = self.extract_song_title(file_name)
                combined_titles.append(song_title)
        combined_title = " > ".join(combined_titles)
        if artist and isinstance(artist, str) and artist.strip().lower() == "grateful dead":
            genre = "Rock"
            album_artist = "Grateful Dead"
        artist = artist or "Unknown Artist"
        album = album or "Unknown Album"
        year = year or "Unknown Year"
        genre = genre or "Unknown Genre"
        album_artist = album_artist or "Unknown Album Artist"
        self.title_edit.setText(combined_title)
        self.artist_edit.setText(artist)
        self.album_edit.setText(album)
        self.year_edit.setText(year)
        self.genre_edit.setText(genre)
        self.album_artist_edit.setText(album_artist)
        self.update_album_art()

    def extract_date_for_filename(self, first_file):
        def extract_date_from_string(s):
            match = re.search(r'(\d{4})[-_\.](\d{2})[-_\.](\d{2})', s)
            if match:
                return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
            return None

        first_file_name = os.path.basename(first_file)
        parent_dir = os.path.basename(os.path.dirname(first_file))
        date_str = extract_date_from_string(parent_dir)
        if not date_str:
            date_str = extract_date_from_string(first_file_name)
        if not date_str:
            metadata_year = None
            try:
                if first_file.lower().endswith('.flac'):
                    audio_file = FLAC(first_file)
                    metadata_year = audio_file.get('date', [None])[0]
                elif first_file.lower().endswith('.mp3'):
                    audio_file = MP3(first_file)
                    year_tag = audio_file.get('TDRC', None)
                    if year_tag:
                        metadata_year = str(year_tag.text[0])
            except Exception:
                pass
            if metadata_year:
                match = re.match(r'(\d{4})(?:[-_\.](\d{2})[-_\.](\d{2}))?', metadata_year)
                if match:
                    y = match.group(1)
                    m = match.group(2) if match.group(2) else '01'
                    d = match.group(3) if match.group(3) else '01'
                    date_str = f"{y}-{m}-{d}"
        if not date_str:
            mod_time = datetime.fromtimestamp(os.path.getmtime(first_file))
            date_str = mod_time.strftime('%Y-%m-%d')
        return date_str

    def has_artwork(self, file_path):
        try:
            if file_path.lower().endswith('.mp3'):
                audio_file = MP3(file_path)
                for tag in audio_file.tags.values():
                    if hasattr(tag, 'FrameID') and tag.FrameID == "APIC":
                        return True
            elif file_path.lower().endswith('.flac'):
                audio_file = FLAC(file_path)
                if hasattr(audio_file, "pictures") and len(audio_file.pictures) > 0:
                    return True
                elif "metadata_block_picture" in audio_file:
                    return True
        except Exception as e:
            print(f"Error checking artwork: {e}")
        return False

    def any_file_has_artwork(self):
        for file_path in self.list_widget.full_paths:
            if self.has_artwork(file_path):
                return True
        return False

    def is_track_order_suspicious(self):
        track_numbers = []
        titles = []
        for file_path in self.list_widget.full_paths:
            num = None
            title = None
            try:
                if file_path.lower().endswith('.flac'):
                    audio = FLAC(file_path)
                    num = audio.get('tracknumber', [None])[0]
                    title = audio.get('title', [None])[0]
                elif file_path.lower().endswith('.mp3'):
                    audio = MP3(file_path)
                    num = audio.get('TRCK', None)
                    if num:
                        num = num.text[0].split('/')[0]
                    title = audio.get('TIT2', None)
                    if title:
                        title = title.text[0]
            except Exception:
                pass
            if not num:
                basename = os.path.basename(file_path)
                m = re.match(r"^(\d+)", basename)
                if m:
                    num = m.group(1)
            track_numbers.append(int(num) if num and str(num).isdigit() else None)
            titles.append(title or os.path.basename(file_path))

        track_nums = [n for n in track_numbers if n is not None]
        if len(track_nums) >= 2:
            if track_nums != sorted(track_nums):
                return True
        if len(titles) >= 2:
            file_names = [os.path.basename(f) for f in self.list_widget.full_paths]
            if file_names != sorted(file_names):
                return True
        return False

    def warn_tracks_out_of_order(self):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Possible Track Order Issue")
        msg.setText("Warning: The files you have added appear to be out of order by track number or filename.\nProceed anyway?")
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msg.setDefaultButton(QMessageBox.Cancel)
        return msg.exec_() == QMessageBox.Ok

    def warn_no_artwork_dialog(self):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("No Album Artwork Detected")
        msg.setText("Warning: No album artwork detected in the metadata of any file in your selection.\nProceed anyway?")
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msg.setDefaultButton(QMessageBox.Cancel)
        return msg.exec_() == QMessageBox.Ok

    def process_files(self):
        if self.list_widget.count() == 0:
            print("No files to process!")
            return
        save_directory = self.settings.value("last_save_directory", "")
        if not save_directory:
            print("Save directory not selected!")
            return

        # Warn if track order looks suspicious
        if self.is_track_order_suspicious():
            if not self.warn_tracks_out_of_order():
                self.progress_bar.setVisible(False)
                self.progress_bar.setValue(0)
                return

        # Warn if none of the files have album art
        if not self.any_file_has_artwork():
            if not self.warn_no_artwork_dialog():
                self.progress_bar.setVisible(False)
                self.progress_bar.setValue(0)
                return

        proposed_file_name = self.file_name_preview_edit.text() if self.edit_metadata_enabled else self.get_auto_proposed_filename()

        # --- Conversion logic for merged file ---
        output_format = None
        bitrate = None
        first_file = self.list_widget.full_paths[0]
        if self.convert_checkbox.isChecked():
            fmt = self.convert_format_combo.currentText()
            if fmt == "FLAC":
                file_extension = ".flac"
                output_format = "flac"
            elif fmt == "WAV":
                file_extension = ".wav"
                output_format = "wav"
            elif fmt == "MP3 320":
                file_extension = ".mp3"
                output_format = "mp3"
                bitrate = "320k"
            elif fmt == "MP3 256":
                file_extension = ".mp3"
                output_format = "mp3"
                bitrate = "256k"
            elif fmt == "MP3 128":
                file_extension = ".mp3"
                output_format = "mp3"
                bitrate = "128k"
        else:
            file_extension = os.path.splitext(first_file)[1].lower()
            output_format = file_extension[1:]

        date_str = self.extract_date_for_filename(first_file)

        total_files = len(self.list_widget.full_paths)
        self.progress_bar.setMaximum(total_files)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(self.show_progress_action.isChecked())
        fade_duration = self.fade_last_spinbox.value() * 1000  # ms

        def get_titles_and_paths():
            titles = []
            for i in range(self.list_widget.count()):
                item_text = self.list_widget.item(i).text()
                file_name = item_text.split("/")[-1].rsplit(".", 1)[0]
                song_title = self.extract_song_title(file_name)
                titles.append(song_title)
            return titles, list(self.list_widget.full_paths)

        # Omit Drums/Space/Rhythm Devils logic
        if self.omit_special_checkbox.isChecked():
            titles, paths = get_titles_and_paths()
            special_names = ["drums", "space", "rhythm devils"]
            omitted_indices = [i for i, t in enumerate(titles)
                               if any(s in t.lower() for s in special_names)]
            if omitted_indices:
                first_omit = omitted_indices[0]
                last_omit = omitted_indices[-1]
                before_titles = titles[:first_omit]
                before_paths = paths[:first_omit]
                after_titles = titles[last_omit + 1:]
                after_paths = paths[last_omit + 1:]

                if before_paths:
                    merged_audio = None
                    for idx, file_path in enumerate(before_paths):
                        audio = AudioSegment.from_file(file_path)
                        merged_audio = audio if merged_audio is None else merged_audio + audio
                        if self.show_progress_action.isChecked():
                            self.progress_bar.setValue(idx + 1)
                            QApplication.processEvents()
                    output_name = " - ".join(before_titles) + f" ({date_str}){file_extension}"
                    output_path = os.path.join(save_directory, output_name)
                    self.export_merged_file(merged_audio, output_path, file_extension, " > ".join(before_titles), output_format, bitrate)
                    self.show_success_dialog(output_path)
                if after_paths:
                    merged_audio = None
                    for idx, file_path in enumerate(after_paths):
                        audio = AudioSegment.from_file(file_path)
                        # Only fade out last song of after_paths if fade is enabled
                        if (
                            self.fade_last_checkbox.isChecked()
                            and fade_duration > 0
                            and idx == len(after_paths) - 1
                        ):
                            audio = audio.fade_out(fade_duration)
                        merged_audio = audio if merged_audio is None else merged_audio + audio
                        if self.show_progress_action.isChecked():
                            self.progress_bar.setValue(len(before_paths) + idx + 1)
                            QApplication.processEvents()
                    output_name = " - ".join(after_titles) + f" ({date_str}){file_extension}"
                    output_path = os.path.join(save_directory, output_name)
                    self.export_merged_file(merged_audio, output_path, file_extension, " > ".join(after_titles), output_format, bitrate)
                    self.show_success_dialog(output_path)
                self.progress_bar.setVisible(False)
                self.progress_bar.setValue(0)
                return

        # Standard merging (no omit or no matches)
        merged_audio = None
        for idx, file_path in enumerate(self.list_widget.full_paths):
            try:
                audio = AudioSegment.from_file(file_path)
                # Only fade last song if enabled and fade duration > 0
                if (
                    self.fade_last_checkbox.isChecked()
                    and fade_duration > 0
                    and idx == self.list_widget.count() - 1
                ):
                    audio = audio.fade_out(fade_duration)
                merged_audio = audio if merged_audio is None else merged_audio + audio
                if self.show_progress_action.isChecked():
                    self.progress_bar.setValue(idx + 1)
                    QApplication.processEvents()
            except Exception as e:
                print(f"Error processing file {file_path}: {e}")
                self.progress_bar.setVisible(False)
                self.progress_bar.setValue(0)
                return
        proposed_file_name_with_date = proposed_file_name
        if not proposed_file_name_with_date.endswith(file_extension):
            proposed_file_name_with_date += file_extension
        output_path = os.path.join(save_directory, proposed_file_name_with_date)
        self.export_merged_file(merged_audio, output_path, file_extension, output_format=output_format, bitrate=bitrate)
        self.show_success_dialog(output_path)
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)

    def export_merged_file(self, merged_audio, output_path, file_extension, title_override=None, output_format=None, bitrate=None):
        try:
            export_kwargs = {}
            if output_format:
                export_kwargs["format"] = output_format
            else:
                export_kwargs["format"] = file_extension[1:]
            if bitrate and output_format == "mp3":
                export_kwargs["bitrate"] = bitrate
            merged_audio.export(output_path, **export_kwargs)
        except Exception as e:
            print(f"Error exporting merged file: {e}")
            return
        try:
            title_value = title_override if title_override is not None else self.title_edit.text()
            artist_value = self.artist_edit.text()
            album_value = self.album_edit.text()
            year_value = self.year_edit.text()
            genre_value = self.genre_edit.text()
            album_artist_value = self.album_artist_edit.text()
            if artist_value.strip().lower() == "grateful dead":
                genre_value = "Rock"
                album_artist_value = "Grateful Dead"
            if file_extension == ".flac":
                merged_file = FLAC(output_path)
                merged_file["title"] = title_value
                merged_file["artist"] = artist_value
                merged_file["album"] = album_value
                merged_file["date"] = year_value
                merged_file["genre"] = genre_value
                merged_file["albumartist"] = album_artist_value
                if self.custom_description_enabled and self.custom_description:
                    merged_file["description"] = self.custom_description
                merged_file.save()
            elif file_extension == ".mp3":
                merged_file = EasyMP3(output_path)
                merged_file["title"] = title_value
                merged_file["artist"] = artist_value
                merged_file["album"] = album_value
                merged_file["date"] = year_value
                merged_file["genre"] = genre_value
                merged_file["albumartist"] = album_artist_value
                if self.custom_description_enabled and self.custom_description:
                    merged_file["comment"] = self.custom_description
                merged_file.save()
        except Exception as e:
            print(f"Error adding metadata: {e}")

    def get_auto_proposed_filename(self):
        song_titles = []
        for i in range(self.list_widget.count()):
            item_text = self.list_widget.item(i).text()
            file_name = item_text.split("/")[-1].rsplit(".", 1)[0]
            song_title = self.extract_song_title(file_name)
            song_titles.append(song_title)
        proposed_name = " - ".join(song_titles)
        if self.list_widget.full_paths:
            date_str = self.extract_date_for_filename(self.list_widget.full_paths[0])
            proposed_name += f" ({date_str})"
        return proposed_name

    def show_success_dialog(self, output_path):
        if not self.show_success_popup_action.isChecked():
            return
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("Processing Complete")
        msg.setText("The merged file has been successfully created!")
        filename = os.path.basename(output_path)
        msg.setInformativeText(f"File saved: {filename}")
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()

    def update_album_art(self):
        if self.edit_metadata_enabled and self.artwork_data and self.artwork_mime:
            image = QImage.fromData(self.artwork_data)
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
                pixmap = pixmap.scaled(self.album_art_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.album_art_label.setPixmap(pixmap)
            return

        self.album_art_label.clear()
        self.artwork_data = None
        self.artwork_mime = None

        for file_path in self.list_widget.full_paths:
            try:
                if file_path.lower().endswith('.mp3'):
                    audio_file = MP3(file_path)
                    for tag in audio_file.tags.values():
                        if hasattr(tag, 'FrameID') and tag.FrameID == "APIC":
                            self.artwork_data = tag.data
                            self.artwork_mime = tag.mime
                            break
                elif file_path.lower().endswith('.flac'):
                    audio_file = FLAC(file_path)
                    if hasattr(audio_file, "pictures") and len(audio_file.pictures) > 0:
                        picture = audio_file.pictures[0]
                        self.artwork_data = picture.data
                        self.artwork_mime = picture.mime
                        break
                    elif "metadata_block_picture" in audio_file:
                        try:
                            picture = Picture(base64.b64decode(audio_file["metadata_block_picture"][0]))
                        except Exception:
                            picture = Picture(audio_file["metadata_block_picture"][0].encode())
                        self.artwork_data = picture.data
                        self.artwork_mime = picture.mime
                        break
            except Exception as e:
                print(f"Error extracting album art for preview from {file_path}: {e}")

        if self.artwork_data:
            image = QImage.fromData(self.artwork_data)
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
                pixmap = pixmap.scaled(self.album_art_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.album_art_label.setPixmap(pixmap)

    def change_artwork(self):
        file_dialog = QFileDialog(self)
        file_dialog.setNameFilter("Images (*.jpg *.jpeg *.png)")
        if file_dialog.exec_():
            selected_file = file_dialog.selectedFiles()[0]
            with open(selected_file, "rb") as f:
                data = f.read()
            if selected_file.lower().endswith(".jpg") or selected_file.lower().endswith(".jpeg"):
                mime = "image/jpeg"
            elif selected_file.lower().endswith(".png"):
                mime = "image/png"
            else:
                QMessageBox.warning(self, "Invalid Image", "Please select a JPG or PNG image.")
                return
            self.artwork_data = data
            self.artwork_mime = mime
            self.update_album_art()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
