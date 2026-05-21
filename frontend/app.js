// Highlight Recovery — frontend (full edit suite + local masks)
// Vanilla JS, no framework.

const $ = (id) => document.getElementById(id);

const PARAM_GROUPS = {
  basic: [
    { id: 'exposure', label: '曝光', min: -2.0, max: 2.0, def: 0, step: 0.01, unit: 'EV', precision: 2 },
    { id: 'brilliance', label: '鲜明度', min: -100, max: 100, def: 0,
      hint: '智能调整：提亮阴影、压暗高光、增强中间调（类似 Apple Brilliance）' },
    { id: 'highlights', label: '高光（−压暗）', min: -100, max: 100, def: 0 },
    { id: 'shadows', label: '阴影（+提亮）', min: -100, max: 100, def: 0 },
    { id: 'whites', label: '白色', min: -100, max: 100, def: 0 },
    { id: 'black_point', label: '黑点', min: -100, max: 100, def: 0 },
    { id: 'brightness', label: '亮度', min: -100, max: 100, def: 0,
      hint: 'γ 曲线提亮，不同于曝光的线性增益' },
    { id: 'contrast', label: '对比度', min: -100, max: 100, def: 0 },
  ],
  color: [
    { id: 'saturation', label: '饱和度', min: -100, max: 100, def: 0 },
    { id: 'vibrance', label: '自然饱和度', min: -100, max: 100, def: 0,
      hint: '选择性饱和：对低饱和色作用更强（Adobe Vibrance 风格）' },
    { id: 'warmth', label: '色温', min: -100, max: 100, def: 0,
      hint: '+ 暖（黄/红） / − 冷（蓝）' },
    { id: 'tint', label: '色调', min: -100, max: 100, def: 0,
      hint: '+ 品红 / − 绿' },
  ],
  detail: [
    { id: 'definition', label: '清晰度', min: -100, max: 100, def: 0,
      hint: '中间调局部对比（类似 Lightroom Clarity）。负值给柔焦效果' },
    { id: 'sharpness', label: '锐度', min: 0, max: 100, def: 0,
      hint: '边缘锐化（USM 反差掩模）' },
    { id: 'noise_reduction', label: '降噪', min: 0, max: 100, def: 0,
      hint: '预览使用双边滤波；导出用 NLM 高质量算法（慢）' },
    { id: 'vignette', label: '晕影', min: -100, max: 100, def: 0,
      hint: '− 暗角（电影感） / + 高光晕' },
  ],
  recovery: [
    { id: '_method', type: 'select', label: '恢复算法',
      hint: '只在「高光」< 0 时生效。负值越大，压缩越强' },
    { id: 'threshold', label: '阈值（压缩起点）', min: 0, max: 100, def: 75 },
    { id: 'smoothness', label: '平滑度（蒙版羽化）', min: 0, max: 100, def: 20 },
    { id: 'color_preservation', label: '色彩保护', min: 0, max: 100, def: 75,
      hint: '高：按比例缩放 RGB 保色；低：逐通道压缩去饱' },
    { id: 'local_contrast', label: '局部对比', min: -100, max: 100, def: 0,
      hint: '仅 detail_preserving / filmic_curve 模式生效' },
    { id: 'saturation_recovery', label: '饱和度恢复', min: 0, max: 100, def: 0,
      hint: '在已恢复的高光处补充饱和度，避免「灰白」效果' },
  ],
};

const MASK_PARAMS = [
  { id: 'exposure', label: '曝光', min: -2.0, max: 2.0, def: 0, step: 0.01, unit: 'EV', precision: 2 },
  { id: 'highlights', label: '高光', min: -100, max: 100, def: 0 },
  { id: 'shadows', label: '阴影', min: -100, max: 100, def: 0 },
  { id: 'contrast', label: '对比度', min: -100, max: 100, def: 0 },
  { id: 'saturation', label: '饱和度', min: -100, max: 100, def: 0 },
  { id: 'warmth', label: '色温', min: -100, max: 100, def: 0 },
  { id: 'tint', label: '色调', min: -100, max: 100, def: 0 },
];

