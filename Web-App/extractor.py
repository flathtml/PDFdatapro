"""
extractor.py — Deterministic PDF Table Extraction Engine
=========================================================
No LLM. Uses pdfplumber vector-line detection + word-position mapping.

Public API
----------
scan_page(pdf_path, page_number)
    -> list of table descriptors: [{id, title, position, n_cols, bbox, row_count}, ...]

extract_tables(pdf_path, page_number, table_ids=None, alignments=None)
    -> list of table dicts: [{title, subtitle, headers, rows, row_types, footnotes}, ...]
    alignments: dict {table_id (1-based int): 'horizontal'|'vertical'}
"""

import re
import pdfplumber
from collections import defaultdict


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _cluster(values, tolerance=3):
    """Cluster nearby float values into representative group centres."""
    if not values:
        return []
    sv = sorted(set(round(v, 1) for v in values))
    groups = [[sv[0]]]
    for v in sv[1:]:
        if v - groups[-1][-1] <= tolerance:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [sum(g) / len(g) for g in groups]


def _words_to_grid(words, col_xs, row_tol=3):
    """
    Assign each word to a (row_idx, col_idx) cell.
    Returns list of (row_y_centre, [cell_text, ...]) sorted by row_y.
    """
    if not words:
        return []
    row_centres = _cluster([w['top'] for w in words], tolerance=row_tol)
    cell_map = defaultdict(lambda: defaultdict(list))
    for w in words:
        ri = min(range(len(row_centres)), key=lambda i: abs(row_centres[i] - w['top']))
        mid = (w['x0'] + w['x1']) / 2
        ci = None
        for idx, (cx0, cx1) in enumerate(col_xs):
            if cx0 - 5 <= mid <= cx1 + 5:
                ci = idx
                break
        if ci is None:
            ci = min(range(len(col_xs)),
                     key=lambda i: abs((col_xs[i][0] + col_xs[i][1]) / 2 - mid))
        cell_map[ri][ci].append(w['text'])

    n = len(col_xs)
    return [(row_centres[ri], [' '.join(cell_map[ri].get(ci, [])) for ci in range(n)])
            for ri in sorted(cell_map)]


def _merge_continuation_rows(grid, n_cols):
    """
    Merge rows that are continuations of the previous row's first cell
    (wrapped text with no numeric values in data columns).
    """
    if not grid:
        return grid
    merged = [[grid[0][0], list(grid[0][1])]]
    for y, row in grid[1:]:
        nums = [row[ci].strip() for ci in range(1, n_cols)]
        has_num = any(re.search(r'\d', v) for v in nums)
        first = row[0].strip()
        is_cont = (
            not has_num and first and
            not re.match(
                r'^[A-Z\(\[\d]|^(At |Total |TOTAL|Equity|Liabilities|Assets|'
                r'Cost|Accumulated|Net Book|Revenue|Profit|Tax|Other|Share|'
                r'Depreciation|Finance|Employee|Changes|Purchases|Mining|'
                r'Exceptional|Borrowing|Foreign|Translation|Deductions|'
                r'Transfer|Additions|Acquired|Disposals)',
                first)
        )
        if is_cont:
            merged[-1][1][0] = (merged[-1][1][0] + ' ' + first).strip()
        else:
            merged.append([y, list(row)])
    return [(m[0], m[1]) for m in merged]


def _split_header_and_data(grid, n_cols):
    """
    Split grid into header rows (no numeric data) and data rows.
    Multi-line headers are merged column-by-column with newline.
    """
    hdr_parts = []
    data_start = 0
    for i, (y, row) in enumerate(grid):
        nums = [row[ci].strip() for ci in range(1, n_cols)]
        if any(re.search(r'\d', v) for v in nums):
            data_start = i
            break
        hdr_parts.append(row)
    else:
        if hdr_parts:
            data_start = 1

    if not hdr_parts:
        return [''] * n_cols, grid

    merged_hdr = []
    for ci in range(n_cols):
        parts = [hdr_parts[ri][ci].strip() for ri in range(len(hdr_parts))
                 if hdr_parts[ri][ci].strip()]
        merged_hdr.append('\n'.join(parts) if parts else '')

    return merged_hdr, grid[data_start:]


