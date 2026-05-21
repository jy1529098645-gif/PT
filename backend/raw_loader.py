"""RAW image loading with rawpy/libraw.

Returns linear float32 RGB (0..1) plus camera metadata so the rest of the
pipeline can decide whether to apply gamma / tone curves.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

import numpy as np
import rawpy

SUPPORTED_EXT = {
    ".cr2", ".cr3", ".nef", ".nrw", ".arw", ".srf", ".sr2",
    ".dng", ".raf", ".orf", ".rw2", ".pef", ".rwl", ".iiq",
    ".3fr", ".fff", ".mrw", ".dcr", ".kdc", ".x3f", ".erf",
}


@dataclass
class RawImage:
    """Linear demosaiced image plus camera metadata."""
    linear_rgb: np.ndarray  # float32 HxWx3 in [0, 1], linear (no gamma)
    camera_wb: Tuple[float, float, float, float]  # as_shot WB multipliers
    daylight_wb: Tuple[float, float, float, float]
    black_level: float
    white_level: float
    iso: float
    camera_make: str
    camera_model: str

    @property
    def shape(self) -> Tuple[int, int]:
        return self.linear_rgb.shape[:2]


def is_raw_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXT


def load_raw(
    path: str | Path,
    *,
    half_size: bool = False,
    max_long_side: int | None = None,
) -> RawImage:
    """Load a RAW file and demosaic to linear float32 RGB.

    Linear (gamma=(1,1)) + no_auto_bright + 16-bit gives us the cleanest
    starting point for tonal work. Use `half_size=True` for fast previews.
    """
    with rawpy.imread(str(path)) as raw:
        try:
            cam_wb = tuple(float(x) for x in raw.camera_whitebalance)
        except Exception:
            cam_wb = (1.0, 1.0, 1.0, 1.0)
        try:
            day_wb = tuple(float(x) for x in raw.daylight_whitebalance)
        except Exception:
            day_wb = (1.0, 1.0, 1.0, 1.0)

        try:
            black_level = float(np.mean(raw.black_level_per_channel))
        except Exception:
            black_level = 0.0
        try:
            white_level = float(raw.white_level)
        except Exception:
            white_level = 16383.0

        try:
            iso = float(raw.metadata.iso_speed) if raw.metadata.iso_speed else 0.0
        except Exception:
            iso = 0.0
        try:
            make = raw.metadata.make if hasattr(raw, "metadata") else ""
            model = raw.metadata.model if hasattr(raw, "metadata") else ""
        except Exception:
            make, model = "", ""

        rgb16 = raw.postprocess(
            output_bps=16,
            no_auto_bright=True,
            use_camera_wb=True,
            gamma=(1.0, 1.0),
            output_color=rawpy.ColorSpace.sRGB,
            demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
            half_size=half_size,
            highlight_mode=rawpy.HighlightMode.Clip,
            user_flip=-1,  # -1 = honor camera-flagged EXIF orientation
        )

    linear = rgb16.astype(np.float32) / 65535.0

    if max_long_side is not None:
        h, w = linear.shape[:2]
        long_side = max(h, w)
        if long_side > max_long_side:
            scale = max_long_side / long_side
            new_size = (int(round(w * scale)), int(round(h * scale)))
            import cv2  # local import to avoid import cycle at module load
            linear = cv2.resize(linear, new_size, interpolation=cv2.INTER_AREA)

    return RawImage(
        linear_rgb=linear,
        camera_wb=cam_wb,
        daylight_wb=day_wb,
        black_level=black_level,
        white_level=white_level,
        iso=iso,
        camera_make=make if isinstance(make, str) else make.decode("ascii", "ignore"),
        camera_model=model if isinstance(model, str) else model.decode("ascii", "ignore"),
    )
