// Highlight Recovery — frontend logic
// Vanilla JS, no framework. Communicates with the FastAPI backend.

const state = {
  sessionId: null,
  presets: [],
  methods: [],
  defaults: null,
  baseUrl: '',           // ObjectURL of the "before" image (no params)
  topUrl: '',            // ObjectURL of the "after" image (with params)
  compareEnabled: true,
  comparePos: 0.5,       // 0..1
  previewInFlight: null, // AbortController
  previewQueued: null,   // {params}
  activePresetId: null,
  busy: false,
};

const $ = (id) => document.getElementById(id);

const PARAM_INPUTS = {
  exposure: $('paramExposure'),
  highlights: $('paramHighlights'),
  whites: $('paramWhites'),
  shadows: $('paramShadows'),
  threshold: $('paramThreshold'),
  smoothness: $('paramSmoothness'),
  color_preservation: $('paramColorPreservation'),
  local_contrast: $('paramLocalContrast'),
  saturation_recovery: $('paramSaturationRecovery'),
  method: $('paramMethod'),
};

const VALUE_LABELS = {};
document.querySelectorAll('.param .value').forEach((el) => {
  VALUE_LABELS[el.dataset.for] = el;
});

// ---------------------------------------------------------------------------
// Bootstrap

async function init() {
  bindEvents();
  await loadPresetsAndMethods();
  formatAllValueLabels();
}

document.addEventListener('DOMContentLoaded', init);

// ---------------------------------------------------------------------------
// Presets / methods fetch

async function loadPresetsAndMethods() {
  try {
    const resp = await fetch('/api/presets');
    if (!resp.ok) throw new Error('cannot load presets');
    const data = await resp.json();
    state.presets = data.presets;
    state.methods = data.methods;
    state.defaults = data.defaults;
    renderPresets();
    renderMethods();
  } catch (e) {
    toast('载入预设失败：' + e.message, 'error');
  }
}

function renderPresets() {
  const root = $('presetsList');
  root.innerHTML = '';
  for (const p of state.presets) {
    const card = document.createElement('div');
    card.className = 'preset';
    card.dataset.id = p.id;
    card.innerHTML = `
      <div class="preset-name">${escapeHTML(p.name)}</div>
      <div class="preset-desc">${escapeHTML(p.description)}</div>`;
    card.addEventListener('click', () => applyPreset(p));
    card.addEventListener('dblclick', (e) => {
      e.preventDefault();
      copyParamsOnly(p);
    });
    root.appendChild(card);
  }
}

function renderMethods() {
  const select = PARAM_INPUTS.method;
  select.innerHTML = '';
  for (const m of state.methods) {
    const opt = document.createElement('option');
    opt.value = m.id;
    opt.textContent = m.name;
    opt.dataset.hint = m.description;
    select.appendChild(opt);
  }
  updateMethodHint();
}

function updateMethodHint() {
  const opt = PARAM_INPUTS.method.selectedOptions[0];
  $('methodHint').textContent = opt ? opt.dataset.hint || '' : '';
}

function applyPreset(preset) {
  state.activePresetId = preset.id;
  document.querySelectorAll('.preset').forEach((c) => {
    c.classList.toggle('active', c.dataset.id === preset.id);
  });
  setParams(preset.params);
  $('resetBtn').disabled = false;
  requestPreview();
  toast(`已应用预设：${preset.name}`);
}

function copyParamsOnly(preset) {
  setParams(preset.params);
  requestPreview();
  toast(`已复制 ${preset.name} 的参数`);
}

function setParams(params) {
  for (const [key, el] of Object.entries(PARAM_INPUTS)) {
    if (params[key] === undefined) continue;
    if (key === 'method') {
      el.value = params.method;
      updateMethodHint();
      continue;
    }
    // exposure uses a *100 scale on the slider
    if (key === 'exposure') {
      el.value = Math.round(params.exposure * 100);
    } else {
      el.value = params[key];
    }
  }
  formatAllValueLabels();
}

function readParams() {
  const out = {};
  for (const [key, el] of Object.entries(PARAM_INPUTS)) {
    if (key === 'method') {
      out.method = el.value;
    } else if (key === 'exposure') {
      out.exposure = Number(el.value) / 100;
    } else {
      out[key] = Number(el.value);
    }
  }
  return out;
}

function formatAllValueLabels() {
  for (const [key, el] of Object.entries(PARAM_INPUTS)) {
    if (key === 'method') continue;
    formatValueLabel(key);
  }
}

function formatValueLabel(key) {
  const lbl = VALUE_LABELS[key];
  if (!lbl) return;
  const v = Number(PARAM_INPUTS[key].value);
  if (key === 'exposure') {
    lbl.textContent = (v / 100).toFixed(2) + ' EV';
  } else {
    lbl.textContent = String(v);
  }
}