def _classify_row(row, n_cols):
    """Return row type string."""
    label = row[0].strip() if row else ''
    vals = [c.strip() for c in row[1:n_cols]]
    has_val = any(vals)

    if not has_val:
        return 'section_header'

    u = label.upper()
    if re.match(r'^TOTAL\s*[-–]\s*(EQUITY|ASSETS|LIABILITIES|EQUITY AND LIABILITIES)', u):
        return 'grand_total'
    if u.startswith('TOTAL ') or label.startswith('Total '):
        return 'total'
    if re.match(r'^At (31 March|01 April)', label):
        return 'subtotal'
    if re.match(r'^(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV)\s', label) and has_val:
        return 'total'
    return 'data'


def _get_title_above(page, bbox, look_up=40):
    """Extract text in the band immediately above a table bbox."""
    x0, top, x1, _ = bbox
    t0 = max(0, top - look_up)
    t1 = top - 1
    if t0 >= t1:
        return ''
    try:
        crop = page.within_bbox((x0 - 10, t0, x1 + 10, t1))
        words = crop.extract_words()
        return ' '.join(w['text'] for w in words).strip()
    except Exception:
        return ''


def _position_label(bbox, page_width):
    """Return a human-readable position label for a table."""
    x0, _, x1, _ = bbox
    mid = (x0 + x1) / 2
    pw = page_width
    if x1 < pw * 0.55:
        return 'left'
    if x0 > pw * 0.45:
        return 'right'
    return 'full-width'


def _find_all_tables(page):
    """Find all valid table regions on a page using multiple strategies."""
    strategies = [
        {},
        {"vertical_strategy": "lines", "horizontal_strategy": "lines",
         "snap_tolerance": 3, "join_tolerance": 3, "edge_min_length": 10},
    ]
    seen = {}
    for ts in strategies:
        try:
            found = page.find_tables(table_settings=ts) if ts else page.find_tables()
            for t in found:
                key = tuple(round(x, 0) for x in t.bbox)
                if key not in seen:
                    seen[key] = t
        except Exception:
            pass

    tables = [t for t in seen.values()
              if (t.bbox[2] - t.bbox[0]) > 60 and (t.bbox[3] - t.bbox[1]) > 8]
    return sorted(tables, key=lambda t: (round(t.bbox[0] / 100), t.bbox[1]))


# ─── Vertical (rotated 90° CCW) table extraction ──────────────────────────────

def _is_rotated_90(char):
    """Detect 90° CCW rotation: matrix = [0, s, -s, 0, tx, ty] where s > 0."""
    m = char.get('matrix', None)
    if m is None:
        return False
    return abs(m[0]) < 0.5 and m[1] > 0


def _clean_kerned(text):
    """
    Remove kerning spaces from text like 'D e s c r i p t i o n' → 'Description'.
    Only merges runs of SINGLE-character tokens (len==1) separated by spaces.
    Two-char tokens like 'As', 'at', 'of' are kept as separate words.
    """
    if not text:
        return text
    parts = text.split(' ')
    result = []
    i = 0
    while i < len(parts):
        if not parts[i]:
            i += 1
            continue
        j = i
        # Collect consecutive SINGLE-char tokens only
        while j < len(parts) and len(parts[j]) == 1:
            j += 1
        if j > i + 1:
            # Multiple consecutive single chars = kerned text, merge them
            merged = ''.join(parts[i:j])
            result.append(merged)
            i = j
        else:
            result.append(parts[i])
            i += 1
    return ' '.join(result)


def _extract_rotated_cell_text(page, cell_bbox):
    """
    Extract text from a cell containing 90° CCW rotated characters.
    For CCW rotation, reading order is DECREASING 'top' (bottom→top in PDF = left→right visually).
    """
    x0, top, x1, bottom = cell_bbox

    chars = [c for c in page.chars
             if c['x0'] >= x0 - 1 and c['x1'] <= x1 + 1
             and c['top'] >= top - 1 and c['bottom'] <= bottom + 1
             and _is_rotated_90(c)]

    if not chars:
        return ''

    # Rotated text in PDFs is often stored in multiple x-column streams
    # (each x0 position = a separate character column in the rotated glyph layout).
    # Strategy:
    #   1. Group chars by rounded x0 (each x-column is an independent stream)
    #   2. Within each x-column, sort by decreasing top (= visual left→right order)
    #   3. Concatenate x-columns in ascending x0 order
    #   4. If multiple font families exist within an x-column, keep them separate
    #      and join by mean-x0 order.
    from collections import defaultdict

    # Group by rounded x0 (cluster within 2px)
    x_groups = defaultdict(list)
    for c in chars:
        x_key = round(c['x0'] / 2) * 2  # bucket to 2px
        x_groups[x_key].append(c)

    parts = []
    for x_key in sorted(x_groups.keys()):
        group = sorted(x_groups[x_key], key=lambda c: -c['top'])
        raw = ''.join(c['text'] for c in group)
        raw = re.sub(r'\s+', ' ', raw).strip()
        if raw:
            parts.append(raw)

    if len(parts) > 1:
        # Join x-column parts with a single space; then collapse multiple spaces.
        combined = ' '.join(parts)
    else:
        combined = parts[0] if parts else ''
    combined = re.sub(r'\s+', ' ', combined).strip()
    # Remove spurious spaces after hyphens in dates/numbers (e.g. '01-04- 2024' -> '01-04-2024')
    combined = re.sub(r'(\d)- (\d)', r'\1-\2', combined)
    return _clean_kerned(combined)


