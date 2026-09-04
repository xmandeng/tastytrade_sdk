// TT-156 day-P&L tracker (STATS card): a floating card dragged by its grip
// anywhere over the pane stack; the parked position persists per browser.
// Data arrives in init and once per candle period, computed with the
// report's own accounting.
const pnlCard = document.getElementById('pnlCard');
const pnlRows = document.getElementById('pnlRows');
const pnlFoot = document.getElementById('pnlFoot');
const pnlFootK = document.getElementById('pnlFootK');
const pnlFootV = document.getElementById('pnlFootV');

function pnlUsd(v) { return (v < 0 ? '-$' : '$') + Math.abs(v).toLocaleString(); }

function renderPnl(pnl) {
  if (!pnl || !pnl.arms || !pnl.arms.length) { pnlCard.classList.remove('on'); return; }
  const header = '<span></span><span class="pnl-hdr" style="text-align: center">CYC</span>' +
                 '<span class="pnl-hdr">P&amp;L</span><span class="pnl-hdr">MARGIN</span>';
  pnlRows.innerHTML = header + pnl.arms.map(a => {
    const cls = a.total == null ? 'flat' : (a.total > 0 ? 'pos' : (a.total < 0 ? 'neg' : 'flat'));
    const val = a.total == null ? '&mdash;' : pnlUsd(a.total);
    const cyc = a.cycles ? `<span class="pnl-cyc">${a.cycles}</span>` : '<span class="pnl-cyc">&mdash;</span>';
    const open = a.open ? '<span class="pnl-open">OPEN</span>' : '';
    const mgn = a.margin == null ? '&mdash;' : pnlUsd(a.margin);
    return `<span class="pnl-arm">${a.label}</span>` +
           `<div class="pnl-r">${open}${cyc}</div>` +
           `<span class="pnl-val ${cls}">${val}</span>` +
           `<span class="pnl-mgn">${mgn}</span>`;
  }).join('');
  const tents = pnl.arms
    .map(a => a.tents ? `${a.tents}×${a.label.replace('-wide', 'w')}` : '')
    .filter(Boolean).join(' ');
  if (tents) {
    pnlFootK.textContent = pnl.settled ? 'In tent' : 'Locked';
    pnlFootV.textContent = tents;
    pnlFoot.style.display = 'flex';
  } else {
    pnlFoot.style.display = 'none';
  }
  pnlCard.classList.add('on');
  clampPnlCard();
}

// A remembered position is only valid for the window it was dragged in; a
// smaller window or another device must not leave the card outside the chart.
function clampPnlCard() {
  if (!pnlCard.style.left) return;
  const host = chartEl.getBoundingClientRect();
  const maxLeft = Math.max(0, host.width - pnlCard.offsetWidth);
  const maxTop = Math.max(0, host.height - pnlCard.offsetHeight);
  pnlCard.style.left = Math.min(Math.max(parseFloat(pnlCard.style.left), 0), maxLeft) + 'px';
  pnlCard.style.top = Math.min(Math.max(parseFloat(pnlCard.style.top), 0), maxTop) + 'px';
}

(() => {
  const head = document.getElementById('pnlHead');
  try {
    const saved = JSON.parse(localStorage.getItem('pnlCardPos') || 'null');
    if (saved && saved.left != null) {
      pnlCard.style.left = saved.left + 'px';
      pnlCard.style.top = saved.top + 'px';
      pnlCard.style.right = 'auto';
    }
  } catch (e) { /* storage unavailable — default position */ }
  window.addEventListener('resize', clampPnlCard);
  let drag = null;
  head.addEventListener('pointerdown', (ev) => {
    const r = pnlCard.getBoundingClientRect();
    drag = { dx: ev.clientX - r.left, dy: ev.clientY - r.top, host: chartEl.getBoundingClientRect() };
    head.setPointerCapture(ev.pointerId);
    ev.preventDefault();
  });
  head.addEventListener('pointermove', (ev) => {
    if (!drag) return;
    const left = Math.min(Math.max(ev.clientX - drag.dx - drag.host.left, 0), drag.host.width - pnlCard.offsetWidth);
    const top = Math.min(Math.max(ev.clientY - drag.dy - drag.host.top, 0), drag.host.height - pnlCard.offsetHeight);
    pnlCard.style.left = left + 'px';
    pnlCard.style.top = top + 'px';
    pnlCard.style.right = 'auto';
  });
  head.addEventListener('pointerup', () => {
    if (!drag) return;
    drag = null;
    try {
      localStorage.setItem('pnlCardPos', JSON.stringify({
        left: parseFloat(pnlCard.style.left), top: parseFloat(pnlCard.style.top),
      }));
    } catch (e) { /* storage unavailable — position not remembered */ }
  });
})();
