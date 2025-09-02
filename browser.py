import os
# mew_browser.py
# MewBrowser v2 — adds: simple ad-blocker, custom user-agent (saved), and bookmark sidebar.
# Requires: PySide6
# Run: python mew_browser.py

import sys
from pathlib import Path

USE_PYSIDE = True
if USE_PYSIDE:
    from PySide6.QtCore import Qt, QUrl, QSettings, QSize, Slot, Signal
    from PySide6.QtGui import QAction, QIcon, QKeySequence
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QToolBar, QLineEdit, QTabWidget, QWidget,
        QVBoxLayout, QStatusBar, QLabel, QFileDialog, QMessageBox, QHBoxLayout,
        QPushButton, QDockWidget, QListWidget, QInputDialog, QListWidgetItem, QMenu
    )
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import (
        QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor,
        QWebEngineUrlRequestInfo, QWebEngineDownloadRequest
    )
else:
    raise SystemExit("Set USE_PYSIDE=True and install PySide6.")

APP_ORG = "jacobStuff"
APP_NAME = "Browsey"
HOME_URL = "https://duckduckgo.com/"

def normalize_url(text: str) -> QUrl:
    text = text.strip()
    if not text:
        return QUrl(HOME_URL)
    if " " not in text and "." in text and "://" not in text:
        return QUrl(f"https://{text}")
    if "://" not in text and (" " in text or "." not in text):
        return QUrl(f"https://duckduckgo.com/?q={QUrl.toPercentEncoding(text).data().decode()}")
    return QUrl(text)

# --- Simple AdBlock Interceptor ---
class SimpleAdblockInterceptor(QWebEngineUrlRequestInterceptor):
    def __init__(self, patterns=None, parent=None):
        super().__init__(parent)
        # default tiny rule set (extend via settings file)
        self.patterns = patterns or [
            "doubleclick.net",
            "googlesyndication",
            "adservice.google.",
            "pagead2.googlesyndication.com",
            "/ads?",
            "/adserver",
            ".ads.",
            "ads.",
            "advert",
            "adclick",
            "tracking",
            "analytics.js",
            "googletagservices",
            "adsystem",
        ]
        # lower-case for matching
        self.patterns = [p.lower() for p in self.patterns]

    def interceptRequest(self, info: QWebEngineUrlRequestInfo):
        # block if any pattern in URL
        url = info.requestUrl().toString().lower()
        for p in self.patterns:
            if p in url:
                try:
                    info.block(True)
                except Exception:
                    # some PySide6 builds might not expose block; best effort: do nothing then
                    pass
                return

# --- Find bar (same as before) ---
class FindBar(QWidget):
    def __init__(self, view: 'BrowserView'):
        super().__init__()
        self.view = view
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        self.input = QLineEdit(placeholderText="Find in page...")
        self.input.returnPressed.connect(self.find_next)
        btn_prev = QPushButton("Prev")
        btn_next = QPushButton("Next")
        btn_close = QPushButton("✕")
        btn_prev.clicked.connect(lambda: self.find(next=False))
        btn_next.clicked.connect(lambda: self.find(next=True))
        btn_close.clicked.connect(self.hide)
        layout.addWidget(self.input)
        layout.addWidget(btn_prev)
        layout.addWidget(btn_next)
        layout.addWidget(btn_close)
        self.hide()

    def show_and_focus(self):
        self.show()
        self.input.setFocus()
        self.input.selectAll()

    def find(self, next=True):
        text = self.input.text()
        if not text:
            return
        self.view.findText(
            text,
            QWebEnginePage.FindFlag.FindBackward if not next else QWebEnginePage.FindFlag(0)
        )

    def find_next(self):
        self.find(True)

