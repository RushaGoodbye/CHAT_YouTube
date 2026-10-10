"""Conservative letterbox detection + geometry. No Qt or codec dependencies.

Coordinates are normalized to the decoded frame; a crop is only selected when
several frames agree that broad exterior bands contain no meaningful picture.
"""
from __future__ import annotations
from dataclasses import dataclass
from statistics import median

@dataclass(frozen=True)
class Crop:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top


def detect_letterbox(bright: list[list[bool]]) -> Crop | None:
    """Return safe non-black picture bounds from a small luminance mask.

    Each scan line must contain a significant bright-pixel density to count as
    picture, suppressing logos/subtitles that could otherwise pull the bounds.
    """
    if not bright or not bright[0]:
        return None
    height, width = len(bright), len(bright[0])
    if height < 20 or width < 20 or any(len(row) != width for row in bright):
        return None
    rows = [sum(row) for row in bright]
    cols = [sum(bright[y][x] for y in range(height)) for x in range(width)]
    # Noise and lone subtitles near an exterior edge must not change cropping.
    active_rows = [i for i, count in enumerate(rows) if count >= max(5, round(width * 0.08))]
    active_cols = [i for i, count in enumerate(cols) if count >= max(4, round(height * 0.09))]
    if not active_rows or not active_cols:
        return None
    margin_x = max(1, round(width * 0.01))
    margin_y = max(1, round(height * 0.01))
    x0 = max(0, active_cols[0] - margin_x)
    x1 = min(width, active_cols[-1] + margin_x + 1)
    y0 = max(0, active_rows[0] - margin_y)
    y1 = min(height, active_rows[-1] + margin_y + 1)
    cw, ch = x1-x0, y1-y0
    if cw < width * 0.14 or ch < height * 0.15:
        return None
    # Ignore small dark movie bars and normal low-light framing. Auto zoom is
    # only for noticeably embedded footage (usually pillarbox or letterbox).
    removed_width = (width-cw)/width
    removed_height = (height-ch)/height
    if removed_width < 0.16 and removed_height < 0.16:
        return None
    # Must have a bilateral matte, not an arbitrary dark region on one side.
    horizontal = x0 >= width * 0.06 and (width-x1) >= width * 0.06
    vertical = y0 >= height * 0.06 and (height-y1) >= height * 0.06
    if not horizontal and not vertical:
        return None
    # Exterior bands must be almost entirely black, not merely dark scenery.
    if horizontal:
        outside = [bright[y][x] for y in range(0,height,3)
                   for x in (*range(0,x0,3), *range(x1,width,3))]
    else:
        outside = [bright[y][x] for y in (*range(0,y0,3), *range(y1,height,3))
                   for x in range(0,width,3)]
    if not outside or sum(outside)/len(outside) > 0.012:
        return None
    return Crop(x0/width,y0/height,x1/width,y1/height)


def stable_crop(crops: list[Crop | None]) -> Crop | None:
    """Require 3 consecutive independent picture detections of the same bars."""
    if len(crops) < 3 or any(c is None for c in crops[-3:]):
        return None
    recent = crops[-3:]
    for attr in ('left','top','right','bottom'):
        coords = [getattr(c,attr) for c in recent]
        if max(coords)-min(coords) > 0.035:
            return None
    return Crop(*(median(getattr(c,attr) for c in recent)
                  for attr in ('left','top','right','bottom')))


def video_geometry(view_width: int, view_height: int, source_width: int,
                   source_height: int, crop: Crop) -> tuple[int,int,int,int]:
    """Place a full decoded frame behind a clipping viewport, fitting crop.

    No stretch: the crop fills maximum available height/width while preserving
    the picture aspect ratio. The extraneous encoded matte is clipped away.
    """
    if min(view_width,view_height,source_width,source_height) <= 0:
        return (0,0,max(1,view_width),max(1,view_height))
    active_w = source_width*crop.width
    active_h = source_height*crop.height
    scale = min(view_width/active_w, view_height/active_h)
    full_w, full_h = source_width*scale, source_height*scale
    x = (view_width - active_w*scale)/2 - source_width*crop.left*scale
    y = (view_height - active_h*scale)/2 - source_height*crop.top*scale
    return (round(x),round(y),max(1,round(full_w)),max(1,round(full_h)))
