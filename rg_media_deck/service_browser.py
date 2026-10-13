"""On-demand, isolated sign-in browsers for Telegram Web and ChatGPT.

Uses the sites' genuine HTTPS pages, not a fake login. Accounts are kept in
separate QtWebEngine profiles and their session state is handled by Chromium,
outside RG Media Deck settings.json. No cookie extraction, password logging or
secret interception. A service may reject QtWebEngine/OAuth; always offer the
user's system browser as a fallback.

DOM assisted search is best-effort: Telegram/ChatGPT can change their UIs.
Never claim that a server accepted a search when a DOM lookup failed.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit,
                              QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)
from unified_research import (CHATGPT_URL, TELEGRAM_URL, normalize_query,
                              research_prompt, telegram_search_hint)


# Chords are never synthesized while Qt global mini keyboard shortcuts are
# active. Only named search elements are touched; login/password inputs are
# explicitly excluded, and no cookies or auth data are read.
_TELEGRAM_SEARCH_JS = """
(() => {
  const term = __TERM__;
  const elems = Array.from(document.querySelectorAll(
       'input:not([type=password]):not([type=tel]), [contenteditable=true]'));
  const found = elems.find(el => {
    if (el.type === 'password' || el.type === 'tel') return false;
    const label = [el.getAttribute('placeholder'), el.getAttribute('aria-label'),
      el.getAttribute('data-placeholder'), el.id, el.className]
      .filter(x => typeof x === 'string').join(' ').toLowerCase();
    return /search|поиск|пошук|search-input|input-search/.test(label);
  });
  if (!found) return false;
  found.focus();
  if (found.tagName === 'INPUT') {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value').set;
    setter.call(found, term);
    found.dispatchEvent(new Event('input', {bubbles: true}));
    found.dispatchEvent(new Event('change', {bubbles: true}));
  } else {
    found.textContent = term;
    found.dispatchEvent(new InputEvent('input',
      {inputType:'insertText',data:term,bubbles:true}));
  }
  found.dispatchEvent(new KeyboardEvent('keydown',
     {key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}));
  return true;
})()
"""

_CHATGPT_PREPARE_JS = """
(() => {
  const prompt = __PROMPT__;
  const editor = document.querySelector(
    '[contenteditable=true][data-placeholder], #prompt-textarea[contenteditable], .ProseMirror[contenteditable]');
  if (!editor || editor.closest('[type=password]')) return false;
  editor.focus();
  if (document.execCommand) {
    document.execCommand('selectAll', false, null);
    if (document.execCommand('insertText', false, prompt)) {
      editor.dispatchEvent(new Event('input', {bubbles:true}));
      return true;
    }
  }
  editor.textContent = prompt;
  editor.dispatchEvent(new InputEvent('input',
    {inputType:'insertText', data:prompt, bubbles:true}));
  return true;
})()
"""


_CHATGPT_SEND_JS = """
(() => {
  // No fake login. Only a real composer on chatgpt.com may be submitted.
  if (!['chatgpt.com','chat.openai.com'].includes(location.hostname))
    return {attempted:false, reason:'origin'};
  const composer = document.querySelector(
    '#prompt-textarea, .ProseMirror[contenteditable=true], [contenteditable=true][data-placeholder]');
  if (!composer || composer.closest('form')?.querySelector(
      'input[type=password],input[autocomplete=current-password]'))
    return {attempted:false, reason:'login_or_missing_editor'};
  const form = composer.closest('form');
  const buttons = [...document.querySelectorAll('button')];
  const send = buttons.find(el => {
      const tag = [el.getAttribute('data-testid'), el.getAttribute('aria-label'),
           el.getAttribute('title')].join(' ').toLowerCase();
      return /send-button|send-prompt|send message|send prompt|отправить|надіслати/.test(tag)
        && !el.disabled;
  }) || (form && [...form.querySelectorAll('button[type=submit]')]
                   .find(el => !el.disabled));
  if (!send || send.disabled) return {attempted:false,reason:'button_unavailable'};
  send.click();
  return {attempted:true,reason:'clicked_send'};
})()
"""


class ServiceBrowser(QWidget):
    """Web interface is created lazily to protect running OBS playback."""

    def __init__(self, service: str, profile_root: Path, parent=None):
        super().__init__(parent)
        if service not in ("telegram", "chatgpt"):
            raise ValueError("Unknown web service")
        self.service = service
        self.url = TELEGRAM_URL if service == "telegram" else CHATGPT_URL
        self.profile_root = Path(profile_root)
        self._view = None
        self._profile = None
        self._pending_query = ""
        self._loaded = False
        self._search_result = None
        self._auto_send_pending = False
        self._auto_send_attempted_query = ""
        self._auto_send_last_result = None
        self._auto_send_inflight = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(5, 4, 5, 4)
        lay.setSpacing(6)
        header = QHBoxLayout()
        self.title = QLabel("TELEGRAM" if service == "telegram" else "CHATGPT")
        self.title.setStyleSheet("font-weight:bold")
        header.addWidget(self.title)
        self.address = QLineEdit(self.url)
        self.address.setReadOnly(True)
        self.address.setToolTip("Справжня адреса сайту — перевірте її перед входом")
        header.addWidget(self.address, 1)
        self.reload_button = QPushButton("↻")
        self.reload_button.clicked.connect(self.reload)
        header.addWidget(self.reload_button)
        self.external_button = QPushButton("↗ У браузері")
        self.external_button.setToolTip("Відкрити справжній сайт у стандартному браузері")
        self.external_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.url)))
        header.addWidget(self.external_button)
        lay.addLayout(header)
        self.status = QLabel(
            "Вхід у свій акаунт — у вікні офіційного сайту. "
            "Для безпеки не вводьте пароль у неофіційних формах.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#bbc0c9;font-size:11px")
        lay.addWidget(self.status)
        tools = QHBoxLayout()
        self.send_button = QPushButton(
            "🔎 Шукати у Telegram" if service == "telegram"
            else "📋 Підготувати запит у ChatGPT")
        self.send_button.clicked.connect(self.search_active)
        tools.addWidget(self.send_button)
        self.copy_button = QPushButton("Скопіювати запит")
        self.copy_button.clicked.connect(self.copy_query)
        tools.addWidget(self.copy_button)
        tools.addStretch(1)
        lay.addLayout(tools)
        self.prompt_box = QPlainTextEdit()
        self.prompt_box.setReadOnly(True)
        self.prompt_box.setMaximumHeight(122)
        self.prompt_box.setPlaceholderText(
            "Спільний пошук зверху підготує запит тут.")
        lay.addWidget(self.prompt_box)
        if service == "telegram":
            self.prompt_box.setMaximumHeight(70)
        self.browser_host = QVBoxLayout()
        self.browser_placeholder = QLabel(
            "Натисніть вкладку, щоб завантажити офіційний сайт.\n"
            "Сесія входу зберігається тільки у браузерному профілі на цьому ПК.")
        self.browser_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.browser_placeholder.setWordWrap(True)
        self.browser_host.addWidget(self.browser_placeholder, 1)
        lay.addLayout(self.browser_host, 1)

    @property
    def active(self):
        return self._view is not None

    def ensure_loaded(self) -> bool:
        if self._view is not None:
            return True
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        except (ImportError, RuntimeError, OSError) as exc:
            self.status.setText(
                "Вбудований браузер недоступний у цьому пакеті. "
                "Натисніть «У браузері». " + str(exc)[:180])
            return False
        try:
            profile_path = self.profile_root / self.service
            profile_path.mkdir(parents=True, exist_ok=True)
            profile = QWebEngineProfile(f"rg_media_{self.service}", self)
            profile.setPersistentStoragePath(str(profile_path / "storage"))
            profile.setCachePath(str(profile_path / "cache"))
            profile.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
            view = QWebEngineView(self)
            page = QWebEnginePage(profile, view)
            view.setPage(page)
            page.setAudioMuted(True)  # avoid Telegram/ChatGPT sound leaking into OBS
            view.urlChanged.connect(lambda url: self.address.setText(url.toString()))
            view.loadFinished.connect(self._on_loaded)
            self._profile = profile
            self._view = view
            self.browser_placeholder.hide()
            self.browser_host.addWidget(view, 1)
            view.load(QUrl(self.url))
            self.status.setText("Завантаження офіційного сайту…")
            return True
        except (OSError, RuntimeError, ValueError) as exc:
            self.status.setText(
                "Не вдалося відкрити вбудований сайт. "
                "Скористайтеся кнопкою «У браузері»: " + str(exc)[:180])
            return False

    def _on_loaded(self, ok):
        self._loaded = bool(ok)
        self.status.setText(
            "Сайт відкрито. Увійдіть самостійно, якщо потрібно. "
            "Пошук на сайті може потребувати ручного підтвердження."
            if ok else
            "Не вдалося завантажити сайт. Перевірте інтернет або відкрийте "
            "у стандартному браузері.")
        # Auto-send is an EXPLICIT user command from global Search, never
        # triggered by ordinary browsing or reloading the login page.
        if ok and self._pending_query:
            self._display_query(self._pending_query)
            from PySide6.QtCore import QTimer
            if self.service == 'chatgpt' and self._auto_send_pending:
                QTimer.singleShot(600, self._try_auto_send)
            elif self.service == 'telegram':
                QTimer.singleShot(700, self.search_active)

    def set_query(self, text: str):
        changed = normalize_query(text) != self._pending_query
        self._pending_query = normalize_query(text)
        if changed:
            self._auto_send_pending = False
            self._auto_send_last_result = None
        self._display_query(self._pending_query)

    def request_auto_submit(self):
        """User pressed common SEARCH: send ChatGPT prompt once if logged in.

        Login screen and unexpected domains are never submitted.
        The genuine website shows the response in this very widget.
        """
        if self.service != 'chatgpt' or not self._pending_query:
            return
        if self._auto_send_pending:
            return
        # Explicit new Search is allowed to repeat the same city later.
        # Navigation/reload alone never creates another submission.
        self._auto_send_attempted_query = ""
        self._auto_send_inflight = False
        self._auto_send_pending = True
        if not self.ensure_loaded():
            return
        if self._loaded:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(350, self._try_auto_send)

    def _try_auto_send(self):
        if (not self._auto_send_pending or not self._loaded
                or self._auto_send_inflight
                or self._auto_send_attempted_query == self._pending_query
                or self._view is None):
            return
        page = self._view.page()
        if page.url().host().casefold() not in ('chatgpt.com', 'chat.openai.com'):
            self.status.setText(
                'Не можна надсилати запит: це не офіційна адреса ChatGPT.')
            return
        self._auto_send_inflight = True
        prompt = research_prompt(self._pending_query)
        script = _CHATGPT_PREPARE_JS.replace(
            '__PROMPT__', json.dumps(prompt, ensure_ascii=False))
        query = self._pending_query
        page.runJavaScript(script,
            lambda ready, term=query: self._after_auto_prepare(term, ready))

    def _after_auto_prepare(self, term: str, ready):
        if not ready or term != self._pending_query or not self._auto_send_pending:
            self._auto_send_inflight = False
            self.status.setText(
                'ChatGPT: редактор недоступний. Увійдіть у свій акаунт '
                'або скористайтеся «Скопіювати запит».')
            return
        from PySide6.QtCore import QTimer
        QTimer.singleShot(550,
            lambda query=term: self._click_chatgpt_send(query))

    def _click_chatgpt_send(self, query: str):
        if not self._view or query != self._pending_query or not self._auto_send_pending:
            return
        self._view.page().runJavaScript(_CHATGPT_SEND_JS,
            lambda result, term=query: self._after_chatgpt_send(term, result))

    def _after_chatgpt_send(self, query: str, outcome):
        if query != self._pending_query:
            return
        attempted = isinstance(outcome, dict) and outcome.get('attempted') is True
        self._auto_send_last_result = outcome
        self._auto_send_inflight = False
        if attempted:
            # Never resend on navigation/reload: one request per user query.
            self._auto_send_attempted_query = query
            self._auto_send_pending = False
            self.status.setText(
                'ChatGPT: натиснуто «Надіслати». Чекайте відповідь '
                'прямо тут, у вікні попереднього перегляду.')
        else:
            reason = (outcome or {}).get('reason', 'unknown') if isinstance(outcome, dict) else 'unknown'
            self.status.setText(
                'ChatGPT не підтвердив надсилання (' + str(reason) +
                '). Перевірте вхід; можна скопіювати запит і надіслати вручну.')


    def _display_query(self, term: str):
        if self.service == "telegram":
            self.prompt_box.setPlainText(telegram_search_hint(term))
        else:
            self.prompt_box.setPlainText(research_prompt(term))

    def search_active(self):
        """User presses Search: at most fills supported page's existing form."""
        if not self._pending_query:
            self.status.setText("Спочатку введіть запит у спільний пошук зверху.")
            return
        if not self.ensure_loaded():
            return
        if not self._loaded:
            self.status.setText("Зачекайте завантаження і входу на сайт.")
            return
        query = self._pending_query if self.service == "telegram" else research_prompt(self._pending_query)
        js = _TELEGRAM_SEARCH_JS if self.service == "telegram" else _CHATGPT_PREPARE_JS
        js = js.replace("__TERM__", json.dumps(query, ensure_ascii=False))
        js = js.replace("__PROMPT__", json.dumps(query, ensure_ascii=False))
        self._view.page().runJavaScript(js, self._on_search_attempt)

    def _on_search_attempt(self, prepared):
        self._search_result = bool(prepared)
        if prepared and self.service == "telegram":
            self.status.setText(
                "Пошукове поле Telegram заповнено. Перевірте результати і, "
                "якщо потрібно, натисніть Enter. Показуються лише доступні чати/канали.")
        elif prepared:
            self.status.setText(
                "Запит підготовлено у редакторі ChatGPT. Перевірте й натисніть "
                "Надіслати — відповідь надає сам ChatGPT, не RG Media Deck.")
        else:
            self.status.setText(
                "Пошукове поле не знайдено (можливо, потрібен вхід або сайт "
                "оновив інтерфейс). Скопіюйте запит і вставте його вручну.")

    def copy_query(self):
        from PySide6.QtWidgets import QApplication
        content = (self._pending_query if self.service == "telegram"
                   else research_prompt(self._pending_query))
        if content:
            QApplication.clipboard().setText(content)
            self.status.setText("Запит скопійовано. Вставте його на офіційному сайті.")

    def reload(self):
        if self.ensure_loaded():
            self._loaded = False
            self._view.reload()

    def set_active(self, active: bool):
        """Freeze inactive embedded sites to protect Qt video/OBS resources."""
        if self._view is None:
            return
        try:
            from PySide6.QtWebEngineCore import QWebEnginePage
            page = self._view.page()
            page.setAudioMuted(True)
            page.setLifecycleState(
                QWebEnginePage.LifecycleState.Active
                if active else QWebEnginePage.LifecycleState.Frozen)
        except (RuntimeError, AttributeError, ValueError):
            # Browser lifecycle is advisory; never break the live player.
            pass

    def shutdown(self):
        if self._view:
            self._view.stop()
            self._view.deleteLater()
            self._view = None
        self._profile = None