def _extract_vertical_table(page, tbl_obj):
    """
    Extract a vertically-oriented (90° CCW rotated) table.

    Correct approach:
    - Find LEAF y-ranges (non-merged): each leaf y-range = one visual column
    - The last (largest y) leaf y-range = Description column (row labels)
    - All other leaf y-ranges = data columns, in reverse order (last = leftmost visual col)
    - For each visual row (x-band from description row), crop each leaf y-range to get the value
    - Deduplicate rows that appear in merged cells (keep only rows from leaf x-bands)

    Returns dict with same structure as _extract_one_table.
    """
    cells = tbl_obj.cells
    if not cells:
        return None

    # ── Step 1: Find all unique y-ranges and identify LEAF y-ranges ──────────
    all_y = sorted(set((round(c[1], 1), round(c[3], 1)) for c in cells))

    def is_leaf(yr):
        """A y-range is a leaf if no other y-range is strictly contained within it."""
        for other in all_y:
            if other == yr:
                continue
            if yr[0] <= other[0] and other[1] <= yr[1]:
                return False
        return True

    leaf_y = [yr for yr in all_y if is_leaf(yr)]
    if not leaf_y:
        leaf_y = all_y  # fallback

    # ── Step 2: Find all unique x-ranges ─────────────────────────────────────
    all_x = sorted(set((round(c[0], 1), round(c[2], 1)) for c in cells))

    # ── Step 3: Identify the header x-range ──────────────────────────────────
    # The header x-range is the LEAF x-range that contains column header text.
    # We must use a LEAF x-range (one that is not a superset of another x-range),
    # because combined x-ranges mix section labels with sub-column headers.
    def is_leaf_xr(xr):
        for other in all_x:
            if other == xr:
                continue
            if xr[0] <= other[0] and other[1] <= xr[1]:
                return False
        return True

    leaf_x = [xr for xr in all_x if is_leaf_xr(xr)]

    header_xr = None
    header_keywords = ["As at", "Additions", "Deductions", "For the", "Acquisitions",
                       "Description", "ta sA", "noitiddA", "noitcudeD", "raeY eht roF"]
    # Check leaf x-ranges first (smallest, non-combined)
    for xr in leaf_x[:6]:
        text = _extract_rotated_cell_text(page, (xr[0], leaf_y[0][0], xr[1], leaf_y[-1][1]))
        if any(kw in text for kw in header_keywords):
            header_xr = xr
            break
    # Fallback: check all x-ranges
    if header_xr is None:
        for xr in all_x[:6]:
            text = _extract_rotated_cell_text(page, (xr[0], leaf_y[0][0], xr[1], leaf_y[-1][1]))
            if any(kw in text for kw in header_keywords):
                header_xr = xr
                break
    if header_xr is None and all_x:
        header_xr = leaf_x[1] if len(leaf_x) > 1 else (all_x[1] if len(all_x) > 1 else all_x[0])

    # ── Step 4: Get column headers from each leaf y-range ────────────────────
    # Visual columns are leaf_y in REVERSE order (last leaf_y = Description = col 0)
    visual_col_yranges = list(reversed(leaf_y))  # [Description_yr, col1_yr, col2_yr, ...]

    raw_headers = []
    for yr in visual_col_yranges:
        text = _extract_rotated_cell_text(page, (header_xr[0], yr[0], header_xr[1], yr[1]))
        raw_headers.append(text.strip())

    # ── Step 5: Get row labels from the Description y-range ──────────────────
    desc_yr = leaf_y[-1]  # last leaf y-range = Description column

    # Find all x-bands that have description text (= visual rows)
    # Use leaf x-ranges to avoid duplicates from merged cells
    all_x_leaf = []
    for xr in all_x:
        # Check if this x-range is a leaf (not merged with another)
        is_x_leaf = True
        for other_xr in all_x:
            if other_xr == xr:
                continue
            if xr[0] <= other_xr[0] and other_xr[1] <= xr[1]:
                is_x_leaf = False
                break
        if is_x_leaf:
            all_x_leaf.append(xr)

    # Get description text for each leaf x-range
    row_x_bands = []  # [(x0, x1, desc_text), ...]
    for xr in all_x_leaf:
        # Skip the header x-range
        if header_xr and abs(xr[0] - header_xr[0]) < 2 and abs(xr[1] - header_xr[1]) < 2:
            continue
        text = _extract_rotated_cell_text(page, (xr[0], desc_yr[0], xr[1], desc_yr[1]))
        if text.strip():
            row_x_bands.append((xr[0], xr[1], text.strip()))

    if not row_x_bands:
        return None

    # ── Step 6: Build the full data grid ─────────────────────────────────────
    # For each visual row (x-band), get value from each visual column (leaf y-range)
    all_rows = []
    for x0, x1, desc_text in row_x_bands:
        row_values = []
        for yr in visual_col_yranges:
            text = _extract_rotated_cell_text(page, (x0, yr[0], x1, yr[1]))
            row_values.append(text.strip())
        all_rows.append(row_values)

    if not all_rows:
        return None

    n_cols = len(visual_col_yranges)

    # ── Step 7: Build multi-level headers ────────────────────────────────────
    # Some header cells span multiple leaf y-ranges (merged headers like "Gross Block").
    # We detect these by looking at non-leaf y-ranges that span 2+ leaf y-ranges.
    # Only use a merged-cell text as a section header if:
    #   - It spans at least 2 leaf y-ranges
    #   - The text is SHORT (i.e. a true section label, not a full column header)
    #   - It does NOT contain sub-column keywords (As at, Additions, etc.)
    section_headers = {}  # visual_col_index -> section_name

    # Section labels (e.g. "Gross Block", "Net Block", "Depreciation...") are stored
    # in the FIRST x-range (the narrow leftmost column in PDF space).
    # IMPORTANT: Only use OUTERMOST non-leaf y-ranges (not nested ones).
    # A non-leaf y-range is outermost if no other non-leaf y-range contains it.
    section_xr = all_x[0] if all_x else header_xr
    non_leaf_y = [yr for yr in all_y if yr not in leaf_y]

    def is_outermost_nonleaf(yr):
        """True if no other non-leaf y-range strictly contains this one."""
        for other in non_leaf_y:
            if other == yr:
                continue
            if other[0] <= yr[0] and yr[1] <= other[1]:
                return False
        return True

    # For each column, find the best section header by checking ALL non-leaf ranges
    # that span it and picking the one with the longest (most complete) text.
    # This handles both outermost and nested ranges correctly.
    for ci, _ in enumerate(visual_col_yranges):
        lyr = visual_col_yranges[ci]
        best_text = ''
        for yr in non_leaf_y:
            if not (yr[0] <= lyr[0] and lyr[1] <= yr[1]):
                continue  # this non-leaf range doesn't span this column
            # Find all leaf columns spanned by this non-leaf range
            spanned = [i for i, l in enumerate(visual_col_yranges)
                       if yr[0] <= l[0] and l[1] <= yr[1]]
            if len(spanned) < 2:
                continue
            text = _extract_rotated_cell_text(page, (section_xr[0], yr[0], section_xr[1], yr[1]))
            text = text.strip()
            # Keep the longest text (most complete section label)
            if text and len(text) > len(best_text):
                best_text = text
        if best_text:
            section_headers[ci] = best_text

    # Post-process section_headers: if any section header is a prefix of another,
    # replace it with the longer one (handles truncated merged-cell text).
    all_section_texts = list(set(section_headers.values()))
    for ci, sec in list(section_headers.items()):
        for longer in all_section_texts:
            if longer != sec and longer.startswith(sec) and len(longer) > len(sec):
                section_headers[ci] = longer
                break

    # Build final headers: prepend section header if available
    headers = []
    for ci, h in enumerate(raw_headers):
        section = section_headers.get(ci, '')
        if section and section not in h:
            headers.append(f"{section}\n{h}" if h else section)
        else:
            headers.append(h)

    # ── Step 8: Classify rows ─────────────────────────────────────────────────
    rows_out = []
    types_out = []
    for row in all_rows:
        rows_out.append(row)
        types_out.append(_classify_row(row, n_cols))

    title = _get_title_above(page, tbl_obj.bbox)

    return {
        'title': title,
        'subtitle': '(rotated → displayed horizontally)',
        'headers': headers,
        'rows': rows_out,
        'row_types': types_out,
        'footnotes': '',
        'n_cols': n_cols,
        'bbox': [round(x, 1) for x in tbl_obj.bbox],
    }


