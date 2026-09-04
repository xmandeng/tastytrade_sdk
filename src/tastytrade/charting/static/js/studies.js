// Studies registry, the Studies menu and persisted visibility. Overlays live
// on the candle pane; lower studies each own a pane (panes.js). Future
// studies register here and in LOWER_STUDIES; nothing else needs to change.
const STUDIES = {
  hma: { kind: 'simple', section: 'overlay', label: 'Hull MA', params: '20',
    swatch: { color: C.hmaUp, style: 'solid' } },
  priorOHLC: { kind: 'group', section: 'overlay', label: 'Prior day OHLC', params: 'C · H · L',
    swatch: { color: 'rgba(255,183,77,0.9)', style: 'dashed' },
    children: {
      priorClose: { label: 'Prior Close', swatch: { color: C.priorClose, style: 'dotted' } },
      priorHigh:  { label: 'Prior Hi',    swatch: { color: C.priorHigh,  style: 'dotted' } },
      priorLow:   { label: 'Prior Lo',    swatch: { color: C.priorLow,   style: 'dotted' } },
    } },
  openingRange: { kind: 'group', section: 'overlay', label: 'Opening range', params: '5 · 15 · 30',
    swatch: { color: C.orLevel, style: 'solid' },
    children: {
      or5:  { label: '5m OR',  swatch: { color: C.orLevel, style: 'solid' } },
      or15: { label: '15m OR', swatch: { color: C.orLevel, style: 'dashed' } },
      or30: { label: '30m OR', swatch: { color: C.orLevel, style: 'dotted' } },
    } },
  tradePins: { kind: 'simple', section: 'overlay', label: 'Trade pins', params: '0DTE fly',
    swatch: { color: TRADE_STYLE.fly.hue, style: 'dotted' } },
  macd: { kind: 'simple', section: 'lower', label: 'MACD', params: '12, 26, 9',
    swatch: { color: C.macdValue, style: 'solid' } },
  kalVel: { kind: 'simple', section: 'lower', label: 'Kalman velocity', params: 'q/r 0.025',
    swatch: { color: C.kalVelUp, style: 'solid' } },
};

const SECTIONS = [
  { id: 'overlay', label: 'Overlays' },
  { id: 'lower',   label: 'Lower studies' },
];

const STUDY_STORAGE_KEY = 'chart.studies.v1';
const STUDY_DEFAULTS = {
  hma: true, macd: true, kalVel: true, tradePins: true,
  priorOHLC: true, priorClose: true, priorHigh: true, priorLow: true,
  openingRange: true, or5: true, or15: true, or30: true,
};

function loadStudyState() {
  const state = { ...STUDY_DEFAULTS };
  try {
    const saved = JSON.parse(localStorage.getItem(STUDY_STORAGE_KEY) || 'null');
    if (saved && typeof saved === 'object') {
      for (const k of Object.keys(STUDY_DEFAULTS)) if (typeof saved[k] === 'boolean') state[k] = saved[k];
    }
  } catch (e) { /* storage unavailable — defaults */ }
  return state;
}
const studyState = loadStudyState();

function saveStudyState() {
  try { localStorage.setItem(STUDY_STORAGE_KEY, JSON.stringify(studyState)); } catch (e) {}
}

function setStudy(key, on) {
  if (!(key in studyState)) return;
  studyState[key] = on;
  saveStudyState();
  applyStudyState();
}

// Apply the full studyState to the chart. Called on every toggle and init.
function applyStudyState() {
  hmaPrimitive.setVisible(studyState.hma);
  Object.keys(levels).forEach(id => applyLevelVisibility(id));
  setTradePinsVisible(studyState.tradePins);
  mountLowerPanes();
  renderStudiesPanel();
  renderStrips();
}

function isGroupIndeterminate(groupKey) {
  const study = STUDIES[groupKey];
  if (!study || !study.children) return false;
  const states = Object.keys(study.children).map(k => studyState[k]);
  return !states.every(Boolean) && !states.every(s => !s);
}

function renderStudiesPanel() {
  const panel = document.getElementById('studiesPanel');
  if (!panel) return;
  const swatchHtml = (swatch) => {
    if (!swatch) return '<span class="study-swatch" style="border-color:transparent"></span>';
    const cls = swatch.style === 'dotted' ? 'dotted' : swatch.style === 'dashed' ? 'dashed' : '';
    return `<span class="study-swatch ${cls}" style="border-color:${swatch.color}"></span>`;
  };
  const checkboxState = (key, indeterminate) => indeterminate ? 'indeterminate' : (studyState[key] ? 'checked' : '');
  const row = (key, cls, s, indet) =>
    `<div class="study-row ${cls} ${checkboxState(key, indet)}" data-study="${key}">` +
    `<span class="study-checkbox"></span>${swatchHtml(s.swatch)}` +
    `<span class="study-label">${escapeHtml(s.label)}</span>` +
    (s.params ? `<span class="study-params">${escapeHtml(s.params)}</span>` : '') +
    `</div>`;
  const out = [];
  SECTIONS.forEach(sec => {
    const keys = Object.keys(STUDIES).filter(k => STUDIES[k].section === sec.id);
    if (!keys.length) return;
    out.push(`<div class="studies-section-header">${sec.label}</div>`);
    keys.forEach(key => {
      const s = STUDIES[key];
      if (s.kind === 'simple') { out.push(row(key, '', s, false)); return; }
      out.push(row(key, 'group', s, isGroupIndeterminate(key)));
      Object.keys(s.children).forEach(ck => out.push(row(ck, 'child', s.children[ck], false)));
    });
  });
  panel.innerHTML = out.join('');
}

// Attached to the panel itself (not document) so the toggle fires before the
// dropdown's stopPropagation guard; the panel element survives re-renders.
document.getElementById('studiesPanel').addEventListener('click', (e) => {
  const row = e.target.closest('.study-row');
  if (!row || !row.dataset.study) return;
  // Toggling a group flips just the parent flag — children keep their own
  // state, so re-enabling the group restores what was individually on.
  setStudy(row.dataset.study, !studyState[row.dataset.study]);
});
