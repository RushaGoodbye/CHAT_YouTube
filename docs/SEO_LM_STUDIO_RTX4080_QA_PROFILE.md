# LM Studio RTX 4080 — QA inference profile

Applies only to local, review-only SEO testing. Never run two 12–14B models on the 16 GB RTX 4080 at the same time.

## Verified working profile

Unloading Qwen before independent Gemma critique, then loading Gemma with full GPU offload and a single parallel request:

```powershell
lms unload rg-qwen3-14b
lms unload google/gemma-4-e4b
lms load google/gemma-4-e4b --identifier google/gemma-4-e4b --gpu max --parallel 1 -c 8192 -y
lms ps
```

Actual AlexPC A/B source-critic test using the same video prompt:

- Gemma default placement: 33.9 s.
- Full GPU offload, parallel 1: 2.3 s.
- Subsequent independent 17-video critic batch: 43.16 s total, 10 medium and 7 high risk. These are suggestions for editorial review, not approvals.

Use separate Qwen-3-14B as the SEO generator, not simultaneously with Gemma when VRAM is limited. Keep `reasoning_effort="none"` for JSON requests. Validate source-quote context and fail closed on empty or malformed model responses. Limit retries to one and retain publication_allowed=false.

When QA is finished, `lms unload google/gemma-4-e4b` releases GPU memory. Video processing remains owned by the open Studio application, never a detached background worker.

This staged profile is not yet integrated with the installed Windows application. Do not claim G6 release readiness based on it.
