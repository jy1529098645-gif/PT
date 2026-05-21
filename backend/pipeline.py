"""Full processing pipeline (Camera Raw-style ordering).

Stages, in order:
    Linear-space:
      1.  Geometry (rotation / flip)
      2.  Exposure
      3.  Highlight recovery (one of six algorithms)
      4.  Whites / Shadows / Black point
      5.  Warmth / Tint (white balance)
      6.  Dehaze
      7.  Local masks (radial / linear gradient)
    sRGB-encoded:
      8.  Brightness / Brilliance
      9.  Contrast
      10. HSL Color Mixer (8 hue bands × hue/sat/lum)
      11. Color Grading (3-range tonal tint)
      12. Vibrance / Saturation
    8-bit perceptual:
      13. Definition (clarity)
      14. Texture
      15. Noise reduction
      16. Sharpening (Amount / Radius / Detail / Masking)
      17. Vignette
      18. Grain
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List

import cv2
import numpy as np

from . import adjustments as adj
from . import color_mixer
from . import masks
from . import recovery


@dataclass
class ProcessResult:
    image_srgb_u8: np.ndarray
    timing_ms: float


# ----------------------------------------------------------------------------
# Parameter coercion
# ----------------------------------------------------------------------------

_DEFAULTS: Dict[str, float] = {
    # Geometry
    "rotation": 0.0, "flip_h": 0.0, "flip_v": 0.0,
    # Linear-space tonal
    "exposure": 0.0,
    "highlights": 0.0, "whites": 0.0, "shadows": 0.0, "black_point": 0.0,
    # WB
    "warmth": 0.0, "tint": 0.0,
    # Dehaze
    "dehaze": 0.0,
    # sRGB-space tonal
    "brightness": 0.0, "brilliance": 0.0, "contrast": 0.0,
    # Color
    "saturation": 0.0, "vibrance": 0.0,
    # Detail
    "definition": 0.0,
    "texture": 0.0,
    "sharpness": 0.0,
    "sharpness_radius": 1.0,
    "sharpness_detail": 50.0,
    "sharpness_masking": 0.0,
    "noise_reduction": 0.0,
    # Effects
    "vignette": 0.0,
    "grain": 0.0, "grain_size": 25.0, "grain_roughness": 50.0,
    # Recovery method specific
    "threshold": 75.0, "smoothness": 25.0, "color_preservation": 85.0,
    "local_contrast": 0.0, "saturation_recovery": 0.0,
    # Color grading (3-range × hue/sat + blending + balance)
    "grade_shadows_hue": 0.0, "grade_shadows_sat": 0.0,
    "grade_mids_hue":    0.0, "grade_mids_sat":    0.0,
    "grade_highlights_hue": 0.0, "grade_highlights_sat": 0.0,
    "grade_blending": 50.0, "grade_balance": 0.0,
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
    if p["highlights"] >= -1.0:
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

def _apply_local_masks(linear_img: np.ndarray, local_specs: List[Dict[str, Any]]) -> np.ndarray:
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
            strength = float(min(1.0, abs(hl) / 100.0))
            if hl < 0:
                edited = recovery.luminance_mask(
                    edited, strength=strength, threshold=0.55,
                    feather=18.0, color_preservation=0.85,
                )
            else:
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
    hsl_params = color_mixer.coerce_hsl_params(params.get("hsl") or {})

    p = _norm(params)
    img = linear_rgb.astype(np.float32, copy=False)
    if not np.all(np.isfinite(img)):
        img = np.nan_to_num(img, nan=0.0, posinf=1.0, neginf=0.0)
    img = np.clip(img, 0.0, None)

    # 1. Geometry
    img = _apply_transform(img, p["rotation"], p["flip_h"], p["flip_v"])

    # 2-5. Linear-space tonal
    img = adj.exposure(img, p["exposure"])
    img = _apply_recovery(img, p, method_key)
    img = adj.whites(img, p["whites"])
    img = adj.shadows(img, p["shadows"])
    img = adj.black_point(img, p["black_point"])
    img = adj.warmth_tint(img, p["warmth"], p["tint"])

    # 6. Dehaze (still in linear)
    img = adj.dehaze(img, p["dehaze"])

    # 7. Local masks
    img = _apply_local_masks(img, local_specs)
    img = np.clip(img, 0.0, 1.0)

    # → sRGB encode
    srgb = _linear_to_srgb(img)

    # 8-9. Brightness / Brilliance / Contrast
    srgb = adj.brightness(srgb, p["brightness"])
    srgb = adj.brilliance(srgb, p["brilliance"])
    srgb = adj.contrast(srgb, p["contrast"])

    # 10. HSL Color Mixer (operates on float, uses HSV internally)
    srgb = color_mixer.hsl_mixer(srgb, hsl_params)

    # 11. Color Grading (3-range tint)
    srgb = color_mixer.color_grading(
        srgb,
        shadows_hue=p["grade_shadows_hue"], shadows_sat=p["grade_shadows_sat"],
        mids_hue=p["grade_mids_hue"], mids_sat=p["grade_mids_sat"],
        highlights_hue=p["grade_highlights_hue"], highlights_sat=p["grade_highlights_sat"],
        blending=p["grade_blending"], balance=p["grade_balance"],
    )

    # 12. Vibrance / Saturation
    srgb = adj.vibrance(srgb, p["vibrance"])
    srgb = adj.saturation(srgb, p["saturation"])

    # Legacy: in-mask saturation recovery (only when highlight recovery is engaged)
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

    # → uint8 for the remaining detail / effect stages
    out_u8 = (np.clip(srgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)

    # 13-16. Detail
    out_u8 = adj.definition(out_u8, p["definition"])
    out_u8 = adj.texture(out_u8, p["texture"])
    out_u8 = adj.noise_reduction(out_u8, p["noise_reduction"],
                                 high_quality=high_quality_denoise)
    out_u8 = adj.sharpness(
        out_u8, p["sharpness"],
        radius=p["sharpness_radius"],
        detail=p["sharpness_detail"],
        masking=p["sharpness_masking"],
    )

    # 17. Vignette
    if abs(p["vignette"]) > 1.0:
        out_f = out_u8.astype(np.float32) / 255.0
        out_f = adj.vignette(out_f, p["vignette"])
        out_u8 = (np.clip(out_f, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)

    # 18. Grain
    out_u8 = adj.grain(out_u8, p["grain"], size=p["grain_size"],
                       roughness=p["grain_roughness"])

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