// ---------------------------------------------------------------------------
// Events

function bindEvents() {
  $('fileInput').addEventListener('change', (e) => {
    const f = e.target.files[0];
    if (f) handleUpload(f);
    e.target.value = '';
  });

  const dz = $('dropzone');
  ['dragenter', 'dragover'].forEach((ev) => {
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add('dragover'); });
  });
  ['dragleave', 'drop'].forEach((ev) => {
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove('dragover'); });
  });
  dz.addEventListener('drop', (e) => {
    e.preventDefault();
    dz.classList.remove('dragover');
    const f = e.dataTransfer.files[0];
    if (f) handleUpload(f);
  });
  // Also accept drops anywhere in the canvas area
  ['dragover', 'drop'].forEach((ev) => {
    document.querySelector('.canvas').addEventListener(ev, (e) => e.preventDefault());
  });
  document.querySelector('.canvas').addEventListener('drop', (e) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) handleUpload(f);
  });

  for (const [key, el] of Object.entries(PARAM_INPUTS)) {
    if (key === 'method') {
      el.addEventListener('change', () => {
        updateMethodHint();
        clearActivePreset();
        requestPreview();
      });
    } else {
      el.addEventListener('input', () => {
        formatValueLabel(key);
        clearActivePreset();
        requestPreview();
      });
    }
  }

  $('resetBtn').addEventListener('click', () => {
    if (!state.defaults) return;
    setParams(state.defaults);
    clearActivePreset();
    requestPreview();
    toast('参数已重置');
  });

  $('randomizeBtn').addEventListener('click', () => {
    randomizeParams();
    clearActivePreset();
    requestPreview();
  });

  $('exportBtn').addEventListener('click', exportFull);

  $('compareToggle').addEventListener('change', (e) => {
    state.compareEnabled = e.target.checked;
    updateComparePosition();
  });

  setupCompareDrag();
}

function clearActivePreset() {
  if (!state.activePresetId) return;
  state.activePresetId = null;
  document.querySelectorAll('.preset.active').forEach((c) => c.classList.remove('active'));
}

function randomizeParams() {
  const r = (a, b) => a + Math.random() * (b - a);
  setParams({
    exposure: r(-0.4, 0.1),
    highlights: Math.round(r(-90, -10)),
    whites: Math.round(r(-50, 0)),
    shadows: Math.round(r(0, 25)),
    threshold: Math.round(r(50, 85)),
    smoothness: Math.round(r(15, 35)),
    color_preservation: Math.round(r(60, 95)),
    local_contrast: Math.round(r(0, 40)),
    saturation_recovery: Math.round(r(5, 30)),
    method: PARAM_INPUTS.method.value,
  });
}

// ---------------------------------------------------------------------------
// Upload + preview

async function handleUpload(file) {
  setBusy(true, '读取 RAW 中…');
  try {
    const fd = new FormData();
    fd.append('file', file);
    const resp = await fetch('/api/upload', { method: 'POST', body: fd });
    if (!resp.ok) {
      const err = await safeJson(resp);
      throw new Error(err.detail || `上传失败：HTTP ${resp.status}`);
    }
    const data = await resp.json();
    state.sessionId = data.session_id;
    showMeta(data.metadata);
    $('dropzone').classList.add('hidden');
    $('previewWrap').classList.remove('hidden');
    $('exportBtn').disabled = false;
    $('resetBtn').disabled = false;

    // First preview: render with identity params, then again with current params
    await renderBaseImage();
    await renderTopImage();
    toast('RAW 已载入');
  } catch (e) {
    toast(e.message, 'error');
  } finally {
    setBusy(false);
  }
}

function showMeta(m) {
  const sizeMB = (m.size_bytes / (1024 * 1024)).toFixed(1);
  const camera = [m.camera_make, m.camera_model].filter(Boolean).join(' ');
  $('fileMeta').innerHTML = `
    <span><b>${escapeHTML(m.filename || '')}</b></span>
    <span class="muted">${m.width}×${m.height}</span>
    <span class="muted">${sizeMB} MB</span>
    ${camera ? `<span class="muted">${escapeHTML(camera)}</span>` : ''}
    ${m.iso ? `<span class="muted">ISO ${Math.round(m.iso)}</span>` : ''}`;
}

async function renderBaseImage() {
  // The "before" image is processed with default (identity) params.
  if (!state.defaults) return;
  const blob = await previewFetch(state.defaults);
  if (state.baseUrl) URL.revokeObjectURL(state.baseUrl);
  state.baseUrl = URL.createObjectURL(blob);
  $('previewBase').src = state.baseUrl;
}

async function renderTopImage() {
  const params = readParams();
  const blob = await previewFetch(params);
  if (state.topUrl) URL.revokeObjectURL(state.topUrl);
  state.topUrl = URL.createObjectURL(blob);
  const top = $('previewTop');
  top.src = state.topUrl;
  top.onload = () => updateComparePosition();
}

