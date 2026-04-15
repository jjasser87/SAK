# Swiss Army Knife (SAK)

A collection of utility scripts for miscellaneous tasks.

## Table of Contents
- [Benchmarks](#benchmarks)
- [PDF Converters](#pdf-converters)
- [Requirements](#requirements)

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

## Requirements

The converter scripts require `Pillow` and `reportlab`. You can install them using:
```bash
pip install -r requirements.txt
```

Note: `convert_docx_to_pdf.py` supports `--engine auto`, `--engine libreoffice`, and `--engine word`. The default is `auto`, which prefers LibreOffice and falls back to Microsoft Word on macOS.
