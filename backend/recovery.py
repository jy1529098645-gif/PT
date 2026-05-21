"""Highlight recovery algorithms.

The functions here all operate on a linear float32 RGB array in [0, 1]
shape HxWx3. Returning the same dtype/range keeps the pipeline composable.

Algorithms (all professionally used in commercial RAW developers):

1. ``luminance_mask`` - Mask-based highlight compression with smooth
   feathering. The reference approach used by darktable's "highlight
   compression" module and Lightroom's Highlights slider.

2. ``channel_aware`` - Per-channel Reinhard-style roll-off that
   preserves chromaticity by compressing each channel with awareness of
   the local max. Used by Capture One's "Highlight" tool.

3. ``hsl_compression`` - Convert to HSL, compress L only, re-saturate.
   Preserves hue cleanly which matters for skin and skies.

4. ``detail_preserving`` - Durand-style bilateral base/detail
   decomposition. Compress the base layer, keep detail. Best when you
   want texture back in fabrics or clouds.

5. ``exposure_fusion`` - Mertens multi-exposure fusion synthesized from
   the linear RAW data. Gives the most aggressive recovery (effectively
   a tone-mapped HDR) while keeping naturalness via local weighting.

6. ``filmic_curve`` - Filmic / Blender-style log-roll-off curve in
   linear space. Smooth, cinematic, no banding.
"""
from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np

# Rec.709 luminance weights used everywhere here (matches sRGB primaries).
LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def _luminance(rgb: np.ndarray) -> np.ndarray:
    return (rgb * LUMA_WEIGHTS).sum(axis=-1)


def _smooth_mask(luma: np.ndarray, threshold: float, feather_px: float) -> np.ndarray:
    """Build a feathered [0,1] mask of pixels brighter than threshold."""
    raw_mask = np.clip((luma - threshold) / max(1e-4, 1.0 - threshold), 0.0, 1.0)
    raw_mask = raw_mask ** 1.5  # bias toward the brightest pixels
    if feather_px > 0.5:
        ksize = int(max(3, round(feather_px * 2) | 1))
        raw_mask = cv2.GaussianBlur(raw_mask, (ksize, ksize), feather_px)
    return raw_mask.astype(np.float32)


def _knee_curve(x: np.ndarray, knee: float, strength: float) -> np.ndarray:
    """Soft highlight compression above ``knee`` — output is always ≤ input.

    Below the knee the curve is the identity. Above the knee it pulls
    bright values toward (but never past) 1.0 along a rational
    concave function that has ``y' = 1`` at the knee point, so there
    is no visible seam where compression begins.

    The formula is ``y = knee + (1 - knee) * t / (1 + a*t)`` with
    ``t = (x - knee) / (1 - knee)`` and ``a = 8 * strength``.

    Why this and not ``(1 - exp(-k*t)) / (1 - exp(-k))`` (the previous
    formulation): that normalized exponential, although it looks like
    a "soft saturation" curve, actually maps the knee endpoint (x=1)
    back to 1 by construction and bows ABOVE the y=x identity in
    between — i.e. it brightens highlights instead of darkening them.
    The rational form below stays strictly below identity:

        d/dt [knee + (1-knee)*t/(1+a*t)] = (1-knee) / (1+a*t)^2

    which is ≤ (1 - knee) for a, t ≥ 0; integrated from knee that
    keeps the curve ≤ x. Proof: ``t/(1+a*t) ≤ t ↔ 0 ≤ a t²``.

    Parameters
    ----------
    knee : float in [0, 0.99]
        Where compression begins.
    strength : float in [0, 1]
        At 0 the curve is the identity. At 1 an input of x=1 is pulled
        down to roughly ``knee + 0.11 * (1-knee)`` (~78% of the way
        toward the knee — strong but not crushing).
    """
    knee = float(np.clip(knee, 0.0, 0.99))
    strength = float(np.clip(strength, 0.0, 1.0))
    if strength <= 1e-6:
        return x.copy()

    out = x.copy()
    above = x > knee
    if above.any():
        t = (x[above] - knee) / max(1.0 - knee, 1e-6)
        t = np.maximum(t, 0.0)
        a = 8.0 * strength
        compressed = t / (1.0 + a * t)
        compressed = np.minimum(compressed, 1.0)  # safety cap for x ≫ 1
        out[above] = knee + (1.0 - knee) * compressed
    return out


# ---------------------------------------------------------------------------
# 1. Luminance-mask compression
# ---------------------------------------------------------------------------

