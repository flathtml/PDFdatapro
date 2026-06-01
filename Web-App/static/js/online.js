/* ═══════════════════════════════════════════════════════════════════
   PDFdataPro — Online Mode Frontend JS
═══════════════════════════════════════════════════════════════════ */
'use strict';

let blockCounter = 0;
let globalPageCount = 0;

// ── Init ───────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadPdfs();
  addPageBlock();

  document.getElementById('pdf-select').addEventListener('change', onPdfChange);
  document.getElementById('add-page-btn').addEventListener('click', addPageBlock);
  document.getElementById('extract-btn').addEventListener('click', startExtraction);
  document.getElementById('clear-btn') &&
    document.getElementById('clear-btn').addEventListener('click', clearResults);
});

// ── Load PDF list ──────────────────────────────────────────────────────────────
async function loadPdfs() {
  try {
    const res  = await fetch('/api/pdfs');
    const data = await res.json();
    const sel  = document.getElementById('pdf-select');
    (data.pdfs || []).forEach(name => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      sel.appendChild(opt);
    });
  } catch (e) {
    console.error('Failed to load PDFs:', e);
  }
}

// ── PDF selection ──────────────────────────────────────────────────────────────
async function onPdfChange() {
  const pdf    = document.getElementById('pdf-select').value;
  const hint   = document.getElementById('page-count-hint');
  const addBtn = document.getElementById('add-page-btn');
  const extBtn = document.getElementById('extract-btn');

  globalPageCount = 0;
  hint.textContent = '';
  addBtn.disabled  = !pdf;
  extBtn.disabled  = !pdf;

  if (!pdf) return;

  hint.textContent = 'Loading…';
  try {
    const res  = await fetch(`/api/page_count?pdf=${encodeURIComponent(pdf)}`);
    const data = await res.json();
    if (data.count) {
      globalPageCount = data.count;
      hint.textContent = `${data.count.toLocaleString()} pages`;
      document.querySelectorAll('.page-num-input').forEach(inp => { inp.max = data.count; });
    }
  } catch (e) {
    hint.textContent = 'Could not read page count';
  }
}

// ── Page block management ──────────────────────────────────────────────────────
function addPageBlock() {
  blockCounter++;
  const id  = blockCounter;
  const tpl = document.getElementById('page-block-tpl');
  const el  = tpl.content.cloneNode(true);
  const blk = el.querySelector('.page-block');

  blk.dataset.blockId = id;
  blk.querySelector('.block-num').textContent = id;

  blk.querySelectorAll('.mode-radio').forEach(r => { r.name = `mode-${id}`; });

  blk.querySelector('.btn-remove').addEventListener('click', () => {
    blk.remove();
    renumberBlocks();
  });

  blk.querySelectorAll('.mode-radio').forEach(r => {
    r.addEventListener('change', () => onModeChange(blk));
  });

  blk.querySelector('.scan-btn').addEventListener('click', () => scanPage(blk));

  if (globalPageCount) {
    blk.querySelector('.page-num-input').max = globalPageCount;
  }

  document.getElementById('page-requests-container').appendChild(el);
  renumberBlocks();
}

function renumberBlocks() {
  document.querySelectorAll('.page-block').forEach((b, i) => {
    b.querySelector('.block-num').textContent = i + 1;
  });
}

// ── Mode toggle ────────────────────────────────────────────────────────────────
function onModeChange(blk) {
  const scanResults = blk.querySelector('.scan-results');
  if (scanResults.classList.contains('hidden')) return;

  const isPartial = blk.querySelector('.mode-radio[value=partial]').checked;
  const items = blk.querySelectorAll('.table-desc-item');
  items.forEach(item => {
    const cb = item.querySelector('.tdi-checkbox');
    if (cb) {
      cb.disabled = !isPartial;
      if (!isPartial) cb.checked = true;
    }
    updateItemState(item);
    // Sync preview dim state
    const wrapper = item.closest('.table-desc-wrapper');
    if (wrapper) {
      const preview = wrapper.querySelector('.tdi-preview');
      if (preview) {
        const checked = cb ? cb.checked : true;
        preview.classList.toggle('tdi-preview-dimmed', !checked);
      }
    }
  });

  const intro = blk.querySelector('.scan-intro');
  intro.textContent = isPartial
    ? 'Check the tables you want to extract and enter a description for each selected table:'
    : 'All tables will be extracted. Enter a description for each table:';
}

