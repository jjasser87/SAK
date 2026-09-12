"""Combine a folder of images into one PDF, in natural filename order."""

import argparse
import os
from pathlib import Path
import re
import tempfile

from PIL import Image, ImageOps
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def natural_key(value):
    """Sort numbered filenames numerically, with a deterministic tie-breaker."""
    text = str(value)
    return (
        tuple(
            (1, int(part)) if part.isdigit() else (0, part.casefold())
            for part in re.split(r"(\d+)", text)
        ),
        text,
    )


def combine_images_to_pdf(directory, output=None, recursive=False, overwrite=False):
    """Write one page per image; return the output path and image count.

    Only extensions readable by the installed Pillow are considered. Animated
    images and multi-page TIFFs contribute their first frame. Pages match image
    dimensions at 72 pixels per inch. Invalid images abort the entire conversion.
    """
    directory = Path(directory).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f"Not a folder: {directory}")
    output = (
        Path(output).expanduser().absolute()
        if output is not None
        else directory / f"{directory.name or 'images'}.pdf"
    )
    if output.suffix.lower() != ".pdf":
        raise ValueError("The output filename must end in .pdf.")
    if output.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {output}. Use --overwrite to replace it.")

    Image.init()
    extensions = {
        ext for ext, format_name in Image.registered_extensions().items()
        if format_name in Image.OPEN and ext != ".pdf"
    }
    candidates = directory.rglob("*") if recursive else directory.iterdir()
    images = sorted(
        (item for item in candidates if item.is_file() and item.suffix.lower() in extensions),
        key=lambda item: natural_key(item.relative_to(directory)),
    )
    if not images:
        raise ValueError(f"No supported images found in {directory}.")

    # Build beside the destination so an unsuccessful conversion never leaves a
    # partial PDF or replaces an existing output.
    with tempfile.NamedTemporaryFile(
        dir=output.parent, prefix=f".{output.stem}-", suffix=".pdf", delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        pdf = canvas.Canvas(str(temporary_path))
        pdf.setTitle(output.stem)
        for image_path in images:
            try:
                with Image.open(image_path) as source:
                    with ImageOps.exif_transpose(source) as oriented:
                        with oriented.convert("RGBA") as rgba:
                            with Image.new("RGB", rgba.size, "white") as page_image:
                                with rgba.getchannel("A") as alpha:
                                    page_image.paste(rgba, mask=alpha)
                                width, height = page_image.size
                                pdf.setPageSize((width, height))
                                pdf.drawImage(ImageReader(page_image), 0, 0, width, height)
                                pdf.showPage()
            except Exception as exc:
                raise ValueError(f"Could not convert {image_path}: {exc}") from exc
        pdf.save()
        if overwrite:
            os.replace(temporary_path, output)
        else:
            # Unlike replace(), link() also refuses a destination created while
            # the images were being processed.
            os.link(temporary_path, output)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output, len(images)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", help="Folder containing images.")
    parser.add_argument(
        "-o", "--output", help="Output PDF (default: FOLDER/FOLDER_NAME.pdf)."
    )
    parser.add_argument("-r", "--recursive", action="store_true", help="Include subfolders.")
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace an existing output PDF."
    )
    args = parser.parse_args()
    try:
        output, count = combine_images_to_pdf(
            args.folder, args.output, args.recursive, args.overwrite
        )
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(f"Combined {count} images into {output}")


if __name__ == "__main__":
    main()
