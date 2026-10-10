"""Convert comic or text EPUBs to PDF, automatically joining comic spreads."""

import argparse
import math
import os
from pathlib import Path
import posixpath
import tempfile
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile

if __package__:
    from .convert_cbz_to_pdf import write_image_pdf
else:
    from convert_cbz_to_pdf import write_image_pdf


PAGE_SIZES = {"A4": (595.276, 841.890), "LETTER": (612, 792)}


def resource_path(base, reference):
    """Resolve an EPUB URL relative to a document, without extracting it."""
    url = urlsplit(reference)
    path = unquote(url.path)
    if url.scheme or url.netloc or path.startswith("/") or "\\" in path:
        raise ValueError(f"Expected a local EPUB resource: {reference}")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(base), path))
    if resolved == ".." or resolved.startswith("../"):
        raise ValueError(f"Resource escapes the EPUB: {reference}")
    return resolved


def read_xml(archive, name):
    try:
        return ET.fromstring(archive.read(name))
    except (KeyError, ET.ParseError) as exc:
        raise ValueError(f"Missing or invalid EPUB document {name}: {exc}") from exc


def local_name(element):
    return element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""


def comic_image(archive, name, media_type):
    """Return a sole page image, or None when the document needs layout rendering.

    Never discard prose, captions, blank pages, vector art, or multi-image layouts
    merely to make a book qualify for the comic path.
    """
    if media_type.startswith("image/") and media_type != "image/svg+xml":
        return archive.getinfo(name)
    if media_type not in {"application/xhtml+xml", "text/html", "image/svg+xml"}:
        return None
    root = read_xml(archive, name)
    body = root.find(".//{*}body") if local_name(root) == "html" else root
    if body is None:
        return None
    references = []
    needs_layout = False

    def visit(element):
        nonlocal needs_layout
        tag = local_name(element)
        if tag in {"script", "style", "title", "desc", "metadata"}:
            return
        if element.text and element.text.strip():
            needs_layout = True
        if tag in {"img", "image"}:
            href = (element.get("src") if tag == "img" else
                    element.get("href") or element.get("{http://www.w3.org/1999/xlink}href"))
            if not href:
                needs_layout = True
            else:
                references.append(resource_path(name, href))
        elif tag not in {"body", "div", "span", "p", "a", "svg", "g", "figure", "section"}:
            needs_layout = True
        # Transforming or clipping an SVG image requires a renderer.
        if any(key in element.attrib for key in ("transform", "clip-path", "mask")):
            needs_layout = True
        for child in element:
            visit(child)
            if child.tail and child.tail.strip():
                needs_layout = True

    visit(body)
    if needs_layout or len(references) != 1:
        return None
    try:
        entry = archive.getinfo(references[0])
    except KeyError as exc:
        raise ValueError(f"Missing image in {name}: {references[0]}") from exc
    # Standalone vector SVGs must be rendered, not treated as raster pages.
    return None if entry.filename.lower().endswith(".svg") else entry


def inspect_epub(archive):
    """Read the package and spine; return title, direction, and comic images."""
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise ValueError("EPUB contains duplicate archive paths.")
    if "META-INF/encryption.xml" in names:
        encryption = read_xml(archive, "META-INF/encryption.xml")
        font_obfuscation = {"http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC"}
        for method in encryption.findall(".//{*}EncryptionMethod"):
            if method.get("Algorithm") not in font_obfuscation:
                raise ValueError("Encrypted/DRM-protected EPUB content is not supported.")
    container = read_xml(archive, "META-INF/container.xml")
    rootfile = container.find(".//{*}rootfile")
    if rootfile is None or not rootfile.get("full-path"):
        raise ValueError("EPUB container has no package document.")
    package_path = resource_path("", rootfile.get("full-path"))
    package = read_xml(archive, package_path)
    manifest = {}
    for item in package.findall("./{*}manifest/{*}item"):
        identity = item.get("id")
        if not identity or identity in manifest or not item.get("href"):
            raise ValueError("EPUB manifest contains missing or duplicate item IDs/hrefs.")
        manifest[identity] = item
    spine = package.find("./{*}spine")
    if spine is None:
        raise ValueError("EPUB has no reading-order spine.")
    title_element = package.find("./{*}metadata/{*}title")
    title = "".join(title_element.itertext()).strip() if title_element is not None else ""
    direction = spine.get("page-progression-direction", "ltr")
    images = []
    comic = True
    count = 0
    for reference in spine.findall("./{*}itemref"):
        if reference.get("linear") == "no":
            continue
        item = manifest.get(reference.get("idref"))
        if item is None:
            raise ValueError(f"Spine references an unknown manifest item: {reference.get('idref')}")
        if "nav" in item.get("properties", "").split():
            continue
        name = resource_path(package_path, item.get("href"))
        if name not in names:
            raise ValueError(f"Missing spine document: {name}")
        count += 1
        entry = comic_image(archive, name, item.get("media-type", ""))
        if entry is None:
            comic = False
        else:
            images.append(entry)
    if count == 0:
        raise ValueError("EPUB has no readable spine items.")
    return title, direction == "rtl", images if comic else None