// ── Scan page ─────────────────────────────────────────────────────────────────
async function scanPage(blk) {
  const pdf  = document.getElementById('pdf-select').value;
  const page = parseInt(blk.querySelector('.page-num-input').value, 10);

  if (!pdf)  { alert('Please select a PDF file first.'); return; }
  if (!page) { alert('Please enter a page number first.'); return; }

  const scanBtn   = blk.querySelector('.scan-btn');
  const statusEl  = blk.querySelector('.scan-status');
  const resultsEl = blk.querySelector('.scan-results');
  const listEl    = blk.querySelector('.table-desc-list');

  scanBtn.disabled = true;
  statusEl.classList.remove('hidden');
  resultsEl.classList.add('hidden');
  listEl.innerHTML = '';

  try {
    const res  = await fetch('/api/scan_page', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pdf, page }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    const tables    = data.tables || [];
    const isPartial = blk.querySelector('.mode-radio[value=partial]').checked;
    const intro     = blk.querySelector('.scan-intro');

    if (tables.length === 0) {
      intro.textContent = '';
      listEl.innerHTML  = '<p class="scan-empty">No tables detected on this page.</p>';
    } else {
      intro.textContent = isPartial
        ? 'Check the tables you want to extract and enter a description for each selected table:'
        : 'All tables will be extracted. Enter a description for each table:';

      tables.forEach((tbl, idx) => {
        const serialNum = idx + 1;
        const { wrapper, img, spinner } = buildTableDescItem(tbl, isPartial, serialNum);
        listEl.appendChild(wrapper);

        // Load the preview image asynchronously
        const previewUrl = `/api/table_preview?pdf=${encodeURIComponent(pdf)}&page=${page}&table_id=${tbl.id}`;
        img.onload  = () => { spinner.style.display = 'none'; img.style.display = 'block'; };
        img.onerror = () => { spinner.textContent = 'Preview unavailable'; };
        img.src = previewUrl;
      });
    }

    resultsEl.classList.remove('hidden');
  } catch (e) {
    blk.querySelector('.scan-intro').textContent = '';
    listEl.innerHTML = `<p class="scan-error">Scan failed: ${escHtml(e.message)}</p>`;
    blk.querySelector('.scan-results').classList.remove('hidden');
  } finally {
    statusEl.classList.add('hidden');
    scanBtn.disabled = false;
  }
}