# ─── Standard (horizontal) table extraction ───────────────────────────────────

def _derive_col_xs_from_words(words, n_cols_hint):
    """
    Derive column x-ranges from word positions when cell-based detection is unreliable.
    Uses x-midpoint clustering to find n_cols_hint column centres, then builds ranges.
    """
    if not words:
        return None
    mids = [(w['x0'] + w['x1']) / 2 for w in words]
    centres = _cluster(mids, tolerance=15)
    if len(centres) < 2:
        return None
    # Build (x0, x1) ranges from centres
    col_xs = []
    for i, c in enumerate(centres):
        left  = (centres[i-1] + c) / 2 if i > 0 else min(w['x0'] for w in words) - 5
        right = (c + centres[i+1]) / 2 if i < len(centres)-1 else max(w['x1'] for w in words) + 5
        col_xs.append((left, right))
    return col_xs


def _extract_one_table(page, tbl_obj, next_top=None):
    """
    Extract a single horizontal table object into structured data.
    Uses the row with the most non-None cells for column detection,
    and falls back to word-position column detection when needed.
    """
    bb = tbl_obj.bbox
    if not tbl_obj.rows:
        return None

    # Use the row with the most non-None cells to get correct column boundaries
    # (Row 0 often has merged header cells that give fewer columns than actual)
    best_row = max(tbl_obj.rows, key=lambda r: sum(1 for c in r.cells if c and c[0] is not None))
    best_cells = [c for c in best_row.cells if c and c[0] is not None]

    # Also collect the label column from Row 0 (first non-None cell, usually the widest left cell)
    # This handles tables where the label column is a merged cell not present in best_row
    row0_cells = [c for c in tbl_obj.rows[0].cells if c and c[0] is not None]
    label_col = None
    if row0_cells:
        # The label column is the leftmost cell in row 0
        leftmost_row0 = min(row0_cells, key=lambda c: c[0])
        # Check if this label column is NOT already covered by best_row cells
        already_covered = any(
            abs(bc[0] - leftmost_row0[0]) < 20 for bc in best_cells
        )
        if not already_covered:
            label_col = leftmost_row0

    # Build final col_xs: label column first (if separate), then data columns
    if label_col:
        col_xs = [(label_col[0], label_col[2])] + [(c[0], c[2]) for c in best_cells]
    else:
        col_xs = [(c[0], c[2]) for c in best_cells]

    if not col_xs:
        return None
    n_cols = len(col_xs)

    x0, top, x1, bottom = bb
    page_bottom = page.height - 35
    exp_bottom = (next_top - 2) if next_top else page_bottom

    # Widen the crop region to capture text that may sit outside the detected table bbox
    # (e.g. row labels in a narrow left column, or values in columns beyond detected boundary)
    crop_x0 = max(0, x0 - 30)   # extend left to capture row labels
    crop_x1 = min(page.width, x1 + 30)  # extend right to capture extra value columns

    try:
        crop = page.within_bbox((crop_x0, top - 2, crop_x1, exp_bottom))
        words = crop.extract_words(keep_blank_chars=False, x_tolerance=3, y_tolerance=3)
    except Exception:
        words = []

    if not words:
        return None

    # Check if cell-based col_xs covers all word x-positions
    # If many words fall outside col_xs, re-derive columns from word positions
    out_of_range = sum(
        1 for w in words
        if not any(cx0 - 10 <= (w['x0']+w['x1'])/2 <= cx1 + 10 for cx0, cx1 in col_xs)
    )
    coverage_ratio = 1 - (out_of_range / len(words)) if words else 1
    if coverage_ratio < 0.75:
        # Re-derive columns from actual word positions
        derived = _derive_col_xs_from_words(words, n_cols)
        if derived and len(derived) >= n_cols:
            col_xs = derived
            n_cols = len(col_xs)

    grid = _words_to_grid(words, col_xs, row_tol=3)
    grid = _merge_continuation_rows(grid, n_cols)
    headers, data_grid = _split_header_and_data(grid, n_cols)

    rows_out = []
    types_out = []
    for _, row in data_grid:
        rows_out.append(row)
        types_out.append(_classify_row(row, n_cols))

    title = _get_title_above(page, bb)

    footnotes = ''
    if data_grid:
        last_y = data_grid[-1][0]
        try:
            fn_crop = page.within_bbox((x0 - 2, last_y + 8, x1 + 2, exp_bottom))
            fn_words = fn_crop.extract_words()
            if fn_words:
                fn_text = ' '.join(w['text'] for w in fn_words)
                if re.match(r'^[@\*\dNn]', fn_text):
                    footnotes = fn_text
        except Exception:
            pass

    return {
        'title': title,
        'subtitle': '',
        'headers': headers,
        'rows': rows_out,
        'row_types': types_out,
        'footnotes': footnotes,
        'n_cols': n_cols,
        'bbox': [round(x, 1) for x in bb],
    }