const state = {
  sessionId: null,
  presets: [],
  methods: [],
  defaults: null,
  baseUrl: '',
  topUrl: '',
  compareEnabled: true,
  comparePos: 0.5,
  previewInFlight: null,
  previewQueued: false,
  activePresetId: null,
  busy: false,
  params: {},          // current global params
  masks: [],           // list of mask specs
  selectedMaskId: null,
  nextMaskId: 1,
};

// ============================================================================
// Bootstrap

async function init() {
  buildParamPanels();
  bindEvents();
  await loadPresetsAndMethods();
  resetAllParams();
  renderMaskList();
}
document.addEventListener('DOMContentLoaded', init);

async function loadPresetsAndMethods() {
  try {
    const resp = await fetch('/api/presets');
    if (!resp.ok) throw new Error('cannot load presets');
    const data = await resp.json();
    state.presets = data.presets;
    state.methods = data.methods;
    state.defaults = data.defaults;
    renderPresets();
    populateMethodSelect();
  } catch (e) {
    toast('载入预设失败：' + e.message, 'error');
  }
}

// ============================================================================
// Param panel rendering

function buildParamPanels() {
  for (const [group, items] of Object.entries(PARAM_GROUPS)) {
    const panel = $('panel' + group.charAt(0).toUpperCase() + group.slice(1));
    if (!panel) continue;
    panel.innerHTML = '';
    for (const item of items) {
      panel.appendChild(renderParam(item));
    }
  }
}

function renderParam(item) {
  const wrap = document.createElement('div');
  wrap.className = 'param';

  if (item.type === 'select') {
    wrap.innerHTML = `
      <div class="param-row"><label>${escapeHTML(item.label)}</label></div>
      <select data-key="${item.id}"></select>
      ${item.hint ? `<p class="hint">${escapeHTML(item.hint)}</p>` : ''}`;
    const sel = wrap.querySelector('select');
    sel.addEventListener('change', () => {
      state.params.method = sel.value;
      updateMethodHint(sel.parentElement);
      requestPreview();
    });
    return wrap;
  }

  const step = item.step ?? 1;
  // For non-integer steps (e.g. exposure 0.01), use a *100 scale on the slider
  // so the value reads cleanly in user units.
  const scale = step < 1 ? Math.round(1 / step) : 1;
  const sliderMin = Math.round(item.min * scale);
  const sliderMax = Math.round(item.max * scale);
  const sliderDef = Math.round(item.def * scale);

  wrap.innerHTML = `
    <div class="param-row">
      <label>${escapeHTML(item.label)}</label>
      <span class="value" data-for="${item.id}" title="点击重置">${formatValue(item, item.def)}</span>
    </div>
    <input type="range" min="${sliderMin}" max="${sliderMax}" value="${sliderDef}"
           data-key="${item.id}" data-scale="${scale}">
    ${item.hint ? `<p class="hint">${escapeHTML(item.hint)}</p>` : ''}`;

  const input = wrap.querySelector('input');
  const valueEl = wrap.querySelector('.value');
  input.addEventListener('input', () => {
    const v = Number(input.value) / scale;
    state.params[item.id] = v;
    valueEl.textContent = formatValue(item, v);
    clearActivePreset();
    requestPreview();
  });
  valueEl.addEventListener('click', () => {
    input.value = sliderDef;
    state.params[item.id] = item.def;
    valueEl.textContent = formatValue(item, item.def);
    clearActivePreset();
    requestPreview();
  });
  return wrap;
}

function formatValue(item, v) {
  if (item.precision !== undefined) {
    return v.toFixed(item.precision) + (item.unit ? ' ' + item.unit : '');
  }
  return Math.round(v) + (item.unit ? ' ' + item.unit : '');
}

function populateMethodSelect() {
  const sel = document.querySelector('select[data-key="_method"]');
  if (!sel) return;
  sel.innerHTML = '';
  for (const m of state.methods) {
    const opt = document.createElement('option');
    opt.value = m.id;
    opt.textContent = m.name;
    opt.dataset.hint = m.description;
    sel.appendChild(opt);
  }
  sel.value = state.params.method || 'luminance_mask';
  updateMethodHint(sel.parentElement);
}

