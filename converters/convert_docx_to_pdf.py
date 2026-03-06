import os
import subprocess
import sys

def convert_docx_to_pdf(file_path):
    """
    Converts a specific .docx file to .pdf using LibreOffice.
    """
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' not found.")
        return False

    if not file_path.lower().endswith(".docx"):
        print(f"Error: '{file_path}' is not a .docx file.")
        return False

    try:
        # LibreOffice headless conversion command
        # --headless: Run without a GUI
        # --convert-to pdf: Specify the target format
        # --outdir: Specify the output directory (defaults to current dir)
        output_dir = os.path.dirname(os.path.abspath(file_path))
        command = [
            "libreoffice",
            "--headless",
            "--convert-to", "pdf",
            "--outdir", output_dir,
            file_path
        ]
        
        print(f"Converting: {file_path}...")
        result = subprocess.run(command, capture_output=True, text=True)
        
        if result.returncode == 0:
            pdf_path = os.path.splitext(file_path)[0] + ".pdf"
            print(f"Successfully converted to: {pdf_path}")
            return True
        else:
            print(f"Error during conversion: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return False

def convert_all_docx_in_dir(directory="."):
    """
    Finds all .docx files in the given directory and converts them to .pdf.
    """
    files = [f for f in os.listdir(directory) if f.lower().endswith(".docx")]
    
    if not files:
        print("No .docx files found in the current directory.")
        return

    print(f"Found {len(files)} .docx files. Starting conversion...")
    for docx_file in files:
        convert_docx_to_pdf(os.path.join(directory, docx_file))

if __name__ == "__main__":
    # If a filename is provided as an argument, convert only that file.
    # Otherwise, convert all .docx files in the current directory.
    if len(sys.argv) > 1:
        convert_docx_to_pdf(sys.argv[1])
    else:
        convert_all_docx_in_dir()