def render_text_epub(source, output, overwrite, page_size, font_size):
    """Reflow the complete EPUB with MuPDF, retaining selectable text and outlines."""
    try:
        import pymupdf
    except ImportError as exc:
        raise ValueError("Text EPUB rendering requires PyMuPDF. Run: pip install PyMuPDF") from exc
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=f".{output.stem}-",
                                     suffix=".pdf", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with pymupdf.open(str(source)) as book:
            book.layout(width=PAGE_SIZES[page_size][0], height=PAGE_SIZES[page_size][1], fontsize=font_size)
            with pymupdf.open("pdf", book.convert_to_pdf()) as pdf:
                if not len(pdf):
                    raise ValueError("EPUB rendered no pages.")
                pdf.set_metadata({key: value for key, value in book.metadata.items()
                                  if key in {"title", "author", "subject", "keywords", "creator"} and value})
                toc = book.get_toc()
                if toc:
                    pdf.set_toc(toc)
                # convert_to_pdf does not copy URI links by itself.
                for index in range(len(book)):
                    for link in book[index].get_links():
                        if link.get("kind") == pymupdf.LINK_URI:
                            pdf[index].insert_link({"kind": pymupdf.LINK_URI,
                                                    "from": link["from"], "uri": link["uri"]})
                pdf.save(str(temporary_path), garbage=3, deflate=True)
                count = len(pdf)
        if overwrite:
            os.replace(temporary_path, output)
        else:
            os.link(temporary_path, output)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output, count


def convert_epub_to_pdf(source, output=None, overwrite=False, spreads=None,
                        spread_threshold=0.08, progress=None, mode="auto",
                        page_size="A4", font_size=11, reading_direction="auto"):
    """Convert an EPUB; return (output path, PDF page count)."""
    source = Path(source).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".epub":
        raise ValueError(f"Not an EPUB file: {source}")
    output = Path(output).expanduser().absolute() if output else source.with_suffix(".pdf")
    if output.suffix.lower() != ".pdf":
        raise ValueError("The output filename must end in .pdf.")
    if output.resolve() == source or (output.exists() and os.path.samefile(source, output)):
        raise ValueError("The output must not replace the source EPUB.")
    if output.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {output}. Use --overwrite to replace it.")
    if mode not in {"auto", "comic", "text"} or reading_direction not in {"auto", "ltr", "rtl"}:
        raise ValueError("Invalid conversion mode or reading direction.")
    if page_size not in PAGE_SIZES or not math.isfinite(font_size) or not 6 <= font_size <= 48:
        raise ValueError("Use page size A4 or LETTER and a font size from 6 to 48 points.")
    with zipfile.ZipFile(source) as archive:
        title, rtl, images = inspect_epub(archive)
        if mode == "comic" and images is None:
            raise ValueError("This EPUB needs text/layout rendering. Use --mode auto or --mode text.")
        if images is not None and mode != "text":
            if progress:
                progress(f"Comic mode: {len(images)} images in EPUB reading order.")
            return write_image_pdf(archive, images, output, title or source.stem, overwrite,
                                   spreads, spread_threshold, progress,
                                   rtl if reading_direction == "auto" else reading_direction == "rtl")
    if spreads:
        raise ValueError("Explicit spreads apply only to image-only comic EPUBs, not reflowed text pages.")
    if progress:
        progress("Text/layout mode: rendering the complete EPUB; comic spread joining is not applied.")
    return render_text_epub(source, output, overwrite, page_size, font_size)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="EPUB book to convert.")
    parser.add_argument("-o", "--output", help="Output PDF (default: beside the EPUB).")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--mode", choices=("auto", "comic", "text"), default="auto")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--spreads", help="Override detection with pairs such as 2-3,12-13 in EPUB image reading order.")
    selection.add_argument("--no-auto-spreads", dest="spreads", action="store_const", const="")
    parser.add_argument("--spread-threshold", type=float, default=0.08)
    parser.add_argument("--reading-direction", choices=("auto", "ltr", "rtl"), default="auto",
                        help="Comic pair direction; auto follows EPUB metadata.")
    parser.add_argument("--page-size", type=str.upper, choices=PAGE_SIZES, default="A4",
                        help="Paper size for text/layout mode (default: A4).")
    parser.add_argument("--font-size", type=float, default=11, help="Base text size in points, 6-48.")
    args = parser.parse_args()
    try:
        output, count = convert_epub_to_pdf(
            args.source, args.output, args.overwrite, args.spreads, args.spread_threshold,
            lambda message: print(message, flush=True), args.mode, args.page_size,
            args.font_size, args.reading_direction,
        )
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(f"Converted {count} pages into {output}")


if __name__ == "__main__":
    main()
