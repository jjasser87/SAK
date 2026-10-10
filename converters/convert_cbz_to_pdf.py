"""Convert a CBZ comic to PDF, keeping complete spreads on portrait pages."""

import argparse
from contextlib import ExitStack, contextmanager
import os
from pathlib import Path, PurePosixPath
import statistics
import shutil
import tempfile
import zipfile

from PIL import Image, ImageOps, ImageStat
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

if __package__:
    from .combine_images_to_pdf import natural_key
else:
    from combine_images_to_pdf import natural_key


def spread_starts(specification, image_count):
    """Validate explicit adjacent pairs against one-based, sorted image positions."""
    starts = set()
    used = set()
    if not specification or not specification.strip():
        return starts
    for pair in specification.split(","):
        try:
            left, right = (int(value) for value in pair.strip().split("-"))
        except ValueError as exc:
            raise ValueError("Spreads must be adjacent pairs, e.g. 2-3,12-13.") from exc
        if left < 1 or right != left + 1 or right > image_count:
            raise ValueError(f"Invalid spread {pair!r}: use adjacent pages within 1-{image_count}.")
        if left in used or right in used:
            raise ValueError(f"Overlapping spread: {pair!r}.")
        used.update((left, right))
        starts.add(left)
    return starts


def edge_profile(image, right=False):
    """Average a narrow edge into a resolution-independent vertical RGB profile."""
    width, height = image.size
    band = max(1, round(width * 0.0025))
    box = (width - band, 0, width, height) if right else (0, 0, band, height)
    with image.crop(box) as crop, crop.convert("RGBA") as rgba, Image.new("RGB", crop.size, "white") as rgb:
        with rgba.getchannel("A") as alpha:
            rgb.paste(rgba, mask=alpha)
        with rgb.resize((1, 256), Image.Resampling.BOX) as strip:
            variation = sum(ImageStat.Stat(strip).stddev) / (3 * 255)
            return [strip.getpixel((0, row)) for row in range(256)], variation


def detect_spreads(archive, images, threshold=0.08, progress=None):
    """Find matching adjacent portrait edges; reject blank and ambiguous seams.

    This is a visual heuristic, not knowledge of a book, filename, or page parity.
    Profiles preserve vertical color/structure while averaging JPEG noise. Both
    edges must vary, most rows must agree, and alignment must beat a shifted
    comparison. Ambiguous overlapping candidates are left separate.
    """
    if not 0 < threshold <= 1:
        raise ValueError("Spread threshold must be greater than 0 and at most 1.")
    candidates = {}
    previous = None
    for index, entry in enumerate(images):
        try:
            with archive.open(entry) as stream, Image.open(stream) as source:
                with ImageOps.exif_transpose(source) as image:
                    if image.width >= image.height:
                        current = None
                    else:
                        current = (image.width / image.height,
                                   edge_profile(image), edge_profile(image, right=True))
        except Exception as exc:
            raise ValueError(f"Could not inspect {entry.filename}: {exc}") from exc
        if previous is not None and current is not None:
            aspect, (left, left_variation), _ = current
            old_aspect, _, (right, right_variation) = previous
            if min(left_variation, right_variation) >= 0.04 and abs(aspect / old_aspect - 1) <= 0.2:
                differences = [sum(abs(a - b) for a, b in zip(l, r)) / (3 * 255)
                               for l, r in zip(left, right)]
                error = statistics.mean(differences)
                shifted = statistics.mean(
                    sum(abs(a - b) for a, b in zip(left[row], right[(row + 64) % 256])) / (3 * 255)
                    for row in range(256)
                )
                if (error <= threshold and sorted(differences)[204] <= threshold * 1.5
                        and error < shifted * 0.65):
                    candidates[index] = error  # index is the previous image's 1-based position
        previous = current
        if progress and (index + 1) % 50 == 0:
            progress(f"Inspected {index + 1}/{len(images)} images for spreads.")
    # A candidate must clearly beat either overlapping neighbor. Otherwise avoid
    # guessing which two of three similar pages are a spread.
    return {start for start, error in candidates.items()
            if all(neighbor not in candidates or error < candidates[neighbor] * 0.7
                   for neighbor in (start - 1, start + 1))}


@contextmanager
def read_page(archive, entry, temporary_dir):
    """Provide image dimensions and a PDF reader, preserving eligible JPEG data."""
    try:
        with archive.open(entry) as stream, Image.open(stream) as image:
            if image.format == "JPEG" and image.getexif().get(274, 1) == 1:
                # Embed the original compressed JPEG instead of expanding the
                # entire comic into much larger lossless raster data.
                # Passing a filename lets ReportLab embed JPEG bytes without
                # decoding all pixels merely to compute its image-cache key.
                # Use a generated filename, never an untrusted archive path.
                with tempfile.NamedTemporaryFile(dir=temporary_dir, suffix=".jpg", delete=False) as temporary:
                    jpeg_path = Path(temporary.name)
                try:
                    stream.seek(0)
                    with jpeg_path.open("wb") as target:
                        shutil.copyfileobj(stream, target)
                    yield image, str(jpeg_path)
                finally:
                    jpeg_path.unlink(missing_ok=True)
                return
            with ImageOps.exif_transpose(image) as oriented:
                with oriented.convert("RGBA") as rgba:
                    with Image.new("RGB", rgba.size, "white") as page:
                        with rgba.getchannel("A") as alpha:
                            page.paste(rgba, mask=alpha)
                        yield page, ImageReader(page)
    except Exception as exc:
        raise ValueError(f"Could not convert {entry.filename}: {exc}") from exc