// ── Build per-table description row ───────────────────────────────────────────
function buildTableDescItem(tbl, isPartial, serialNum) {
  // Outer wrapper: form row on top, image preview below
  const wrapper = document.createElement('div');
  wrapper.className = 'table-desc-wrapper';

  // ── Top row: selection + serial label + form fields ────────────────────────
  const item = document.createElement('div');
  item.className = 'table-desc-item';
  item.dataset.tableId = tbl.id;

  const selCol = document.createElement('div');
  selCol.className = 'tdi-sel';

  if (isPartial) {
    const cb = document.createElement('input');
    cb.type      = 'checkbox';
    cb.className = 'tdi-checkbox';
    cb.checked   = true;
    cb.addEventListener('change', () => {
      updateItemState(item);
      // Dim the preview when unchecked
      previewEl.classList.toggle('tdi-preview-dimmed', !cb.checked);
    });
    selCol.appendChild(cb);
  } else {
    const tick = document.createElement('span');
    tick.className   = 'tdi-locked';
    tick.textContent = '✓';
    selCol.appendChild(tick);
  }

  // Serial number label — replaces old metadata title/info
  const metaCol = document.createElement('div');
  metaCol.className = 'tdi-meta';
  const serialLabel = document.createElement('span');
  serialLabel.className = 'tdi-serial';
  serialLabel.textContent = `Table #${serialNum}`;
  metaCol.appendChild(serialLabel);

  const descCol = document.createElement('div');
  descCol.className = 'tdi-desc-col';

  const ta = document.createElement('textarea');
  ta.className   = 'form-input tdi-desc-input';
  ta.rows        = 2;
  ta.placeholder = 'Enter a description for this table…';
  ta.addEventListener('input', () => updateItemState(item));
  descCol.appendChild(ta);

  const err = document.createElement('span');
  err.className = 'tdi-desc-error hidden';
  err.textContent = 'Description is required for selected tables.';
  descCol.appendChild(err);

  // Alignment dropdown
  const alignWrap = document.createElement('div');
  alignWrap.className = 'tdi-align-wrap';
  const alignLabel = document.createElement('label');
  alignLabel.className = 'tdi-align-label';
  alignLabel.textContent = 'Table Alignment:';
  const alignSel = document.createElement('select');
  alignSel.className = 'form-input tdi-align-select';
  [['horizontal', 'Horizontal (default)'], ['vertical', 'Vertical (rotated 90°)']].forEach(([val, txt]) => {
    const opt = document.createElement('option');
    opt.value = val; opt.textContent = txt;
    alignSel.appendChild(opt);
  });
  alignSel.value = 'horizontal';
  alignWrap.appendChild(alignLabel);
  alignWrap.appendChild(alignSel);
  descCol.appendChild(alignWrap);

  item.appendChild(selCol);
  item.appendChild(metaCol);
  item.appendChild(descCol);

  // ── Image preview section below the form row ───────────────────────────────
  const previewEl = document.createElement('div');
  previewEl.className = 'tdi-preview';

  const previewLabel = document.createElement('div');
  previewLabel.className = 'tdi-preview-label';
  previewLabel.textContent = `Table #${serialNum} — Preview`;
  previewEl.appendChild(previewLabel);

  const spinner = document.createElement('div');
  spinner.className = 'tdi-preview-spinner';
  spinner.textContent = 'Loading preview…';
  previewEl.appendChild(spinner);

  const img = document.createElement('img');
  img.className = 'tdi-preview-img';
  img.alt       = `Preview of Table #${serialNum}`;
  img.style.display = 'none';  // shown after load
  previewEl.appendChild(img);

  wrapper.appendChild(item);
  wrapper.appendChild(previewEl);

  updateItemState(item);
  return { wrapper, item, img, spinner };
}

// ── Update visual state of a table-desc-item ──────────────────────────────────
function updateItemState(item) {
  const cb        = item.querySelector('.tdi-checkbox');
  const ta        = item.querySelector('.tdi-desc-input');
  const err       = item.querySelector('.tdi-desc-error');
  const alignSel  = item.querySelector('.tdi-align-select');
  const checked   = cb ? cb.checked : true;

  item.classList.toggle('tdi-unchecked', !checked);
  ta.disabled = !checked;
  if (alignSel) alignSel.disabled = !checked;
  if (!checked) {
    ta.value = '';
    err.classList.add('hidden');
    item.classList.remove('tdi-invalid');
  }
}

