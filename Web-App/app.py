"""
PDFdataPro — Advanced PDF Table Extractor
Flask backend — fully deterministic, zero LLM calls

Modes:
  /           → Home page (Welcome + Online/Batch buttons)
  /online     → Online mode (interactive, single PDF)
  /batch      → Batch mode (JSON-driven, automated)

API:
  GET  /api/pdfs                  → list PDFs in Input-PDF folder
  GET  /api/batch_jsons           → list JSON files in Input-Batch-JSON folder
  GET  /api/page_count?pdf=       → page count for a PDF
  POST /api/scan_page             → scan a page for tables
  POST /api/extract               → extract tables (online mode)
  POST /api/batch_extract         → run a full batch JSON spec
"""

import os
import json
import csv
import io
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent

# Folder containing input PDFs (generic — not just annual reports)
_default_input_pdf = BASE_DIR.parent / 'Input-PDF'
INPUT_PDF_DIR = Path(os.environ.get('INPUT_PDF_DIR', str(_default_input_pdf)))

# Folder containing batch JSON specification files
_default_batch_json = BASE_DIR.parent / 'Input-Batch-JSON'
BATCH_JSON_DIR = Path(os.environ.get('BATCH_JSON_DIR', str(_default_batch_json)))

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB


def _pdf_path(filename):
    """Resolve a PDF filename to its full path in Input-PDF folder."""
    return INPUT_PDF_DIR / filename


def list_pdfs():
    if not INPUT_PDF_DIR.exists():
        return []
    return sorted(p.name for p in INPUT_PDF_DIR.glob('*.pdf'))


def list_batch_jsons():
    if not BATCH_JSON_DIR.exists():
        return []
    return sorted(p.name for p in BATCH_JSON_DIR.glob('*.json'))


# ── Page Routes ───────────────────────────────────────────────────────────────

@app.route('/')
def home():
    return render_template('home.html')


@app.route('/online')
def online():
    return render_template('online.html')


@app.route('/batch')
def batch():
    return render_template('batch.html')


# ── API: PDF & JSON listing ───────────────────────────────────────────────────

@app.route('/api/pdfs')
def api_pdfs():
    return jsonify({'pdfs': list_pdfs()})


@app.route('/api/batch_jsons')
def api_batch_jsons():
    return jsonify({'jsons': list_batch_jsons()})


# ── API: Page count ───────────────────────────────────────────────────────────

@app.route('/api/page_count')
def api_page_count():
    pdf_name = request.args.get('pdf', '')
    if not pdf_name:
        return jsonify({'error': 'No PDF specified'}), 400
    path = _pdf_path(pdf_name)
    if not path.exists():
        return jsonify({'error': 'File not found'}), 404
    try:
        from extractor import get_page_count
        return jsonify({'count': get_page_count(str(path))})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── API: Scan page ────────────────────────────────────────────────────────────

@app.route('/api/scan_page', methods=['POST'])
def api_scan_page():
    """Return list of table descriptors found on a page."""
    data = request.get_json(force=True)
    pdf_name = data.get('pdf', '')
    page_number = int(data.get('page', 1))
    path = _pdf_path(pdf_name)
    if not path.exists():
        return jsonify({'error': 'File not found'}), 404
    try:
        from extractor import scan_page
        tables = scan_page(str(path), page_number)
        return jsonify({'tables': tables})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── API: Online extract ───────────────────────────────────────────────────────

@app.route('/api/extract', methods=['POST'])
def api_extract():
    """
    Extract tables from one or more pages (Online mode).
    Payload:
    {
      "pdf": "filename.pdf",
      "pages": [
        {
          "page": 277,
          "mode": "full",
          "tables": [
            {"table_id": 1, "description": "Balance Sheet"},
            {"table_id": 2, "description": "P&L Statement"}
          ]
        }
      ]
    }
    """
    data = request.get_json(force=True)
    pdf_name = data.get('pdf', '')
    pages = data.get('pages', [])
    if not pdf_name or not pages:
        return jsonify({'error': 'Missing parameters'}), 400
    path = _pdf_path(pdf_name)
    if not path.exists():
        return jsonify({'error': 'File not found'}), 404

    from extractor import extract_tables

    results = []
    for req in pages:
        page_num = int(req.get('page', 1))
        table_entries = req.get('tables', [])
        table_ids = [int(t['table_id']) for t in table_entries] if table_entries else None
        desc_map      = {int(t['table_id']): t.get('description', '').strip() for t in table_entries}
        alignment_map = {int(t['table_id']): t.get('alignment', 'horizontal').strip() for t in table_entries}
        try:
            tables = extract_tables(str(path), page_num, table_ids, alignments=alignment_map)
            for i, tbl in enumerate(tables):
                tid = table_ids[i] if table_ids and i < len(table_ids) else (i + 1)
                tbl['description'] = desc_map.get(tid, '')
            results.append({'page': page_num, 'tables': tables, 'error': None})
        except Exception as e:
            results.append({'page': page_num, 'tables': [], 'error': str(e)})

    return jsonify({'results': results})