def convert_cbz_to_pdf(source, output=None, overwrite=False, spreads=None,
                       spread_threshold=0.08, progress=None):
    """Return (output path, page count); fit each complete image on a portrait page.

    Portrait images retain their pixel dimensions at 72 pixels per inch. Wide
    images use those dimensions swapped as the paper size and are scaled to fit,
    without rotation or cropping. Only the first frame of animated images is used.
    Archive paths are never used as filesystem destinations. JPEGs use generated
    temporary filenames so ReportLab can embed the compressed data efficiently.
    By default, visually matching adjacent edges are joined automatically.
    `spreads` overrides detection with explicit pairs, e.g. "2-3,12-13"; an empty
    string disables joining. Detection can miss cropped/misaligned scans and can
    mistake similar artwork for a spread, so review the reported pairs.
    Positions refer to naturally sorted images, not printed page numbers. Joined
    images share a common displayed height and fit on the first image's portrait
    paper size. Other images remain separate.
    """
    source = Path(source).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".cbz":
        raise ValueError(f"Not a CBZ file: {source}")
    output = Path(output).expanduser().absolute() if output else source.with_suffix(".pdf")
    if output.suffix.lower() != ".pdf":
        raise ValueError("The output filename must end in .pdf.")
    if output.resolve() == source or (output.exists() and os.path.samefile(source, output)):
        raise ValueError("The output must not replace the source archive.")
    if output.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {output}. Use --overwrite to replace it.")

    Image.init()
    extensions = {
        ext for ext, name in Image.registered_extensions().items()
        if name in Image.OPEN and ext != ".pdf"
    }
    with zipfile.ZipFile(source) as archive:
        images = sorted(
            (entry for entry in archive.infolist()
             if not entry.is_dir()
             and PurePosixPath(entry.filename).suffix.lower() in extensions
             and not any(part == "__MACOSX" or part.startswith(".")
                         for part in PurePosixPath(entry.filename).parts)),
            key=lambda entry: natural_key(entry.filename),
        )
        if not images:
            raise ValueError(f"No supported images found in {source}.")
        starts = (detect_spreads(archive, images, spread_threshold, progress)
                  if spreads is None else spread_starts(spreads, len(images)))
        if progress:
            pairs = ",".join(f"{start}-{start + 1}" for start in sorted(starts)) or "none"
            progress(f"{'Detected' if spreads is None else 'Selected'} spreads: {pairs}")
        with tempfile.NamedTemporaryFile(
            dir=output.parent, prefix=f".{output.stem}-", suffix=".pdf", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        try:
            pdf = canvas.Canvas(str(temporary_path))
            pdf.setTitle(source.stem)
            index = 0
            page_count = 0
            while index < len(images):
                group_size = 2 if index + 1 in starts else 1
                with ExitStack() as resources:
                    pages = [resources.enter_context(read_page(archive, entry, output.parent))
                             for entry in images[index:index + group_size]]
                    width, height = pages[0][0].size
                    page_width, page_height = min(width, height), max(width, height)
                    # Normalize displayed heights without resampling either source.
                    ratios = [page.width / page.height for page, reader in pages]
                    draw_height = min(page_height, page_width / sum(ratios))
                    x = (page_width - draw_height * sum(ratios)) / 2
                    y = (page_height - draw_height) / 2
                    pdf.setPageSize((page_width, page_height))
                    for (page, reader), ratio in zip(pages, ratios):
                        draw_width = draw_height * ratio
                        pdf.drawImage(reader, x, y, draw_width, draw_height)
                        x += draw_width
                    pdf.showPage()
                index += group_size
                page_count += 1
                if progress and page_count % 50 == 0:
                    progress(f"Wrote {page_count}/{len(images) - len(starts)} PDF pages.")
            pdf.save()
            if overwrite:
                os.replace(temporary_path, output)
            else:
                os.link(temporary_path, output)
        finally:
            temporary_path.unlink(missing_ok=True)
    return output, len(images) - len(starts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="CBZ archive to convert.")
    parser.add_argument("-o", "--output", help="Output PDF (default: beside the CBZ).")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing PDF.")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--spreads", help="Join adjacent images left-to-right, e.g. 2-3,12-13. "
        "Use 1-based positions in natural image-path order, including the cover, "
        "not printed page numbers. Overrides automatic detection."
    )
    selection.add_argument("--no-auto-spreads", dest="spreads", action="store_const", const="",
                           help="Keep separate source images on separate pages.")
    parser.add_argument("--spread-threshold", type=float, default=0.08,
                        help="Maximum normalized edge difference (default: 0.08); lower is stricter.")
    args = parser.parse_args()
    try:
        output, count = convert_cbz_to_pdf(
            args.source, args.output, args.overwrite, args.spreads, args.spread_threshold,
            progress=lambda message: print(message, flush=True),
        )
    except (OSError, ValueError, zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(f"Converted {count} pages into {output}")


if __name__ == "__main__":
    main()