// ── Build extraction payload ───────────────────────────────────────────────────
function buildPayload() {
  const pdf = document.getElementById('pdf-select').value;
  if (!pdf) { alert('Please select a PDF file.'); return null; }

  const pages = [];
  let hasValidationError = false;

  for (const blk of document.querySelectorAll('.page-block')) {
    const page = parseInt(blk.querySelector('.page-num-input').value, 10);
    if (!page || page < 1) {
      alert('Please enter a valid page number for all page requests.');
      return null;
    }

    const mode     = blk.querySelector('.mode-radio[value=partial]').checked ? 'partial' : 'full';
    const scanDone = !blk.querySelector('.scan-results').classList.contains('hidden');
    // Items live inside .table-desc-wrapper > .table-desc-item
    const items    = blk.querySelectorAll('.table-desc-item');

    if (!scanDone || items.length === 0) {
      alert(`Page ${page}: Please scan the page for tables first.`);
      return null;
    }

    const tableEntries = [];
    items.forEach(item => {
      const cb      = item.querySelector('.tdi-checkbox');
      const checked = cb ? cb.checked : true;
      if (!checked) return;

      const ta        = item.querySelector('.tdi-desc-input');
      const desc      = (ta.value || '').trim();
      const err       = item.querySelector('.tdi-desc-error');
      const alignSel  = item.querySelector('.tdi-align-select');
      const alignment = alignSel ? alignSel.value : 'horizontal';

      if (!desc) {
        err.classList.remove('hidden');
        item.classList.add('tdi-invalid');
        hasValidationError = true;
      } else {
        err.classList.add('hidden');
        item.classList.remove('tdi-invalid');
        tableEntries.push({
          table_id:    parseInt(item.dataset.tableId, 10),
          description: desc,
          alignment:   alignment,
        });
      }
    });

    if (hasValidationError) continue;

    if (tableEntries.length === 0) {
      alert(`Page ${page}: Please select at least one table.`);
      return null;
    }

    pages.push({ page, mode, tables: tableEntries });
  }

  if (hasValidationError) {
    alert('Please enter a description for every selected table (highlighted in red).');
    return null;
  }

  if (!pages.length) { alert('Please add at least one page request.'); return null; }
  return { pdf, pages };
}