# ── API: Table image preview ─────────────────────────────────────────────────

@app.route('/api/table_preview')
def api_table_preview():
    """
    Render a cropped image of a specific table on a PDF page.
    Uses PyMuPDF for rendering (pure-Python, no Ghostscript/Wand needed on Windows).
    Uses scan_page() for correct table bbox (same logic as extraction).
    Query params: pdf=filename.pdf, page=277, table_id=1
    Returns: PNG image
    """
    pdf_name = request.args.get('pdf', '')
    page_num = int(request.args.get('page', 1))
    table_id = int(request.args.get('table_id', 1))  # 1-based

    if not pdf_name:
        return jsonify({'error': 'No PDF specified'}), 400
    path = _pdf_path(pdf_name)
    if not path.exists():
        return jsonify({'error': 'File not found'}), 404

    try:
        # PyMuPDF installs as 'PyMuPDF' on pip.
        # The Python module name is 'pymupdf' (v1.24+) or 'fitz' (older versions).
        try:
            import pymupdf as _mupdf
        except ImportError:
            import fitz as _mupdf  # older PyMuPDF
        import io
        from extractor import scan_page

        # Get table bboxes using the same logic as extraction
        tables = scan_page(str(path), page_num)
        tbl = next((t for t in tables if t['id'] == table_id), None)

        if not tbl:
            # Return a grey placeholder if table not found
            try:
                from PIL import Image
                img = Image.new('RGB', (600, 100), color=(240, 240, 240))
                buf = io.BytesIO()
                img.save(buf, format='PNG')
            except Exception:
                # Minimal 1x1 PNG fallback
                buf = io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)
            buf.seek(0)
            return send_file(buf, mimetype='image/png')

        bbox = tbl['bbox']  # [x0, top, x1, bottom] — full table extent
        pad  = 10

        # Open with PyMuPDF and render the clipped region
        doc  = _mupdf.open(str(path))
        page = doc[page_num - 1]
        pw, ph = page.rect.width, page.rect.height

        x0  = max(0,  bbox[0] - pad)
        top = max(0,  bbox[1] - pad)
        x1  = min(pw, bbox[2] + pad)
        bot = min(ph, bbox[3] + pad)

        # Render at 120 DPI (scale = 120/72 ≈ 1.667)
        scale = 120 / 72
        mat   = _mupdf.Matrix(scale, scale)
        clip  = _mupdf.Rect(x0, top, x1, bot)
        pix   = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
        doc.close()

        buf = io.BytesIO(pix.tobytes('png'))
        buf.seek(0)
        return send_file(buf, mimetype='image/png',
                         max_age=300,
                         as_attachment=False)

    except Exception as e:
        import traceback
        print(f'[table_preview ERROR] {e}\n{traceback.format_exc()}')
        return jsonify({'error': str(e)}), 500


# ── API: Batch JSON preview ─────────────────────────────────────────────────────

@app.route('/api/batch_json_preview')
def api_batch_json_preview():
    """Return parsed JSON spec for preview in the UI."""
    json_filename = request.args.get('file', '')
    if not json_filename:
        return jsonify({'error': 'No file specified'}), 400
    json_path = BATCH_JSON_DIR / json_filename
    if not json_path.exists():
        return jsonify({'error': f'File not found: {json_filename}'}), 404
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            spec = json.load(f)
        return jsonify({'spec': spec})
    except Exception as e:
        return jsonify({'error': f'Failed to parse JSON: {e}'}), 400


# ── API: Batch extract ────────────────────────────────────────────────────────

