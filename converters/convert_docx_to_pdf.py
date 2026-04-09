import argparse
import os
import platform
import shutil
import subprocess
import sys

LIBREOFFICE_CANDIDATES = ("libreoffice", "soffice")
MICROSOFT_WORD_APP = "/Applications/Microsoft Word.app"
WORD_JXA_SCRIPT = r"""
ObjC.import("stdlib");
var SystemEvents = Application("System Events");

function run(argv) {
    var inputPath = argv[0];
    var outputPath = argv[1];
    var word = Application("Microsoft Word");

    if (!word.running()) {
        word.activate();
        delay(1);
    } else {
        word.launch();
    }

    try {
        SystemEvents.processes["Microsoft Word"].visible = false;
    } catch (error) {
        // Hiding the app is best-effort only.
    }

    word.open(inputPath);
    var doc = word.activeDocument;
    doc.saveAs({ fileName: outputPath, fileFormat: "format PDF" });
    doc.close({ saving: "no" });
}
"""


def find_libreoffice_executable():
    for executable in LIBREOFFICE_CANDIDATES:
        path = shutil.which(executable)
        if path:
            return path
    return None


def is_microsoft_word_available():
    return platform.system() == "Darwin" and os.path.exists(MICROSOFT_WORD_APP)


def convert_with_libreoffice(file_path):
    libreoffice_executable = find_libreoffice_executable()
    if not libreoffice_executable:
        print("LibreOffice is not installed or not available in PATH.")
        return False

    pdf_path = os.path.splitext(os.path.abspath(file_path))[0] + ".pdf"
    output_dir = os.path.dirname(os.path.abspath(file_path))
    command = [
        libreoffice_executable,
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        output_dir,
        file_path,
    ]

    print(f"Converting with LibreOffice: {file_path}...")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"LibreOffice conversion failed: {result.stderr.strip()}")
        return False

    return os.path.exists(pdf_path)


def convert_with_word(file_path):
    if not is_microsoft_word_available():
        print("Microsoft Word is not installed. Expected /Applications/Microsoft Word.app")
        return False

    input_path = os.path.abspath(file_path)
    pdf_path = os.path.splitext(input_path)[0] + ".pdf"

    print(f"Converting with Microsoft Word: {file_path}...")
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", WORD_JXA_SCRIPT, input_path, pdf_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip() or "Unknown error."
        print(f"Microsoft Word conversion failed: {details}")
        return False

    return os.path.exists(pdf_path)


def resolve_engine(engine):
    if engine == "libreoffice":
        return "libreoffice"
    if engine == "word":
        return "word"
    if find_libreoffice_executable():
        return "libreoffice"
    if is_microsoft_word_available():
        return "word"
    return None


def convert_docx_to_pdf(file_path, engine="auto"):
    """
    Converts a specific .docx file to .pdf using LibreOffice or Microsoft Word.
    """
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' not found.")
        return False

    if not file_path.lower().endswith(".docx"):
        print(f"Error: '{file_path}' is not a .docx file.")
        return False

    selected_engine = resolve_engine(engine)
    if selected_engine is None:
        print(
            "No DOCX conversion engine is available. Install LibreOffice, or on macOS install Microsoft Word."
        )
        return False

    try:
        if selected_engine == "libreoffice":
            success = convert_with_libreoffice(file_path)
        else:
            success = convert_with_word(file_path)

        if success:
            pdf_path = os.path.splitext(file_path)[0] + ".pdf"
            print(f"Successfully converted to: {pdf_path}")
            return True

        return False
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return False


def convert_all_docx_in_dir(directory=".", engine="auto"):
    """
    Finds all .docx files in the given directory and converts them to .pdf.
    """
    files = [f for f in os.listdir(directory) if f.lower().endswith(".docx")]

    if not files:
        print(f"No .docx files found in: {directory}")
        return

    print(f"Found {len(files)} .docx files in: {directory}. Starting conversion...")
    for docx_file in files:
        convert_docx_to_pdf(os.path.join(directory, docx_file), engine=engine)


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Convert DOCX files to PDF.")
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to a .docx file or a directory containing .docx files.",
    )
    parser.add_argument(
        "--engine",
        choices=("auto", "libreoffice", "word"),
        default="auto",
        help="Conversion engine to use. 'auto' prefers LibreOffice and falls back to Microsoft Word on macOS.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args(sys.argv[1:])
    path = args.path
    if os.path.isdir(path):
        convert_all_docx_in_dir(path, engine=args.engine)
    else:
        convert_docx_to_pdf(path, engine=args.engine)