function updateMethodHint(paramEl) {
  const sel = paramEl.querySelector('select');
  const hint = paramEl.querySelector('.hint');
  if (sel && hint) {
    const opt = sel.selectedOptions[0];
    if (opt) hint.textContent = opt.dataset.hint || hint.textContent;
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
    card.addEventListener('dblclick', (e) => { e.preventDefault(); applyParamsOnly(p); });
    root.appendChild(card);
  }
}

// ============================================================================
// Param state I/O

function resetAllParams() {
  state.params = { ...(state.defaults || {}) };
  state.params.method = state.params.method || 'luminance_mask';
  state.params.local_masks = state.masks;
  syncParamsToUI();
  syncTransformButtons();
}

function syncTransformButtons() {
  const h = !!state.params.flip_h, v = !!state.params.flip_v;
  $('flipHBtn')?.classList.toggle('active', h);
  $('flipVBtn')?.classList.toggle('active', v);
  // No "active" indicator for rotation (it's a 4-state cycle); a tooltip suffices.
  const rot = Number(state.params.rotation || 0);
  const btn = $('rotateRightBtn');
  if (btn) btn.title = `向右旋转 90°（当前累计 ${rot}°）`;
}

function syncParamsToUI() {
  document.querySelectorAll('input[type="range"][data-key]').forEach((el) => {
    const key = el.dataset.key;
    if (state.params[key] === undefined) return;
    const scale = Number(el.dataset.scale || 1);
    el.value = Math.round(state.params[key] * scale);
    const valEl = document.querySelector(`.value[data-for="${key}"]`);
    if (valEl) {
      // find the param config to format
      const cfg = findParamConfig(key);
      valEl.textContent = cfg ? formatValue(cfg, state.params[key]) : String(state.params[key]);
    }
  });
  const methodSel = document.querySelector('select[data-key="_method"]');
  if (methodSel) {
    methodSel.value = state.params.method || 'luminance_mask';
    updateMethodHint(methodSel.parentElement);
  }
}

function findParamConfig(key) {
  for (const group of Object.values(PARAM_GROUPS)) {
    for (const item of group) {
      if (item.id === key) return item;
    }
  }
  return null;
}

function applyPreset(preset) {
  // Start fresh from defaults, then overlay preset params.
  state.params = { ...(state.defaults || {}) };
  Object.assign(state.params, preset.params || {});
  state.params.method = state.params.method || 'luminance_mask';
  state.params.local_masks = state.masks;
  state.activePresetId = preset.id;
  document.querySelectorAll('.preset').forEach((c) => {
    c.classList.toggle('active', c.dataset.id === preset.id);
  });
  syncParamsToUI();
  $('resetBtn').disabled = false;
  requestPreview();
  toast(`已应用预设：${preset.name}`);
}

function applyParamsOnly(preset) {
  Object.assign(state.params, preset.params || {});
  syncParamsToUI();
  requestPreview();
  toast(`已复制 ${preset.name} 的参数`);
}

function clearActivePreset() {
  if (!state.activePresetId) return;
  state.activePresetId = null;
  document.querySelectorAll('.preset.active').forEach((c) => c.classList.remove('active'));
}

// ============================================================================
// Local masks

function createMask(type) {
  const id = state.nextMaskId++;
  const adj = {};
  for (const p of MASK_PARAMS) adj[p.id] = p.def;
  const spec = {
    id, type,
    enabled: true,
    invert: false,
    adjustments: adj,
  };
  if (type === 'radial') {
    spec.cx = 0.5; spec.cy = 0.5;
    spec.rx = 0.18; spec.ry = 0.18;
    spec.rotation = 0;
    spec.feather = 0.45;
    // Give a sensible starting adjustment so the user immediately sees the
    // mask's effect.
    spec.adjustments.exposure = -0.8;
  } else {
    spec.x1 = 0.5; spec.y1 = 0.15;
    spec.x2 = 0.5; spec.y2 = 0.85;
    spec.adjustments.exposure = -0.5;
  }
  state.masks.push(spec);
  state.params.local_masks = state.masks;
  state.selectedMaskId = id;
  renderMaskList();
  renderMaskOverlay();
  requestPreview();
}