# ─── Public API ───────────────────────────────────────────────────────────────

def get_page_count(pdf_path):
    """Return total page count of a PDF."""
    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)


def scan_page(pdf_path, page_number):
    """
    Scan a page and return a list of table descriptors.
    Each descriptor: {id, title, position, n_cols, bbox, row_count}
    """
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_number - 1]
        pw = page.width
        tables = _find_all_tables(page)

        result = []
        for idx, tbl_obj in enumerate(tables):
            bb = tbl_obj.bbox
            if not tbl_obj.rows:
                continue
            cells = tbl_obj.rows[0].cells
            col_xs = [(c[0], c[2]) for c in cells if c and c[0] is not None]
            n_cols = len(col_xs)

            title = _get_title_above(page, bb)
            position = _position_label(bb, pw)

            # Compute full table bbox by finding the last word in the column range
            try:
                crop = page.within_bbox((bb[0]-2, bb[1]-2, bb[2]+2, page.height-35))
                words = crop.extract_words(keep_blank_chars=False,
                                           x_tolerance=3, y_tolerance=3)
                y_vals = _cluster([w['top'] for w in words], tolerance=3)
                row_count = len(y_vals)
                # Full bbox: from table header top to last word bottom
                if words:
                    full_bottom = max(w['bottom'] for w in words)
                    full_bbox = [bb[0], bb[1], bb[2], full_bottom]
                else:
                    full_bbox = list(bb)
            except Exception:
                row_count = len(tbl_obj.rows)
                full_bbox = list(bb)

            if not title:
                hdr = tbl_obj.extract()
                if hdr and hdr[0]:
                    title = ' | '.join(c for c in hdr[0] if c and c.strip())

            result.append({
                'id': idx + 1,
                'title': title or f'Table {idx + 1}',
                'position': position,
                'n_cols': n_cols,
                'bbox': [round(x, 1) for x in full_bbox],
                'row_count': row_count,
            })

        return result


