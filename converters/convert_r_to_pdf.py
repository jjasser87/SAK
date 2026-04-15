import argparse
import os
import sys
from textwrap import wrap

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

FONT_NAME = "Courier"
FONT_SIZE = 10
LEFT_MARGIN = 54
TOP_MARGIN = 54
BOTTOM_MARGIN = 54
LINE_SPACING = 14


def build_pdf_path(r_path):
    return os.path.splitext(r_path)[0] + ".pdf"


def wrap_line(line, max_chars):
    expanded = line.expandtabs(4)
    if not expanded:
        return [""]

    wrapped = wrap(
        expanded,
        width=max_chars,
        replace_whitespace=False,
        drop_whitespace=False,
        break_long_words=True,
        break_on_hyphens=False,
    )
    return wrapped or [""]


def convert_r_to_pdf(r_path):
    if not r_path.lower().endswith(".r"):
        print(f"Skipping {r_path}: Not an R script.")
        return False

    if not os.path.exists(r_path):
        print(f"Error: File '{r_path}' not found.")
        return False

    pdf_path = build_pdf_path(r_path)

    try:
        page_width, page_height = LETTER
        usable_width = page_width - (2 * LEFT_MARGIN)
        max_chars = max(20, int(usable_width // (FONT_SIZE * 0.6)))

        pdf = canvas.Canvas(pdf_path, pagesize=LETTER)
        pdf.setTitle(os.path.basename(pdf_path))
        pdf.setAuthor("Swiss Army Knife")
        pdf.setFont(FONT_NAME, FONT_SIZE)

        y_position = page_height - TOP_MARGIN

        with open(r_path, "r", encoding="utf-8") as source_file:
            for original_line in source_file.read().splitlines():
                for wrapped_line in wrap_line(original_line, max_chars):
                    if y_position <= BOTTOM_MARGIN:
                        pdf.showPage()
                        pdf.setFont(FONT_NAME, FONT_SIZE)
                        y_position = page_height - TOP_MARGIN

                    pdf.drawString(LEFT_MARGIN, y_position, wrapped_line)
                    y_position -= LINE_SPACING

        pdf.save()
        print(f"Converted: {r_path} -> {pdf_path}")
        return True
    except Exception as exc:
        print(f"Error converting {r_path}: {exc}")
        return False


def convert_r_scripts_in_directory(directory="."):
    files = [f for f in os.listdir(directory) if f.lower().endswith(".r")]

    if not files:
        print(f"No R scripts found in {directory}.")
        return

    for r_file in files:
        convert_r_to_pdf(os.path.join(directory, r_file))


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Convert R scripts to PDF.")
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to a specific .R file or a directory containing .R files.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args(sys.argv[1:])

    if os.path.isfile(args.path):
        convert_r_to_pdf(args.path)
    elif os.path.isdir(args.path):
        convert_r_scripts_in_directory(args.path)
    else:
        print(f"Error: {args.path} is not a valid file or directory.")