function removeMask(id) {
  state.masks = state.masks.filter((m) => m.id !== id);
  state.params.local_masks = state.masks;
  if (state.selectedMaskId === id) state.selectedMaskId = null;
  renderMaskList();
  renderMaskOverlay();
  requestPreview();
}

function selectMask(id) {
  state.selectedMaskId = state.selectedMaskId === id ? null : id;
  renderMaskList();
  renderMaskOverlay();
}

function renderMaskList() {
  const root = $('maskList');
  root.innerHTML = '';
  if (state.masks.length === 0) {
    root.innerHTML = '<p class="muted small" style="padding:6px 2px">尚未添加蒙版。</p>';
    return;
  }
  for (const m of state.masks) {
    const card = document.createElement('div');
    card.className = 'mask-card' + (m.id === state.selectedMaskId ? ' selected expanded' : '');
    card.dataset.id = m.id;
    const label = m.type === 'radial' ? '径向蒙版' : '渐变蒙版';

    const head = document.createElement('div');
    head.className = 'mask-card-head';
    head.innerHTML = `
      <div class="mask-card-title">
        <span class="mask-type-badge">${m.type === 'radial' ? 'RADIAL' : 'LINEAR'}</span>
        ${escapeHTML(label)} #${m.id}
      </div>
      <div class="mask-card-actions">
        <button class="mask-icon-btn" title="启用/停用" data-action="toggle">${m.enabled ? '●' : '○'}</button>
        <button class="mask-icon-btn danger" title="删除" data-action="delete">×</button>
      </div>`;
    head.addEventListener('click', (e) => {
      const act = e.target.dataset?.action;
      if (act === 'toggle') {
        e.stopPropagation();
        m.enabled = !m.enabled;
        renderMaskList();
        renderMaskOverlay();
        requestPreview();
        return;
      }
      if (act === 'delete') {
        e.stopPropagation();
        removeMask(m.id);
        return;
      }
      selectMask(m.id);
    });
    card.appendChild(head);

    if (m.id === state.selectedMaskId) {
      const body = document.createElement('div');
      body.className = 'mask-card-body';

      // Geometry-specific controls
      if (m.type === 'radial') {
        body.appendChild(renderMaskRangeParam(m, 'feather', '羽化',
          0.05, 1.0, 0.01, 2, '柔和度（0.02=硬边 / 1=渐变）'));
      }

      const inv = document.createElement('label');
      inv.className = 'check-row';
      inv.innerHTML = `<input type="checkbox" ${m.invert ? 'checked' : ''}> 反向（应用于蒙版外）`;
      inv.querySelector('input').addEventListener('change', (e) => {
        m.invert = e.target.checked;
        renderMaskOverlay();
        requestPreview();
      });
      body.appendChild(inv);

      const sub = document.createElement('div');
      sub.className = 'subhead';
      sub.textContent = '蒙版内调整';
      body.appendChild(sub);

      for (const cfg of MASK_PARAMS) {
        body.appendChild(renderMaskSliderParam(m, cfg));
      }
      card.appendChild(body);
    }
    root.appendChild(card);
  }
}

function renderMaskRangeParam(mask, key, label, min, max, step, prec, hint) {
  const cfg = { id: key, label, min, max, def: mask[key], step, precision: prec, unit: '', hint };
  return renderMaskCustom(cfg, () => mask[key], (v) => {
    mask[key] = v;
    renderMaskOverlay();
    requestPreview();
  });
}

function renderMaskSliderParam(mask, cfg) {
  return renderMaskCustom(cfg, () => mask.adjustments[cfg.id], (v) => {
    mask.adjustments[cfg.id] = v;
    requestPreview();
  });
}

