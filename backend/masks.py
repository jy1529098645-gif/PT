"""Local-adjustment masks (radial + linear gradient).

Both mask types produce a float32 HxW array in [0, 1] that the pipeline
uses to blend a locally-adjusted copy with the base image:

    output = base * (1 - mask) + adjusted * mask

All geometric parameters are stored in **normalized** image coordinates
(0..1 along width / height) so the same mask works for a 1400px preview
and a 24 MP export without re-fitting.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

import numpy as np


def _smoothstep(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def build_radial_mask(
    h: int, w: int,
    cx: float, cy: float,
    rx: float, ry: float,
    rotation: float,
    feather: float,
    *,
    invert: bool = False,
) -> np.ndarray:
    """Soft elliptical mask. ``cx, cy, rx, ry`` in normalized image coords.

    ``feather`` in [0, 1] controls the softness band relative to the
    ellipse radius. ``invert=True`` flips the mask (everything outside
    the ellipse).
    """
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    long_side = float(max(w, h))
    cxp, cyp = float(cx) * w, float(cy) * h
    rxp = max(float(rx) * long_side, 4.0)
    ryp = max(float(ry) * long_side, 4.0)

    ct, st = float(np.cos(rotation)), float(np.sin(rotation))
    dx = (xx - cxp) * ct + (yy - cyp) * st
    dy = -(xx - cxp) * st + (yy - cyp) * ct
    d = np.sqrt((dx / rxp) ** 2 + (dy / ryp) ** 2)

    f = float(np.clip(feather, 0.02, 1.0))
    inner = max(0.0, 1.0 - f)
    mask = 1.0 - _smoothstep((d - inner) / max(1.0 - inner, 1e-3))
    if invert:
        mask = 1.0 - mask
    return mask.astype(np.float32)


def build_linear_mask(
    h: int, w: int,
    x1: float, y1: float,
    x2: float, y2: float,
    *,
    invert: bool = False,
) -> np.ndarray:
    """Linear gradient. 1 at (x1,y1), 0 at (x2,y2), smooth in-between.

    Geometry in normalized image coords. The mask uses a smoothstep so
    the transition isn't a hard linear ramp.
    """
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    x1p, y1p = x1 * w, y1 * h
    x2p, y2p = x2 * w, y2 * h
    dx = x2p - x1p
    dy = y2p - y1p
    L2 = dx * dx + dy * dy + 1e-3
    t = ((xx - x1p) * dx + (yy - y1p) * dy) / L2
    mask = 1.0 - _smoothstep(t)
    if invert:
        mask = 1.0 - mask
    return mask.astype(np.float32)


def build_mask(spec: Dict[str, Any], h: int, w: int) -> np.ndarray:
    """Dispatch on ``spec['type']``."""
    typ = (spec.get("type") or "radial").lower()
    invert = bool(spec.get("invert"))
    if typ == "radial":
        return build_radial_mask(
            h, w,
            cx=float(spec.get("cx", 0.5)),
            cy=float(spec.get("cy", 0.5)),
            rx=float(spec.get("rx", 0.2)),
            ry=float(spec.get("ry", 0.2)),
            rotation=float(spec.get("rotation", 0.0)),
            feather=float(spec.get("feather", 0.4)),
            invert=invert,
        )
    if typ == "linear":
        return build_linear_mask(
            h, w,
            x1=float(spec.get("x1", 0.5)),
            y1=float(spec.get("y1", 0.0)),
            x2=float(spec.get("x2", 0.5)),
            y2=float(spec.get("y2", 1.0)),
            invert=invert,
        )
    # Unknown type -> all-zero (no-op)
    return np.zeros((h, w), dtype=np.float32)


def collect_masks(specs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter / sanitize an incoming list of mask specs."""
    out: List[Dict[str, Any]] = []
    for s in specs or []:
        if not isinstance(s, dict):
            continue
        if not s.get("enabled", True):
            continue
        out.append(s)
    return out