async function previewFetch(params) {
  if (!state.sessionId) throw new Error('no session');
  const resp = await fetch('/api/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: state.sessionId, params }),
  });
  if (!resp.ok) {
    const err = await safeJson(resp);
    throw new Error(err.detail || `预览失败：HTTP ${resp.status}`);
  }
  const ms = resp.headers.get('X-Process-Ms');
  if (ms) $('timingInfo').textContent = `处理耗时 ${Math.round(Number(ms))} ms`;
  return await resp.blob();
}

// Debounced preview with cancellation
let previewDebounce = null;
function requestPreview() {
  if (!state.sessionId) return;
  if (previewDebounce) clearTimeout(previewDebounce);
  previewDebounce = setTimeout(actuallyPreview, 80);
}

async function actuallyPreview() {
  if (state.previewInFlight) {
    // queue the latest params
    state.previewQueued = readParams();
    return;
  }
  const params = readParams();
  state.previewInFlight = new AbortController();
  try {
    const resp = await fetch('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, params }),
      signal: state.previewInFlight.signal,
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const ms = resp.headers.get('X-Process-Ms');
    if (ms) $('timingInfo').textContent = `处理耗时 ${Math.round(Number(ms))} ms`;
    const blob = await resp.blob();
    if (state.topUrl) URL.revokeObjectURL(state.topUrl);
    state.topUrl = URL.createObjectURL(blob);
    $('previewTop').src = state.topUrl;
  } catch (e) {
    if (e.name !== 'AbortError') toast('预览失败：' + e.message, 'error');
  } finally {
    state.previewInFlight = null;
    if (state.previewQueued) {
      state.previewQueued = null;
      actuallyPreview();
    }
  }
}

// ---------------------------------------------------------------------------
// Export full-res

async function exportFull() {
  if (!state.sessionId) return;
  setBusy(true, '导出全分辨率…');
  try {
    const fmt = $('exportFormat').value;
    const resp = await fetch('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: state.sessionId,
        params: readParams(),
        format: fmt,
        quality: 95,
      }),
    });
    if (!resp.ok) {
      const err = await safeJson(resp);
      throw new Error(err.detail || `导出失败：HTTP ${resp.status}`);
    }
    // Read suggested filename from Content-Disposition
    const cd = resp.headers.get('Content-Disposition') || '';
    const m = /filename="([^"]+)"/.exec(cd);
    const filename = m ? m[1] : `recovered.${fmt === 'tiff' ? 'tiff' : fmt}`;
    const blob = await resp.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
    toast(`导出完成：${filename}`);
  } catch (e) {
    toast(e.message, 'error');
  } finally {
    setBusy(false);
  }
}

// ---------------------------------------------------------------------------
// Before/After compare slider

function setupCompareDrag() {
  const stage = document.querySelector('.preview-stage');
  const handle = $('compareHandle');
  let dragging = false;

  const onMove = (e) => {
    if (!dragging) return;
    const rect = stage.getBoundingClientRect();
    const x = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
    state.comparePos = Math.max(0, Math.min(1, x / rect.width));
    updateComparePosition();
  };

  handle.addEventListener('mousedown', (e) => { dragging = true; e.preventDefault(); });
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', () => { dragging = false; });

  handle.addEventListener('touchstart', (e) => { dragging = true; }, { passive: true });
  document.addEventListener('touchmove', onMove, { passive: true });
  document.addEventListener('touchend', () => { dragging = false; });

  // Also: drag anywhere on the preview stage moves the handle
  stage.addEventListener('mousedown', (e) => {
    if (e.target === handle || handle.contains(e.target)) return;
    dragging = true;
    onMove(e);
  });
}

function updateComparePosition() {
  const top = $('previewTop');
  const handle = $('compareHandle');
  if (!state.compareEnabled) {
    top.style.clipPath = 'none';
    handle.classList.add('hidden');
    return;
  }
  handle.classList.remove('hidden');
  const pct = (state.comparePos * 100).toFixed(2);
  top.style.clipPath = `inset(0 0 0 ${pct}%)`;
  handle.style.left = `${pct}%`;
}

// ---------------------------------------------------------------------------
// Utilities

function setBusy(on, text) {
  state.busy = on;
  $('busy').classList.toggle('active', !!on);
  $('busyText').textContent = text || '处理中…';
}

let toastTimer = null;
function toast(msg, level) {
  const t = $('toast');
  t.textContent = msg;
  t.className = 'toast show ' + (level || '');
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.classList.remove('show'); }, 2400);
}

async function safeJson(resp) {
  try { return await resp.json(); } catch { return {}; }
}

function escapeHTML(s) {
  return String(s || '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}
