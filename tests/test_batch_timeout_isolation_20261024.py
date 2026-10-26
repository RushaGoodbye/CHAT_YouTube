"""Do not overlap SEO workers after timeout."""
from pathlib import Path

def test_batch_timeout_stops_further_candidates():
    source = Path("src/rg_youtube_control/ui.py").read_text(encoding="utf-8")
    start = source.index("    def local_seo_batch(")
    end = source.index("    def _save_local_seo_batch(", start)
    batch = source[start:end]
    assert "if isinstance(exc, TimeoutError):" in batch
    assert "stopped_early = True\n                        break" in batch