def extract_tables(pdf_path, page_number, table_ids=None, alignments=None):
    """
    Extract tables from a page.

    Parameters
    ----------
    pdf_path    : str or Path
    page_number : int (1-based)
    table_ids   : list of int (1-based) to extract; None = extract all
    alignments  : dict {table_id (int): 'horizontal'|'vertical'}
                  Defaults to 'horizontal' for any table not specified.

    Returns list of table dicts.
    """
    if alignments is None:
        alignments = {}

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_number - 1]
        all_tables = _find_all_tables(page)

        if table_ids:
            selected = [(i + 1, t) for i, t in enumerate(all_tables) if (i + 1) in table_ids]
        else:
            selected = [(i + 1, t) for i, t in enumerate(all_tables)]

        results = []
        for tid, tbl_obj in selected:
            alignment = alignments.get(tid, 'horizontal').lower()

            if alignment == 'vertical':
                tbl = _extract_vertical_table(page, tbl_obj)
            else:
                bb = tbl_obj.bbox
                same_col = [t for t in all_tables
                            if abs(t.bbox[0] - bb[0]) < 60 and t.bbox[1] > bb[1] + 5]
                next_top = same_col[0].bbox[1] if same_col else None
                tbl = _extract_one_table(page, tbl_obj, next_top)

            if tbl:
                results.append(tbl)

        return results
