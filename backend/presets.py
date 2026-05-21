"""Built-in presets — professional, restrained values.

Design principles drawn from Lightroom / Capture One / darktable / RawTherapee
defaults and from feedback that earlier presets caused "image distortion":

1. **Single dominant operation per preset.** Stacking strong highlight
   recovery + heavy shadow lift + strong clarity + heavy vibrance produces
   the unmistakable "fake HDR" look. Each preset here pushes one tool hard
   and uses the rest only to support.
2. **Conservative highlight strengths.** Real-world Lightroom auto sits at
   highlights ≈ -25 .. -50, not -80. Going past -65 is rare and looks
   artificial on most scenes.
3. **High color preservation (80–95).** Keeps highlight hue stable so skies
   stay blue, skin stays warm, fabric stays white.
4. **No exposure_fusion / Mertens in stock presets.** Multi-exposure fusion
   is inherently HDR-looking; users who specifically want that can switch
   to it manually.
5. **Modest definition / sharpness.** Definition > 25 starts making fabrics
   and skin look "digital"; sharpness > 20 starts ringing on edges.
6. **No simultaneous heavy contrast + clarity + vibrance.** Two of three at
   most, at modest values.
"""
from __future__ import annotations

from typing import Any, Dict, List


def default_params() -> Dict[str, Any]:
    """Identity defaults — pipeline becomes a near no-op."""
    return {
        "rotation": 0,
        "flip_h": False,
        "flip_v": False,
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
        "smoothness": 25,
        "color_preservation": 85,
        "local_contrast": 0,
        "saturation_recovery": 0,
        "method": "luminance_mask",
        "local_masks": [],
    }


PRESETS: Dict[str, Dict[str, Any]] = {
    # =========================================================================
    # Recovery presets — primary purpose is highlight rescue.
    # =========================================================================
    "natural_subtle": {
        "name": "柔和恢复",
        "description": "日常照片首选。轻度高光压缩 + 微调阴影，保留自然观感。",
        "params": {
            "highlights": -25,
            "whites": -8,
            "shadows": 5,
            "vibrance": 8,
            "color_preservation": 85,
            "smoothness": 25,
            "method": "luminance_mask",
        },
    },
    "strong_recovery": {
        "name": "强力恢复",
        "description": "严重过曝救场。中等强度压缩 + 保色，避免人造 HDR 感。",
        "params": {
            "exposure": -0.15,
            "highlights": -55,
            "whites": -20,
            "shadows": 10,
            "vibrance": 5,
            "color_preservation": 90,
            "smoothness": 30,
            "method": "luminance_mask",
        },
    },
    "sky_blue": {
        "name": "天空云层",
        "description": "针对过曝天空：HSL 模式锁色相，找回云层蓝调。",
        "params": {
            "highlights": -45,
            "whites": -15,
            "vibrance": 15,
            "warmth": -3,
            "color_preservation": 95,
            "smoothness": 28,
            "method": "hsl_compression",
            "saturation_recovery": 10,
        },
    },
    "sunset_warm": {
        "name": "日落暖光",
        "description": "日落、霓虹等单通道过曝。通道感知保住色温，避免发紫。",
        "params": {
            "highlights": -40,
            "whites": -12,
            "vibrance": 12,
            "warmth": 5,
            "color_preservation": 90,
            "method": "channel_aware",
        },
    },
    "portrait_skin": {
        "name": "人像高光",
        "description": "保护肤色与高光过渡。HSL 锁色相，弱化清晰度避免数码感。",
        "params": {
            "highlights": -30,
            "whites": -10,
            "shadows": 5,
            "vibrance": 8,
            "warmth": 3,
            "definition": -5,
            "sharpness": 12,
            "color_preservation": 90,
            "method": "hsl_compression",
        },
    },
    "wedding_whites": {
        "name": "婚纱白色",
        "description": "找回白色衣物的褶皱与质感。中度细节增强，不过度。",
        "params": {
            "highlights": -45,
            "whites": -15,
            "shadows": 5,
            "definition": 12,
            "sharpness": 10,
            "local_contrast": 25,
            "color_preservation": 65,
            "smoothness": 22,
            "method": "detail_preserving",
        },
    },
    "interior_window": {
        "name": "室内逆光",
        "description": "室内拍摄、窗户严重过曝。强压高光，不用 HDR 融合。",
        "params": {
            "exposure": -0.15,
            "highlights": -60,
            "whites": -25,
            "shadows": 18,
            "vibrance": 8,
            "color_preservation": 88,
            "smoothness": 30,
            "method": "luminance_mask",
        },
    },
    "landscape_natural": {
        "name": "风光自然",
        "description": "风光摄影：天空与阴影平衡，不过度增强。",
        "params": {
            "highlights": -42,
            "whites": -12,
            "shadows": 15,
            "vibrance": 12,
            "definition": 8,
            "color_preservation": 85,
            "smoothness": 26,
            "method": "luminance_mask",
        },
    },

    # =========================================================================
    # Look presets — stylistic, applied after recovery.
    # =========================================================================
    "vivid_clean": {
        "name": "鲜明",
        "description": "增加画面冲击力但不失真。柔和压暗 + 自然饱和 + 适度清晰度。",
        "params": {
            "highlights": -22,
            "shadows": 8,
            "contrast": 12,
            "vibrance": 18,
            "definition": 8,
            "sharpness": 12,
            "color_preservation": 85,
            "method": "luminance_mask",
        },
    },
    "filmic_soft": {
        "name": "胶片柔和",
        "description": "电影质感：柔和高光、低对比、轻微冷调、低饱和。",
        "params": {
            "highlights": -38,
            "whites": -15,
            "shadows": 8,
            "contrast": -6,
            "warmth": -5,
            "saturation": -5,
            "color_preservation": 82,
            "method": "filmic_curve",
        },
    },
    "mono_silver": {
        "name": "黑白",
        "description": "黑白片：保留中间调层次，适度对比。",
        "params": {
            "highlights": -25,
            "whites": -10,
            "shadows": 12,
            "contrast": 10,
            "saturation": -100,
            "definition": 8,
            "sharpness": 12,
            "method": "luminance_mask",
        },
    },
    "auto_enhance": {
        "name": "自动",
        "description": "智能增强：iPhone Auto 风格。鲜明度 + 适度恢复 + 自然饱和。",
        "params": {
            "highlights": -25,
            "shadows": 12,
            "brilliance": 15,
            "vibrance": 12,
            "definition": 5,
            "sharpness": 10,
            "color_preservation": 85,
            "method": "luminance_mask",
        },
    },
}


def list_presets() -> List[Dict[str, Any]]:
    return [
        {"id": pid, "name": p["name"], "description": p["description"], "params": p["params"]}
        for pid, p in PRESETS.items()
    ]
