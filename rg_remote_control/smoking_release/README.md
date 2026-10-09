# SMOKING_COMPLIANCE_BLUR release candidate

The current installed Studio remains **0.20.20.3**. This branch is an isolated
engineering candidate. **Stable release and production installation are blocked.**
The available smoke masks do not meet visual acceptance. Green software jobs
prove the listed invariants, not smoking detection accuracy.

The old detector can classify a microphone emblem as a cigarette and treat zero
detections as successful full coverage. The candidate requires exact source and
frame coverage, four separately stored binary layers, local mask guards,
independent source-bound review, and a decoded render matching the compositor.
Missing evidence, changed media, lost tracks, unsupported mapping and ambiguous
observations block export. The specific dialogue **886_5 stays quarantined**.

| Component | Verified behavior |
| --- | --- |
| `rg_smoking_compliance.py` | Conditional four-layer union; missing/unknown targets block; padding and feather cannot touch forbidden regions; source-bound review and cache keys |
| `rg_smoking_media.py` | Video-only QTRLE candidate; every encoded frame must exactly match the four-layer render; pixels outside alpha are preserved |
| `rg_smoking_xml.py` | New candidate XML; original audio media, routing, filters and timing remain equivalent; camera filters remain intact; original fractional Premiere ticks are shifted without rounding |
| `rg_smoking_studio_gate.py` | Actual source, scan, review, raster masks, derivative and XML content checked; a legacy `passed: true` cannot authorize export |
| `rg_smoking_stage.py` | Patch only a copy of the exact pinned installed gate; refuse a changed baseline or staging inside the live app |
| Runner workflows | Existing isolated environments; source/app/hold checks; failed diagnostics retained; immutable NAS checkpoints with verified hashes |

**Validation:** 45 software regressions pass locally and on the GitHub test host.
On ALEXPC, all 720 frames of the 24-second 892 example and all 10,708 frames
referenced by the withheld 886_5 source in/out ranges were decoded and scanned.
These are inference activity counts, not precision/recall measurements.
Eight 886_5 proposals were captured as exact original references: six match the
known microphone fixture; two additional crops show fingers near an ear.
No masks were applied to the control source and no whole-stream exemption was made.

The real four-layer render covers **60 frames only**, at source frames 360–419,
30 fps, 1920×1080. Every decoded lossless output frame matches the compositor.
The preview has no audio. Stereo audio invariants are exercised separately by
software fixtures. The withheld real clean XML also passes its installed structural
validator: four video tracks, two audio tracks, 233 video and 172 audio clips.
Actual Premiere application import of a new smoking deliverable is unverified.

**Quality remains unqualified:** cigarette/grip prompts describe this particular
scene; the smoke envelope misses part of the plume, and SAM2 smoke proposals
include background. Conditional mouth phases and full-scene automatic masks are
unverified. The existing pixel-label workbench has no human annotations. The
checked locations contain no independently verified annotation dataset or cached
SAM3 weights. SAM3 metadata access returns 401 publicly and 403 through the
existing Hub client; no new account conditions were accepted.

The one-button inference/QA producer and censorship UI still need implementation
and qualification after the detector is calibrated. **Do not install the staged
gate alone:** it intentionally rejects legacy exports without new evidence. No
installer, release tag, main-branch merge or production configuration change has
been made. The source backup and all inspection artifacts are on NAS; exact run
links, checksums, locations and outstanding work are in
[release_readiness.json](release_readiness.json).

To run the portable regressions, use an isolated Python 3.12 environment with
NumPy, OpenCV and FFmpeg/FFprobe:

```bash
python -m unittest discover -s rg_remote_control/smoking_release -p 'test_*.py' -v
```

The next quality experiment needs an authorized official SAM3 checkpoint/model
snapshot on NAS, or independent pixel annotations to calibrate smoke, grip and
smoking phases. Model masks must not be relabeled as human ground truth. After
that input is available, finish automatic inference and review, evaluate the full
positive and control timelines, check Premiere import, and test backup/rollback
in staging before any live installation.
