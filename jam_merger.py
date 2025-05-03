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
    QFileDialog, QHBoxLayout, QLineEdit, QMessageBox, QCheckBox, QFormLayout, QMenuBar, QAction
)
from pydub import AudioSegment
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3, EasyMP3
from mutagen.id3 import APIC, ID3
import base64

APP_NAME = "Jam Merger"
APP_VERSION = "1.0"
APP_DATE = "2025-05-03"
APP_AUTHOR = "blatchy and GitHub Copilot"
BUG_EMAIL = "jbriggs585@gmail.com"
COFFEE_LINK = "https://buymeacoffee.com/blatchy"

def resource_path(relative_path):
    """
    Get absolute path to resource, works for dev and for PyInstaller bundle
    """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# --- Setup ffmpeg path for pydub (bundled ffmpeg.exe support) ---
def set_ffmpeg():
    ffmpeg_path = resource_path("ffmpeg.exe")
    if os.path.exists(ffmpeg_path):
        AudioSegment.converter = ffmpeg_path

set_ffmpeg()

# --- Prevent ffmpeg.exe window from flashing (Windows only, PyInstaller safe) ---
import platform
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
        # Set the window icon to turtle.ico for toolbar/taskbar
        self.setWindowIcon(QIcon(resource_path("turtle.ico")))

        self.setWindowTitle(APP_NAME)
        self.setGeometry(100, 100, 800, 700)
        self.settings = QSettings("JamMerger", "Settings")
        self.song_list = self.load_song_list()
        self.shortname_map = self.load_shortname_map()
        self.shortnames_enabled = False
        self.edit_metadata_enabled = False

        # ---------- Menu Bar -----------
        self.menu_bar = QMenuBar(self)
        about_menu = self.menu_bar.addMenu("&About")

        # Suggestions/Report a Bug
        self.bug_action = QAction("Suggestions / Report a Bug", self)
        self.bug_action.triggered.connect(self.send_bug_email)
        about_menu.addAction(self.bug_action)

        # About
        self.about_action = QAction("About", self)
        self.about_action.triggered.connect(self.show_about_dialog)
        about_menu.addAction(self.about_action)

        # Buy Me a Coffee
        self.coffee_action = QAction("Buy Me a Coffee", self)
        self.coffee_action.triggered.connect(self.open_coffee_link)
        about_menu.addAction(self.coffee_action)

        self.setMenuBar(self.menu_bar)
        # ---------- End Menu Bar -----------

        self.central_widget = QWidget()
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.addWidget(QLabel("Drag and drop audio files here, or use the 'Add Files' button:"))

        self.list_widget = DragDropListWidget(self)
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.list_widget.setMinimumHeight(100)
        self.list_widget.setMaximumHeight(200)
        self.main_layout.addWidget(self.list_widget)

        # Metadata/artwork
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

        # Short Names Checkbox
        self.shortnames_checkbox = QCheckBox("Short Names")
        self.shortnames_checkbox.stateChanged.connect(self.toggle_shortnames)
        self.main_layout.addWidget(self.shortnames_checkbox)

        # Edit Metadata Checkbox
        self.edit_metadata_checkbox = QCheckBox("Edit Metadata")
        self.edit_metadata_checkbox.stateChanged.connect(self.toggle_edit_metadata)
        self.main_layout.addWidget(self.edit_metadata_checkbox)

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

        self.list_widget.itemChanged.connect(self.update_file_name_preview)
        self.setCentralWidget(self.central_widget)
        self.load_last_directories()

        # Internal: hold artwork image data and mime
        self.artwork_data = None
        self.artwork_mime = None

    # -------- Menu Actions --------
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
    # -------- End Menu Actions --------

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

    def extract_song_title(self, raw_title):
        cleaned = re.sub(r"^(?:\d+-)?\d+\s*", "", raw_title)
        cleaned = cleaned.replace("_", " ").replace("-", " ").strip()
        matches = difflib.get_close_matches(cleaned, self.song_list, n=1, cutoff=0.6)
        if matches:
            matched_full_title = matches[0]
            key = matched_full_title.lower()
            if self.shortnames_enabled and key in self.shortname_map:
                return self.shortname_map[key]
            else:
                return matched_full_title
        for song in self.song_list:
            if cleaned.lower() == song.lower():
                key = song.lower()
                return self.shortname_map[key] if self.shortnames_enabled and key in self.shortname_map else song
        return cleaned

    def toggle_shortnames(self):
        self.shortnames_enabled = self.shortnames_checkbox.isChecked()
        self.update_file_name_preview()
        self.update_combined_metadata()

    def toggle_edit_metadata(self):
        self.edit_metadata_enabled = self.edit_metadata_checkbox.isChecked()
        # Toggle editability for all fields
        for widget in [
            self.file_name_preview_edit, self.title_edit, self.artist_edit,
            self.album_edit, self.year_edit, self.genre_edit, self.album_artist_edit
        ]:
            widget.setReadOnly(not self.edit_metadata_enabled)
        self.change_artwork_button.setEnabled(self.edit_metadata_enabled)
        if not self.edit_metadata_enabled:
            self.update_file_name_preview()
            self.update_combined_metadata()

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

    def update_file_name_preview(self):
        # If editing is enabled, do not auto-update so user can type
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
        # Do not auto-update if editing is enabled, except on clear
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

    def process_files(self):
        if self.list_widget.count() == 0:
            print("No files to process!")
            return
        save_directory = self.settings.value("last_save_directory", "")
        if not save_directory:
            print("Save directory not selected!")
            return

        # Use user-edited values if editing enabled, otherwise current preview
        proposed_file_name = self.file_name_preview_edit.text() if self.edit_metadata_enabled else self.get_auto_proposed_filename()
        first_file = self.list_widget.full_paths[0]
        file_extension = os.path.splitext(first_file)[1].lower()

        date_str = self.extract_date_for_filename(first_file)
        match = re.match(r'^(.*) \(\d{4}-\d{2}-\d{2}\)$', proposed_file_name)
        if match:
            core_name = match.group(1)
        else:
            core_name = proposed_file_name
        proposed_file_name_with_date = f"{core_name} ({date_str})"

        output_path = os.path.join(save_directory, proposed_file_name_with_date + file_extension)
        merged_audio = None

        # Use selected artwork if any, else extract from first file
        album_art_data = self.artwork_data
        album_art_mime = self.artwork_mime
        if not (album_art_data and album_art_mime) and self.list_widget.full_paths:
            try:
                if first_file.lower().endswith('.mp3'):
                    audio_file = MP3(first_file)
                    for tag in audio_file.tags.values():
                        if hasattr(tag, 'FrameID') and tag.FrameID == "APIC":
                            album_art_data = tag.data
                            album_art_mime = tag.mime
                            break
                elif first_file.lower().endswith('.flac'):
                    audio_file = FLAC(first_file)
                    if hasattr(audio_file, "pictures") and len(audio_file.pictures) > 0:
                        picture = audio_file.pictures[0]
                        album_art_data = picture.data
                        album_art_mime = picture.mime
                    elif "metadata_block_picture" in audio_file:
                        try:
                            picture = Picture(base64.b64decode(audio_file["metadata_block_picture"][0]))
                        except Exception:
                            picture = Picture(audio_file["metadata_block_picture"][0].encode())
                        album_art_data = picture.data
                        album_art_mime = picture.mime
            except Exception as e:
                print(f"Error extracting album art from the first file: {e}")

        for file_path in self.list_widget.full_paths:
            try:
                audio = AudioSegment.from_file(file_path)
                if merged_audio is None:
                    merged_audio = audio
                else:
                    merged_audio += audio
            except Exception as e:
                print(f"Error processing file {file_path}: {e}")
                return
        try:
            merged_audio.export(output_path, format=file_extension[1:])
        except Exception as e:
            print(f"Error exporting merged file: {e}")
            return
        try:
            # Use user metadata if editing enabled, else from preview fields
            title_value = self.title_edit.text()
            artist_value = self.artist_edit.text()
            album_value = self.album_edit.text()
            year_value = self.year_edit.text()
            genre_value = self.genre_edit.text()
            album_artist_value = self.album_artist_edit.text()
            if file_extension == ".flac":
                merged_file = FLAC(output_path)
                merged_file["title"] = title_value
                merged_file["artist"] = artist_value
                merged_file["album"] = album_value
                merged_file["date"] = year_value
                merged_file["genre"] = genre_value
                merged_file["albumartist"] = album_artist_value
                if album_art_data and album_art_mime:
                    picture = Picture()
                    picture.data = album_art_data
                    picture.type = 3
                    picture.mime = album_art_mime
                    picture.width = 0
                    picture.height = 0
                    picture.depth = 0
                    merged_file.clear_pictures()
                    merged_file.add_picture(picture)
                merged_file.save()
            elif file_extension == ".mp3":
                merged_file = EasyMP3(output_path)
                merged_file["title"] = title_value
                merged_file["artist"] = artist_value
                merged_file["album"] = album_value
                merged_file["date"] = year_value
                merged_file["genre"] = genre_value
                merged_file["albumartist"] = album_artist_value
                merged_file.save()
                if album_art_data and album_art_mime:
                    id3_tags = ID3(output_path)
                    id3_tags.delall("APIC")
                    id3_tags.add(
                        APIC(
                            mime=album_art_mime,
                            type=3,
                            desc="Cover",
                            data=album_art_data,
                        )
                    )
                    id3_tags.save(v2_version=3)
        except Exception as e:
            print(f"Error adding metadata: {e}")
            return
        self.show_success_dialog(output_path)

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
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("Processing Complete")
        msg.setText("The merged file has been successfully created!")
        msg.setInformativeText(f"File saved to:\n{output_path}")
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()

    def update_album_art(self):
        # If editing and user has selected artwork, keep that; else use from first file
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

        # Get album art from first file
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
            # Determine mime type
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