# --- BrowserView (slightly adapted) ---
class BrowserView(QWebEngineView):
    def __init__(self, profile: QWebEngineProfile, main_window: 'MainWindow'):
        super().__init__()
        self.main_window = main_window
        self.setPage(QWebEnginePage(profile, self))
        self.urlChanged.connect(self._on_url_changed)
        self.titleChanged.connect(self._on_title_changed)
        self.iconChanged.connect(self._on_icon_changed)
        self.loadProgress.connect(self._on_load_progress)
        self.loadFinished.connect(self._on_load_finished)

    def createWindow(self, _type):
        return self.main_window.open_new_tab(return_view=True)

    def _on_url_changed(self, url: QUrl):
        if self is self.main_window.current_view():
            self.main_window.address_bar.setText(url.toString())
            self.main_window.update_lock_icon(url)

    def _on_title_changed(self, title: str):
        idx = self.main_window.tabs.indexOf(self)
        if idx >= 0:
            self.main_window.tabs.setTabText(idx, title if title else "New Tab")

    def _on_icon_changed(self):
        idx = self.main_window.tabs.indexOf(self)
        if idx >= 0:
            self.main_window.tabs.setTabIcon(idx, self.icon())

    def _on_load_progress(self, p: int):
        if self is self.main_window.current_view():
            self.main_window.status.showMessage(f"Loading… {p}%")

    def _on_load_finished(self, ok: bool):
        if self is self.main_window.current_view():
            self.main_window.status.showMessage("Done" if ok else "Load failed", 2000)
            if not ok:
                html = f"""
                <html><body style="font-family:system-ui;margin:40px">
                <h2>Well, that didn’t work.</h2>
                <p>Meowth couldn’t fetch <code>{self.url().toString()}</code>.</p>
                <p>Check your connection or try again.</p>
                </body></html>
                """
                self.setHtml(html, self.url())

