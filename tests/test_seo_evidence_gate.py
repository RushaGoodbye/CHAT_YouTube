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

    def test_fourth_title_quote_must_be_verified(self):
        self.data["titles"].append("«Цитата якої немає у розшифровці»")
        self.data["expected_title_count"] = 4
        decision = check_seo_evidence(**self.data)
        self.assertIn("UNVERIFIED_DIRECT_QUOTE", decision.issues)

    def test_requires_all_four_titles_in_ui_mode(self):
        self.data["expected_title_count"] = 4
        self.assertIn("INVALID_TITLE_COUNT", check_seo_evidence(**self.data).issues)

    def test_quote_must_match_complete_words(self):
        self.data["transcript"] = ("Розмова про шкільний процес. " * 40) + "космонавтика"
        self.data["titles"][0] = "«навтика» та навчання"
        self.assertIn("UNVERIFIED_DIRECT_QUOTE", check_seo_evidence(**self.data).issues)

    def test_quote_with_punctuation_matches_source(self):
        self.data["transcript"] += " В кінці він сказав: Все йде за планом!"
        self.data["titles"][0] = "«Все йде за планом» — розмова"
        self.assertNotIn("UNVERIFIED_DIRECT_QUOTE", check_seo_evidence(**self.data).issues)

    def test_boilerplate_description_flagged(self):
        self.data["description"] = (
            "Обговорюємо аргументи учасників. " * 9
        )
        decision = check_seo_evidence(**self.data)
        self.assertIn("GENERIC_DESCRIPTION_BOILERPLATE", decision.issues)

    def test_specific_description_not_flagged(self):
        decision = check_seo_evidence(**self.data)
        self.assertNotIn("GENERIC_DESCRIPTION_BOILERPLATE", decision.issues)

    def test_near_duplicate_angles_warn(self):
        self.data["titles"] = [
            "Шойгу и коррупция что обсуждали в разговоре",
            "Коррупция и Шойгу что обсуждали в разговоре",
            "Увольнение Шойгу причины и реакция",
        ]
        self.assertIn(
            "NEAR_DUPLICATE_TITLE_ANGLES",
            check_seo_evidence(**self.data).issues,
        )

    def test_no_transcript_fails_closed(self):
        self.data["transcript"] = ""
        self.assertIn("INSUFFICIENT_TRANSCRIPT", check_seo_evidence(**self.data).issues)

    def test_duplicate_titles_rejected(self):
        self.data["titles"][1] = self.data["titles"][0]
        self.assertIn("DUPLICATE_OR_EMPTY_TITLE", check_seo_evidence(**self.data).issues)


if __name__ == "__main__":
    unittest.main()
