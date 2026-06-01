# PDFdataPro — Advanced PDF Table Extractor

A fully deterministic, zero-AI Flask web application for extracting tables from PDF files.
No API keys, no internet connection, no LLM calls — pure PDF geometry parsing.

---

## Folder Structure

Place the app files so your directory looks like this:

```
C:\Daya\Indian-Annrpt-Data-Extractor\
├── Input-PDF\                         ← Put your PDF files here
│   └── JSW-2024-25.pdf
├── Input-Batch-JSON\                  ← Put your JSON spec files here
│   └── TEST1.json
└── Web-App\                           ← The Flask app lives here
    ├── app.py
    ├── extractor.py
    ├── requirements.txt
    ├── README.md
    ├── templates\
    │   ├── home.html
    │   ├── online.html
    │   └── batch.html
    └── static\
        ├── css\style.css
        └── js\
            ├── online.js
            └── batch.js
```

---

## Setup (One-time)

**1. Install dependencies:**
```bash
pip install -r requirements.txt
```
Only two packages needed: `flask` and `pdfplumber`.

**2. Run the app:**
```bash
python app.py
```

**3. Open in browser:**
```
http://localhost:5000
```

---

## Modes

### Home Page
The home page (`/`) shows a welcome message and two buttons — **Online** and **Batch**.

---

### Online Mode (`/online`)
Interactive extraction — one PDF, one or more pages at a time.

1. Select a PDF file from the dropdown (reads from `Input-PDF\`)
2. Enter a page number
3. Choose **Full** (all tables) or **Partial** (specific tables)
4. Click **Scan Page for Tables** — instantly detects all tables on the page
5. For each table, enter a description (required)
6. For Partial mode, uncheck tables you don't want
7. Click **Extract Data**
8. Results appear below with styled tables and **⬇ Download CSV** buttons
9. Click **+ Add Another Page** to queue multiple pages in one run

---

### Batch Mode (`/batch`)
Automated extraction driven by a JSON specification file.

1. Select a JSON spec file from the dropdown (reads from `Input-Batch-JSON\`)
2. The **Specification Preview** panel shows the PDF path, request count, and a table of all requests
3. Click **Run Batch Extraction**
4. All requests are processed automatically — results appear with the same styled tables and CSV download buttons

---

## JSON Specification Format

```json
{
  "INPUT-PDF-PATH": "C:\\Daya\\Indian-Annrpt-Data-Extractor\\Input-PDF\\JSW-2024-25.pdf",
  "REQUESTS": [
    {
      "REQUEST-NUM": "001",
      "PAGE-NUM": 277,
      "PAGE-CHOICE": "Full",
      "TABLES": [
        { "TABLE-NUM": 1, "TABLE-DESCRIPTION": "Balance Sheet" },
        { "TABLE-NUM": 2, "TABLE-DESCRIPTION": "Income Statement" }
      ]
    },
    {
      "REQUEST-NUM": "002",
      "PAGE-NUM": 291,
      "PAGE-CHOICE": "Partial",
      "TABLES": [
        { "TABLE-NUM": 1, "TABLE-DESCRIPTION": "PPE Details" }
      ]
    }
  ]
}
```

**Key rules:**
- `INPUT-PDF-PATH`: Only the **filename** is used; the file must exist in `Input-PDF\`
- `PAGE-CHOICE`: `"Full"` extracts all tables; `"Partial"` extracts only the listed `TABLE-NUM`s
- `TABLE-NUM` numbering: top-left = 1, bottom-left = 2, right column = 3 (reading order, left-to-right, top-to-bottom)
- For `"Full"` mode, `TABLES` entries assign descriptions to tables by position order (T1 = first table, T2 = second, etc.)

---

## How Extraction Works (Fully Deterministic)

1. **Table detection** — reads PDF vector lines to find table bounding boxes
2. **Column mapping** — derives column boundaries from the table's cell structure
3. **Word assignment** — maps every word to a `(row, col)` cell by X/Y coordinate
4. **Row merging** — merges wrapped continuation lines into single rows
5. **Row classification** — labels each row as `data`, `section_header`, `subtotal`, `total`, or `grand_total`
6. **Title extraction** — reads text immediately above each table as its title

Works on any **text-based PDF** (not scanned/image PDFs).

---

## Troubleshooting

| Problem | Solution |
|---|---|
| No PDFs in dropdown | Check that `Input-PDF\` folder exists and contains `.pdf` files |
| No JSON files in dropdown | Check that `Input-Batch-JSON\` folder exists and contains `.json` files |
| "File not found" in batch | The filename in `INPUT-PDF-PATH` must match a file in `Input-PDF\` exactly |
| No tables detected on a page | The page may not have ruled/bordered tables; try an adjacent page |
| Port 5000 already in use | Run `python app.py` after closing other Flask apps, or change port in `app.py` |

---

## Requirements

```
flask>=3.0.0
pdfplumber>=0.11.0
```
