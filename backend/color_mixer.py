"""HSL Color Mixer + Color Grading — Camera Raw style.

HSL Mixer
---------
8 hue bands (Red, Orange, Yellow, Green, Aqua, Blue, Purple, Magenta)
each with three controls:
    - Hue: shift the color along the hue circle (±30°)
    - Saturation: scale per-band saturation (±100 -> ×0..×2)
    - Luminance: shift per-band brightness (±100 -> ±30%)

Implementation: compute a smooth weight per hue band per pixel (overlapping
Gaussian-like falloffs that taper to zero at ±45° from each band center),
then apply weighted adjustments in HSV space and convert back.

Color Grading
-------------
Three tonal ranges (shadows / midtones / highlights), each with hue + saturation.
A "blending" slider widens the overlap between ranges, and "balance" shifts the
midpoint between shadow-emphasis and highlight-emphasis. Implementation is a
small color offset added to each pixel proportional to its tonal-range weights.
"""
from __future__ import annotations

from typing import Any, Dict

import cv2
import numpy as np

# Hue centers in degrees, in the order Camera Raw uses.
HSL_BANDS = ("red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta")
HSL_CENTERS = np.array([0.0, 30.0, 60.0, 130.0, 175.0, 230.0, 285.0, 330.0],
                       dtype=np.float32)
_BAND_HALF = 45.0  # half-width of the falloff window in degrees


def _hue_masks(H: np.ndarray) -> np.ndarray:
    """Soft per-band masks over the 8 ACR hue centers.

    ``H`` is HxW in [0, 360]. Returns HxWx8 in [0, 1]. Adjacent bands
    overlap by design so a hue at e.g. 15° gets ~50% of red and ~50%
    of orange.
    """
    H_exp = H[..., None]
    delta = np.abs(H_exp - HSL_CENTERS[None, None, :])
    delta = np.minimum(delta, 360.0 - delta)
    # Tent function with smoothstep falloff
    m = np.clip(1.0 - delta / _BAND_HALF, 0.0, 1.0)
    return (m * m * (3.0 - 2.0 * m)).astype(np.float32)


def hsl_mixer(rgb: np.ndarray, hsl_params: Dict[str, Dict[str, float]]) -> np.ndarray:
    """Apply per-color HSL adjustments.

    ``hsl_params`` shape: ``{'red': {'h': h, 's': s, 'l': l}, 'orange': ...}``.
    All band values default to 0. Range: ±100 each.
    """
    if not hsl_params:
        return rgb
    # Are any values non-zero?
    any_active = False
    for band in HSL_BANDS:
        v = hsl_params.get(band) or {}
        if abs(v.get("h", 0)) > 0.5 or abs(v.get("s", 0)) > 0.5 or abs(v.get("l", 0)) > 0.5:
            any_active = True
            break
    if not any_active:
        return rgb

    bgr = rgb[..., ::-1].astype(np.float32)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    masks = _hue_masks(H)  # HxWx8

    h_shifts = np.zeros(8, dtype=np.float32)
    s_factors = np.zeros(8, dtype=np.float32)  # additive factor; result = 1 + sum
    v_shifts = np.zeros(8, dtype=np.float32)
    for i, band in enumerate(HSL_BANDS):
        v = hsl_params.get(band) or {}
        h_shifts[i] = float(v.get("h", 0)) * 0.30   # ±100 -> ±30°
        s_factors[i] = float(v.get("s", 0)) / 100.0  # ±100 -> ±1.0 multiplier delta
        v_shifts[i] = float(v.get("l", 0)) * 0.0030  # ±100 -> ±30%

    H_delta = (masks * h_shifts[None, None, :]).sum(axis=-1)
    S_factor = 1.0 + (masks * s_factors[None, None, :]).sum(axis=-1)
    V_delta = (masks * v_shifts[None, None, :]).sum(axis=-1)

    H_new = (H + H_delta) % 360.0
    S_new = np.clip(S * S_factor, 0.0, 1.0)
    V_new = np.clip(V + V_delta, 0.0, 1.0)

    hsv_new = np.stack([H_new, S_new, V_new], axis=-1)
    bgr_new = cv2.cvtColor(hsv_new, cv2.COLOR_HSV2BGR)
    return np.clip(bgr_new[..., ::-1], 0.0, 1.0).astype(np.float32)


