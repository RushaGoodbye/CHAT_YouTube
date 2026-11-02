from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QMessageBox, QPushButton

from .comment_action_ai import review_comment_actions_local
from .comment_action_runtime import prepare_action_reply_drafts, preview_safe_auto_replies, propose_diverse_safe_replies, generate_personal_reply_preview
from .db import comment_action_counts, get_setting, reclassify_comment_actions, set_setting, save_comment_draft
from .style import MUTED, SUCCESS, WARNING, YOUTUBE_RED


class _PersonalReplyWorker(QThread):
    completed = Signal(dict)

    def __init__(self, comment_text: str, parent=None):
        super().__init__(parent)
        self.comment_text = comment_text

    def run(self):
        try:
            result = generate_personal_reply_preview(self.comment_text)
        except Exception:
            result = {"status": "LOCAL_MODEL_UNAVAILABLE", "reply": ""}
        self.completed.emit(result)


class _BatchPersonalRepliesWorker(QThread):
    progress = Signal(int, int)
    completed = Signal(list)

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.rows = rows

    def run(self):
        results = []
        for index, (comment_id, comment_text) in enumerate(self.rows, 1):
            try:
                result = generate_personal_reply_preview(comment_text)
            except Exception:
                result = {"status": "LOCAL_MODEL_UNAVAILABLE", "reply": ""}
            results.append((comment_id, result))
            self.progress.emit(index, len(self.rows))
        self.completed.emit(results)


ACTION_LABELS = {
    "reply": "ВІДПОВІСТИ",
    "like": "ЛАЙК",
    "review": "REVIEW",
    "skip": "SKIP",
    "": "",
}

CATEGORY_LABELS = {
    "patriotic_support": "патріотична підтримка",
    "reaction_or_humor": "реакція / гумор",
    "question": "питання",
    "substantive_comment": "змістовний коментар",
    "duplicate": "дубль",
    "toxic_or_risky": "токсичний / ризиковий",
    "spam": "спам",
    "moderation_locked": "модерація YouTube",
    "empty": "порожній",
    "replied": "вже відповіли",
    "ignored": "проігноровано",
}

ACTION_COLORS = {
    "reply": SUCCESS,
    "like": "#4da3ff",
    "review": WARNING,
    "skip": MUTED,
}


