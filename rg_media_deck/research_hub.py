"""Live Research desk: real opt-in Telegram search, sourced AI and topic cards.

Each network operation runs in its own QThread. Web passwords or auth codes
never enter settings.json, stream logs or broadcast output. Every result has
provenance; no connected account -> no fabricated results.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import html
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QPlainTextEdit, QSplitter,
    QTabWidget, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout,
    QWidget, QHeaderView,
)

from research_connectors import (
    ai_research, credentials, filter_sort_posts, save_credentials,
    telegram_auth, telegram_search, telegram_settings_valid,
)
from topic_cards import TopicCards, recency_label
from unified_research import normalize_query


class ResearchWorker(QThread):
    done = Signal(str, str, object)
    failed = Signal(str, str, str)

    def __init__(self, kind: str, profile: Path, *, query: str = "", action: str = "",
                 code: str = "", code_hash: str = "", password: str = "",
                 days: int = 7, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.profile = Path(profile)
        self.query = query
        self.action = action
        self.code = code
        self.code_hash = code_hash
        self.password = password
        self.days = days

    def run(self):
        try:
            keys = credentials()
            if self.kind == "telegram":
                result = asyncio.run(telegram_search(
                    self.query, keys, self.profile, days=self.days))
            elif self.kind == "ai":
                result = ai_research(self.query, keys)
            elif self.kind == "telegram_auth":
                result = asyncio.run(telegram_auth(
                    self.action, keys, self.profile,
                    code=self.code, code_hash=self.code_hash,
                    password=self.password))
            else:
                raise ValueError("Unknown connector operation")
            if not self.isInterruptionRequested():
                self.done.emit(self.kind, self.query, result)
        except Exception as exc:
            if not self.isInterruptionRequested():
                # Hide API tokens and login confirmation codes from UI/logs.
                label = type(exc).__name__
                reason = str(exc).replace(self.code, "[REDACTED]") if self.code else str(exc)
                if self.password:
                    reason = reason.replace(self.password, "[REDACTED]")
                for secret in (keys.get("openai_api_key", ""),
                               keys.get("telegram_api_hash", ""),
                               keys.get("telegram_phone", "")):
                    if secret:
                        reason = reason.replace(secret, "[REDACTED]")
                reason = reason[:420]
                self.failed.emit(self.kind, self.query, f"{label}: {reason}")


class ResearchHub(QWidget):
    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.profile = self.root / "telegram_native"
        self.cards = TopicCards(self.root / "topic_cards.json")
        self.query = ""
        self.posts = []
        self.research = None
        self._pending_code_hash = ""
        self._workers = []
        self._active = set()
        self._rerun_on_finish = set()
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(5, 4, 5, 4)
        outer.setSpacing(5)
        title = QLabel("🔎 ДОСЛІДЖЕННЯ · РЕАЛЬНІ РЕЗУЛЬТАТИ")
        title.setStyleSheet("font-size:14px;font-weight:bold")
        outer.addWidget(title)
        line = QHBoxLayout()
        self.current_term = QLabel("Запит: —")
        line.addWidget(self.current_term, 1)
        self.telegram_login = QPushButton("⚙ Telegram API")
        self.telegram_login.clicked.connect(self.configure_telegram)
        line.addWidget(self.telegram_login)
        self.telegram_signin = QPushButton("Вхід Telegram")
        self.telegram_signin.clicked.connect(self.connect_telegram)
        line.addWidget(self.telegram_signin)
        self.ai_setup = QPushButton("⚙ OpenAI API")
        self.ai_setup.clicked.connect(self.configure_ai)
        line.addWidget(self.ai_setup)
        outer.addLayout(line)
        self.status = QLabel(
            "Введіть запит у пошук угорі. Для live-результатів потрібна "
            "окрема авторизація Telegram API / OpenAI API.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#d1bd87;font-size:11px")
        outer.addWidget(self.status)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        telegram_page = QWidget()
        tg_box = QVBoxLayout(telegram_page)
        controls = QHBoxLayout()
        self.days = QComboBox()
        self.days.addItem("24 години", 1)
        self.days.addItem("7 днів", 7)
        self.days.addItem("30 днів", 30)
        self.days.addItem("За весь час", 0)
        self.days.setCurrentIndex(1)
        controls.addWidget(self.days)
        self.sorting = QComboBox()
        self.sorting.addItem("Спочатку нові", "newest")
        self.sorting.addItem("Спочатку старі", "oldest")
        self.sorting.addItem("За каналом", "channel")
        controls.addWidget(self.sorting)
        self.media_only = QCheckBox("Фото / відео")
        controls.addWidget(self.media_only)
        self.telegram_refresh = QPushButton("🔄 Шукати Telegram")
        self.telegram_refresh.clicked.connect(self.search_telegram)
        controls.addWidget(self.telegram_refresh)
        tg_box.addLayout(controls)
        self.tg_table = QTableWidget(0, 4)
        self.tg_table.setHorizontalHeaderLabels(["Дата", "Канал", "Медіа", "Публікація"])
        self.tg_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tg_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tg_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch)
        self.tg_table.doubleClicked.connect(self.open_telegram_selected)
        tg_box.addWidget(self.tg_table, 1)
        self.post_view = QPlainTextEdit()
        self.post_view.setReadOnly(True)
        self.post_view.setMaximumHeight(100)
        tg_box.addWidget(self.post_view)
        self.tg_table.itemSelectionChanged.connect(self.show_telegram_selected)
        self.open_source = QPushButton("↗ Відкрити джерело в Telegram")
        self.open_source.clicked.connect(self.open_telegram_selected)
        tg_box.addWidget(self.open_source)
        self.telegram_label = QLabel("Telegram API: не підключено")
        tg_box.addWidget(self.telegram_label)
        self.tabs.addTab(telegram_page, "✈ TELEGRAM")

        ai_page = QWidget()
        ai_layout = QVBoxLayout(ai_page)
        ai_buttons = QHBoxLayout()
        self.ai_refresh = QPushButton("✨ Отримати AI-справку з веб-джерелами")
        self.ai_refresh.clicked.connect(self.search_ai)
        ai_buttons.addWidget(self.ai_refresh)
        self.ai_date = QLabel("Немає перевіреної довідки")
        ai_buttons.addWidget(self.ai_date, 1)
        ai_layout.addLayout(ai_buttons)
        self.ai_text = QTextBrowser()
        self.ai_text.setOpenExternalLinks(True)
        ai_layout.addWidget(self.ai_text)
        self.ai_label = QLabel(
            "OpenAI Responses API з web_search. Потрібен окремий ключ; "
            "запит може тарифікуватися.")
        self.ai_label.setWordWrap(True)
        ai_layout.addWidget(self.ai_label)
        self.tabs.addTab(ai_page, "✦ AI-АНАЛІТИК")

        card_page = QWidget()
        card_layout = QVBoxLayout(card_page)
        self.card_header = QLabel("Введіть назву міста або тему")
        self.card_header.setWordWrap(True)
        card_layout.addWidget(self.card_header)
        card_layout.addWidget(QLabel("Власні нотатки (залишаються тільки на цьому ПК):"))
        self.card_notes = QPlainTextEdit()
        card_layout.addWidget(self.card_notes, 1)
        row = QHBoxLayout()
        self.save_card = QPushButton("💾 Зберегти картку")
        self.save_card.clicked.connect(self.save_current_card)
        row.addWidget(self.save_card)
        self.refresh_card = QPushButton("↻ Відкрити збережені дані")
        self.refresh_card.clicked.connect(self.load_current_card)
        row.addWidget(self.refresh_card)
        card_layout.addLayout(row)
        self.card_sources = QPlainTextEdit()
        self.card_sources.setReadOnly(True)
        self.card_sources.setMaximumHeight(140)
        card_layout.addWidget(self.card_sources)
        self.tabs.addTab(card_page, "📚 КАРТКА МІСТА")

        for widget in (self.sorting, self.media_only):
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self.update_post_display)
            else:
                widget.toggled.connect(self.update_post_display)
        self.days.currentIndexChanged.connect(self.update_post_display)

    def set_query(self, raw: str):
        term = normalize_query(raw)
        if not term:
            return
        if term != self.query:
            self.query = term
            self.current_term.setText(f"Запит: {term}")
            self.posts = []
            self.research = None
            self.update_post_display()
            self.load_current_card()

    def search_all(self, query: str, media_paths: list[str] | None = None):
        self.set_query(query)
        if media_paths is not None:
            self.cards.put(self.query, media=media_paths)
        keys = self._read_credentials()
        if telegram_settings_valid(keys):
            self.search_telegram()
        else:
            self.telegram_label.setText(
                "Telegram API не підключено. Налаштуйте API ID/Hash і виконайте вхід.")
        if keys.get("openai_api_key", "").startswith("sk-"):
            self.search_ai()
        else:
            self.ai_label.setText(
                "OpenAI API не підключено — відкрийте ⚙ OpenAI API. "
                "Підписка на ChatGPT не є ключем API.")
        self.status.setText(
            f"Локальний пошук завершено: «{self.query}». "
            "Telegram/AI запускаються лише за наявності окремих підключень.")

    def _read_credentials(self):
        try:
            return credentials()
        except Exception as exc:
            self.status.setText(f"Сховище Windows недоступне: {type(exc).__name__}")
            return {}

    def _start(self, worker: ResearchWorker):
        if worker.kind in self._active:
            if worker.kind in ("telegram", "ai"):
                self._rerun_on_finish.add(worker.kind)
                self.status.setText(
                    "Новий запит поставлено після завершення поточного; "
                    "застарілий результат не буде показано.")
            else:
                self.status.setText(f"Операція {worker.kind} уже виконується.")
            return
        self._active.add(worker.kind)
        self._workers.append(worker)
        worker.done.connect(self._worker_done)
        worker.failed.connect(self._worker_failed)
        worker.finished.connect(lambda w=worker: self._worker_finished(w))
        worker.start()

    def _worker_finished(self, worker):
        self._active.discard(worker.kind)
        if worker in self._workers:
            self._workers.remove(worker)
        worker.deleteLater()
        if worker.kind in self._rerun_on_finish:
            self._rerun_on_finish.discard(worker.kind)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(75,
                self.search_telegram if worker.kind == "telegram" else self.search_ai)

    def _worker_failed(self, kind: str, query: str, reason: str):
        self._active.discard(kind)
        if kind in ("telegram", "ai") and query != self.query:
            self._rerun_on_finish.add(kind)
            return
        if kind == "telegram":
            self.telegram_label.setText("Помилка Telegram: " + reason)
        elif kind == "ai":
            self.ai_label.setText("Помилка OpenAI: " + reason)
        else:
            self.status.setText("Telegram авторизація: " + reason)

    def _worker_done(self, kind: str, query: str, result):
        self._active.discard(kind)
        if kind in ("telegram", "ai") and query != self.query:
            self._rerun_on_finish.add(kind)
            return
        if kind == "telegram_auth":
            status = result.get("status")
            if status == "code_sent":
                self._pending_code_hash = result.get("code_hash", "")
                code, ok = QInputDialog.getText(
                    self, "Код Telegram", "Введіть код із Telegram:",
                    QLineEdit.EchoMode.Password)
                if ok and code.strip():
                    self._start(ResearchWorker(
                        "telegram_auth", self.profile, action="confirm",
                        code=code.strip(), code_hash=self._pending_code_hash))
            elif status == "password_required":
                password, ok = QInputDialog.getText(
                    self, "Telegram 2FA",
                    "Введіть пароль двофакторної автентифікації:",
                    QLineEdit.EchoMode.Password)
                if ok and password:
                    self._start(ResearchWorker(
                        "telegram_auth", self.profile,
                        action="password", password=password))
            elif status == "authorized":
                self.telegram_label.setText("Telegram API: авторизовано ✓")
                self.status.setText("Telegram підключено. Можна шукати повідомлення.")
            else:
                self.status.setText("Сесія Telegram API не авторизована.")
        elif kind == "telegram":
            self.posts = list(result)
            self.update_post_display()
            self.cards.put(self.query, posts=self.posts)
            self.telegram_label.setText(
                f"Telegram: отримано {len(self.posts)} публікацій з доступних чатів; "
                "кожен запис має дату/канал, факти НЕ перевірені.")
        elif kind == "ai":
            self.research = dict(result)
            self.show_ai(result)
            self.cards.put(self.query, ai=result)
            self.ai_label.setText("AI-справка отримана через OpenAI API. "
                                  "Джерела перевіряйте перед ефіром.")

    def configure_telegram(self):
        keys = self._read_credentials()
        api_id, ok = QInputDialog.getInt(
            self, "Telegram API", "API ID із my.telegram.org:",
            int(keys.get("telegram_api_id", "") or 0),
            min=1, max=2147483647)
        if not ok:
            return
        api_hash, ok = QInputDialog.getText(
            self, "Telegram API", "API Hash (32 hex, не публікуйте його):",
            QLineEdit.EchoMode.Password)
        if not ok:
            return
        phone, ok = QInputDialog.getText(
            self, "Telegram API", "Номер телефону (+380...):",
            QLineEdit.EchoMode.Normal, keys.get("telegram_phone", ""))
        if not ok:
            return
        record = dict(telegram_api_id=str(api_id),
                      telegram_api_hash=api_hash.strip(),
                      telegram_phone=phone.strip())
        if not telegram_settings_valid(record):
            QMessageBox.warning(self, "Telegram API",
                                "Невірний API Hash або номер телефону.")
            return
        try:
            save_credentials(**record)
            self.status.setText(
                "Telegram API реквізити захищено в Windows Credential Manager. "
                "Тепер натисніть «Вхід Telegram».")
        except Exception as exc:
            QMessageBox.warning(self, "Windows Credential Manager",
                                type(exc).__name__)

    def configure_ai(self):
        key, ok = QInputDialog.getText(
            self, "OpenAI API", "Введіть OpenAI API key (не ChatGPT-підписка):",
            QLineEdit.EchoMode.Password)
        if not ok:
            return
        key = key.strip()
        if not key.startswith("sk-") or len(key) < 18:
            QMessageBox.warning(self, "OpenAI API", "Недійсний формат API ключа.")
            return
        try:
            save_credentials(openai_api_key=key)
            self.status.setText(
                "API ключ захищено в Windows Credential Manager. "
                "AI-запити можуть бути платними.")
        except Exception as exc:
            QMessageBox.warning(self, "Windows Credential Manager",
                                type(exc).__name__)

    def connect_telegram(self):
        if not telegram_settings_valid(self._read_credentials()):
            QMessageBox.information(self, "Telegram API",
                "Налаштуйте Telegram API ID, API Hash та номер телефону. "
                "Вхід у Telegram Web не дає доступу до Telegram API.")
            return
        self._start(ResearchWorker(
            "telegram_auth", self.profile, action="request"))
        self.telegram_label.setText("Telegram API: запит авторизації…")

    def search_telegram(self):
        if not self.query:
            return
        if not telegram_settings_valid(self._read_credentials()):
            self.telegram_label.setText("Спочатку налаштуйте Telegram API.")
            return
        self._start(ResearchWorker(
            "telegram", self.profile, query=self.query,
            days=0, parent=self))
        self.telegram_label.setText("Telegram: шукаю реальні повідомлення…")

    def search_ai(self):
        if not self.query:
            return
        if not self._read_credentials().get("openai_api_key", "").startswith("sk-"):
            self.ai_label.setText("Спочатку підключіть окремий OpenAI API ключ.")
            return
        self._start(ResearchWorker("ai", self.profile,
                                   query=self.query, parent=self))
        self.ai_label.setText("OpenAI API: веб-пошук джерел у фоні…")

    def update_post_display(self, *_):
        days = self.days.currentData()
        ordered = filter_sort_posts(self.posts, days=days,
                                    media_only=self.media_only.isChecked(),
                                    sort=self.sorting.currentData())
        self._visible_posts = ordered
        self.tg_table.setRowCount(len(ordered))
        for row, post in enumerate(ordered):
            for column, value in enumerate((
                str(post["date"])[:16].replace("T", " "),
                post["chat"], post["kind"] or "текст",
                post["text"].replace("\n", " ")[:170])):
                self.tg_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.telegram_label.setText(
            f"Telegram: {len(ordered)} із {len(self.posts)} • "
            "джерела за датою; достовірність змісту не підтверджена")

    def selected_post(self):
        row = self.tg_table.currentRow()
        return self._visible_posts[row] if 0 <= row < len(self._visible_posts) else None

    def show_telegram_selected(self):
        post = self.selected_post()
        self.post_view.setPlainText(post["text"] if post else "")

    def open_telegram_selected(self, *_):
        post = self.selected_post()
        if post and post.get("url"):
            QDesktopServices.openUrl(QUrl(post["url"]))
        else:
            self.status.setText("Приватна публікація: публічного посилання немає.")

    def show_ai(self, response: dict):
        text = str(response.get("text", ""))
        blocks = ['<pre style="white-space:pre-wrap">' +
                  html.escape(text) + '</pre>']
        sources = response.get("sources", [])
        if sources:
            blocks.append("<h4>Джерела для перевірки:</h4><ol>")
            for source in sources:
                url = html.escape(source["url"], quote=True)
                title = html.escape(source["title"] or source["url"])
                blocks.append(f'<li><a href="{url}">{title}</a></li>')
            blocks.append("</ol>")
        else:
            blocks.append(
                "<p style='color:orange'>Підтверджених посилань не знайдено. "
                "Не використовуйте неперевірені цифри в ефірі.</p>")
        self.ai_text.setHtml("\n".join(blocks))
        self.ai_date.setText("AI: " + str(response.get("date", ""))[:16])

    def load_current_card(self):
        if not self.query:
            return
        card = self.cards.get(self.query)
        self.card_notes.setPlainText(card.get("notes", ""))
        self.card_header.setText(
            f"КАРТКА: {card['topic']} • {recency_label(card)}")
        ai = card.get("ai")
        if ai and self.research is None:
            self.show_ai(ai)
            self.ai_label.setText(
                "ПОКАЗАНО КЕШ. Дата та джерела можуть бути застарілими.")
        links = (ai or {}).get("sources", [])
        self.card_sources.setPlainText("\n".join(
            f"{entry.get('title', '')}: {entry.get('url', '')}"
            for entry in links[:100]))
        if card.get("posts") and not self.posts:
            self.posts = card["posts"]
            self.update_post_display()
            self.telegram_label.setText("ПОКАЗАНО ЗБЕРЕЖЕНІ ПОСТИ. "
                                        "Для свіжих — виконайте новий пошук.")

    def save_current_card(self):
        if not self.query:
            self.status.setText("Спочатку введіть тему або місто.")
            return
        self.cards.put(self.query, notes=self.card_notes.toPlainText())
        self.status.setText(f"Картку «{self.query}» збережено локально.")
        self.load_current_card()

    def can_close(self) -> bool:
        return not any(w.isRunning() for w in self._workers)

    def cancel_workers(self):
        for worker in self._workers:
            worker.requestInterruption()
