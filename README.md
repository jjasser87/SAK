# Swiss Army Knife (SAK)

A collection of utility scripts for miscellaneous tasks.

## Table of Contents
- [PDF Converters](#pdf-converters)
- [Requirements](#requirements)

## PDF Converters

Located in the `converters/` directory, these scripts help you convert different file formats to PDF.

### 1. `convert_docx_to_pdf.py`
Converts `.docx` files to `.pdf` using LibreOffice.
- **Usage**: 
  - `python converters/convert_docx_to_pdf.py` (converts all `.docx` files in the current directory)
  - `python converters/convert_docx_to_pdf.py <filename>.docx` (converts a specific file)
- **Dependency**: Requires `libreoffice` to be installed on your system.

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

## Requirements

The image conversion scripts require the `Pillow` library. You can install it using:
```bash
pip install -r requirements.txt
```

Note: `convert_docx_to_pdf.py` requires LibreOffice to be installed and available in your system's PATH.
