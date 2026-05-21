"""iPhone-style basic adjustments + professional global edits.

Each function operates on float32 RGB in [0, 1], either linear or sRGB
(noted per-function). Returns the same dtype/range. Functions short-circuit
when the parameter is near zero to keep preview latency down.

References:
- Brilliance: Apple's adaptive tonal compression (highlight pull + shadow lift
  + midtone clarity). Reverse-engineered from Photos.app behavior.
- Vibrance: Adobe's selective saturation - boost weighted by (1 - current_sat).
- Definition / Clarity: large-radius unsharp mask masked to midtones.
- Sharpness: classic unsharp mask (USM).
- Warmth / Tint: shift along blue-yellow and green-magenta axes. The
  professional approach uses chromatic adaptation matrices (Bradford or
  CAT16) - here we approximate with channel-scale, which matches Photos'
  visual behavior closely while staying fast.
- Noise Reduction: bilateral filter for preview (fast), Non-Local-Means
  for export (high quality, slow).
- Vignette: radial multiply with quadratic falloff (Lightroom-style).
"""
from __future__ import annotations

import cv2
import numpy as np

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def luma(rgb: np.ndarray) -> np.ndarray:
    return (rgb * LUMA).sum(axis=-1)


# ----------------------------------------------------------------------------
# Tonal (operate in linear space, before sRGB encode)
# ----------------------------------------------------------------------------

def exposure(rgb: np.ndarray, ev: float) -> np.ndarray:
    """Linear gain by 2^ev."""
    if abs(ev) < 1e-3:
        return rgb
    return rgb * (2.0 ** ev)


def whites(rgb: np.ndarray, amount: float) -> np.ndarray:
    """Push/pull the top end above 0.7 luminance."""
    if abs(amount) < 1.0:
        return rgb
    w = amount / 100.0
    L = luma(rgb)
    t = np.clip((L - 0.7) / 0.3, 0.0, 1.0)[..., None]
    gain = 1.0 + w * 0.30 * t
    return rgb * gain


def shadows(rgb: np.ndarray, amount: float) -> np.ndarray:
    """Lift / crush the bottom end below 0.45 luminance."""
    if abs(amount) < 1.0:
        return rgb
    s = amount / 100.0
    L = luma(rgb)
    toe = (np.clip(1.0 - L / 0.45, 0.0, 1.0) ** 1.5)[..., None]
    return rgb + s * 0.28 * toe


def black_point(rgb: np.ndarray, amount: float) -> np.ndarray:
    """Shift the bottom endpoint. Positive = lift blacks, negative = crush."""
    if abs(amount) < 1.0:
        return rgb
    b = amount / 100.0
    if b > 0:
        offset = b * 0.18
        return rgb * (1.0 - offset) + offset
    else:
        crush = -b * 0.20
        out = (rgb - crush) / max(1.0 - crush, 1e-3)
        return np.clip(out, 0.0, None)


def brightness(rgb: np.ndarray, amount: float) -> np.ndarray:
    """Gamma-based midtone brightness (matches Photos.app behavior)."""
    if abs(amount) < 1.0:
        return rgb
    b = amount / 100.0
    gamma = 1.0 / (1.0 + b * 0.65)
    return np.power(np.clip(rgb, 0.0, None), gamma)


def brilliance(rgb: np.ndarray, amount: float) -> np.ndarray:
    """Apple's Brilliance: adaptive shadow lift + highlight pull + clarity.

    Positive value: brighten shadows, recover highlights, gentle midtone
    pop. Negative: flatten the image.
    """
    if abs(amount) < 1.0:
        return rgb
    b = amount / 100.0
    L = luma(np.clip(rgb, 0.0, 1.0))[..., None]
    if b > 0:
        shadow_lift = np.power(1.0 - L, 2.2) * b * 0.18
        highlight_pull = np.power(L, 2.0) * b * 0.14
        out = rgb + shadow_lift - highlight_pull
        # Slight local-contrast bump (small radius unsharp on luminance)
        h, w = rgb.shape[:2]
        sigma = max(2.0, min(h, w) / 200.0)
        blurred_L = cv2.GaussianBlur(L.squeeze(-1), (0, 0), sigmaX=sigma)[..., None]
        out = out + (L - blurred_L) * b * 0.5
        return np.clip(out, 0.0, None)
    else:
        # Flatten: mix toward mid-gray, keep colors
        return rgb * (1.0 + b * 0.20) + 0.5 * (-b) * 0.20


def contrast(rgb: np.ndarray, amount: float) -> np.ndarray:
    """Symmetric S-curve / inverse-S contrast in sRGB-space."""
    if abs(amount) < 1.0:
        return rgb
    c = amount / 100.0
    x = np.clip(rgb, 0.0, 1.0)
    if c > 0:
        # Sigmoid centered at 0.5; k controls steepness
        k = 3.0 + c * 5.0
        out = 1.0 / (1.0 + np.exp(-k * (x - 0.5)))
        # Renormalize so 0->0, 1->1
        out_min = 1.0 / (1.0 + np.exp(k * 0.5))
        out_max = 1.0 / (1.0 + np.exp(-k * 0.5))
        out = (out - out_min) / max(out_max - out_min, 1e-6)
    else:
        # Reduce contrast: lerp toward 0.5
        out = x * (1.0 - (-c) * 0.6) + 0.5 * (-c) * 0.6
    return np.clip(out, 0.0, 1.0)