function renderMaskCustom(item, getter, setter) {
  const wrap = document.createElement('div');
  wrap.className = 'param';
  const step = item.step ?? 1;
  const scale = step < 1 ? Math.round(1 / step) : 1;
  const sliderMin = Math.round(item.min * scale);
  const sliderMax = Math.round(item.max * scale);
  const initVal = getter();
  wrap.innerHTML = `
    <div class="param-row">
      <label>${escapeHTML(item.label)}</label>
      <span class="value">${formatValue(item, initVal)}</span>
    </div>
    <input type="range" min="${sliderMin}" max="${sliderMax}"
           value="${Math.round(initVal * scale)}">
    ${item.hint ? `<p class="hint">${escapeHTML(item.hint)}</p>` : ''}`;
  const inp = wrap.querySelector('input');
  const lbl = wrap.querySelector('.value');
  inp.addEventListener('input', () => {
    const v = Number(inp.value) / scale;
    lbl.textContent = formatValue(item, v);
    setter(v);
  });
  return wrap;
}

// ----- Mask overlay rendering & drag handling --------------------------------

function getImageRect() {
  const img = $('previewBase');
  const stage = $('previewStage');
  if (!img.complete || img.naturalWidth === 0) return null;
  const ib = img.getBoundingClientRect();
  const sb = stage.getBoundingClientRect();
  return {
    left: ib.left - sb.left,
    top: ib.top - sb.top,
    width: ib.width,
    height: ib.height,
  };
}

function renderMaskOverlay() {
  const overlay = $('maskOverlay');
  overlay.innerHTML = '';
  const rect = getImageRect();
  if (!rect) return;

  for (const m of state.masks) {
    if (!m.enabled) continue;
    const selected = m.id === state.selectedMaskId;
    if (m.type === 'radial') drawRadial(overlay, rect, m, selected);
    else drawLinear(overlay, rect, m, selected);
  }
}

function drawRadial(overlay, rect, m, selected) {
  const long = Math.max(rect.width, rect.height);
  const cxPx = rect.left + m.cx * rect.width;
  const cyPx = rect.top + m.cy * rect.height;
  const rxPx = m.rx * long;
  const ryPx = m.ry * long;

  const ell = document.createElement('div');
  ell.className = 'mask-shape radial' + (selected ? ' selected' : '');
  ell.style.left = (cxPx - rxPx) + 'px';
  ell.style.top = (cyPx - ryPx) + 'px';
  ell.style.width = (rxPx * 2) + 'px';
  ell.style.height = (ryPx * 2) + 'px';
  ell.addEventListener('mousedown', (e) => {
    if (!selected) selectMaskNoRender(m.id);
    startDrag(e, 'move', m);
  });
  ell.addEventListener('click', (e) => { e.stopPropagation(); });
  overlay.appendChild(ell);

  if (!selected) return;

  // 4 edge handles
  const handles = [
    { cls: 'edge-n', x: cxPx, y: cyPx - ryPx, mode: 'rN' },
    { cls: 'edge-s', x: cxPx, y: cyPx + ryPx, mode: 'rS' },
    { cls: 'edge-e', x: cxPx + rxPx, y: cyPx, mode: 'rE' },
    { cls: 'edge-w', x: cxPx - rxPx, y: cyPx, mode: 'rW' },
  ];
  for (const h of handles) {
    const dot = document.createElement('div');
    dot.className = 'mask-handle ' + h.cls;
    dot.style.left = h.x + 'px';
    dot.style.top = h.y + 'px';
    dot.addEventListener('mousedown', (e) => startDrag(e, h.mode, m));
    overlay.appendChild(dot);
  }
  // center
  const c = document.createElement('div');
  c.className = 'mask-handle center';
  c.style.left = cxPx + 'px';
  c.style.top = cyPx + 'px';
  c.addEventListener('mousedown', (e) => startDrag(e, 'move', m));
  overlay.appendChild(c);
}

