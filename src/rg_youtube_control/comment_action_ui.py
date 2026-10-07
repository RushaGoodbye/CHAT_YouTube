from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QMessageBox, QPushButton

from .comment_action_runtime import prepare_action_reply_drafts
from .db import comment_action_counts, reclassify_comment_actions
from .style import MUTED, SUCCESS, WARNING, YOUTUBE_RED


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
    bar.addStretch()

    prepare_replies = QPushButton("Підготувати ВІДПОВІДІ x20 · 0 квоти")
    prepare_replies.setProperty("role", "success")
    bar.addWidget(prepare_replies)

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

    recalc.clicked.connect(recalc_actions)

    window._comment_action_filter = action_filter
    window._comment_action_summary = summary
    window._comment_action_recalc = recalc
    decorate_table()


def _item(text: str):
    from PySide6.QtWidgets import QTableWidgetItem

    return QTableWidgetItem(str(text or ""))
