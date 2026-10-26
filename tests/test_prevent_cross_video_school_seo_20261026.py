import pytest
from rg_youtube_control.free_tools import generate_seo_package_local


def test_school_conviction_video_rejects_other_video_transcript_before_model_call():
    with pytest.raises(ValueError, match="SOURCE_VIDEO_MISMATCH"):
        generate_seo_package_local(
            current_title="Могут ли ОСУЖДЕННЫЕ за тяжкие ПРЕСТУПЛЕНИЯ преподавать в ШКОЛАХ РФ?",
            transcript="00:00:10 По фальшивим новинам, перевіряйте джерела інформації. "
                       "00:00:40 Законопроєкт про фейкові новини.",
        )