function drawLinear(overlay, rect, m, selected) {
  const x1 = rect.left + m.x1 * rect.width;
  const y1 = rect.top + m.y1 * rect.height;
  const x2 = rect.left + m.x2 * rect.width;
  const y2 = rect.top + m.y2 * rect.height;
  const len = Math.hypot(x2 - x1, y2 - y1);
  const ang = Math.atan2(y2 - y1, x2 - x1);

  const line = document.createElement('div');
  line.className = 'mask-line' + (selected ? ' selected' : '');
  line.style.left = x1 + 'px';
  line.style.top = y1 + 'px';
  line.style.width = len + 'px';
  line.style.transform = `rotate(${ang}rad)`;
  overlay.appendChild(line);

  // Two endpoint handles
  for (const [hx, hy, mode] of [[x1, y1, 'lin1'], [x2, y2, 'lin2']]) {
    const dot = document.createElement('div');
    dot.className = 'mask-handle linear';
    dot.style.left = hx + 'px';
    dot.style.top = hy + 'px';
    dot.addEventListener('mousedown', (e) => {
      if (!selected) selectMaskNoRender(m.id);
      startDrag(e, mode, m);
    });
    overlay.appendChild(dot);
  }
}

// Select a mask and update the sidebar list, but don't tear down the
// overlay DOM — the caller is mid-mousedown on an overlay element and
// needs it to stay alive long enough for the drag to start cleanly.
function selectMaskNoRender(id) {
  if (state.selectedMaskId === id) return;
  state.selectedMaskId = id;
  renderMaskList();
  // Schedule the overlay re-render for after the current event loop tick
  // so the original element survives the mousedown.
  setTimeout(renderMaskOverlay, 0);
}

