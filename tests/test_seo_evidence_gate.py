import unittest

from rg_youtube_control.seo_evidence_gate import check_seo_evidence, as_review_record


class EvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.data = dict(
            video_id="AbCdEfGhI12",
            transcript_video_id="AbCdEfGhI12",
            verified_video_mapping=True,
            titles=["Питання про школу", "Освіта та навчання", "Шкільні програми"],
            description="Обговорення шкільних програм та навчання в розмові. " * 4,
            transcript="Розмова про школу, освіту та навчання. " * 35,
        )

    def test_valid_package_is_still_not_publishable(self):
        d = check_seo_evidence(**self.data)
        self.assertTrue(d.approved_for_review)
        self.assertFalse(as_review_record(d)["eligible_for_youtube_write"])

    def test_unmatched_video_is_rejected(self):
        self.data["verified_video_mapping"] = False
        self.assertIn("UNVERIFIED_VIDEO_MAPPING", check_seo_evidence(**self.data).issues)

    def test_unverified_quote_is_rejected(self):
        self.data["titles"][0] = "«Невідома вигадана цитата»"
        self.assertIn("UNVERIFIED_DIRECT_QUOTE", check_seo_evidence(**self.data).issues)

    def test_no_transcript_fails_closed(self):
        self.data["transcript"] = ""
        self.assertIn("INSUFFICIENT_TRANSCRIPT", check_seo_evidence(**self.data).issues)

    def test_duplicate_titles_rejected(self):
        self.data["titles"][1] = self.data["titles"][0]
        self.assertIn("DUPLICATE_OR_EMPTY_TITLE", check_seo_evidence(**self.data).issues)


if __name__ == "__main__":
    unittest.main()