def install_comment_action_ui(window) -> None:
    if getattr(window, "_comment_action_ui_installed", False):
        return
    if not hasattr(window, "comment_table") or not hasattr(window, "tabs"):
        return

    window._comment_action_ui_installed = True
    table = window.comment_table

    if table.columnCount() < 9:
        table.insertColumn(table.columnCount())
    action_column = table.columnCount() - 1
    table.setHorizontalHeaderItem(action_column, _item("Рішення"))
    table.setColumnWidth(action_column, 120)

    bar = QHBoxLayout()
    bar.addWidget(QLabel("Рішення:"))

    action_filter = QComboBox()
    action_filter.addItem("Усі", "")
    action_filter.addItem("ВІДПОВІСТИ", "reply")
    action_filter.addItem("ЛАЙК", "like")
    action_filter.addItem("REVIEW", "review")
    action_filter.addItem("SKIP", "skip")
    bar.addWidget(action_filter)

    summary = QLabel("")
    summary.setProperty("role", "success")
    bar.addWidget(summary)
    prepare_replies = QPushButton("Підготувати ВІДПОВІДІ x20 · 0 квоти")
    prepare_replies.setProperty("role", "success")
    bar.addWidget(prepare_replies)

    preview_replies = QPushButton("Перевірити автовідповіді · без публікації")
    bar.addWidget(preview_replies)

    diverse_preview = QPushButton("Варіанти відповідей · без публікації")
    bar.addWidget(diverse_preview)

    personalized = QPushButton("AI відповідь на вибраний · LM Studio")
    bar.addWidget(personalized)

    batch_personalized = QPushButton("AI чернетки x20 · LM Studio")
    bar.addWidget(batch_personalized)

    ai_review = QPushButton("AI REVIEW x20 · 0 квоти")
    bar.addWidget(ai_review)

    auto_replies = QCheckBox("Автовідповіді: лише короткі подяки / вітання")
    def sync_auto_replies():
        key = f"comment_auto_reply_enabled_{window.current_profile}"
        auto_replies.blockSignals(True)
        auto_replies.setChecked(get_setting(window.conn, key, "0") == "1")
        auto_replies.blockSignals(False)

    def toggle_auto_replies(checked):
        if checked:
            choice = QMessageBox.question(
                window, "Увімкнути автовідповіді?",
                "Це дозволяє автоматично публікувати короткі відповіді на "
                "однозначні подяки та привітання під час сканування. "
                "Питання, донати, політика і спірні коментарі лишаться на перевірці. "
                "Увімкнути для поточного каналу?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                sync_auto_replies()
                return
        set_setting(window.conn, f"comment_auto_reply_enabled_{window.current_profile}",
                    "1" if checked else "0")
        set_setting(window.conn, f"auto_reply_enabled_{window.current_profile}",
                    "1" if checked else "0")
        if hasattr(window, "auto_box"):
            window.auto_box.blockSignals(True)
            window.auto_box.setChecked(bool(checked))
            window.auto_box.blockSignals(False)
        sync_auto_replies()

    auto_replies.toggled.connect(toggle_auto_replies)
    sync_auto_replies()
    bar.addWidget(auto_replies)

    recalc = QPushButton("Перерахувати рішення · 0 квоти")
    bar.addWidget(recalc)

    comments_page = window.tabs.widget(3)
    comments_layout = comments_page.layout()

    for button in comments_page.findChildren(QPushButton):
        if button.text().startswith("Створити x20") or button.text().startswith("Перегенерувати x20"):
            button.setVisible(False)

    comments_layout.insertLayout(0, bar)

    original_reload = window.reload_comments

    def decorate_table() -> None:
        if table.columnCount() < 9:
            table.insertColumn(table.columnCount())
        col = table.columnCount() - 1
        table.setHorizontalHeaderItem(col, _item("Рішення"))
        table.setColumnWidth(col, 120)

        ids = []
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            comment_id = item.data(Qt.ItemDataRole.UserRole) if item else None
            if comment_id:
                ids.append(str(comment_id))

        action_map = {}
        reason_map = {}
        category_map = {}
        if ids:
            placeholders = ",".join("?" for _ in ids)
            rows = window.conn.execute(
                f"""SELECT comment_id,action,action_reason
                    ,category
                    FROM comments
                    WHERE comment_id IN ({placeholders})""",
                tuple(ids),
            ).fetchall()
            for db_row in rows:
                cid = str(db_row["comment_id"])
                action_map[cid] = str(db_row["action"] or "")
                reason_map[cid] = str(db_row["action_reason"] or "")
                category_map[cid] = str(db_row["category"] or "")

        wanted = str(action_filter.currentData() or "")
        for row in range(table.rowCount()):
            key = table.item(row, 0)
            cid = str(
                key.data(Qt.ItemDataRole.UserRole)
                if key and key.data(Qt.ItemDataRole.UserRole)
                else ""
            )
            action = action_map.get(cid, "")
            category = category_map.get(cid, "")
            category_item = table.item(row, 4)
            if category_item is not None and category in CATEGORY_LABELS:
                category_item.setText(CATEGORY_LABELS[category])
            item = _item(ACTION_LABELS.get(action, action))
            item.setForeground(QColor(ACTION_COLORS.get(action, MUTED)))
            if reason_map.get(cid):
                item.setToolTip(reason_map[cid])
            table.setItem(row, col, item)
            if wanted:
                table.setRowHidden(row, action != wanted)

        stats = comment_action_counts(window.conn, window.current_profile)
        summary.setText(
            f"Відповісти {stats['reply']} · Лайк {stats['like']} · "
            f"Review {stats['review']} · SKIP {stats['skip']}"
        )

    def reload_with_actions(*args, **kwargs):
        result = original_reload(*args, **kwargs)
        sync_auto_replies()
        decorate_table()
        return result

    window.reload_comments = reload_with_actions

    for combo_name in (
        "comment_status_filter",
        "comment_category_filter",
        "comment_draft_filter",
    ):
        combo = getattr(window, combo_name, None)
        if combo is None:
            continue
        try:
            combo.currentIndexChanged.disconnect()
        except Exception:
            pass
        combo.currentIndexChanged.connect(window.reload_comments)

    action_filter.currentIndexChanged.connect(lambda _i: decorate_table())

    def recalc_actions() -> None:
        stats = reclassify_comment_actions(window.conn)
        window.reload_comments()
        if hasattr(window, "statusBar"):
            window.statusBar().showMessage(
                "Рішення перераховано локально · "
                f"Відповісти {stats['reply']} · Лайк {stats['like']} · "
                f"Review {stats['review']} · SKIP {stats['skip']} · "
                "YouTube API: 0"
            )

    def prepare_replies_action() -> None:
        stats = prepare_action_reply_drafts(
            window.conn,
            window.current_profile,
            limit=20,
        )
        window.reload_comments()
        QMessageBox.information(
            window,
            "Чернетки відповідей",
            f"Оброблено: {stats['processed']}.\n"
            f"Готові: {stats['ready']}.\n"
            f"SKIP: {stats['skipped']}.\n"
            f"Помилки: {stats['errors']}.\n\n"
            "Оброблялися лише коментарі з рішенням ВІДПОВІСТИ.\n"
            "YouTube API: 0 квоти. Нічого не відправлено.",
        )

    prepare_replies.clicked.connect(prepare_replies_action)

    def preview_replies_action() -> None:
        stats = preview_safe_auto_replies(window.conn, window.current_profile)
        QMessageBox.information(
            window, "Безпечні автовідповіді: попередній перегляд",
            f"Перевірено: {stats['checked']}\\n"
            f"Безпечні кандидати: {stats['eligible']}\\n"
            f"Потрібна ручна перевірка: {stats['manual_review']}\\n"
            f"Без готової відповіді: {stats['no_reply']}\\n\\n"
            "Це лише локальна перевірка. YouTube не змінювався.",
        )

    preview_replies.clicked.connect(preview_replies_action)

    def ai_review_action() -> None:
        stats = review_comment_actions_local(
            window.conn,
            window.current_profile,
            limit=20,
        )
        window.reload_comments()
        QMessageBox.information(
            window,
            "AI REVIEW",
            f"Оброблено: {stats['processed']}.\n"
            f"ЛАЙК: {stats['like']}.\n"
            f"REVIEW: {stats['review']}.\n"
            f"SKIP: {stats['skip']}.\n"
            f"Помилки Ollama: {stats['errors']}.\n\n"
            "YouTube API: 0 квоти. Нічого не відправлено.",
        )

    def diverse_preview_action() -> None:
        result = propose_diverse_safe_replies(window.conn, window.current_profile)
        examples = "\n".join(
            entry["reply"] for entry in result["proposals"][:8]
        )
        QMessageBox.information(
            window, "Варіанти безпечних відповідей",
            f"Перевірено: {result['checked']}\n"
            f"Підготовлено: {result['proposed']}\n"
            f"Відкладено: {result['withheld']}\n"
            f"Різних формулювань: {result['distinct_replies']}\n\n"
            + examples + "\n\nНічого не надіслано на YouTube.",
        )

    diverse_preview.clicked.connect(diverse_preview_action)

    def personal_reply_action() -> None:
        selection = table.selectedItems()
        if not selection:
            QMessageBox.information(window, "AI відповідь", "Спочатку виберіть коментар у таблиці.")
            return
        row_index = selection[0].row()
        key = table.item(row_index, 0)
        comment_id = str(key.data(Qt.ItemDataRole.UserRole) or "") if key else ""
        record = window.conn.execute(
            "SELECT text,status FROM comments WHERE comment_id=?", (comment_id,)
        ).fetchone()
        if not record or record["status"] != "new":
            QMessageBox.information(window, "AI відповідь", "Цей коментар недоступний для чернетки.")
            return
        personalized.setEnabled(False)
        personalized.setText("AI генерує відповідь…")
        worker = _PersonalReplyWorker(str(record["text"] or ""), window)
        window._personal_reply_worker = worker
        def finished(result):
            personalized.setEnabled(True)
            personalized.setText("AI відповідь на вибраний · LM Studio")
            if result.get("reply"):
                saved = save_comment_draft(window.conn, comment_id, result["reply"], state="review", reason=("lm_studio_fact_check_required" if result["status"] == "FACT_CHECK_REQUIRED" else "lm_studio_manual_review_required"))
                window.reload_comments()
                QMessageBox.information(window, "AI чернетка · перевірка фактів" if result["status"] == "FACT_CHECK_REQUIRED" else "AI чернетка · потребує перевірки", result["reply"]
                    + "\n\n" + ("Збережено для ручної перевірки." if saved else "Не збережено: статус коментаря змінився.")
                    + "\nНічого не опубліковано.")
            else:
                reasons = {"generic_reply": "Шаблонна відповідь", "too_short_or_long": "Відповідь надто коротка або довга", "needless_context_deflection": "Модель ухилилась від відповіді", "empty_model_reply": "Модель повернула порожню відповідь", "echo": "Модель повторила коментар", "unsupported_claim": "Неперевірене твердження"}
                status = str(result.get("status") or "UNKNOWN")
                reason = reasons.get(str(result.get("reason") or ""), status)
                QMessageBox.warning(window, "AI відповідь", "Чернетку не збережено: " + reason + ".\nНічого не опубліковано.")
        worker.completed.connect(finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def batch_personal_reply_action() -> None:
        rows = window.conn.execute(
            """SELECT c.comment_id,c.text FROM comments c
               JOIN videos v ON v.video_id=c.video_id
               WHERE v.profile=? AND c.status='new'
                 AND COALESCE(c.draft_state,'')=''
                 AND LENGTH(TRIM(c.text)) BETWEEN 1 AND 160
               ORDER BY c.published_at DESC LIMIT 20""",
            (window.current_profile,),
        ).fetchall()
        if not rows:
            QMessageBox.information(window, "AI чернетки", "Немає нових коментарів без чернеток.")
            return
        batch_personalized.setEnabled(False)
        entries = [(str(row["comment_id"]), str(row["text"])) for row in rows]
        worker = _BatchPersonalRepliesWorker(entries, window)
        window._batch_personal_reply_worker = worker

        def update_progress(done, total):
            batch_personalized.setText(f"AI чернетки {done}/{total}…")

        def finished(results):
            batch_personalized.setEnabled(True)
            batch_personalized.setText("AI чернетки x20 · LM Studio")
            saved = rejected = 0
            for comment_id, result in results:
                reply = str(result.get("reply") or "").strip()
                if not reply:
                    rejected += 1
                    continue
                reason = ("lm_studio_fact_check_required"
                          if result.get("status") == "FACT_CHECK_REQUIRED"
                          else "lm_studio_manual_review_required")
                if save_comment_draft(window.conn, comment_id, reply,
                                      state="review", reason=reason):
                    saved += 1
                else:
                    rejected += 1
            window.reload_comments()
            QMessageBox.information(window, "AI чернетки",
                f"Збережено для REVIEW: {saved}\\nВідхилено: {rejected}\\nОпубліковано: 0")

        worker.progress.connect(update_progress)
        worker.completed.connect(finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    batch_personalized.clicked.connect(batch_personal_reply_action)

    personalized.clicked.connect(personal_reply_action)

    ai_review.clicked.connect(ai_review_action)

    recalc.clicked.connect(recalc_actions)

    window._comment_auto_enabled = auto_replies
    window._comment_action_filter = action_filter
    window._comment_action_summary = summary
    window._comment_action_prepare_replies = prepare_replies
    window._comment_action_ai_review = ai_review
    window._comment_action_recalc = recalc
    decorate_table()


def _item(text: str):
    from PySide6.QtWidgets import QTableWidgetItem

    return QTableWidgetItem(str(text or ""))
