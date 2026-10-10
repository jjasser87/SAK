import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from PIL import Image, ImageDraw
from pypdf import PdfReader

from converters.convert_cbz_to_pdf import convert_cbz_to_pdf


class ConvertCbzTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.source = self.folder / "comic.cbz"

    def image(self, size):
        data = io.BytesIO()
        with Image.new("RGB", size, "red") as image:
            image.save(data, format="PNG")
        return data.getvalue()

    def test_order_and_intact_centered_spread(self):
        with zipfile.ZipFile(self.source, "w") as archive:
            archive.writestr("chapter/page10.png", self.image((20, 30)))
            archive.writestr("chapter/page2.PNG", self.image((80, 40)))
            archive.writestr("ComicInfo.xml", "metadata")
            archive.writestr("__MACOSX/._page.png", b"ignored")
        output, count = convert_cbz_to_pdf(self.source)
        pages = PdfReader(output).pages
        self.assertEqual(count, 2)
        self.assertEqual([(float(p.mediabox.width), float(p.mediabox.height))
                          for p in pages], [(40, 80), (20, 30)])
        self.assertEqual(pages[0].images[0].image.size, (80, 40))
        # A 40 x 20 drawing at (0, 30) retains the full spread's aspect ratio.
        matrices = [list(operands) for operands, op in pages[0].get_contents().operations
                    if op == b"cm"]
        self.assertIn([40, 0, 0, 20, 0, 30], matrices)

    def test_failed_conversion_preserves_output_and_cleans_temporary_file(self):
        with zipfile.ZipFile(self.source, "w") as archive:
            archive.writestr("page1.png", self.image((20, 30)))
        output, _ = convert_cbz_to_pdf(self.source)
        original = output.read_bytes()
        with self.assertRaises(FileExistsError):
            convert_cbz_to_pdf(self.source)
        with zipfile.ZipFile(self.source, "a") as archive:
            archive.writestr("page2.png", b"broken")
        with self.assertRaisesRegex(ValueError, "page2.png"):
            convert_cbz_to_pdf(self.source, overwrite=True)
        self.assertEqual(output.read_bytes(), original)
        self.assertEqual(set(self.folder.iterdir()), {self.source, output})

    def test_empty_and_invalid_archive(self):
        with zipfile.ZipFile(self.source, "w") as archive:
            archive.writestr("notes.txt", "no images")
        with self.assertRaisesRegex(ValueError, "No supported images"):
            convert_cbz_to_pdf(self.source)
        self.source.write_bytes(b"not a zip")
        with self.assertRaises(zipfile.BadZipFile):
            convert_cbz_to_pdf(self.source)

    def test_separate_halves_join_without_cropping_or_reordering(self):
        with zipfile.ZipFile(self.source, "w") as archive:
            for number, size in [(10, (20, 30)), (3, (40, 60)), (2, (20, 30)), (1, (10, 15))]:
                archive.writestr(f"page{number}.png", self.image(size))
        output, count = convert_cbz_to_pdf(self.source, spreads="2-3")
        pages = PdfReader(output).pages
        self.assertEqual(count, 3)
        self.assertEqual(len(pages), 3)
        self.assertEqual(len(pages[0].images), 1)
        self.assertEqual(len(pages[2].images), 1)
        self.assertEqual(sorted(image.image.size for image in pages[1].images), [(20, 30), (40, 60)])
        self.assertEqual((float(pages[1].mediabox.width), float(pages[1].mediabox.height)), (20, 30))
        matrices = [list(operands) for operands, op in pages[1].get_contents().operations if op == b"cm"]
        self.assertIn([10, 0, 0, 15, 0, 7.5], matrices)
        self.assertIn([10, 0, 0, 15, 10, 7.5], matrices)

    def test_invalid_spreads_do_not_create_output(self):
        with zipfile.ZipFile(self.source, "w") as archive:
            for number in range(1, 5):
                archive.writestr(f"page{number}.png", self.image((20, 30)))
        for specification in ["0-1", "1-3", "4-5", "2-3,3-4", "2-3,2-3", "2", "bad", "1-2-3"]:
            with self.subTest(specification=specification), self.assertRaises(ValueError):
                convert_cbz_to_pdf(self.source, spreads=specification)
        self.assertEqual(list(self.folder.iterdir()), [self.source])

    def test_cli_spreads(self):
        with zipfile.ZipFile(self.source, "w") as archive:
            archive.writestr("page1.png", self.image((20, 30)))
            archive.writestr("page2.png", self.image((30, 45)))
        script = Path(__file__).resolve().parents[1] / "converters/convert_cbz_to_pdf.py"
        result = subprocess.run([sys.executable, str(script), str(self.source), "--spreads", "1-2"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(PdfReader(self.source.with_suffix(".pdf")).pages), 1)

    def test_jpeg_passthrough_and_exif_orientation(self):
        data = io.BytesIO()
        rotated = io.BytesIO()
        with Image.new("RGB", (30, 20), "red") as image:
            image.paste("blue", (0, 0, 10, 20))
            image.save(data, format="JPEG")
            exif = Image.Exif()
            exif[274] = 6
            image.save(rotated, format="JPEG", exif=exif)
        with zipfile.ZipFile(self.source, "w") as archive:
            archive.writestr("page1.jpg", data.getvalue())
            archive.writestr("page2.jpg", rotated.getvalue())
        output, _ = convert_cbz_to_pdf(self.source)
        pages = PdfReader(output).pages
        first = next(iter(pages[0]["/Resources"]["/XObject"].values())).get_object()
        self.assertIn("/DCTDecode", first["/Filter"])
        self.assertEqual(first.get_data(), data.getvalue())
        self.assertEqual(pages[1].images[0].image.size, (20, 30))

    def test_automatic_detection_uses_artwork_not_page_numbers_or_parity(self):
        # A generated scene has continuous sloping shapes through its center.
        # It has no relationship to the supplied comic or any known page list.
        with Image.new("RGB", (240, 180)) as scene:
            draw = ImageDraw.Draw(scene)
            for y in range(180):
                draw.line((0, y, 239, y), fill=(y, 255 - y, (y * 2) % 256))
            draw.polygon([(40, 10), (210, 150), (190, 170), (20, 30)], fill="navy")
            draw.ellipse((75, 55, 170, 125), fill="orange")
            with scene.crop((0, 0, 120, 180)) as left, scene.crop((120, 0, 240, 180)) as right:
                left_data, right_data = io.BytesIO(), io.BytesIO()
                left.save(left_data, format="PNG")
                # Different source resolutions must not prevent a match.
                with right.resize((240, 360)) as larger:
                    larger.save(right_data, format="PNG")
        for cover_count in (0, 1, 2):
            with self.subTest(cover_count=cover_count):
                with zipfile.ZipFile(self.source, "w") as archive:
                    for i in range(cover_count):
                        archive.writestr(f"a{i}.png", self.image((120, 180)))
                    archive.writestr("z-right.png", right_data.getvalue())
                    archive.writestr("m-left.png", left_data.getvalue())
                output, count = convert_cbz_to_pdf(self.source, overwrite=True)
                self.assertEqual(count, cover_count + 1)
                self.assertEqual(len(PdfReader(output).pages[-1].images), 2)
                _, separate = convert_cbz_to_pdf(self.source, overwrite=True, spreads="")
                self.assertEqual(separate, cover_count + 2)

    def test_auto_rejects_uniform_borders_and_ambiguous_neighbors(self):
        for kind in ("white-margins", "transparent-margins", "repeating-edges", "unrelated"):
            with self.subTest(kind=kind), zipfile.ZipFile(self.source, "w") as archive:
                for index in range(3):
                    with Image.new("RGBA", (120, 180), "white") as page:
                        draw = ImageDraw.Draw(page)
                        for y in range(180):
                            color = (y, 255 - y, y)
                            if kind == "transparent-margins":
                                color = (*color, 0)
                            if kind == "unrelated":
                                color = (255 - y, y, 255 - y) if index == 1 else color
                            draw.line((10 if kind == "white-margins" else 0, y,
                                       110 if kind == "white-margins" else 119, y), fill=color)
                        data = io.BytesIO()
                        page.save(data, format="PNG")
                        archive.writestr(f"page{index}.png", data.getvalue())
            _, count = convert_cbz_to_pdf(self.source, overwrite=True)
            self.assertEqual(count, 3, kind)

    def test_cli_custom_output_and_overwrite(self):
        with zipfile.ZipFile(self.source, "w") as archive:
            archive.writestr("nested/page.png", self.image((60, 30)))
        output = self.folder / "reading copy.pdf"
        script = Path(__file__).resolve().parents[1] / "converters/convert_cbz_to_pdf.py"
        command = [sys.executable, str(script), str(self.source), "-o", str(output)]
        for extra, expected in [([], 0), ([], 1), (["--overwrite"], 0)]:
            result = subprocess.run(command + extra, capture_output=True, text=True)
            self.assertEqual(result.returncode, expected, result.stderr)
        self.assertEqual(len(PdfReader(output).pages), 1)


if __name__ == "__main__":
    unittest.main()
