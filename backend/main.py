"""FastAPI app: serves the frontend and exposes the processing endpoints."""
from __future__ import annotations

import io
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict

import numpy as np
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import pipeline
from .presets import default_params, list_presets
from .raw_loader import is_raw_file, load_raw, SUPPORTED_EXT

log = logging.getLogger("highlight_recovery")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

PREVIEW_LONG_SIDE = 1400
MAX_SESSIONS = 8

app = FastAPI(title="Highlight Recovery", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ---- session store (in-memory; single-user local app) -----------------------

class Session:
    __slots__ = ("session_id", "path", "linear_preview", "metadata", "created_at")

    def __init__(self, session_id: str, path: Path, linear_preview: np.ndarray,
                 metadata: Dict[str, Any]):
        self.session_id = session_id
        self.path = path
        self.linear_preview = linear_preview
        self.metadata = metadata
        self.created_at = time.time()


_SESSIONS: Dict[str, Session] = {}


def _evict_if_needed() -> None:
    while len(_SESSIONS) > MAX_SESSIONS:
        oldest = min(_SESSIONS.values(), key=lambda s: s.created_at)
        _drop_session(oldest.session_id)


def _drop_session(sid: str) -> None:
    s = _SESSIONS.pop(sid, None)
    if s and s.path.exists():
        try:
            s.path.unlink()
        except OSError:
            pass


# ---- routes ----------------------------------------------------------------

@app.get("/")
async def root() -> FileResponse:
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/api/presets")
async def get_presets() -> JSONResponse:
    return JSONResponse({
        "presets": list_presets(),
        "defaults": default_params(),
        "methods": [
            {"id": "luminance_mask", "name": "亮度蒙版（通用）",
             "description": "蒙版式高光压缩，类似 Lightroom Highlights 滑块"},
            {"id": "channel_aware", "name": "通道感知（彩色高光）",
             "description": "按通道滚动压缩，处理日落/霓虹等单通道过曝"},
            {"id": "hsl_compression", "name": "HSL 压缩（保护色相）",
             "description": "仅压缩 L 通道，色相完全不变。适合人像、天空"},
            {"id": "detail_preserving", "name": "细节保留（Durand）",
             "description": "双边滤波分解，恢复纹理。适合婚纱、云层"},
            {"id": "exposure_fusion", "name": "曝光融合（Mertens）",
             "description": "多虚拟曝光融合，最强力。室内窗户、HDR 风光"},
            {"id": "filmic_curve", "name": "胶片曲线（Filmic）",
             "description": "Log 软滚降，柔和过渡。电影、复古"},
        ],
        "supported_formats": sorted(ext.upper().lstrip(".") for ext in SUPPORTED_EXT),
    })


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> JSONResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if not suffix or suffix not in SUPPORTED_EXT:
        raise HTTPException(400, f"不支持的 RAW 格式: {suffix or '(无扩展名)'}.")

    session_id = uuid.uuid4().hex[:12]
    target = UPLOAD_DIR / f"{session_id}{suffix}"
    contents = await file.read()
    target.write_bytes(contents)

    try:
        raw = load_raw(target, max_long_side=PREVIEW_LONG_SIDE)
    except Exception as e:
        target.unlink(missing_ok=True)
        log.exception("RAW load failed")
        raise HTTPException(400, f"RAW 读取失败: {e}") from e

    metadata = {
        "filename": file.filename,
        "width": int(raw.linear_rgb.shape[1]),
        "height": int(raw.linear_rgb.shape[0]),
        "camera_make": raw.camera_make,
        "camera_model": raw.camera_model,
        "iso": raw.iso,
        "size_bytes": len(contents),
    }

    sess = Session(session_id, target, raw.linear_rgb, metadata)
    _SESSIONS[session_id] = sess
    _evict_if_needed()

    log.info("uploaded %s as session %s (%dx%d)", file.filename, session_id,
             metadata["width"], metadata["height"])

    return JSONResponse({"session_id": session_id, "metadata": metadata})


@app.post("/api/preview")
async def preview(payload: Dict[str, Any]) -> Response:
    sid = payload.get("session_id")
    if not sid or sid not in _SESSIONS:
        raise HTTPException(404, "Session not found")
    params = payload.get("params") or {}

    sess = _SESSIONS[sid]
    result = pipeline.process(sess.linear_preview, params)
    jpeg = pipeline.encode_jpeg(result.image_srgb_u8, quality=88)

    return Response(
        content=jpeg, media_type="image/jpeg",
        headers={"X-Process-Ms": f"{result.timing_ms:.1f}"},
    )


@app.post("/api/export")
async def export(payload: Dict[str, Any]) -> Response:
    sid = payload.get("session_id")
    if not sid or sid not in _SESSIONS:
        raise HTTPException(404, "Session not found")
    params = payload.get("params") or {}
    fmt = (payload.get("format") or "jpeg").lower()
    quality = int(payload.get("quality") or 95)

    sess = _SESSIONS[sid]
    log.info("exporting session %s as %s", sid, fmt)
    full_raw = load_raw(sess.path)  # full resolution this time
    result = pipeline.process(full_raw.linear_rgb, params)

    if fmt in ("jpg", "jpeg"):
        body = pipeline.encode_jpeg(result.image_srgb_u8, quality=quality)
        mime, ext = "image/jpeg", "jpg"
    elif fmt == "png":
        body = pipeline.encode_png(result.image_srgb_u8)
        mime, ext = "image/png", "png"
    elif fmt == "tiff":
        body = pipeline.encode_tiff_16(result.image_srgb_u8)
        mime, ext = "image/tiff", "tiff"
    else:
        raise HTTPException(400, f"unsupported export format: {fmt}")

    base = Path(sess.metadata.get("filename") or sid).stem
    filename = f"{base}_recovered.{ext}"

    return Response(
        content=body, media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Process-Ms": f"{result.timing_ms:.1f}",
        },
    )


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str) -> JSONResponse:
    _drop_session(session_id)
    return JSONResponse({"ok": True})


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True, "sessions": len(_SESSIONS)})