// Drag handling
function startDrag(e, mode, mask) {
  e.preventDefault();
  e.stopPropagation();
  const rect = getImageRect();
  if (!rect) return;
  const stage = $('previewStage');
  const stageBB = stage.getBoundingClientRect();
  const long = Math.max(rect.width, rect.height);

  const startMx = e.clientX - stageBB.left;
  const startMy = e.clientY - stageBB.top;
  // Snapshot relevant geometry for differential drag.
  const snap = { ...mask };

  const onMove = (ev) => {
    const mx = ev.clientX - stageBB.left;
    const my = ev.clientY - stageBB.top;
    const dx = mx - startMx;
    const dy = my - startMy;
    if (mode === 'move') {
      mask.cx = clamp(snap.cx + dx / rect.width, 0, 1);
      mask.cy = clamp(snap.cy + dy / rect.height, 0, 1);
    } else if (mode === 'rN') {
      mask.ry = clamp(snap.ry - dy / long, 0.01, 2);
    } else if (mode === 'rS') {
      mask.ry = clamp(snap.ry + dy / long, 0.01, 2);
    } else if (mode === 'rE') {
      mask.rx = clamp(snap.rx + dx / long, 0.01, 2);
    } else if (mode === 'rW') {
      mask.rx = clamp(snap.rx - dx / long, 0.01, 2);
    } else if (mode === 'lin1') {
      mask.x1 = clamp(snap.x1 + dx / rect.width, -0.1, 1.1);
      mask.y1 = clamp(snap.y1 + dy / rect.height, -0.1, 1.1);
    } else if (mode === 'lin2') {
      mask.x2 = clamp(snap.x2 + dx / rect.width, -0.1, 1.1);
      mask.y2 = clamp(snap.y2 + dy / rect.height, -0.1, 1.1);
    }
    renderMaskOverlay();
    requestPreview();
  };
  const onUp = () => {
    window.removeEventListener('mousemove', onMove);
    window.removeEventListener('mouseup', onUp);
  };
  window.addEventListener('mousemove', onMove);
  window.addEventListener('mouseup', onUp);
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

// ============================================================================
// Geometry transforms (rotation + flip) — apply to image AND existing masks.
// All rotations are clockwise.

async function applyRotation(deltaCW) {
  transformMasks({ rotation: deltaCW });
  state.params.rotation = (((state.params.rotation || 0) + deltaCW) % 360 + 360) % 360;
  syncTransformButtons();
  await afterTransform();
}

async function applyFlip(axis) {
  transformMasks({ flip: axis });
  if (axis === 'H') state.params.flip_h = !state.params.flip_h;
  else state.params.flip_v = !state.params.flip_v;
  syncTransformButtons();
  await afterTransform();
}

async function afterTransform() {
  // Re-render the BEFORE image with the same geometry so the compare slider
  // still works (otherwise a 90°-rotated AFTER would overlap an un-rotated
  // BEFORE of mismatched dimensions).
  try { await renderBaseImage(); } catch {}
  renderMaskOverlay();
  requestPreview();
}

function transformMasks(op) {
  for (const m of state.masks) {
    if (op.rotation !== undefined) {
      const r = ((op.rotation % 360) + 360) % 360;
      if (r === 90) {
        // CW 90°: (x, y) -> (1-y, x)
        if (m.type === 'radial') {
          const { cx, cy, rx, ry } = m;
          m.cx = 1 - cy; m.cy = cx;
          m.rx = ry; m.ry = rx;
        } else {
          const { x1, y1, x2, y2 } = m;
          m.x1 = 1 - y1; m.y1 = x1;
          m.x2 = 1 - y2; m.y2 = x2;
        }
      } else if (r === 180) {
        if (m.type === 'radial') {
          m.cx = 1 - m.cx; m.cy = 1 - m.cy;
        } else {
          m.x1 = 1 - m.x1; m.y1 = 1 - m.y1;
          m.x2 = 1 - m.x2; m.y2 = 1 - m.y2;
        }
      } else if (r === 270) {
        // CW 270° (= CCW 90°): (x, y) -> (y, 1-x)
        if (m.type === 'radial') {
          const { cx, cy, rx, ry } = m;
          m.cx = cy; m.cy = 1 - cx;
          m.rx = ry; m.ry = rx;
        } else {
          const { x1, y1, x2, y2 } = m;
          m.x1 = y1; m.y1 = 1 - x1;
          m.x2 = y2; m.y2 = 1 - x2;
        }
      }
    }
    if (op.flip === 'H') {
      if (m.type === 'radial') m.cx = 1 - m.cx;
      else { m.x1 = 1 - m.x1; m.x2 = 1 - m.x2; }
    }
    if (op.flip === 'V') {
      if (m.type === 'radial') m.cy = 1 - m.cy;
      else { m.y1 = 1 - m.y1; m.y2 = 1 - m.y2; }
    }
  }
}

// ============================================================================
// Tabs

function bindTabs() {
  $('paramTabs').addEventListener('click', (e) => {
    const btn = e.target.closest('.tab');
    if (!btn) return;
    document.querySelectorAll('.tab').forEach((b) => b.classList.toggle('active', b === btn));
    document.querySelectorAll('.tab-panel').forEach((p) => {
      p.classList.toggle('active', p.dataset.panel === btn.dataset.tab);
    });
  });
}

// ============================================================================
// Upload + preview + export

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
    for (const id of ['rotateLeftBtn', 'rotateRightBtn', 'flipHBtn', 'flipVBtn']) {
      $(id).disabled = false;
    }

    // First render: base = defaults, top = current params.
    await renderBaseImage();
    await actuallyPreview();
    setTimeout(renderMaskOverlay, 50);
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
  if (!state.defaults) return;
  // The "before" image must share the user's current geometry so the
  // before/after compare overlay aligns. Otherwise a rotated AFTER would
  // mismatch a landscape BEFORE.
  const baseParams = {
    ...state.defaults,
    rotation: state.params.rotation || 0,
    flip_h: state.params.flip_h || false,
    flip_v: state.params.flip_v || false,
  };
  const resp = await fetch('/api/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: state.sessionId, params: baseParams }),
  });
  if (!resp.ok) throw new Error('base preview failed');
  const blob = await resp.blob();
  if (state.baseUrl) URL.revokeObjectURL(state.baseUrl);
  state.baseUrl = URL.createObjectURL(blob);
  $('previewBase').src = state.baseUrl;
}

let previewDebounce = null;
let previewSeq = 0;
function requestPreview() {
  if (!state.sessionId) return;
  if (previewDebounce) clearTimeout(previewDebounce);
  previewDebounce = setTimeout(actuallyPreview, 80);
}