# --- Main window with settings and bookmarks ---
class MainWindow(QMainWindow):
    def __init__(self, off_the_record: bool = False):
        super().__init__()
        self.setWindowTitle(APP_NAME + (" — Private" if off_the_record else ""))
        self.resize(1200, 780)

        # settings
        self.settings = QSettings(APP_ORG, APP_NAME)

        # Profile
        if off_the_record:
            self.profile = QWebEngineProfile.offTheRecordProfile(self)
        else:
            self.profile = QWebEngineProfile(self)

        # load user-agent from settings (or default)
        default_ua = self.profile.httpUserAgent() or ""
        saved_ua = self.settings.value("browser/user_agent", "")
        if saved_ua:
            try:
                self.profile.setHttpUserAgent(saved_ua)
            except Exception:
                pass

        # Adblock
        self.adblock_enabled = self.settings.value("adblock/enabled", True, type=bool)
        # load custom patterns if saved
        saved_patterns = self.settings.value("adblock/patterns", [])
        if saved_patterns:
            patterns = saved_patterns
        else:
            patterns = None
        self.adblock_interceptor = SimpleAdblockInterceptor(patterns=patterns, parent=self)
        try:
            self.profile.setUrlRequestInterceptor(self.adblock_interceptor)
        except Exception:
            pass  # some Qt builds might behave differently; best-effort

        # central tabs
        self.tabs = QTabWidget(movable=True, tabsClosable=True, documentMode=True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.setCentralWidget(self.tabs)

        # Find bar
        self.find_bar = FindBar(self)

        # Address toolbar
        tb = QToolBar("Navigation")
        tb.setIconSize(QSize(18, 18))
        self.addToolBar(tb)

        self.action_back = QAction("Back", self, shortcut=QKeySequence.MoveToPreviousPage, triggered=lambda: self.current_view().back() if self.current_view() else None)
        self.action_forward = QAction("Forward", self, shortcut=QKeySequence.MoveToNextPage, triggered=lambda: self.current_view().forward() if self.current_view() else None)
        self.action_reload = QAction("Reload", self, shortcut=QKeySequence.Refresh, triggered=lambda: self.current_view().reload() if self.current_view() else None)
        self.action_home = QAction("Home", self, triggered=lambda: self.load_url(HOME_URL))
        self.action_new_tab = QAction("New Tab", self, shortcut=QKeySequence.AddTab, triggered=lambda: self.open_new_tab(HOME_URL))
        self.action_close_tab = QAction("Close Tab", self, shortcut=QKeySequence.Close, triggered=lambda: self.close_tab(self.tabs.currentIndex()))
        self.action_find = QAction("Find", self, shortcut=QKeySequence.Find, triggered=self.find_bar.show_and_focus)
        self.action_private = QAction("New Private Window", self, shortcut=QKeySequence("Ctrl+Shift+N"), triggered=self.open_private_window)
        self.action_devtools = QAction("View Source", self, shortcut=QKeySequence("Ctrl+U"), triggered=self.view_source)

        for a in [self.action_back, self.action_forward, self.action_reload, self.action_home]:
            tb.addAction(a)

        self.lock_label = QLabel(" ")
        tb.addWidget(self.lock_label)

        self.address_bar = QLineEdit()
        self.address_bar.setPlaceholderText("Search or enter address")
        self.address_bar.returnPressed.connect(self.on_address_entered)
        tb.addWidget(self.address_bar)

        tb.addAction(self.action_new_tab)

        # Tools toolbar
        tb2 = QToolBar("Tools")
        tb2.setIconSize(QSize(18, 18))
        self.addToolBar(Qt.ToolBarArea.RightToolBarArea, tb2)
        tb2.addAction(self.action_find)
        tb2.addAction(self.action_private)
        tb2.addAction(self.action_devtools)

        # --- Toolbar button hover animation ---
        from PySide6.QtCore import QPropertyAnimation

        for tb in self.findChildren(QToolBar):
            for btn in tb.findChildren(QPushButton):
                anim = QPropertyAnimation(btn, b"geometry", btn)
                anim.setDuration(150)
                btn.enterEvent = lambda e, a=anim, b=btn: (
                    a.setStartValue(b.geometry()),
                    a.setEndValue(b.geometry().adjusted(-2, -2, 2, 2)),
                    a.start()
                )
                btn.leaveEvent = lambda e, a=anim, b=btn: (
                    a.setStartValue(b.geometry()),
                    a.setEndValue(b.geometry()),
                    a.start()
                )

        # Bookmarks dock
        self.bookmark_dock = QDockWidget("Bookmarks", self)
        self.bookmark_list = QListWidget()
        self.bookmark_dock.setWidget(self.bookmark_list)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.bookmark_dock)
        self.bookmark_list.itemActivated.connect(self._open_bookmark_item)

        # Bookmark context menu (right-click)
        self.bookmark_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.bookmark_list.customContextMenuRequested.connect(self._bookmark_context_menu)

        # --- Extensions system ---
        self.extensions = {}

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.addPermanentWidget(self.find_bar)

        # Download handling
        self.profile.downloadRequested.connect(self.on_download_requested)

        # Menu bar: Settings
        menubar = self.menuBar()
        settings_menu = menubar.addMenu("Settings")
        toggle_adblock = QAction("Toggle AdBlock", self, triggered=self.toggle_adblock)
        set_ua = QAction("Set User-Agent...", self, triggered=self.set_user_agent)
        add_bookmark = QAction("Add Bookmark", self, triggered=self.add_bookmark_for_current)
        show_bookmarks = QAction("Show/Hide Bookmarks", self, triggered=lambda: self.bookmark_dock.setVisible(not self.bookmark_dock.isVisible()))
        manage_extensions = QAction("Manage Extensions", self, triggered=self._show_manage_extensions)
        settings_menu.addAction(toggle_adblock)
        settings_menu.addAction(set_ua)
        settings_menu.addSeparator()
        settings_menu.addAction(add_bookmark)
        settings_menu.addAction(show_bookmarks)
        settings_menu.addSeparator()
        settings_menu.addAction(manage_extensions)

        # Restore bookmarks and session
        self._load_bookmarks()
        if not off_the_record:
            self.restore_session()

        # Load extensions
        self._load_extensions()

        if self.tabs.count() == 0:
            self.open_new_tab(HOME_URL)

        # Show adblock state in status
        self._update_adblock_status()
    # --- Extensions support ---
    def _load_extensions(self):
        """Load extensions from the ./extensions directory."""
        import os
        import json
        self.extensions = {}
        ext_dir = Path(__file__).parent / "extensions"
        ext_dir.mkdir(exist_ok=True)
        for sub in ext_dir.iterdir():
            if sub.is_dir():
                manifest_path = sub / "manifest.json"
                content_js = sub / "content.js"
                styles_css = sub / "styles.css"
                ext_name = sub.name
                manifest = {}
                if manifest_path.exists():
                    try:
                        with open(manifest_path, "r", encoding="utf-8") as f:
                            manifest = json.load(f)
                    except Exception:
                        pass
                    ext_name = manifest.get("name", ext_name)
                entry = {"manifest": manifest}
                if content_js.exists():
                    try:
                        with open(content_js, "r", encoding="utf-8") as f:
                            entry["content_js"] = f.read()
                    except Exception:
                        entry["content_js"] = ""
                if styles_css.exists():
                    try:
                        with open(styles_css, "r", encoding="utf-8") as f:
                            entry["styles_css"] = f.read()
                    except Exception:
                        entry["styles_css"] = ""
                if "content_js" in entry or "styles_css" in entry:
                    self.extensions[ext_name] = entry

    def _inject_extensions(self, view):
        """Inject loaded extensions' JS and CSS into the given BrowserView."""
        # Inject CSS
        for ext in self.extensions.values():
            css = ext.get("styles_css")
            if css:
                js = (
                    "(function(){"
                    "var style=document.createElement('style');"
                    "style.textContent=%r;"
                    "document.head.appendChild(style);"
                    "})();"
                ) % css
                view.page().runJavaScript(js)
        # Inject JS
        for ext in self.extensions.values():
            content_js = ext.get("content_js")
            if content_js:
                view.page().runJavaScript(content_js)

    def _show_manage_extensions(self):
        names = list(self.extensions.keys())
        if not names:
            msg = "No extensions loaded."
        else:
            msg = "Loaded extensions:\n" + "\n".join(names)
        QMessageBox.information(self, "Manage Extensions", msg)

        # --- StyleSheet for tab and hover effect ---
        self.setStyleSheet("""
            QTabBar::tab {
                background: #f5f5f5;
                border: 1px solid #d0d0d0;
                padding: 7px 16px 7px 16px;
                margin-right: 3px;
                border-top-left-radius: 7px;
                border-top-right-radius: 7px;
                color: #222;
            }
            QTabBar::tab:selected {
                background: #e0e0e0;
                color: #222;
            }
            QTabBar::tab:hover {
                background: #3498db;
            }
            QListWidget::item {
                transition: all 0.2s ease-in-out;
            }
            QListWidget::item:hover {
                background: #2980b9;
                color: white;
                padding-left: 10px;
            }
        """)

    # --- Bookmarks ---
    def _load_bookmarks(self):
        raw = self.settings.value("bookmarks/list", [])
        self.bookmark_list.clear()
        for entry in raw:
            # entry expected "Title|URL"
            if isinstance(entry, str) and "|" in entry:
                title, url = entry.split("|", 1)
                item = QListWidgetItem(title)
                item.setData(Qt.UserRole, url)
                self.bookmark_list.addItem(item)
            else:
                # fallback: treat as URL
                item = QListWidgetItem(entry)
                item.setData(Qt.UserRole, entry)
                self.bookmark_list.addItem(item)

    def _save_bookmarks(self):
        entries = []
        for i in range(self.bookmark_list.count()):
            item = self.bookmark_list.item(i)
            url = item.data(Qt.UserRole) or ""
            title = item.text() or url
            entries.append(f"{title}|{url}")
        self.settings.setValue("bookmarks/list", entries)

    def add_bookmark_for_current(self):
        view = self.current_view()
        if not view:
            return
        url = view.url().toString()
        title = view.title() or url
        item = QListWidgetItem(title)
        item.setData(Qt.UserRole, url)
        self.bookmark_list.addItem(item)
        self._save_bookmarks()
        self.status.showMessage("Bookmark added", 2000)

    def _open_bookmark_item(self, item: QListWidgetItem):
        url = item.data(Qt.UserRole)
        if url:
            self.open_new_tab(url)

    def _bookmark_context_menu(self, pos):
        item = self.bookmark_list.itemAt(pos)
        menu = QMenu(self)
        if item:
            remove = menu.addAction("Remove")
            open_in_new = menu.addAction("Open in new tab")
            action = menu.exec(self.bookmark_list.mapToGlobal(pos))
            if action == remove:
                self.bookmark_list.takeItem(self.bookmark_list.row(item))
                self._save_bookmarks()
            elif action == open_in_new:
                self._open_bookmark_item(item)
        else:
            # empty area
            add = menu.addAction("Add current page as bookmark")
            action = menu.exec(self.bookmark_list.mapToGlobal(pos))
            if action == add:
                self.add_bookmark_for_current()

    # --- Helpers ---
    def current_view(self) -> BrowserView:
        w = self.tabs.currentWidget()
        return w if isinstance(w, BrowserView) else None

    def load_url(self, url: str | QUrl):
        if isinstance(url, str):
            url = QUrl(url)
        if self.current_view():
            self.current_view().setUrl(url)

    def update_lock_icon(self, url: QUrl):
        scheme = url.scheme().lower()
        if scheme in ("https", "chrome"):
            self.lock_label.setText("🔒")
            self.lock_label.setToolTip("Secure connection (HTTPS)")
        elif scheme == "http":
            self.lock_label.setText("⚠️")
            self.lock_label.setToolTip("Not secure (HTTP)")
        else:
            self.lock_label.setText(" ")
            self.lock_label.setToolTip("")

    # --- UI actions ---
    def on_address_entered(self):
        url = normalize_url(self.address_bar.text())
        self.load_url(url)

    def open_new_tab(self, url: str | QUrl = HOME_URL, return_view: bool = False):
        # apply adblock interceptor only if enabled; Qt requires set once on profile, so interceptor always exists
        view = BrowserView(self.profile, self)
        idx = self.tabs.addTab(view, "New Tab")
        self.tabs.setCurrentIndex(idx)
        if isinstance(url, str):
            url = QUrl(url)
        if url.isValid():
            view.setUrl(url)
        # Inject extensions after page load
        view.loadFinished.connect(lambda ok, v=view: self._inject_extensions(v))
        if return_view:
            return view
        return idx

    def close_tab(self, index: int):
        if self.tabs.count() <= 1:
            self.open_new_tab(HOME_URL)
        widget = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if widget:
            widget.deleteLater()
        self.save_session()

    def on_tab_changed(self, index: int):
        view = self.current_view()
        if view:
            self.address_bar.setText(view.url().toString())
            self.update_lock_icon(view.url())

    def on_download_requested(self, item: QWebEngineDownloadRequest):
        suggested = Path(item.downloadFileName())
        path, _ = QFileDialog.getSaveFileName(self, "Save Download As", str(suggested))
        if path:
            item.setDownloadFileName(Path(path).name)
            item.setDownloadDirectory(str(Path(path).parent))
            item.accept()
            self.status.showMessage(f"Downloading to {path}")
        else:
            item.cancel()

    def view_source(self):
        view = self.current_view()
        if not view:
            return
        def show_html(html):
            src_win = QMessageBox(self)
            src_win.setWindowTitle("Page Source (truncated)")
            text = html if len(html) < 20000 else html[:20000] + "\n...\n[truncated]"
            src_win.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            src_win.setText(text)
            src_win.resize(800, 600)
            src_win.exec()
        view.page().toHtml(show_html)

    def open_private_window(self):
        self._spawn_window(off_the_record=True)

    def _spawn_window(self, off_the_record=False):
        w = MainWindow(off_the_record=off_the_record)
        w.show()

    # --- Adblock & UA settings ---
    def toggle_adblock(self):
        self.adblock_enabled = not self.adblock_enabled
        self.settings.setValue("adblock/enabled", self.adblock_enabled)
        # If disabled, replace interceptor with no-op patterns; if enabled restore previous patterns
        if not self.adblock_enabled:
            self.adblock_interceptor.patterns = []
        else:
            saved_patterns = self.settings.value("adblock/patterns", [])
            if saved_patterns:
                self.adblock_interceptor.patterns = saved_patterns
        self._update_adblock_status()
        self.status.showMessage(f"AdBlock {'enabled' if self.adblock_enabled else 'disabled'}", 2000)

    def _update_adblock_status(self):
        if self.adblock_enabled:
            self.status.showMessage("AdBlock: ON", 1500)
        else:
            self.status.showMessage("AdBlock: OFF", 1500)

    def set_user_agent(self):
        current = self.profile.httpUserAgent() or ""
        text, ok = QInputDialog.getText(self, "Set User-Agent", "Custom User-Agent (leave blank for default):", text=current)
        if ok:
            try:
                if text:
                    self.profile.setHttpUserAgent(text)
                    self.settings.setValue("browser/user_agent", text)
                    self.status.showMessage("Custom User-Agent saved", 2000)
                else:
                    # reset to default: clear saved and leave Qt-provided UA
                    self.settings.setValue("browser/user_agent", "")
                    # Not all Qt builds allow resetting; best-effort:
                    try:
                        self.profile.setHttpUserAgent("")
                    except Exception:
                        pass
                    self.status.showMessage("User-Agent reset to default", 2000)
            except Exception:
                self.status.showMessage("Failed to set User-Agent (Qt limitation)", 3000)

    # --- Session persistence ---
    def save_session(self):
        if self.profile.isOffTheRecord():
            return
        urls = []
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, BrowserView):
                urls.append(w.url().toString())
        self.settings.setValue("session/urls", urls)

    def restore_session(self):
        urls = self.settings.value("session/urls", [])
        if urls:
            for u in urls:
                self.open_new_tab(u)

    def closeEvent(self, e):
        self.save_session()
        self._save_bookmarks()
        # save adblock patterns
        self.settings.setValue("adblock/patterns", self.adblock_interceptor.patterns)
        super().closeEvent(e)