# ----------------------------------------------------------------------------
# Color grading (3-range hue+sat tinting)
# ----------------------------------------------------------------------------

def _smoothstep_band(x: np.ndarray, edge0: float, edge1: float) -> np.ndarray:
    """Smoothstep that's 0 outside [edge0, edge1] and 1 inside, with smooth edges."""
    t = np.clip((x - edge0) / max(edge1 - edge0, 1e-4), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _hue_sat_to_offset(hue_deg: float, sat_pct: float) -> np.ndarray:
    """Convert a hue+saturation pair to a small RGB tint vector.

    ``sat_pct`` is in [-100, 100]. Negative sat inverts the tint (i.e. tint
    toward the complementary color), matching Lightroom's behavior.
    """
    if abs(sat_pct) < 0.5:
        return np.zeros(3, dtype=np.float32)
    h = (float(hue_deg) % 360.0) / 60.0
    c = 1.0  # fully saturated color
    x = 1.0 - abs((h % 2.0) - 1.0)
    if   h < 1: r, g, b = c, x, 0
    elif h < 2: r, g, b = x, c, 0
    elif h < 3: r, g, b = 0, c, x
    elif h < 4: r, g, b = 0, x, c
    elif h < 5: r, g, b = x, 0, c
    else:       r, g, b = c, 0, x
    rgb = np.array([r, g, b], dtype=np.float32)
    # Center around gray (0) so the offset is signed and can be subtracted too.
    rgb -= rgb.mean()
    scale = (sat_pct / 100.0) * 0.30  # ±30% peak shift
    return rgb * scale


def color_grading(
    rgb: np.ndarray,
    *,
    shadows_hue: float = 0.0, shadows_sat: float = 0.0,
    mids_hue:    float = 0.0, mids_sat:    float = 0.0,
    highlights_hue: float = 0.0, highlights_sat: float = 0.0,
    blending: float = 50.0,
    balance: float = 0.0,
) -> np.ndarray:
    """3-range color grade. Operates on float32 RGB in [0, 1]."""
    if all(abs(s) < 0.5 for s in (shadows_sat, mids_sat, highlights_sat)):
        return rgb

    # Tonal weights based on Rec.709 luminance.
    L = (rgb * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).sum(axis=-1)

    bal = float(np.clip(balance / 100.0, -1.0, 1.0))
    blend = float(np.clip(blending / 100.0, 0.0, 1.0))
    # Shadow center 0.25 by default; balance shifts both centers
    sh_center = 0.20 + bal * 0.08
    hl_center = 0.80 + bal * 0.08
    band = 0.10 + blend * 0.25   # how wide each range is

    # w_sh: bright where pixels are dark; w_hl: bright where pixels are bright
    w_sh = 1.0 - _smoothstep_band(L, sh_center - band, sh_center + band)
    w_hl = _smoothstep_band(L, hl_center - band, hl_center + band)
    w_mid = np.clip(1.0 - w_sh - w_hl, 0.0, 1.0)

    off_sh = _hue_sat_to_offset(shadows_hue, shadows_sat)
    off_mid = _hue_sat_to_offset(mids_hue,    mids_sat)
    off_hl = _hue_sat_to_offset(highlights_hue, highlights_sat)

    out = rgb.copy()
    out = out + off_sh[None, None, :] * w_sh[..., None]
    out = out + off_mid[None, None, :] * w_mid[..., None]
    out = out + off_hl[None, None, :] * w_hl[..., None]
    return np.clip(out, 0.0, 1.0).astype(np.float32)


# ----------------------------------------------------------------------------
# Coerce frontend payload
# ----------------------------------------------------------------------------

def coerce_hsl_params(raw: Any) -> Dict[str, Dict[str, float]]:
    """Accept ``{'red': {'h': ..., 's': ..., 'l': ...}, ...}`` from JSON."""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, float]] = {}
    for band in HSL_BANDS:
        v = raw.get(band) or {}
        if not isinstance(v, dict):
            continue
        out[band] = {
            "h": float(v.get("h", 0) or 0),
            "s": float(v.get("s", 0) or 0),
            "l": float(v.get("l", 0) or 0),
        }
    return out
