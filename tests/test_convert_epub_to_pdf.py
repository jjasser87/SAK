import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from PIL import Image, ImageDraw
from pypdf import PdfReader

from converters.convert_epub_to_pdf import convert_epub_to_pdf, inspect_epub, resource_path


def png(size=(120, 180), color="red"):
    with Image.new("RGB", size, color) as image:
        data = io.BytesIO()
        image.save(data, format="PNG")
        return data.getvalue()


def make_epub(path, bodies, images=None, direction="ltr"):
    images = images or {}
    documents = [f"chapter-{len(bodies)-i}.xhtml" for i in range(len(bodies))]
    manifest = "".join(f'<item id="d{i}" href="text/{name}" media-type="application/xhtml+xml"/>'
                       for i, name in enumerate(documents))
    manifest += "".join(f'<item id="img{i}" href="images/{name}" media-type="image/png"/>'
                        for i, name in enumerate(images))
    manifest += '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
    spine = "".join(f'<itemref idref="d{i}"/>' for i in range(len(bodies)))
    package = f'''<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
        <dc:identifier id="id">urn:uuid:test-book</dc:identifier><dc:title>Test Book</dc:title>
        <dc:creator>Test Author</dc:creator><dc:language>en</dc:language>
      </metadata><manifest>{manifest}</manifest>
      <spine page-progression-direction="{direction}">{spine}</spine></package>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", '''<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
          <rootfiles><rootfile full-path="OPS/book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>''')
        archive.writestr("OPS/book.opf", package)
        links = "".join(f'<li><a href="text/{name}">Chapter {i+1}</a></li>' for i, name in enumerate(documents))
        archive.writestr("OPS/nav.xhtml", f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Contents</title></head><body><nav epub:type="toc"><ol>{links}</ol></nav></body></html>')
        for name, body in zip(documents, bodies):
            archive.writestr(f"OPS/text/{name}", f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Page</title></head><body>{body}</body></html>')
        for name, data in images.items():
            archive.writestr(f"OPS/images/{name}", data)


class EpubTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.source = self.folder / "book.epub"

    def test_spine_order_relative_urls_svg_and_unused_assets(self):
        make_epub(self.source, ['<img src="../images/z%20page.png#view"/>',
                               '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"><image xlink:href="../images/a.png"/></svg>'],
                  {"a.png": png((40, 60)), "z page.png": png((20, 30)), "unused.png": png()})
        output, count = convert_epub_to_pdf(self.source, spreads="")
        pages = PdfReader(output).pages
        self.assertEqual(count, 2)
        self.assertEqual([(float(p.mediabox.width), float(p.mediabox.height)) for p in pages], [(20, 30), (40, 60)])

    def test_dynamic_spreads_both_reading_directions(self):
        with Image.new("RGB", (240, 180)) as scene:
            draw = ImageDraw.Draw(scene)
            for y in range(180):
                draw.line((0, y, 239, y), fill=(y, 255-y, (2*y) % 256))
            draw.polygon([(40, 10), (210, 150), (190, 170), (20, 30)], fill="navy")
            images = {"cover.png": png()}
            for name, x in [("left.png", 0), ("right.png", 120)]:
                with scene.crop((x, 0, x+120, 180)) as half:
                    data = io.BytesIO()
                    half.save(data, format="PNG")
                    images[name] = data.getvalue()
        for direction in ("ltr", "rtl"):
            ordered = ["left.png", "right.png"] if direction == "ltr" else ["right.png", "left.png"]
            make_epub(self.source, [f'<img src="../images/{name}"/>' for name in ["cover.png"] + ordered], images, direction)
            output, count = convert_epub_to_pdf(self.source, overwrite=True)
            self.assertEqual(count, 2, direction)
            page = PdfReader(output).pages[1]
            draws = [operands[0] for operands, op in page.get_contents().operations if op == b"Do"]
            self.assertEqual(page.images[draws[0]].image.tobytes(), Image.open(io.BytesIO(images["left.png"])).tobytes())
            self.assertEqual(page.images[draws[1]].image.tobytes(), Image.open(io.BytesIO(images["right.png"])).tobytes())

    def test_text_mixed_content_and_searchable_output(self):
        make_epub(self.source, ['<h1>First chapter</h1><p>A readable book with <b>bold</b> text.</p><img src="../images/figure.png"/><p>Illustration caption.</p>',
                               '<h1>Second chapter</h1><p>Final words.</p>'], {"figure.png": png()})
        with zipfile.ZipFile(self.source) as archive:
            self.assertIsNone(inspect_epub(archive)[2])
        output, count = convert_epub_to_pdf(self.source)
        reader = PdfReader(output)
        text = "\n".join(page.extract_text() for page in reader.pages)
        self.assertIn("Illustration caption.", text)
        self.assertLess(text.index("First chapter"), text.index("Second chapter"))
        self.assertIn("Final words.", text)
        self.assertTrue(any(len(page.images) for page in reader.pages))
        self.assertGreaterEqual(count, 2)
        self.assertAlmostEqual(float(reader.pages[0].mediabox.width), 595.276, places=2)
        self.assertEqual(reader.metadata.title, "Test Book")

    def test_manual_spreads_and_cli(self):
        make_epub(self.source, ['<img src="../images/a.png"/>', '<img src="../images/b.png"/>'],
                  {"a.png": png(), "b.png": png(color="blue")})
        script = Path(__file__).resolve().parents[1] / "converters/convert_epub_to_pdf.py"
        result = subprocess.run([sys.executable, str(script), str(self.source), "--spreads", "1-2"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(PdfReader(self.source.with_suffix(".pdf")).pages), 1)
        with self.assertRaises(FileExistsError):
            convert_epub_to_pdf(self.source)

    def test_failure_preserves_output(self):
        make_epub(self.source, ['<img src="../images/a.png"/>'], {"a.png": b"broken"})
        output = self.source.with_suffix(".pdf")
        output.write_bytes(b"original")
        with self.assertRaises(ValueError):
            convert_epub_to_pdf(self.source, overwrite=True)
        self.assertEqual(output.read_bytes(), b"original")
        self.assertEqual(set(self.folder.iterdir()), {self.source, output})

    def test_invalid_structure_and_paths(self):
        for href in ("../../outside.png", "https://example.com/a.png", "/absolute.png", "%2e%2e/%2e%2e/outside.png"):
            with self.assertRaises(ValueError):
                resource_path("OPS/page.xhtml", href)
        with zipfile.ZipFile(self.source, "w") as archive:
            archive.writestr("notes.txt", "Not an EPUB")
        with self.assertRaisesRegex(ValueError, "container.xml"):
            convert_epub_to_pdf(self.source)

    def test_text_cannot_be_silently_discarded_by_comic_mode(self):
        make_epub(self.source, ['<p>A caption matters.</p><img src="../images/a.png"/>'], {"a.png": png()})
        with self.assertRaisesRegex(ValueError, "needs text/layout"):
            convert_epub_to_pdf(self.source, mode="comic")
        with self.assertRaisesRegex(ValueError, "Explicit spreads"):
            convert_epub_to_pdf(self.source, spreads="1-2")


if __name__ == "__main__":
    unittest.main()