def main():
    QApplication.setOrganizationName(APP_ORG)
    QApplication.setApplicationName(APP_NAME)

    app = QApplication(sys.argv)
    app.setApplicationDisplayName(APP_NAME)

    win = MainWindow(off_the_record=False)
    win.show()
    sys.exit(app.exec())


# --- Create the darkmode extension if it doesn't exist ---
def _ensure_darkmode_extension():
    base_dir = Path(__file__).parent
    ext_dir = base_dir / "extensions" / "darkmode"
    ext_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = ext_dir / "manifest.json"
    styles_path = ext_dir / "styles.css"
    # Write manifest.json if not present
    if not manifest_path.exists():
        manifest_path.write_text(
            '{\n'
            '  "name": "Dark Mode",\n'
            '  "description": "Forces dark mode on all sites",\n'
            '  "version": "1.0"\n'
            '}\n',
            encoding="utf-8"
        )
    # Write styles.css if not present
    if not styles_path.exists():
        styles_path.write_text(
            "html, body {\n"
            "    background: #111 !important;\n"
            "    color: #eee !important;\n"
            "}\n"
            "img, video {\n"
            "    filter: brightness(0.8) contrast(1.2);\n"
            "}\n"
            "a {\n"
            "    color: #4aa3ff !important;\n"
            "}\n",
            encoding="utf-8"
        )


# Ensure the darkmode extension exists when running the browser
_ensure_darkmode_extension()

if __name__ == "__main__":
    main()