// ── Start extraction ───────────────────────────────────────────────────────────
async function startExtraction() {
  const payload = buildPayload();
  if (!payload) return;

  const progressSec = document.getElementById('progress-section');
  const progressTxt = document.getElementById('progress-text');
  const resultsSec  = document.getElementById('results-section');
  const resultsCtr  = document.getElementById('results-container');
  const extBtn      = document.getElementById('extract-btn');

  progressSec.classList.remove('hidden');
  resultsSec.classList.add('hidden');
  resultsCtr.innerHTML = '';
  extBtn.disabled = true;

  const pageList = payload.pages.map(p => `page ${p.page}`).join(', ');
  progressTxt.textContent = `Extracting data from ${pageList}…`;

  try {
    const res  = await fetch('/api/extract', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    renderResults(data.results, payload.pdf);
    resultsSec.classList.remove('hidden');
    resultsSec.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) {
    resultsCtr.innerHTML = `<div class="error-card"><strong>Extraction failed</strong><br>${escHtml(e.message)}</div>`;
    resultsSec.classList.remove('hidden');
  } finally {
    progressSec.classList.add('hidden');
    extBtn.disabled = false;
  }
}

// ── Render results ─────────────────────────────────────────────────────────────
function renderResults(results, pdfName) {
  const ctr = document.getElementById('results-container');
  ctr.innerHTML = '';

  results.forEach(pr => {
    const group = document.createElement('div');
    group.className = 'page-result-group';

    const lbl = document.createElement('div');
    lbl.className = 'page-result-label';
    lbl.textContent = `${pdfName}  —  Page ${pr.page}`;
    group.appendChild(lbl);

    if (pr.error) {
      const err = document.createElement('div');
      err.className = 'error-card';
      err.innerHTML = `<strong>Error on page ${pr.page}</strong><br>${escHtml(pr.error)}`;
      group.appendChild(err);
    } else if (!pr.tables || pr.tables.length === 0) {
      const msg = document.createElement('div');
      msg.className = 'no-tables';
      msg.textContent = 'No tables were detected on this page.';
      group.appendChild(msg);
    } else {
      pr.tables.forEach((tbl, idx) => {
        group.appendChild(buildTableCard(tbl, pr.page, idx, tbl.description || ''));
      });
    }

    ctr.appendChild(group);
  });
}

// ── Build table card ───────────────────────────────────────────────────────────
function buildTableCard(tbl, pageNum, tblIdx, description) {
  const card = document.createElement('div');
  card.className = 'table-card';

  if (description) {
    const banner = document.createElement('div');
    banner.className = 'table-desc-banner';
    banner.textContent = description;
    card.appendChild(banner);
  }

  const hdr = document.createElement('div');
  hdr.className = 'table-card-header';
  hdr.innerHTML = `
    <div>
      <div class="table-card-title">${escHtml(tbl.title || 'Table')}</div>
      ${tbl.subtitle ? `<div class="table-card-subtitle">${escHtml(tbl.subtitle)}</div>` : ''}
      ${tbl.rotated  ? `<div class="table-card-rotated-badge">(rotated → displayed horizontally)</div>` : ''}
    </div>`;

  const dlBtn = document.createElement('button');
  dlBtn.className = 'dl-btn';
  dlBtn.textContent = '⬇ Download CSV';
  dlBtn.addEventListener('click', () => downloadCSV(tbl, pageNum, tblIdx, description));
  hdr.appendChild(dlBtn);
  card.appendChild(hdr);

  const scroll = document.createElement('div');
  scroll.className = 'table-scroll';
  scroll.appendChild(buildDataTable(tbl));
  card.appendChild(scroll);

  if (tbl.footnotes) {
    const fn = document.createElement('div');
    fn.className = 'table-footnote';
    fn.textContent = tbl.footnotes;
    card.appendChild(fn);
  }

  return card;
}

function buildDataTable(tbl) {
  const table = document.createElement('table');
  table.className = 'data-table';

  if (tbl.headers && tbl.headers.length) {
    const thead = document.createElement('thead');
    const tr    = document.createElement('tr');
    tbl.headers.forEach(h => {
      const th = document.createElement('th');
      th.textContent = h || '';
      tr.appendChild(th);
    });
    thead.appendChild(tr);
    table.appendChild(thead);
  }

  const tbody = document.createElement('tbody');
  const nCols = (tbl.headers || []).length || (tbl.rows && tbl.rows[0] ? tbl.rows[0].length : 1);

  (tbl.rows || []).forEach((row, ri) => {
    const rtype = (tbl.row_types && tbl.row_types[ri]) || 'data';
    const tr    = document.createElement('tr');
    tr.className = `row-${rtype}`;

    if (rtype === 'section_header') {
      const td = document.createElement('td');
      td.colSpan = nCols;
      td.textContent = (row[0] || '').trimStart();
      tr.appendChild(td);
    } else {
      row.forEach((cell, ci) => {
        const td = document.createElement('td');
        if (ci === 0) {
          const leading = (cell.match(/^(\s+)/) || ['', ''])[1].length;
          const indent  = Math.floor(leading / 2);
          td.style.paddingLeft = `${11 + indent * 16}px`;
          td.textContent = cell.trimStart();
        } else {
          td.textContent = cell;
        }
        tr.appendChild(td);
      });
      for (let i = row.length; i < nCols; i++) {
        tr.appendChild(document.createElement('td'));
      }
    }
    tbody.appendChild(tr);
  });

  table.appendChild(tbody);
  return table;
}

// ── CSV download ───────────────────────────────────────────────────────────────
function downloadCSV(tbl, pageNum, tblIdx, description) {
  const csvEscape = s => {
    const str = String(s);
    return (str.includes(',') || str.includes('"') || str.includes('\n'))
      ? '"' + str.replace(/"/g, '""') + '"'
      : str;
  };

  const allRows = [];
  if (description) {
    allRows.push([`Description: ${description}`]);
    allRows.push([]);
  }
  if (tbl.headers && tbl.headers.length) allRows.push(tbl.headers);
  (tbl.rows || []).forEach(row => allRows.push(row.map(c => c.trimStart())));

  const csv  = allRows.map(row => row.map(csvEscape).join(',')).join('\r\n');
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  const safe = (tbl.title || `table_${tblIdx + 1}`)
    .replace(/[^a-zA-Z0-9_\- ]/g, '').replace(/\s+/g, '_').substring(0, 60);
  a.download = `Page${pageNum}_${safe}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ── Clear results ──────────────────────────────────────────────────────────────
function clearResults() {
  document.getElementById('results-container').innerHTML = '';
  document.getElementById('results-section').classList.add('hidden');
}

// ── Utility ────────────────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
