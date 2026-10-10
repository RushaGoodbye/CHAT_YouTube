"""Conservative detection of a rectangular video inset inside an edited frame.

Unlike letterbox detection, this also tolerates title text, logos, colored
decorative overlays and end-cards in the matte. It never changes player size.
It is intentionally confidence-limited: uncertain footage stays uncropped.
"""
from __future__ import annotations
from statistics import median

from video_fit import Crop


def _runs(mask: list[bool], max_gap: int = 2) -> list[tuple[int, int]]:
    spans = []
    start = None
    last = None
    for i, on in enumerate(mask):
        if on:
            if start is None:
                start = i
            last = i
        elif start is not None and i - last > max_gap:
            spans.append((start, last + 1))
            start = None
            last = None
    if start is not None:
        spans.append((start, last + 1))
    return spans


def detect_content_region(rgb: list[list[tuple[int, int, int]]]) -> Crop | None:
    """Find the dominant large, centered, textured rectangle on flat matte.

    RGB samples should be a small uniformly downscaled frame (e.g. 192x108).
    No ML, no third-party dependencies, no file I/O or GPU allocation.
    """
    if not rgb or not rgb[0]:
        return None
    h, w = len(rgb), len(rgb[0])
    if w < 48 or h < 36 or any(len(row) != w for row in rgb):
        return None

    # Matte is learned from all four corners. Varied corner content means
    # this is a normal full-frame shot, not a composited video-in-frame.
    corner_w, corner_h = max(3, w // 12), max(3, h // 12)
    corners = [
        rgb[y][x]
        for y in (*range(corner_h), *range(h - corner_h, h))
        for x in (*range(corner_w), *range(w - corner_w, w))
    ]
    bg = tuple(int(median(c[k] for c in corners)) for k in range(3))

    def difference(pixel):
        return max(abs(int(pixel[k]) - bg[k]) for k in range(3))

    if sum(difference(c) <= 24 for c in corners) / len(corners) < 0.87:
        return None

    different = [[difference(pixel) > 38 for pixel in row] for row in rgb]
    counts = [sum(row) for row in different]
    # Looking for a broad, sustained picture region, not a thin caption.
    smooth = [median(counts[max(0, i - 2): min(h, i + 3)]) for i in range(h)]
    high = max(smooth)
    if high < w * 0.19:
        return None
    threshold = max(w * 0.15, high * 0.59)
    candidates = [pair for pair in _runs([x >= threshold for x in smooth])
                  if pair[1] - pair[0] >= h * 0.20]
    if not candidates:
        return None
    y0, y1 = max(candidates, key=lambda p: sum(smooth[p[0]:p[1]]))
    # Require the inset to dominate caption rows, if present.
    if (sum(smooth[y0:y1]) < sum(smooth) * 0.51):
        return None

    inside_rows = different[y0:y1]
    col_counts = [sum(row[x] for row in inside_rows) for x in range(w)]
    smooth_cols = [median(col_counts[max(0, i - 2): min(w, i + 3)]) for i in range(w)]
    high_col = max(smooth_cols)
    if high_col < (y1 - y0) * 0.18:
        return None
    threshold_col = max((y1 - y0) * 0.14, high_col * 0.55)
    xcandidates = [p for p in _runs([x >= threshold_col for x in smooth_cols])
                   if p[1] - p[0] >= w * 0.20]
    if not xcandidates:
        return None
    x0, x1 = max(xcandidates, key=lambda p: sum(smooth_cols[p[0]:p[1]]))
    # Add a small margin; preserve all pixels at image's natural boundaries.
    px, py = max(1, w // 100), max(1, h // 100)
    x0, x1 = max(0, x0 - px), min(w, x1 + px)
    y0, y1 = max(0, y0 - py), min(h, y1 + py)
    cw, ch = x1 - x0, y1 - y0
    if cw < w * 0.23 or ch < h * 0.22:
        return None
    if cw > w * 0.92 and ch > h * 0.92:
        return None
    bilateral_x = x0 >= w * 0.055 and w - x1 >= w * 0.055
    bilateral_y = y0 >= h * 0.075 and h - y1 >= h * 0.075
    if not bilateral_x and not bilateral_y:
        return None

    # The selected rectangle must be visually distinct from the matte.
    in_count = sum(sum(row[x0:x1]) for row in different[y0:y1])
    if in_count / (cw * ch) < 0.27:
        return None

    outside_count = 0
    outside_total = 0
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            if x0 <= x < x1 and y0 <= y < y1:
                continue
            outside_total += 1
            outside_count += different[y][x]
    # Up to ~17% of the exterior can be occupied by labels and logos.
    if outside_total == 0 or outside_count / outside_total > 0.17:
        return None
    return Crop(x0 / w, y0 / h, x1 / w, y1 / h)