async function actuallyPreview() {
  // Abort any in-flight request — the user has new params they want to see.
  if (state.previewInFlight) {
    try { state.previewInFlight.abort(); } catch {}
    state.previewInFlight = null;
  }
  const mySeq = ++previewSeq;
  const ctl = new AbortController();
  state.previewInFlight = ctl;
  try {
    const params = { ...state.params };
    params.local_masks = state.masks;
    const resp = await fetch('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId, params }),
      signal: ctl.signal,
    });
    if (mySeq !== previewSeq) return; // a newer request has started — drop result
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const ms = resp.headers.get('X-Process-Ms');
    if (ms) $('timingInfo').textContent = `处理耗时 ${Math.round(Number(ms))} ms`;
    const blob = await resp.blob();
    if (mySeq !== previewSeq) return;
    if (state.topUrl) URL.revokeObjectURL(state.topUrl);
    state.topUrl = URL.createObjectURL(blob);
    const top = $('previewTop');
    top.src = state.topUrl;
    top.onload = () => updateComparePosition();
  } catch (e) {
    if (e.name !== 'AbortError') toast('预览失败：' + e.message, 'error');
  } finally {
    if (state.previewInFlight === ctl) state.previewInFlight = null;
  }
}

async function exportFull() {
  if (!state.sessionId) return;
  setBusy(true, '导出全分辨率（请耐心，处理 + 编码可能要数秒）…');
  try {
    const fmt = $('exportFormat').value;
    const params = { ...state.params };
    params.local_masks = state.masks;
    const resp = await fetch('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: state.sessionId, params, format: fmt, quality: 95,
      }),
    });
    if (!resp.ok) {
      const err = await safeJson(resp);
      throw new Error(err.detail || `导出失败：HTTP ${resp.status}`);
    }
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

// ============================================================================
// Compare slider

function setupCompareDrag() {
  const stage = $('previewStage');
  const handle = $('compareHandle');
  let dragging = false;

  const onMove = (e) => {
    if (!dragging) return;
    const rect = stage.getBoundingClientRect();
    const x = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
    state.comparePos = clamp(x / rect.width, 0, 1);
    updateComparePosition();
  };

  handle.addEventListener('mousedown', (e) => { dragging = true; e.preventDefault(); });
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', () => { dragging = false; });
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

// ============================================================================
// Wiring

function bindEvents() {
  bindTabs();

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
    e.preventDefault(); dz.classList.remove('dragover');
    const f = e.dataTransfer.files[0]; if (f) handleUpload(f);
  });
  ['dragover', 'drop'].forEach((ev) => {
    document.querySelector('.canvas').addEventListener(ev, (e) => e.preventDefault());
  });
  document.querySelector('.canvas').addEventListener('drop', (e) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0]; if (f) handleUpload(f);
  });

  $('resetBtn').addEventListener('click', () => {
    resetAllParams();
    state.masks = [];
    state.selectedMaskId = null;
    state.params.local_masks = state.masks;
    renderMaskList();
    renderMaskOverlay();
    clearActivePreset();
    requestPreview();
    toast('参数与蒙版已重置');
  });

  $('exportBtn').addEventListener('click', exportFull);
  $('compareToggle').addEventListener('change', (e) => {
    state.compareEnabled = e.target.checked;
    updateComparePosition();
  });
  setupCompareDrag();

  $('addRadialBtn').addEventListener('click', () => createMask('radial'));
  $('addLinearBtn').addEventListener('click', () => createMask('linear'));

  $('rotateLeftBtn').addEventListener('click', () => applyRotation(-90));
  $('rotateRightBtn').addEventListener('click', () => applyRotation(90));
  $('flipHBtn').addEventListener('click', () => applyFlip('H'));
  $('flipVBtn').addEventListener('click', () => applyFlip('V'));

  // Re-render mask overlay on window resize (image bounding box changes)
  window.addEventListener('resize', () => setTimeout(renderMaskOverlay, 0));
  // And whenever the preview image finishes loading (it can resize between previews)
  $('previewBase').addEventListener('load', () => setTimeout(renderMaskOverlay, 0));
}

// ============================================================================
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
