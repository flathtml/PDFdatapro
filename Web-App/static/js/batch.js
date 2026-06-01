/* ═══════════════════════════════════════════════════════════════════
   PDFdataPro — Batch Mode Frontend JS
═══════════════════════════════════════════════════════════════════ */
'use strict';

// ── Init ───────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadJsonList();

  document.getElementById('json-select').addEventListener('change', onJsonChange);
  document.getElementById('refresh-json-btn').addEventListener('click', onRefreshJson);
  document.getElementById('batch-extract-btn').addEventListener('click', runBatchExtraction);
  document.getElementById('clear-btn') &&
    document.getElementById('clear-btn').addEventListener('click', clearResults);
});

// ── Load JSON spec list ────────────────────────────────────────────────────────
async function loadJsonList() {
  try {
    const res  = await fetch('/api/batch_jsons');
    const data = await res.json();
    const sel  = document.getElementById('json-select');
    (data.jsons || []).forEach(name => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      sel.appendChild(opt);
    });
  } catch (e) {
    console.error('Failed to load JSON list:', e);
  }
}

// ── JSON selection ─────────────────────────────────────────────────────────────
async function onJsonChange() {
  const jsonFile = document.getElementById('json-select').value;
  const hint     = document.getElementById('json-hint');
  const panel    = document.getElementById('json-preview-panel');
  const extBtn   = document.getElementById('batch-extract-btn');

  hint.textContent = '';
  panel.classList.add('hidden');
  extBtn.disabled = !jsonFile;

  if (!jsonFile) return;

  await loadJsonPreview(jsonFile);
}

async function onRefreshJson() {
  const jsonFile = document.getElementById('json-select').value;
  if (jsonFile) await loadJsonPreview(jsonFile);
}

async function loadJsonPreview(jsonFile) {
  const hint    = document.getElementById('json-hint');
  const panel   = document.getElementById('json-preview-panel');
  const summary = document.getElementById('json-summary');

  hint.textContent = 'Loading preview…';
  panel.classList.add('hidden');
  summary.innerHTML = '';

  try {
    // Fetch the JSON content via a dedicated API endpoint
    const res  = await fetch(`/api/batch_json_preview?file=${encodeURIComponent(jsonFile)}`);
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    hint.textContent = '';
    renderJsonSummary(data.spec, summary);
    panel.classList.remove('hidden');
  } catch (e) {
    hint.textContent = `Preview failed: ${e.message}`;
  }
}

// ── Render JSON summary ────────────────────────────────────────────────────────
function renderJsonSummary(spec, container) {
  container.innerHTML = '';

  // PDF path row
  const pdfRow = document.createElement('div');
  pdfRow.className = 'json-summary-row';
  pdfRow.innerHTML = `
    <span class="jsrow-label">PDF File</span>
    <span class="jsrow-value jsrow-pdf">${escHtml(spec['INPUT-PDF-PATH'] || '—')}</span>`;
  container.appendChild(pdfRow);

  const requests = spec['REQUESTS'] || [];
  const countRow = document.createElement('div');
  countRow.className = 'json-summary-row';
  countRow.innerHTML = `
    <span class="jsrow-label">Requests</span>
    <span class="jsrow-value">${requests.length} page request${requests.length !== 1 ? 's' : ''}</span>`;
  container.appendChild(countRow);

  // Request details table
  if (requests.length > 0) {
    const tbl = document.createElement('table');
    tbl.className = 'json-req-table';
    tbl.innerHTML = `
      <thead>
        <tr>
          <th>#</th>
          <th>Page</th>
          <th>Mode</th>
          <th>Tables</th>
        </tr>
      </thead>`;
    const tbody = document.createElement('tbody');

    requests.forEach(req => {
      const tables = req['TABLES'] || [];
      const tableList = tables.map(t =>
        `<span class="json-table-chip">T${t['TABLE-NUM']}: ${escHtml(t['TABLE-DESCRIPTION'] || '')}</span>`
      ).join(' ');

      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="jrt-num">${escHtml(req['REQUEST-NUM'] || '')}</td>
        <td class="jrt-page">${escHtml(String(req['PAGE-NUM'] || ''))}</td>
        <td><span class="jrt-mode jrt-mode-${(req['PAGE-CHOICE'] || '').toLowerCase()}">${escHtml(req['PAGE-CHOICE'] || '')}</span></td>
        <td class="jrt-tables">${tableList}</td>`;
      tbody.appendChild(tr);
    });

    tbl.appendChild(tbody);
    container.appendChild(tbl);
  }
}

// ── Run batch extraction ───────────────────────────────────────────────────────
async function runBatchExtraction() {
  const jsonFile = document.getElementById('json-select').value;
  if (!jsonFile) { alert('Please select a JSON specification file.'); return; }

  const progressSec = document.getElementById('progress-section');
  const progressTxt = document.getElementById('progress-text');
  const resultsSec  = document.getElementById('results-section');
  const resultsCtr  = document.getElementById('results-container');
  const extBtn      = document.getElementById('batch-extract-btn');

  progressSec.classList.remove('hidden');
  resultsSec.classList.add('hidden');
  resultsCtr.innerHTML = '';
  extBtn.disabled = true;
  progressTxt.textContent = `Running batch extraction from ${jsonFile}…`;

  try {
    const res  = await fetch('/api/batch_extract', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ json_file: jsonFile }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    renderBatchResults(data);
    resultsSec.classList.remove('hidden');
    resultsSec.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) {
    resultsCtr.innerHTML = `<div class="error-card"><strong>Batch extraction failed</strong><br>${escHtml(e.message)}</div>`;
    resultsSec.classList.remove('hidden');
  } finally {
    progressSec.classList.add('hidden');
    extBtn.disabled = false;
  }
}

// ── Render batch results ───────────────────────────────────────────────────────
function renderBatchResults(data) {
  const ctr = document.getElementById('results-container');
  ctr.innerHTML = '';

  // Summary header
  const summaryBar = document.createElement('div');
  summaryBar.className = 'batch-summary-bar';
  summaryBar.innerHTML = `
    <span class="bsb-label">Batch complete</span>
    <span class="bsb-detail">
      ${escHtml(data.json_file)} &nbsp;|&nbsp;
      PDF: ${escHtml(data.pdf)} &nbsp;|&nbsp;
      ${(data.results || []).length} request${(data.results || []).length !== 1 ? 's' : ''} processed
    </span>`;
  ctr.appendChild(summaryBar);

  (data.results || []).forEach(pr => {
    const group = document.createElement('div');
    group.className = 'page-result-group';

    const lbl = document.createElement('div');
    lbl.className = 'page-result-label';
    lbl.innerHTML = `
      <span>${escHtml(data.pdf)}  —  Page ${pr.page}</span>
      <span class="prl-badge prl-badge-${pr.page_choice}">${escHtml((pr.page_choice || '').charAt(0).toUpperCase() + (pr.page_choice || '').slice(1))}</span>
      <span class="prl-req">Request #${escHtml(pr.request_num || '')}</span>`;
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

// ── Build table card (shared with online) ─────────────────────────────────────
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
