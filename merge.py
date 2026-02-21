import os
import argparse
import re
from PyPDF2 import PdfMerger
from config import Config

def get_unique_output_path(folder, base_name):
    name, ext = os.path.splitext(base_name)
    ext = ext or ".pdf"

    candidate = f"{name}{ext}"
    counter = 1
    while os.path.exists(os.path.join(folder, candidate)):
        candidate = f"{name}[{counter}]{ext}"
        counter += 1

    return os.path.join(folder, candidate)

def merge(folder, output_name=None):
    if not os.path.exists(folder) or not os.path.isdir(folder):
        print(f"Folder doesn't exist: {folder}")
        return

    # Filter to merge strictly Slide PDFs. Notes and QBs are ignored.
    pdfs = [f for f in os.listdir(folder) if f.lower().endswith(".pdf") and f.startswith("Slide_")]
    if len(pdfs) < 2:
        print("Not enough Slide PDFs to merge.")
        return

    pdfs = sorted(
        pdfs,
        key=lambda x: (
            int(re.search(r'\d+', x).group())
            if re.search(r'\d+', x)
            else float("inf")
        ),
    )

    if not output_name:
        output_name = "merged.pdf"
    if not output_name.lower().endswith(".pdf"):
        output_name += ".pdf"

    output_path = get_unique_output_path(folder, output_name)

    merger = PdfMerger()
    for pdf in pdfs:
        merger.append(os.path.join(folder, pdf))

    merger.write(output_path)
    merger.close()

    print(f"Merged PDF created → {output_path}")

<<<<<<< HEAD

# 7. MERGE PDFs
def ask_and_merge_pdfs(folder, output_name = None):
    Config.load_env()
    pref = Config.get_merge_pdfs_preference()
=======
def ask_and_merge_pdfs(folder, output_name=None):
    values = dotenv_values(ENV_FILE) if os.path.exists(ENV_FILE) else {}
    pref = values.get("MERGE_PDFS", None)
>>>>>>> 6ac7945 (Add support for downloading Notes and QB separately from Slides)

    other_files = [
        f for f in os.listdir(folder)
        if os.path.isfile(os.path.join(folder, f)) and not f.lower().endswith(".pdf")
    ]

    if other_files:
        print("\n--- The following files are NOT PDFs ---")
        for f in other_files:
            print("  •", f)
        print("--- These will NOT be included in merging ---")

    if pref == "-1":
        return
    if pref == "1":
        merge(folder, output_name)
        keep_only_merged(folder)
        return

    print("\nMerge all Slide PDFs into a single file?")
    print("1. Always")
    print("2. Yes")
    print("3. No")
    print("4. Don't ask again (always no)")
    choice = input("Select option: ").strip()

    if choice == "1":
        merge(folder, output_name)
        keep_only_merged(folder)
        Config.set_merge_pdfs_preference("1")
    elif choice == "2":
        merge(folder, output_name)
        keep_only_merged(folder)
        Config.set_merge_pdfs_preference("0")
    elif choice == "3":
        Config.set_merge_pdfs_preference("0")
    elif choice == "4":
        Config.set_merge_pdfs_preference("-1")
        print("Preference saved. Will not merge.")

def delete_non_merged(folder):
    for filename in os.listdir(folder):
        # Target only Slide_ files for deletion post-merge
        if filename.endswith(".pdf") and filename.startswith("Slide_") and "merged" not in filename.lower():
            filepath = os.path.join(folder, filename)
            os.remove(filepath)
            print(f"Deleted file: {filepath}")

def keep_only_merged(folder):
    Config.load_env()
    pref = Config.get("KEEP_ONLY_MERGED")

    if pref == "1":
        delete_non_merged(folder)
        return
    if pref == "-1":
        return
    
    print("\nKeep only merged Slide PDF? (Notes and QB will remain untouched)")
    print("1. Always")
    print("2. Yes")
    print("3. No")
    print("4. Don't ask again (always no)")
    choice = input("Select option: ").strip()
    
    if choice == "1":
        delete_non_merged(folder)
        Config.set_env("KEEP_ONLY_MERGED", "1")
    elif choice == "2":
        delete_non_merged(folder)
        Config.set_env("KEEP_ONLY_MERGED", "0")
    elif choice == "3":
        Config.set_env("KEEP_ONLY_MERGED", "0")
    elif choice == "4":
<<<<<<< HEAD
        Config.set_env("KEEP_ONLY_MERGED", "-1")
        print("Preference saved. Will not keep only merged.")
=======
        set_key(ENV_FILE, "KEEP_ONLY_MERGED", "-1")
        print("Preference saved.")
>>>>>>> 6ac7945 (Add support for downloading Notes and QB separately from Slides)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge PDFs in a folder")
    parser.add_argument("--folder", required=True, help="Folder containing PDF files")
    parser.add_argument("--output", help="Output PDF name (optional)")
    args = parser.parse_args()

    ask_and_merge_pdfs(args.folder, args.output)