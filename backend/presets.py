"""Built-in presets covering highlight recovery + iPhone-style edits.

Each preset is a full parameter set the pipeline can apply directly.
Parameters omitted from a preset fall back to ``default_params``.

User-facing parameter scales:
    exposure          - EV, [-2.0, +2.0]
    highlights        - [-100, +100], negative = pull down
    whites            - [-100, +100]
    shadows           - [-100, +100], positive = lift
    black_point       - [-100, +100], positive = lift blacks
    brightness        - [-100, +100], midtone gamma
    brilliance        - [-100, +100], Apple-style adaptive
    contrast          - [-100, +100], S-curve
    warmth            - [-100, +100], positive = warmer
    tint              - [-100, +100], positive = magenta
    saturation        - [-100, +100]
    vibrance          - [-100, +100], selective sat
    definition        - [-100, +100], clarity (midtone local-contrast)
    sharpness         - [0, 100]
    noise_reduction   - [0, 100]
    vignette          - [-100, +100], negative = darken edges
    threshold         - [0, 100], highlight recovery start
    smoothness        - [0, 100], mask feather
    color_preservation- [0, 100]
    local_contrast    - [-100, +100], for detail_preserving / filmic
    saturation_recovery - [0, 100]
    method            - recovery algorithm key
"""
from __future__ import annotations

from typing import Any, Dict, List


def default_params() -> Dict[str, Any]:
    """Identity defaults — pipeline becomes near-no-op."""
    return {
        "exposure": 0.0,
        "highlights": 0,
        "whites": 0,
        "shadows": 0,
        "black_point": 0,
        "brightness": 0,
        "brilliance": 0,
        "contrast": 0,
        "warmth": 0,
        "tint": 0,
        "saturation": 0,
        "vibrance": 0,
        "definition": 0,
        "sharpness": 0,
        "noise_reduction": 0,
        "vignette": 0,
        "threshold": 75,
        "smoothness": 20,
        "color_preservation": 75,
        "local_contrast": 0,
        "saturation_recovery": 0,
        "method": "luminance_mask",
        "local_masks": [],
    }


