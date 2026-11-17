"""Regression: 10 videos, not 30 proposal rows; explicit video-level approvals."""
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_vidiq_batch_has_one_row_per_video_navigation_and_notes(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from rg_youtube_control.vidiq_review_ui import VidIQReviewDialog, best_suggestion
    from rg_youtube_control.vidiq_review import SOURCE, load_inbox

    app=QApplication.instance() or QApplication([])
    videos=[]
    originals={}
    for i in range(10):
        video_id=f"VID{i:08d}"
        originals[video_id]=f"Поточна назва відео номер {i+1}"
        videos.append({
            "video_id":video_id,
            "title_suggestions":[
                {"title":f"vidIQ A {i}","vidiq_score":72},
                {"title":f"vidIQ B {i}","vidiq_score":91},
                {"title":f"vidIQ C {i}","vidiq_score":80},
            ],
        })
    inbox=tmp_path/"inbox.json"
    inbox.write_text(json.dumps({
        "source":SOURCE,"channel_id":"UC_test",
        "publishing_enabled":False,"videos":videos,
    },ensure_ascii=False),encoding="utf-8")
    transcript=tmp_path/"srt"
    transcript.mkdir()
    (transcript/"VID00000000.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nСлова зі стріму\n",
        encoding="utf-8",
    )
    cautions=tmp_path/"notes.json"
    cautions.write_text(json.dumps({
        "items":[{"video_id":"VID00000000","srt_topic":"Фактаж",
                  "caution":"Недоведене твердження","risk":"high"}]
    },ensure_ascii=False),encoding="utf-8")
    dialog=VidIQReviewDialog(
        inbox,transcript,channel_id="UC_test",
        original_titles=originals,remarks_path=cautions,
    )
    try:
        assert dialog.table.rowCount()==10
        assert dialog.table.item(0,0).text()==originals["VID00000000"]
        assert all(r.text() for r in dialog.option_radios)
        assert "vidIQ B 0" in best_suggestion(dialog.data["videos"][0])["title"]
        assert "Найвища оцінка" in dialog.option_score_labels[1].text()
        assert "Недоведене" in dialog.remarks_text.toPlainText()
        assert "Слова зі стріму" in dialog.preview.toPlainText()
        assert not dialog.review_btn.isEnabled()
        dialog.next_btn.click()
        assert dialog.table.currentRow()==1
        dialog.previous_btn.click()
        assert dialog.table.currentRow()==0
        dialog.skip_btn.click()
        assert dialog.table.currentRow()==1
        assert load_inbox(inbox)["videos"][0]["stage"]=="SKIPPED"
        dialog.previous_btn.click()
        assert dialog.reopen_btn.isEnabled()
        dialog.reopen_btn.click()
        dialog.option_radios[2].setChecked(True)
        assert "ВИБРАНО" in dialog.option_score_labels[2].text()
        assert "#0894f9" in dialog.option_cards[2].styleSheet()
        dialog.confirm.setChecked(True)
        assert dialog.review_btn.isEnabled()
        monkeypatch.setattr(QMessageBox,"question",
            lambda *a,**k: QMessageBox.StandardButton.Yes)
        dialog.review_btn.click()
        approved=load_inbox(inbox)["videos"][0]
        assert approved["stage"]=="CONTENT_REVIEWED"
        assert approved["selected_title"]=="vidIQ C 0"
        dialog.previous_btn.click()
        assert "#188755" in dialog.option_cards[2].styleSheet()
        assert "ЗАТВЕРДЖЕНО" in dialog.option_score_labels[2].text()
        dialog.next_btn.click()
        assert dialog.table.currentRow()==1
        assert "Перевірено: 1/10" in dialog.summary.text()
    finally:
        dialog.close()
        app.processEvents()


def test_score_is_not_automatic_editorial_approval(tmp_path):
    from rg_youtube_control.vidiq_review_ui import best_suggestion
    video={"stage":"VIDIQ_SUGGESTED",
           "title_suggestions":[
               {"title":"High score","vidiq_score":97},
               {"title":"Lower score","vidiq_score":45}]}
    assert best_suggestion(video)["title"]=="High score"
    assert video["stage"]=="VIDIQ_SUGGESTED"
    assert "selected_title" not in video


def test_reject_all_is_persistent_without_youtube_calls(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from rg_youtube_control.vidiq_review_ui import VidIQReviewDialog
    from rg_youtube_control.vidiq_review import SOURCE, load_inbox
    app=QApplication.instance() or QApplication([])
    inbox=tmp_path/"vidiq.json"
    inbox.write_text(json.dumps({
        "source":SOURCE,"channel_id":"UC_test","publishing_enabled":False,
        "videos":[{
            "video_id":"abcdefghijk",
            "title_suggestions":[
                {"title":f"vidIQ verified source {i}","vidiq_score":80+i}
                for i in range(3)
            ]
        }]
    }),encoding="utf-8")
    monkeypatch.setattr(QMessageBox,"question",
        lambda *args,**kwargs: QMessageBox.StandardButton.Yes)
    dialog=VidIQReviewDialog(inbox,tmp_path,channel_id="UC_test")
    try:
        assert dialog.reject_btn.isEnabled()
        dialog.reject_btn.click()
        assert load_inbox(inbox)["videos"][0]["stage"]=="REJECTED"
        assert not dialog.review_btn.isEnabled()
        assert dialog.reopen_btn.isEnabled()
        assert "Відхилено: 1" in dialog.summary.text()
        dialog.reopen_btn.click()
        assert load_inbox(inbox)["videos"][0]["stage"]=="VIDIQ_SUGGESTED"
    finally:
        dialog.close()
