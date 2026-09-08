# Swiss Army Knife (SAK)

A collection of utility scripts for miscellaneous tasks.

## Table of Contents
- [Benchmarks](#benchmarks)
- [PDF Converters](#pdf-converters)
- [Article Extractor](#article-extractor)
- [Requirements](#requirements)
- [Calendar Sync](#calendar-sync)

## Benchmarks

Located in the `benchmarks/` directory, these scripts help you run local performance comparisons.

### 1. `benchmark_cpu.py`
Runs a simple CPU benchmark using prime counting, Monte Carlo Pi estimation, and SHA-256 hashing.
- **Usage**: `python benchmarks/benchmark_cpu.py`
- **Options**:
  - `--repeats` to control how many times each benchmark runs
  - `--prime-limit` to adjust the prime-counting workload
  - `--pi-iterations` to adjust the Monte Carlo workload
  - `--hash-rounds` and `--hash-block-size` to adjust the hashing workload

## PDF Converters

Located in the `converters/` directory, these scripts help you convert different file formats to PDF.

### 1. `convert_docx_to_pdf.py`
Converts `.docx` files to `.pdf` using LibreOffice or Microsoft Word on macOS.
- **Usage**: 
  - `python converters/convert_docx_to_pdf.py` (converts all `.docx` files in the current directory)
  - `python converters/convert_docx_to_pdf.py <filename>.docx` (converts a specific file)
  - `python converters/convert_docx_to_pdf.py --engine auto <filename>.docx` (prefers LibreOffice and falls back to Microsoft Word on macOS)
  - `python converters/convert_docx_to_pdf.py --engine word <filename>.docx` (forces Microsoft Word on macOS)
- **Dependency**: Requires LibreOffice in your PATH, or Microsoft Word installed at `/Applications/Microsoft Word.app` on macOS.

### 2. `convert_jpg_to_pdf.py`
Converts `.jpg` and `.jpeg` files to `.pdf`.
- **Usage**: `python converters/convert_jpg_to_pdf.py` (converts all `.jpg`/`.jpeg` files in the current directory)
- **Dependency**: Requires `Pillow`.

### 3. `convert_png_to_pdf.py`
Converts `.png` files to `.pdf`.
- **Usage**: 
  - `python converters/convert_png_to_pdf.py` (converts all `.png` files in the current directory)
  - `python converters/convert_png_to_pdf.py <filename>.png` (converts a specific file)
- **Dependency**: Requires `Pillow`.

### 4. `convert_r_to_pdf.py`
Converts `.R` scripts to paginated `.pdf` files by laying out the source code in a monospaced PDF document.
- **Usage**:
  - `python converters/convert_r_to_pdf.py` (converts all `.R` files in the current directory)
  - `python converters/convert_r_to_pdf.py <filename>.R` (converts a specific file)
- **Dependency**: Requires `reportlab`.

## Article Extractor

`articles/extract_articles.py` downloads web pages, isolates the readable article body,
keeps inline article images, and writes Markdown, PDF, or both. It accepts direct URLs
and `.txt`, `.md`, or `.markdown` files containing bare URLs or Markdown links.

- **One URL to Markdown**:
  ```bash
  python articles/extract_articles.py "https://example.com/article"
  ```
- **A URL-list file to individual PDFs**:
  ```bash
  python articles/extract_articles.py urls.txt --format pdf --page-size LEGAL --scale 90
  ```
- **Use custom PDF dimensions in inches**:
  ```bash
  python articles/extract_articles.py urls.txt --format pdf --page-size 6.5x9
  ```
- **Set uniform margins with a larger inside/left margin**:
  ```bash
  python articles/extract_articles.py urls.txt --format pdf \
    --margin 0.5 --margin-left 0.75
  ```
- **Several inputs into one Markdown file and one PDF**:
  ```bash
  python articles/extract_articles.py \
    "https://example.com/one" reading-list.md \
    --format both \
    --combine reading-pack
  ```
- **Choose an output directory**:
  ```bash
  python articles/extract_articles.py urls.txt \
    --format markdown \
    --output-dir saved-articles
  ```
- **Keep web image links in Markdown instead of downloading image files**:
  ```bash
  python articles/extract_articles.py urls.txt --remote-images
  ```

Markdown defaults to `output/articles/`, with downloaded images in a neighboring
`<article>_assets/` folder. PDFs default to `output/pdf/` and embed the images in the
document. If a Markdown image cannot be downloaded, its original remote URL is retained;
`--remote-images` uses remote URLs for all Markdown images. If a PDF image cannot be
embedded, the PDF includes a clickable source link in its place. Use `--no-images` for
text-only output. The extractor also recovers lazy-loaded image URLs stored in embedded
JSON page data when the readable HTML contains only placeholders. It works on server-rendered
article HTML; pages that require JavaScript execution, authentication, or anti-bot
challenges may need a browser-based workflow instead.

Extraction prefers a single publisher-marked `articleBody` when available, otherwise
uses readability with recovery for truncated articles. Marked navigation, sidebars,
topic lists, sharing controls, and promotional blocks are removed before recovery.
Article paragraphs, section headings, inline links, figures, and captions are retained;
the title and available source metadata remain above the body. Unmarked page furniture
may still require additional site-specific cleanup.

PDF output defaults to Letter size. Use `--page-size` with `LETTER`, `HALF_LETTER`,
`LEGAL`, `GOV_LETTER`, `GOV_LEGAL`, `JUNIOR_LEGAL`, `TABLOID`, `LEDGER`,
`EXECUTIVE`, `A0` through `A7`, or `B0` through `B7`. Values are case-insensitive,
so `--page-size b5` is valid. For a custom size, pass width first and height
second in inches, such as `--page-size 6.5x9` or `--page-size "6.5 in x 9 in"`.
Each custom dimension must be from 2 to 200 inches. Use `--scale PERCENT` (also
`--zoom` or `--zoom-scale`) to size PDF content from 25% to 200%; the paper
dimensions do not change. Use `--margin INCHES` to set all four PDF margins.
`--margin-top`, `--margin-right`, `--margin-bottom`, and `--margin-left` can
override individual sides. If no margin options are supplied, the existing
defaults remain in effect: 0.70 inches on top and 0.72 inches on the other sides.
The page-number footer is omitted when the bottom margin is below 0.5 inches so
it cannot overlap the article content.

## Requirements

The utility scripts use the packages listed in `requirements.txt`. You can install them using:
```bash
pip install -r requirements.txt
```

Note: `convert_docx_to_pdf.py` supports `--engine auto`, `--engine libreoffice`, and `--engine word`. The default is `auto`, which prefers LibreOffice and falls back to Microsoft Word on macOS.

## Calendar Sync

Located in the `calendars/` directory, these scripts help move calendar data between services.

### 1. `sync_outlook_ics_to_google.py`
Downloads an Outlook `.ics` calendar feed and syncs it into a Google Calendar.

- **Usage**:
  ```bash
  python calendars/sync_outlook_ics_to_google.py --calendar-id "primary"
  ```
  By default, the script reads the Outlook ICS URL from `calendars/ics.txt`.
- **Dry run**:
  ```bash
  python calendars/sync_outlook_ics_to_google.py \
    --calendar-id "primary" \
    --dry-run
  ```
- **Override the default ICS URL**:
  ```bash
  python calendars/sync_outlook_ics_to_google.py \
    --ics-url "https://outlook.office365.com/owa/calendar/..."
  ```
- **Use a different fallback timezone**:
  ```bash
  python calendars/sync_outlook_ics_to_google.py --time-zone "America/Chicago"
  ```
- **Authorize Google only, without syncing**:
  ```bash
  python calendars/sync_outlook_ics_to_google.py --auth-only
  ```
- **Delete events removed from Outlook**:
  ```bash
  python calendars/sync_outlook_ics_to_google.py \
    --calendar-id "primary" \
    --delete-missing
  ```
- **Google setup**:
  1. Create an OAuth desktop client in Google Cloud with the Google Calendar API enabled.
  2. Download the OAuth client file as `credentials.json` in this repo, or pass it with `--credentials`.
  3. Run the script once interactively. It opens a browser for Google consent and stores `token.json`.

The sync is one-way from Outlook to Google. It uses each Outlook event's iCalendar UID to avoid duplicate Google events on repeated runs. If a UID already belongs to a Google event that this sync did not create, that event is reported and skipped so it cannot block the rest of the feed or overwrite an invitation owned by someone else. Recurring event rules are copied, but standalone recurrence exceptions are skipped with a warning because they need manual review. The default `calendars/ics.txt` file is ignored by git because it contains a private calendar URL. If Outlook exports events without timezone data, or uses a Windows timezone name such as `Eastern Standard Time`, the script uses `America/New_York` unless you pass `--time-zone`.
