"""Built-in presets for highlight recovery.

Each preset is a complete parameter set that the pipeline can apply
without further user input. Users can choose one as a starting point
and then fine-tune individual sliders.

All numeric parameters use the **user-facing scale**:
    exposure          - EV, range [-2.0, +2.0]
    highlights        - [-100, +100], negative = pull down
    whites            - [-100, +100], affects top endpoint
    shadows           - [-100, +100], positive = lift
    threshold         - [0, 100], where compression kicks in
    smoothness        - [0, 100], feather softness
    color_preservation- [0, 100], higher = more saturated highlights
    local_contrast    - [-100, +100], positive = more detail
    saturation_recovery- [0, 100], rebuild color in recovered highlights
    method            - one of recovery.METHODS keys
"""
from __future__ import annotations

from typing import Any, Dict


PRESETS: Dict[str, Dict[str, Any]] = {
    "natural_subtle": {
        "name": "自然微调",
        "description": "轻度高光压缩，保留自然观感。日常照片首选。",
        "params": {
            "exposure": 0.0,
            "highlights": -30,
            "whites": -10,
            "shadows": 5,
            "threshold": 75,
            "smoothness": 25,
            "color_preservation": 75,
            "local_contrast": 10,
            "saturation_recovery": 10,
            "method": "luminance_mask",
        },
    },
    "strong_recovery": {
        "name": "强力恢复",
        "description": "大幅压暗高光，挽回严重过曝。可能略显平淡，再叠对比度更佳。",
        "params": {
            "exposure": -0.3,
            "highlights": -80,
            "whites": -40,
            "shadows": 15,
            "threshold": 55,
            "smoothness": 30,
            "color_preservation": 85,
            "local_contrast": 30,
            "saturation_recovery": 20,
            "method": "channel_aware",
        },
    },
    "sky_blue": {
        "name": "天空恢复",
        "description": "针对过曝天空：恢复云层细节与蓝调，保护饱和度。",
        "params": {
            "exposure": -0.2,
            "highlights": -70,
            "whites": -30,
            "shadows": 0,
            "threshold": 60,
            "smoothness": 25,
            "color_preservation": 95,
            "local_contrast": 25,
            "saturation_recovery": 25,
            "method": "luminance_mask",
        },
    },
    "portrait_skin": {
        "name": "人像高光",
        "description": "保护皮肤高光，避免肤色发灰。婚纱、人像通用。",
        "params": {
            "exposure": 0.0,
            "highlights": -40,
            "whites": -15,
            "shadows": 8,
            "threshold": 78,
            "smoothness": 22,
            "color_preservation": 90,
            "local_contrast": 5,
            "saturation_recovery": 10,
            "method": "hsl_compression",
        },
    },
    "wedding_whites": {
        "name": "婚纱白色",
        "description": "找回白色衣物的褶皱与质感，强调局部对比。",
        "params": {
            "exposure": -0.1,
            "highlights": -65,
            "whites": -25,
            "shadows": 10,
            "threshold": 70,
            "smoothness": 18,
            "color_preservation": 60,
            "local_contrast": 45,
            "saturation_recovery": 0,
            "method": "detail_preserving",
        },
    },
    "interior_window": {
        "name": "室内窗外",
        "description": "极强力恢复：室内拍摄时窗户外严重过曝的景物。",
        "params": {
            "exposure": -0.5,
            "highlights": -95,
            "whites": -60,
            "shadows": 25,
            "threshold": 50,
            "smoothness": 35,
            "color_preservation": 80,
            "local_contrast": 50,
            "saturation_recovery": 30,
            "method": "exposure_fusion",
        },
    },
    "landscape_hdr": {
        "name": "风光 HDR",
        "description": "风光摄影 HDR 风格：天空与阴影平衡，强调画面层次。",
        "params": {
            "exposure": 0.0,
            "highlights": -75,
            "whites": -20,
            "shadows": 30,
            "threshold": 60,
            "smoothness": 25,
            "color_preservation": 85,
            "local_contrast": 45,
            "saturation_recovery": 25,
            "method": "exposure_fusion",
        },
    },
    "cinematic": {
        "name": "电影感",
        "description": "胶片质感：柔和的高光过渡，低对比，冷调倾向。",
        "params": {
            "exposure": 0.0,
            "highlights": -55,
            "whites": -35,
            "shadows": 12,
            "threshold": 65,
            "smoothness": 30,
            "color_preservation": 80,
            "local_contrast": 5,
            "saturation_recovery": 10,
            "method": "filmic_curve",
        },
    },
    "stage_concert": {
        "name": "舞台演唱会",
        "description": "舞台射灯下的人物：压暗高光、提亮阴影，恢复服装细节。",
        "params": {
            "exposure": -0.2,
            "highlights": -85,
            "whites": -50,
            "shadows": 35,
            "threshold": 55,
            "smoothness": 28,
            "color_preservation": 75,
            "local_contrast": 35,
            "saturation_recovery": 20,
            "method": "channel_aware",
        },
    },
    "snow_beach": {
        "name": "雪景 / 海滩",
        "description": "高反光环境：找回雪地、沙滩、海面的层次，避免死白。",
        "params": {
            "exposure": -0.4,
            "highlights": -70,
            "whites": -45,
            "shadows": 5,
            "threshold": 65,
            "smoothness": 22,
            "color_preservation": 70,
            "local_contrast": 25,
            "saturation_recovery": 15,
            "method": "detail_preserving",
        },
    },
}


def list_presets() -> list[dict[str, Any]]:
    """Return presets in a UI-friendly shape: [{id, name, description, params}...]."""
    return [
        {"id": pid, "name": p["name"], "description": p["description"], "params": p["params"]}
        for pid, p in PRESETS.items()
    ]


def default_params() -> Dict[str, Any]:
    """Identity parameters — pipeline becomes a no-op (just RAW dev to sRGB)."""
    return {
        "exposure": 0.0,
        "highlights": 0,
        "whites": 0,
        "shadows": 0,
        "threshold": 75,
        "smoothness": 20,
        "color_preservation": 75,
        "local_contrast": 0,
        "saturation_recovery": 0,
        "method": "luminance_mask",
    }