@app.route('/api/batch_extract', methods=['POST'])
def api_batch_extract():
    """
    Run a full batch extraction driven by a JSON spec file.
    Payload: { "json_file": "TEST1.json" }

    The JSON spec format:
    {
      "INPUT-PDF-PATH": "C:\\...\\filename.pdf",
      "REQUESTS": [
        {
          "REQUEST-NUM": "001",
          "PAGE-NUM": 277,
          "PAGE-CHOICE": "Full",
          "TABLES": [
            {"TABLE-NUM": 1, "TABLE-DESCRIPTION": "Balance Sheet"},
            {"TABLE-NUM": 2, "TABLE-DESCRIPTION": "Income Statement"}
          ]
        },
        {
          "REQUEST-NUM": "002",
          "PAGE-NUM": 291,
          "PAGE-CHOICE": "Partial",
          "TABLES": [
            {"TABLE-NUM": 1, "TABLE-DESCRIPTION": "PPE Details"}
          ]
        }
      ]
    }

    For "Full" PAGE-CHOICE: extract all tables on the page, assign descriptions
    by TABLE-NUM order (1-based).
    For "Partial" PAGE-CHOICE: extract only the TABLE-NUMs listed.
    """
    data = request.get_json(force=True)
    json_filename = data.get('json_file', '')
    if not json_filename:
        return jsonify({'error': 'No JSON file specified'}), 400

    json_path = BATCH_JSON_DIR / json_filename
    if not json_path.exists():
        return jsonify({'error': f'JSON file not found: {json_filename}'}), 404

    # Parse the spec
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            spec = json.load(f)
    except Exception as e:
        return jsonify({'error': f'Failed to parse JSON: {e}'}), 400

    # Resolve the PDF path — use just the filename, look in Input-PDF folder
    raw_pdf_path = spec.get('INPUT-PDF-PATH', '')
    if not raw_pdf_path:
        return jsonify({'error': 'INPUT-PDF-PATH missing from JSON spec'}), 400

    # Extract just the filename from the (possibly Windows) path
    pdf_filename = Path(raw_pdf_path.replace('\\', '/')).name
    pdf_path = _pdf_path(pdf_filename)

    if not pdf_path.exists():
        return jsonify({
            'error': (
                f'PDF file "{pdf_filename}" not found in Input-PDF folder. '
                f'Expected at: {pdf_path}'
            )
        }), 404

    requests_list = spec.get('REQUESTS', [])
    if not requests_list:
        return jsonify({'error': 'No REQUESTS found in JSON spec'}), 400

    from extractor import extract_tables, scan_page

    results = []
    for req in requests_list:
        req_num = req.get('REQUEST-NUM', '?')
        page_num = int(req.get('PAGE-NUM', 1))
        page_choice = req.get('PAGE-CHOICE', 'Full').strip().lower()
        tables_spec = req.get('TABLES', [])

        # Build description and alignment maps: TABLE-NUM -> value
        desc_map      = {}
        alignment_map = {}
        for t in tables_spec:
            tnum = int(t.get('TABLE-NUM', 0))
            if tnum:
                desc_map[tnum]      = t.get('TABLE-DESCRIPTION', '').strip()
                alignment_map[tnum] = t.get('TABLE-ALIGNMENT', 'horizontal').strip().lower()

        try:
            if page_choice == 'full':
                # Extract all tables; assign descriptions/alignments by position order
                extracted = extract_tables(str(pdf_path), page_num, table_ids=None,
                                           alignments=alignment_map)
                for i, tbl in enumerate(extracted):
                    tnum = i + 1
                    tbl['description'] = desc_map.get(tnum, f'Table {tnum}')
            else:
                # Partial: extract only the specified TABLE-NUMs
                table_ids = sorted(desc_map.keys())
                extracted = extract_tables(str(pdf_path), page_num, table_ids=table_ids,
                                           alignments=alignment_map)
                for i, tbl in enumerate(extracted):
                    tnum = table_ids[i] if i < len(table_ids) else (i + 1)
                    tbl['description'] = desc_map.get(tnum, f'Table {tnum}')

            results.append({
                'request_num': req_num,
                'page': page_num,
                'page_choice': page_choice,
                'tables': extracted,
                'error': None,
            })
        except Exception as e:
            results.append({
                'request_num': req_num,
                'page': page_num,
                'page_choice': page_choice,
                'tables': [],
                'error': str(e),
            })

    return jsonify({
        'pdf': pdf_filename,
        'json_file': json_filename,
        'results': results,
    })


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print(f'\n  PDFdataPro')
    print(f'  Input-PDF directory      : {INPUT_PDF_DIR}')
    print(f'  Input-Batch-JSON dir     : {BATCH_JSON_DIR}')
    print(f'  Input-PDF exists         : {INPUT_PDF_DIR.exists()}')
    print(f'  Batch-JSON exists        : {BATCH_JSON_DIR.exists()}')
    print(f'  PDFs found               : {list_pdfs()}')
    print(f'  JSON specs found         : {list_batch_jsons()}\n')
    app.run(debug=True, host='0.0.0.0', port=5000)