def luminance_mask(
    rgb: np.ndarray,
    *,
    strength: float = 0.5,
    threshold: float = 0.75,
    feather: float = 12.0,
    color_preservation: float = 0.7,
) -> np.ndarray:
    """Compress only the masked highlight regions, preserve color via ratio.

    Working pixel-by-pixel on luminance keeps hue stable. ``color_preservation``
    blends between (a) scaling each RGB channel by the luminance ratio and
    (b) applying the same curve to each channel independently. (a) preserves
    chromaticity but can clip; (b) desaturates highlights gracefully.
    """
    luma = _luminance(rgb)
    mask = _smooth_mask(luma, threshold, feather)

    # Compressed luminance
    luma_c = _knee_curve(luma, threshold, strength)
    # Ratio path (color preserving) - scale channels by new/old luminance
    safe_luma = np.maximum(luma, 1e-5)
    ratio = (luma_c / safe_luma)[..., None]
    rgb_ratio = rgb * ratio
    # Per-channel path (desaturates highlights, prevents nuclear color)
    rgb_per_ch = _knee_curve(rgb, threshold, strength)

    cp = float(np.clip(color_preservation, 0.0, 1.0))
    rgb_compressed = cp * rgb_ratio + (1.0 - cp) * rgb_per_ch

    # Blend in only the masked region
    m = mask[..., None]
    out = rgb * (1.0 - m) + rgb_compressed * m
    return np.clip(out, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# 2. Channel-aware roll-off (Capture One / Reinhard-style)
# ---------------------------------------------------------------------------

def channel_aware(
    rgb: np.ndarray,
    *,
    strength: float = 0.5,
    threshold: float = 0.6,
    color_preservation: float = 0.85,
) -> np.ndarray:
    """Per-channel roll-off, then nudge toward equal-channel scaling.

    This catches the case where one channel is clipped (e.g. red in
    sunset) but others aren't - we compress all channels with the same
    curve so the resulting tristimulus stays on the camera's response
    curve rather than walking off into a hue shift.
    """
    rgb_curve = _knee_curve(rgb, threshold, strength)

    # Color-preserving variant: compress by the max channel, scale uniformly
    max_ch = rgb.max(axis=-1, keepdims=True)
    safe_max = np.maximum(max_ch, 1e-5)
    max_ch_c = _knee_curve(max_ch, threshold, strength)
    rgb_uniform = rgb * (max_ch_c / safe_max)

    cp = float(np.clip(color_preservation, 0.0, 1.0))
    out = cp * rgb_uniform + (1.0 - cp) * rgb_curve
    return np.clip(out, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# 3. HSL compression (hue-stable)
# ---------------------------------------------------------------------------

def hsl_compression(
    rgb: np.ndarray,
    *,
    strength: float = 0.5,
    threshold: float = 0.75,
    feather: float = 10.0,
    saturation_recovery: float = 0.15,
) -> np.ndarray:
    """Compress L in HSL, optionally rebuild saturation in highlights.

    OpenCV's HLS uses H in [0, 360], L and S in [0, 1] when float input
    is supplied. We work in float to avoid 8-bit banding.
    """
    bgr = rgb[..., ::-1].astype(np.float32)
    hls = cv2.cvtColor(bgr, cv2.COLOR_BGR2HLS)
    h, l, s = hls[..., 0], hls[..., 1], hls[..., 2]

    mask = _smooth_mask(l, threshold, feather)
    l_c = _knee_curve(l, threshold, strength)
    l_new = l * (1.0 - mask) + l_c * mask

    # Boost saturation slightly in recovered highlights so they don't look gray
    sr = float(np.clip(saturation_recovery, 0.0, 1.0))
    if sr > 1e-3:
        s = s + mask * sr * (1.0 - s)
        s = np.clip(s, 0.0, 1.0)

    hls_new = np.stack([h, l_new, s], axis=-1)
    bgr_new = cv2.cvtColor(hls_new, cv2.COLOR_HLS2BGR)
    return np.clip(bgr_new[..., ::-1], 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# 4. Detail-preserving bilateral compression (Durand 2002)
# ---------------------------------------------------------------------------

def detail_preserving(
    rgb: np.ndarray,
    *,
    strength: float = 0.6,
    threshold: float = 0.7,
    local_contrast: float = 0.3,
) -> np.ndarray:
    """Bilateral base/detail decomposition in log luminance.

    base = bilateral(log L)
    detail = log L - base
    log L' = compress(base) + (1 + local_contrast) * detail
    """
    luma = _luminance(rgb) + 1e-4
    log_l = np.log(luma)

    # Bilateral filter on log luminance
    # OpenCV expects either uint8 or float32 single channel; rescale to a
    # sensible range first so sigma values are meaningful.
    log_l_norm = (log_l - log_l.min()) / max(1e-4, log_l.max() - log_l.min())
    h, w = log_l.shape
    sigma_space = max(8.0, min(h, w) / 80.0)
    base_norm = cv2.bilateralFilter(log_l_norm.astype(np.float32), d=0,
                                    sigmaColor=0.08, sigmaSpace=sigma_space)
    base = base_norm * (log_l.max() - log_l.min()) + log_l.min()
    detail = log_l - base

    base_compressed = np.log(_knee_curve(np.exp(base), threshold, strength) + 1e-6)
    log_l_new = base_compressed + (1.0 + float(np.clip(local_contrast, 0.0, 1.0))) * detail
    luma_new = np.exp(log_l_new)

    # Re-apply to RGB via luminance ratio (preserves chromaticity)
    ratio = (luma_new / luma)[..., None]
    out = rgb * ratio
    return np.clip(out, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# 5. Mertens exposure fusion synthesized from linear RAW
# ---------------------------------------------------------------------------

def exposure_fusion(
    rgb_linear: np.ndarray,
    *,
    strength: float = 0.7,
    ev_offsets: Tuple[float, ...] = (-2.0, -1.0, 0.0),
) -> np.ndarray:
    """Mertens fusion of virtual exposures derived from the linear RAW.

    Because we're starting from linear data, "underexposing" is just a
    multiply - no information is lost. We tone-map each virtual exposure
    with sRGB gamma, hand them to Mertens, and blend the result with the
    base image by ``strength``.
    """
    exposures = []
    for ev in ev_offsets:
        e = rgb_linear * (2.0 ** ev)
        e = np.clip(e, 0.0, 1.0)
        # sRGB encode so Mertens' contrast/saturation/exposedness weights
        # operate in a perceptual space.
        e_srgb = _linear_to_srgb(e)
        exposures.append((e_srgb * 255.0).astype(np.uint8))

    merge = cv2.createMergeMertens(1.0, 1.0, 1.0)
    fused = merge.process(exposures)  # float32 in roughly [0, 1]
    fused = np.clip(fused, 0.0, 1.0)
    # Convert back to linear for consistency with the rest of the pipeline.
    fused_linear = _srgb_to_linear(fused)

    base_linear = np.clip(rgb_linear, 0.0, 1.0)
    s = float(np.clip(strength, 0.0, 1.0))
    out = base_linear * (1.0 - s) + fused_linear * s
    return out.astype(np.float32)


# ---------------------------------------------------------------------------
# 6. Filmic / cinematic roll-off (Blender-style)
# ---------------------------------------------------------------------------

def filmic_curve(
    rgb: np.ndarray,
    *,
    strength: float = 0.5,
    threshold: float = 0.65,
    contrast: float = 0.05,
) -> np.ndarray:
    """Filmic / shoulder-style highlight roll-off.

    Same rational compression as ``_knee_curve`` but with an optional
    ``t^p`` shoulder (controlled by ``contrast``) that delays the onset
    of compression slightly so midtones stay snappy while the highlights
    saturate softly — the visual signature of motion-picture print film.

    Always strictly compressing (output ≤ input above the threshold).
    """
    if strength <= 1e-6:
        return rgb.copy()

    a = 6.0 * strength
    p = 1.0 + float(np.clip(contrast, 0.0, 1.0)) * 0.6

    out = rgb.copy()
    above = rgb > threshold
    if above.any():
        t = (rgb[above] - threshold) / max(1.0 - threshold, 1e-6)
        t = np.maximum(t, 0.0)
        u = np.power(t, p)
        compressed = u / (1.0 + a * u)
        compressed = np.minimum(compressed, 1.0)
        out[above] = threshold + (1.0 - threshold) * compressed
    return np.clip(out, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# sRGB gamma helpers
# ---------------------------------------------------------------------------

def _linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    a = 0.055
    return np.where(x <= 0.0031308,
                    12.92 * x,
                    (1.0 + a) * np.power(np.maximum(x, 1e-10), 1.0 / 2.4) - a)


def _srgb_to_linear(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    a = 0.055
    return np.where(x <= 0.04045,
                    x / 12.92,
                    np.power((x + a) / (1.0 + a), 2.4))


# Public exports used by the pipeline dispatcher.
METHODS = {
    "luminance_mask": luminance_mask,
    "channel_aware": channel_aware,
    "hsl_compression": hsl_compression,
    "detail_preserving": detail_preserving,
    "exposure_fusion": exposure_fusion,
    "filmic_curve": filmic_curve,
}