PRESETS: Dict[str, Dict[str, Any]] = {
    # ----- highlight-recovery focused -------------------------------------
    "natural_subtle": {
        "name": "自然微调",
        "description": "轻度高光压缩，保留自然观感。日常照片首选。",
        "params": {
            "highlights": -30, "whites": -10, "shadows": 5,
            "threshold": 75, "smoothness": 25, "color_preservation": 75,
            "saturation_recovery": 10, "method": "luminance_mask",
            "vibrance": 8,
        },
    },
    "strong_recovery": {
        "name": "强力恢复",
        "description": "大幅压暗高光，挽回严重过曝。",
        "params": {
            "exposure": -0.3, "highlights": -80, "whites": -40, "shadows": 15,
            "threshold": 55, "smoothness": 30, "color_preservation": 85,
            "local_contrast": 30, "saturation_recovery": 20,
            "method": "channel_aware",
            "vibrance": 12, "definition": 15,
        },
    },
    "sky_blue": {
        "name": "天空恢复",
        "description": "针对过曝天空：恢复云层细节与蓝调。",
        "params": {
            "exposure": -0.2, "highlights": -70, "whites": -30,
            "threshold": 60, "smoothness": 25, "color_preservation": 95,
            "saturation_recovery": 25, "method": "luminance_mask",
            "vibrance": 20, "warmth": -8, "saturation": 8,
        },
    },
    "portrait_skin": {
        "name": "人像高光",
        "description": "保护皮肤高光与色相。",
        "params": {
            "highlights": -40, "whites": -15, "shadows": 8,
            "threshold": 78, "smoothness": 22, "color_preservation": 90,
            "method": "hsl_compression",
            "warmth": 5, "vibrance": 10, "definition": -8, "sharpness": 25,
        },
    },
    "wedding_whites": {
        "name": "婚纱白色",
        "description": "找回白色衣物的褶皱与质感。",
        "params": {
            "exposure": -0.1, "highlights": -65, "whites": -25, "shadows": 10,
            "threshold": 70, "smoothness": 18, "color_preservation": 60,
            "local_contrast": 45, "method": "detail_preserving",
            "definition": 25, "sharpness": 30,
        },
    },
    "interior_window": {
        "name": "室内窗外",
        "description": "极强力恢复：室内拍摄窗户严重过曝。",
        "params": {
            "exposure": -0.5, "highlights": -95, "whites": -60, "shadows": 25,
            "threshold": 50, "smoothness": 35, "color_preservation": 80,
            "local_contrast": 50, "saturation_recovery": 30,
            "method": "exposure_fusion",
            "vibrance": 15, "brilliance": 20,
        },
    },
    "landscape_hdr": {
        "name": "风光 HDR",
        "description": "风光摄影 HDR 风格：天空与阴影平衡。",
        "params": {
            "highlights": -75, "whites": -20, "shadows": 30,
            "threshold": 60, "smoothness": 25, "color_preservation": 85,
            "local_contrast": 45, "saturation_recovery": 25,
            "method": "exposure_fusion",
            "brilliance": 25, "vibrance": 20, "definition": 20, "vignette": -10,
        },
    },
    "cinematic": {
        "name": "电影感",
        "description": "胶片质感：柔和高光，低对比，冷调。",
        "params": {
            "highlights": -55, "whites": -35, "shadows": 12,
            "threshold": 65, "smoothness": 30, "color_preservation": 80,
            "method": "filmic_curve",
            "contrast": -10, "warmth": -12, "tint": 5, "saturation": -8,
            "vignette": -15,
        },
    },
    "stage_concert": {
        "name": "舞台演唱会",
        "description": "射灯环境：压暗高光，恢复服装细节。",
        "params": {
            "exposure": -0.2, "highlights": -85, "whites": -50, "shadows": 35,
            "threshold": 55, "smoothness": 28, "color_preservation": 75,
            "local_contrast": 35, "saturation_recovery": 20,
            "method": "channel_aware",
            "vibrance": 15, "definition": 20,
        },
    },
    "snow_beach": {
        "name": "雪景 / 海滩",
        "description": "高反光环境：找回雪地、沙滩、海面层次。",
        "params": {
            "exposure": -0.4, "highlights": -70, "whites": -45,
            "threshold": 65, "smoothness": 22, "color_preservation": 70,
            "local_contrast": 25, "saturation_recovery": 15,
            "method": "detail_preserving",
            "vibrance": 15, "warmth": 3,
        },
    },

    # ----- iPhone-style look presets --------------------------------------
    "vivid": {
        "name": "鲜明",
        "description": "iPhone Vivid 风格：高饱和、强对比、增强清晰度。",
        "params": {
            "highlights": -25, "shadows": 18, "brilliance": 15,
            "contrast": 22, "vibrance": 30, "saturation": 10,
            "definition": 18, "sharpness": 20,
            "method": "luminance_mask",
        },
    },
    "vivid_warm": {
        "name": "鲜明暖色",
        "description": "iPhone Vivid Warm：暖色调 + 强对比 + 提高鲜明度。",
        "params": {
            "highlights": -28, "shadows": 15, "brilliance": 18,
            "contrast": 18, "vibrance": 25, "saturation": 8,
            "warmth": 18, "definition": 15,
            "method": "luminance_mask",
        },
    },
    "dramatic": {
        "name": "戏剧",
        "description": "iPhone Dramatic：高对比、阴影下压、增强氛围。",
        "params": {
            "highlights": -45, "shadows": -10, "black_point": -8,
            "contrast": 28, "vibrance": 15, "saturation": -5,
            "definition": 22, "vignette": -18,
            "method": "luminance_mask",
        },
    },
    "mono_silver": {
        "name": "银调黑白",
        "description": "iPhone Silvertone 风格：黑白片，柔和中间调。",
        "params": {
            "highlights": -25, "shadows": 15, "brilliance": 10,
            "contrast": 12, "saturation": -100,
            "definition": 12, "sharpness": 18,
            "method": "luminance_mask",
        },
    },
    "auto_enhance": {
        "name": "自动增强",
        "description": "类似 iPhone 「自动」按钮：智能恢复 + 适度提亮 + 微对比。",
        "params": {
            "highlights": -35, "shadows": 20, "black_point": 3,
            "brilliance": 22, "contrast": 8, "brightness": 5,
            "vibrance": 18, "definition": 12, "sharpness": 15,
            "method": "luminance_mask",
        },
    },
}


def list_presets() -> List[Dict[str, Any]]:
    return [
        {"id": pid, "name": p["name"], "description": p["description"], "params": p["params"]}
        for pid, p in PRESETS.items()
    ]
