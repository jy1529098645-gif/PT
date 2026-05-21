"""Full processing pipeline.

Stages run in an order chosen so each operator works in the domain
where it's mathematically well-defined.

Linear-space (pre-gamma):
    1.  Global exposure
    2.  Highlight recovery (one of six pro algorithms)
    3.  Whites endpoint
    4.  Shadows / Black point
    5.  Warmth / Tint (white balance)
    6.  Local masks (radial / linear gradient)
sRGB-encoded (post-gamma, perceptual):
    7.  Brightness / Brilliance
    8.  Contrast
    9.  Vibrance / Saturation
    10. Definition (clarity)
    11. Noise reduction
    12. Sharpness
    13. Vignette
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List

import cv2
import numpy as np

from . import adjustments as adj
from . import masks
from . import recovery


@dataclass
class ProcessResult:
    image_srgb_u8: np.ndarray  # HxWx3 uint8 sRGB
    timing_ms: float


# ----------------------------------------------------------------------------
# Parameter coercion
# ----------------------------------------------------------------------------

_DEFAULTS: Dict[str, float] = {
    # Geometry (apply first, in the loaded frame)
    "rotation": 0.0,        # 0 / 90 / 180 / 270, clockwise
    "flip_h": 0.0,          # truthy = mirror left/right
    "flip_v": 0.0,          # truthy = mirror top/bottom
    # Linear-space tonal
    "exposure": 0.0,
    "highlights": 0.0,
    "whites": 0.0,
    "shadows": 0.0,
    "black_point": 0.0,
    # WB
    "warmth": 0.0,
    "tint": 0.0,
    # sRGB-space tonal
    "brightness": 0.0,
    "brilliance": 0.0,
    "contrast": 0.0,
    # Color
    "saturation": 0.0,
    "vibrance": 0.0,
    # Detail
    "definition": 0.0,
    "sharpness": 0.0,
    "noise_reduction": 0.0,
    # Effects
    "vignette": 0.0,
    # Recovery-method specific
    "threshold": 75.0,
    "smoothness": 20.0,
    "color_preservation": 75.0,
    "local_contrast": 0.0,
    "saturation_recovery": 0.0,
}


def _norm(p: Dict[str, Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for k, default in _DEFAULTS.items():
        try:
            out[k] = float(p.get(k, default))
        except (TypeError, ValueError):
            out[k] = float(default)
    return out


# ----------------------------------------------------------------------------
# Geometry transform
# ----------------------------------------------------------------------------

_ROT_K = {0: 0, 90: -1, 180: 2, 270: 1}


def _apply_transform(img: np.ndarray, rotation: float, flip_h: float, flip_v: float) -> np.ndarray:
    """Apply 90°-quanta rotation + optional H/V mirror. Returns contiguous array."""
    rot = int(round(rotation)) % 360
    k = _ROT_K.get(rot, 0)
    if k != 0:
        img = np.rot90(img, k=k)
    if flip_h:
        img = img[:, ::-1]
    if flip_v:
        img = img[::-1, :]
    if not img.flags["C_CONTIGUOUS"]:
        img = np.ascontiguousarray(img)
    return img


# ----------------------------------------------------------------------------
# sRGB encode helpers
# ----------------------------------------------------------------------------

def _linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    a = 0.055
    return np.where(
        x <= 0.0031308,
        12.92 * x,
        (1.0 + a) * np.power(np.maximum(x, 1e-10), 1.0 / 2.4) - a,
    ).astype(np.float32)


# ----------------------------------------------------------------------------
# Highlight recovery dispatch
# ----------------------------------------------------------------------------

def _apply_recovery(img: np.ndarray, p: Dict[str, float], method_key: str) -> np.ndarray:
    """If user pulled highlights down, run the chosen recovery algorithm."""
    if p["highlights"] >= -1.0:
        # Positive (boost) - small additive lift in highlight area
        if p["highlights"] > 1.0:
            L = adj.luma(np.clip(img, 0.0, 1.0))
            t = float(np.clip(p["threshold"] / 100.0, 0.05, 0.99))
            f = float(np.clip(p["smoothness"] / 100.0 * 40.0, 0.0, 50.0))
            m = recovery._smooth_mask(L, t * 0.95, f)
            lift = (p["highlights"] / 100.0) * 0.15
            return img + m[..., None] * lift * (1.0 - img)
        return img

    strength = float(min(1.0, -p["highlights"] / 100.0))
    threshold = float(np.clip(p["threshold"] / 100.0, 0.05, 0.99))
    feather = float(np.clip(p["smoothness"] / 100.0 * 40.0, 0.0, 50.0))
    cp = float(np.clip(p["color_preservation"] / 100.0, 0.0, 1.0))
    lc = float(np.clip(p["local_contrast"] / 100.0, -1.0, 1.0))
    sr = float(np.clip(p["saturation_recovery"] / 100.0, 0.0, 1.0))

    if method_key == "luminance_mask":
        return recovery.luminance_mask(img, strength=strength, threshold=threshold,
                                       feather=feather, color_preservation=cp)
    if method_key == "channel_aware":
        return recovery.channel_aware(img, strength=strength, threshold=threshold,
                                      color_preservation=cp)
    if method_key == "hsl_compression":
        return recovery.hsl_compression(img, strength=strength, threshold=threshold,
                                        feather=feather, saturation_recovery=sr)
    if method_key == "detail_preserving":
        return recovery.detail_preserving(img, strength=strength, threshold=threshold,
                                          local_contrast=max(0.0, lc))
    if method_key == "exposure_fusion":
        return recovery.exposure_fusion(img, strength=strength)
    if method_key == "filmic_curve":
        return recovery.filmic_curve(img, strength=strength, threshold=threshold,
                                     contrast=max(0.0, lc))
    return img


# ----------------------------------------------------------------------------
# Local masks
# ----------------------------------------------------------------------------

# Adjustments allowed inside a local mask. Keep this short and intentional —
# local color-temp / sat / contrast / exposure covers 95% of real edits.
_LOCAL_ADJUSTMENTS = (
    "exposure", "highlights", "shadows", "saturation", "contrast", "warmth", "tint",
)


def _apply_local_masks(linear_img: np.ndarray, local_specs: List[Dict[str, Any]]) -> np.ndarray:
    """Apply each local mask. Operates in linear space.

    For each mask we build an adjusted copy of the (current) image and
    blend by the mask. Masks compose left-to-right so later masks see
    earlier masks' edits, which matches Lightroom behavior.
    """
    if not local_specs:
        return linear_img

    h, w = linear_img.shape[:2]
    out = linear_img

    for spec in local_specs:
        m = masks.build_mask(spec, h, w)
        if not np.any(m > 1e-3):
            continue

        params = spec.get("adjustments") or {}
        edited = out.copy()

        ev = float(params.get("exposure", 0.0))
        if abs(ev) > 1e-3:
            edited = adj.exposure(edited, ev)

        hl = float(params.get("highlights", 0.0))
        if abs(hl) > 1.0:
            # Local highlight: reuse global tone curve in luminance space
            strength = float(min(1.0, abs(hl) / 100.0))
            sign = -1.0 if hl < 0 else 1.0
            if sign < 0:
                edited = recovery.luminance_mask(
                    edited, strength=strength, threshold=0.55,
                    feather=18.0, color_preservation=0.85,
                )
            else:
                # Positive: gentle lift via additive
                Ll = adj.luma(np.clip(edited, 0.0, 1.0))
                lift_m = np.clip((Ll - 0.55) / 0.45, 0.0, 1.0)[..., None]
                edited = edited + lift_m * (hl / 100.0) * 0.18 * (1.0 - edited)

        sh = float(params.get("shadows", 0.0))
        if abs(sh) > 1.0:
            edited = adj.shadows(edited, sh)

        cw = float(params.get("warmth", 0.0))
        ct = float(params.get("tint", 0.0))
        if abs(cw) > 1.0 or abs(ct) > 1.0:
            edited = adj.warmth_tint(edited, cw, ct)

        sat = float(params.get("saturation", 0.0))
        if abs(sat) > 1.0:
            edited = adj.saturation(edited, sat)

        co = float(params.get("contrast", 0.0))
        if abs(co) > 1.0:
            # Contrast is best in sRGB but we're in linear here.
            # Approximate by reusing the sRGB curve on linear data — close
            # enough for localized adjustments.
            edited = adj.contrast(np.clip(edited, 0.0, 1.0), co)

        m3 = m[..., None]
        out = out * (1.0 - m3) + edited * m3

    return out


# ----------------------------------------------------------------------------
# Main entry
# ----------------------------------------------------------------------------

def process(
    linear_rgb: np.ndarray,
    params: Dict[str, Any],
    *,
    high_quality_denoise: bool = False,
) -> ProcessResult:
    t0 = time.perf_counter()
    method_key = params.get("method", "luminance_mask")
    if method_key not in recovery.METHODS:
        method_key = "luminance_mask"

    local_specs = masks.collect_masks(params.get("local_masks") or [])

    p = _norm(params)
    # Sanitize: clip negatives, replace any NaN/Inf with safe values so the
    # rest of the pipeline doesn't have to defend against them.
    img = linear_rgb.astype(np.float32, copy=False)
    if not np.all(np.isfinite(img)):
        img = np.nan_to_num(img, nan=0.0, posinf=1.0, neginf=0.0)
    img = np.clip(img, 0.0, None)

    # --- Geometry: rotation / mirror (must come first; downstream stages
    #     and local masks all operate in this user-facing frame) -----------
    img = _apply_transform(img, p["rotation"], p["flip_h"], p["flip_v"])

    # --- Linear-space stages -----------------------------------------------
    img = adj.exposure(img, p["exposure"])
    img = _apply_recovery(img, p, method_key)
    img = adj.whites(img, p["whites"])
    img = adj.shadows(img, p["shadows"])
    img = adj.black_point(img, p["black_point"])
    img = adj.warmth_tint(img, p["warmth"], p["tint"])
    img = _apply_local_masks(img, local_specs)
    img = np.clip(img, 0.0, 1.0)

    # --- sRGB encode --------------------------------------------------------
    srgb = _linear_to_srgb(img)

    # --- Perceptual-space tonal --------------------------------------------
    srgb = adj.brightness(srgb, p["brightness"])
    srgb = adj.brilliance(srgb, p["brilliance"])
    srgb = adj.contrast(srgb, p["contrast"])

    # --- Color --------------------------------------------------------------
    srgb = adj.vibrance(srgb, p["vibrance"])
    srgb = adj.saturation(srgb, p["saturation"])

    # --- In-mask saturation recovery (legacy from highlight-recovery flow) --
    if p["saturation_recovery"] > 1.0 and method_key != "hsl_compression" \
            and p["highlights"] < -1.0:
        threshold = float(np.clip(p["threshold"] / 100.0, 0.05, 0.99))
        feather = float(np.clip(p["smoothness"] / 100.0 * 40.0, 0.0, 50.0))
        pre_L = adj.luma(np.clip(srgb, 0.0, 1.0))
        m = recovery._smooth_mask(pre_L, threshold * 0.95, feather)
        sr = float(np.clip(p["saturation_recovery"] / 100.0, 0.0, 1.0))
        L = adj.luma(srgb)[..., None]
        srgb = srgb + m[..., None] * sr * 0.5 * (srgb - L)
        srgb = np.clip(srgb, 0.0, 1.0)

    # --- Convert to uint8 for the remaining detail / effect stages ---------
    out_u8 = (np.clip(srgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)

    out_u8 = adj.definition(out_u8, p["definition"])
    out_u8 = adj.noise_reduction(out_u8, p["noise_reduction"],
                                 high_quality=high_quality_denoise)
    out_u8 = adj.sharpness(out_u8, p["sharpness"])
    # Vignette ideally lives in linear; for speed we approximate in sRGB
    if abs(p["vignette"]) > 1.0:
        out_f = out_u8.astype(np.float32) / 255.0
        out_f = adj.vignette(out_f, p["vignette"])
        out_u8 = (np.clip(out_f, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)

    return ProcessResult(image_srgb_u8=out_u8, timing_ms=(time.perf_counter() - t0) * 1000.0)


# ----------------------------------------------------------------------------
# Encoders
# ----------------------------------------------------------------------------

def encode_jpeg(image_u8: np.ndarray, quality: int = 92) -> bytes:
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


def encode_tiff_16(image: np.ndarray) -> bytes:
    if image.dtype == np.uint8:
        u16 = image.astype(np.uint16) * 257
    else:
        u16 = (np.clip(image, 0.0, 1.0) * 65535.0 + 0.5).astype(np.uint16)
    bgr = u16[..., ::-1]
    ok, buf = cv2.imencode(".tiff", bgr)
    if not ok:
        raise RuntimeError("TIFF encode failed")
    return buf.tobytes()
