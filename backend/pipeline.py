"""Full processing pipeline: linear RAW -> user parameters -> sRGB output.

The pipeline is deliberately ordered so each stage operates in the
domain where it's best defined:

  1. Exposure (linear gain)            -- multiply in linear space
  2. Highlight recovery (chosen method)-- linear, the heart of the app
  3. Whites endpoint                   -- linear, controls top of curve
  4. Shadow lift                       -- linear, log-style toe
  5. sRGB gamma encode                 -- to perceptual space
  6. Saturation recovery               -- HSL, only in original-highlight mask
  7. 8-bit clamp + JPEG encode         -- final output
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import cv2
import numpy as np

from . import recovery
from .recovery import _linear_to_srgb, _luminance, _smooth_mask


@dataclass
class ProcessResult:
    image_srgb_u8: np.ndarray  # HxWx3 uint8, sRGB encoded
    timing_ms: float


def _normalize_params(p: Dict[str, Any]) -> Dict[str, float]:
    """Coerce user-facing values to floats with sensible defaults."""
    def f(key: str, default: float) -> float:
        v = p.get(key, default)
        try:
            return float(v)
        except (TypeError, ValueError):
            return float(default)

    return {
        "exposure": f("exposure", 0.0),
        "highlights": f("highlights", 0.0),
        "whites": f("whites", 0.0),
        "shadows": f("shadows", 0.0),
        "threshold": f("threshold", 75.0),
        "smoothness": f("smoothness", 20.0),
        "color_preservation": f("color_preservation", 75.0),
        "local_contrast": f("local_contrast", 0.0),
        "saturation_recovery": f("saturation_recovery", 0.0),
    }


def process(linear_rgb: np.ndarray, params: Dict[str, Any]) -> ProcessResult:
    """Apply the full pipeline. Input must be float32 linear RGB [0, 1]."""
    import time

    t0 = time.perf_counter()
    method_key = params.get("method", "luminance_mask")
    if method_key not in recovery.METHODS:
        method_key = "luminance_mask"

    p = _normalize_params(params)
    img = np.clip(linear_rgb.astype(np.float32, copy=False), 0.0, None)

    # 1. Exposure (linear multiplier)
    if abs(p["exposure"]) > 1e-3:
        img = img * (2.0 ** p["exposure"])

    # Pre-recovery luminance mask (used later for saturation recovery)
    pre_luma = _luminance(np.clip(img, 0.0, 1.0))
    threshold = float(np.clip(p["threshold"] / 100.0, 0.05, 0.99))
    feather = float(np.clip(p["smoothness"] / 100.0 * 40.0, 0.0, 50.0))
    highlight_mask = _smooth_mask(pre_luma, threshold * 0.95, feather)

    # 2. Highlight recovery (only when highlights < 0 = "pull down")
    if p["highlights"] < -1.0:
        strength = float(min(1.0, -p["highlights"] / 100.0))
        cp = float(np.clip(p["color_preservation"] / 100.0, 0.0, 1.0))
        lc = float(np.clip(p["local_contrast"] / 100.0, -1.0, 1.0))
        sr = float(np.clip(p["saturation_recovery"] / 100.0, 0.0, 1.0))

        if method_key == "luminance_mask":
            img = recovery.luminance_mask(
                img, strength=strength, threshold=threshold,
                feather=feather, color_preservation=cp,
            )
        elif method_key == "channel_aware":
            img = recovery.channel_aware(
                img, strength=strength, threshold=threshold,
                color_preservation=cp,
            )
        elif method_key == "hsl_compression":
            img = recovery.hsl_compression(
                img, strength=strength, threshold=threshold,
                feather=feather, saturation_recovery=sr,
            )
        elif method_key == "detail_preserving":
            img = recovery.detail_preserving(
                img, strength=strength, threshold=threshold,
                local_contrast=max(0.0, lc),
            )
        elif method_key == "exposure_fusion":
            img = recovery.exposure_fusion(img, strength=strength)
        elif method_key == "filmic_curve":
            img = recovery.filmic_curve(
                img, strength=strength, threshold=threshold,
                contrast=max(0.0, lc),
            )
    elif p["highlights"] > 1.0:
        # Positive highlights = lift highlights subtly (rare but supported)
        lift = float(p["highlights"] / 100.0) * 0.15
        img = img + highlight_mask[..., None] * lift * (1.0 - img)

    img = np.clip(img, 0.0, 4.0)  # allow super-1.0 briefly for whites adjust

    # 3. Whites: scale the top end (above 0.7) toward 1.0 / down from 1.0
    if abs(p["whites"]) > 1.0:
        w = p["whites"] / 100.0
        # Linear interpolation between identity (at 0.7) and 1+w*0.3 (at 1.0)
        gain = np.ones_like(img)
        bright = img > 0.7
        if bright.any():
            t = np.clip((img[bright] - 0.7) / 0.3, 0.0, 1.0)
            gain[bright] = 1.0 + w * 0.3 * t
        img = img * gain

    # 4. Shadow lift: raise values below 0.4 with a smooth toe.
    if abs(p["shadows"]) > 1.0:
        s = p["shadows"] / 100.0
        toe = np.clip(1.0 - img / 0.4, 0.0, 1.0) ** 1.5  # 1 at black, 0 at 0.4
        img = img + s * 0.25 * toe

    img = np.clip(img, 0.0, 1.0)

    # 5. sRGB encode (now in perceptual space)
    srgb = _linear_to_srgb(img)

    # 6. Saturation recovery in originally-highlighted areas, in HSL.
    if p["saturation_recovery"] > 1.0 and method_key not in ("hsl_compression",):
        bgr = srgb[..., ::-1].astype(np.float32)
        hls = cv2.cvtColor(bgr, cv2.COLOR_BGR2HLS)
        h, l, s = hls[..., 0], hls[..., 1], hls[..., 2]
        sr = float(np.clip(p["saturation_recovery"] / 100.0, 0.0, 1.0))
        s = s + highlight_mask * sr * (1.0 - s) * 0.6
        s = np.clip(s, 0.0, 1.0)
        hls_new = np.stack([h, l, s], axis=-1)
        bgr_new = cv2.cvtColor(hls_new, cv2.COLOR_HLS2BGR)
        srgb = np.clip(bgr_new[..., ::-1], 0.0, 1.0)

    out_u8 = (srgb * 255.0 + 0.5).astype(np.uint8)
    return ProcessResult(image_srgb_u8=out_u8, timing_ms=(time.perf_counter() - t0) * 1000.0)


def encode_jpeg(image_u8: np.ndarray, quality: int = 92) -> bytes:
    """JPEG-encode an HxWx3 uint8 RGB image."""
    bgr = image_u8[..., ::-1]
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()


def encode_png(image_u8: np.ndarray) -> bytes:
    bgr = image_u8[..., ::-1]
    ok, buf = cv2.imencode(".png", bgr, [int(cv2.IMWRITE_PNG_COMPRESSION), 6])
    if not ok:
        raise RuntimeError("PNG encode failed")
    return buf.tobytes()


def encode_tiff_16(image_linear: np.ndarray) -> bytes:
    """Encode 16-bit linear TIFF for max quality export.

    ``image_linear`` is expected to be float32 in [0, 1] linear (the
    pipeline's pre-sRGB stage). For UI simplicity, we instead accept the
    sRGB-encoded uint8 the pipeline returns and bump it to 16-bit.
    """
    if image_linear.dtype == np.uint8:
        u16 = (image_linear.astype(np.uint16) * 257)  # 8-bit -> 16-bit
    else:
        u16 = (np.clip(image_linear, 0.0, 1.0) * 65535.0 + 0.5).astype(np.uint16)
    bgr = u16[..., ::-1]
    ok, buf = cv2.imencode(".tiff", bgr)
    if not ok:
        raise RuntimeError("TIFF encode failed")
    return buf.tobytes()