# ----------------------------------------------------------------------------
# Color (white balance + saturation)
# ----------------------------------------------------------------------------

def warmth_tint(rgb: np.ndarray, warmth: float, tint: float) -> np.ndarray:
    """Shift along WB axes. Warmth: blue<->yellow. Tint: green<->magenta.

    Approximates a chromatic-adaptation transform with simple channel
    gains. ``warmth`` positive = warmer (more red/yellow). ``tint``
    positive = magenta, negative = green.
    """
    if abs(warmth) < 1.0 and abs(tint) < 1.0:
        return rgb
    w = warmth / 100.0
    t = tint / 100.0
    r_gain = 1.0 + w * 0.22 + t * 0.06
    g_gain = 1.0 - t * 0.12
    b_gain = 1.0 - w * 0.22 + t * 0.06
    out = rgb.copy()
    out[..., 0] *= r_gain
    out[..., 1] *= g_gain
    out[..., 2] *= b_gain
    return np.clip(out, 0.0, None)


def saturation(rgb: np.ndarray, amount: float) -> np.ndarray:
    """Global saturation: pull toward / away from per-pixel luma."""
    if abs(amount) < 1.0:
        return rgb
    s = amount / 100.0
    L = luma(rgb)[..., None]
    return np.clip(L + (rgb - L) * (1.0 + s), 0.0, None)


def vibrance(rgb: np.ndarray, amount: float) -> np.ndarray:
    """Vibrance: boost less-saturated colors more (Adobe-style)."""
    if abs(amount) < 1.0:
        return rgb
    v = amount / 100.0
    cmax = rgb.max(axis=-1)
    cmin = rgb.min(axis=-1)
    cur_sat = np.where(cmax > 1e-4, (cmax - cmin) / np.maximum(cmax, 1e-4), 0.0)
    factor = 1.0 + v * (1.0 - cur_sat[..., None]) * 0.9
    L = luma(rgb)[..., None]
    return np.clip(L + (rgb - L) * factor, 0.0, None)


# ----------------------------------------------------------------------------
# Detail (operate in sRGB space, post tone-mapping)
# ----------------------------------------------------------------------------

def sharpness(rgb_u8: np.ndarray, amount: float) -> np.ndarray:
    """Unsharp mask sharpening. Operates on uint8."""
    if amount < 1.0:
        return rgb_u8
    a = amount / 100.0
    blurred = cv2.GaussianBlur(rgb_u8, (0, 0), sigmaX=1.0)
    fimg = rgb_u8.astype(np.float32)
    fblur = blurred.astype(np.float32)
    sharpened = fimg + a * 1.4 * (fimg - fblur)
    return np.clip(sharpened, 0.0, 255.0).astype(np.uint8)


def definition(rgb_u8: np.ndarray, amount: float) -> np.ndarray:
    """Clarity: large-radius unsharp mask, masked to midtones.

    Operates on uint8 because we want it after sRGB encode (perceptual).
    Negative value gives a dreamy / softened look (anti-clarity).
    """
    if abs(amount) < 1.0:
        return rgb_u8
    a = amount / 100.0
    h, w = rgb_u8.shape[:2]
    sigma = max(8.0, min(h, w) / 90.0)
    blurred = cv2.GaussianBlur(rgb_u8, (0, 0), sigmaX=sigma).astype(np.float32)
    fimg = rgb_u8.astype(np.float32)

    L = (fimg * LUMA).sum(axis=-1) / 255.0
    midmask = (1.0 - np.abs(L - 0.5) * 1.8)
    midmask = np.clip(midmask, 0.0, 1.0)[..., None]

    detail = fimg - blurred
    out = fimg + a * 1.6 * detail * midmask
    return np.clip(out, 0.0, 255.0).astype(np.uint8)


def noise_reduction(rgb_u8: np.ndarray, amount: float, *, high_quality: bool = False) -> np.ndarray:
    """Denoise. Bilateral for fast preview, NLM for export.

    OpenCV's fastNlMeansDenoisingColored converts the input to LAB
    internally to separate luminance from chroma, and that conversion
    assumes BGR channel order. Bilateral filter is order-agnostic so
    we can pass RGB directly.
    """
    if amount < 1.0:
        return rgb_u8
    a = amount / 100.0
    if high_quality:
        h_strength = a * 12.0 + 3.0
        bgr = cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2BGR)
        bgr = cv2.fastNlMeansDenoisingColored(
            bgr, None, h=h_strength, hColor=h_strength,
            templateWindowSize=7, searchWindowSize=21,
        )
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    sigma_color = a * 32.0 + 6.0
    sigma_space = a * 6.0 + 4.0
    return cv2.bilateralFilter(rgb_u8, d=-1, sigmaColor=float(sigma_color), sigmaSpace=float(sigma_space))


# ----------------------------------------------------------------------------
# Effects
# ----------------------------------------------------------------------------

def vignette(rgb: np.ndarray, amount: float) -> np.ndarray:
    """Radial darken (-) or lighten (+) from image center. Quadratic falloff."""
    if abs(amount) < 1.0:
        return rgb
    a = amount / 100.0
    h, w = rgb.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = (w - 1) * 0.5, (h - 1) * 0.5
    max_r = np.sqrt(cx * cx + cy * cy)
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / max(max_r, 1.0)
    if a < 0:
        gain = 1.0 + a * 0.85 * (r ** 2.2)
    else:
        gain = 1.0 + a * 0.30 * (r ** 2.2)
    return np.clip(rgb * gain[..., None], 0.0, None)
