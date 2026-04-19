import os
import argparse
import re
from PyPDF2 import PdfMerger
from dotenv import set_key, dotenv_values

ENV_FILE = ".env"


def get_unique_output_path(folder, base_name):
    name, ext = os.path.splitext(base_name)
    ext = ext or ".pdf"
    candidate = f"{name}{ext}"
    counter = 1
    while os.path.exists(os.path.join(folder, candidate)):
        candidate = f"{name}_{counter}{ext}"
        counter += 1
    return os.path.join(folder, candidate)

def merge(folder, include_qb, output_name=None):
    if not os.path.exists(folder) or not os.path.isdir(folder):
        print(f"Folder doesn't exist: {folder}")
        return
    slide_pdfs = [
        f for f in os.listdir(folder)
        if f.lower().endswith(".pdf") and not f.startswith("merged")
    ]

    qb_pdfs = []
    if include_qb:
        qb_folder = os.path.join(folder, "QB")
        if os.path.exists(qb_folder):
            qb_pdfs = [
                f for f in os.listdir(qb_folder)
                if f.lower().endswith(".pdf")
            ]

    def sort_key(x):
        match = re.match(r'^QB_(\d+)_', x)
        if match:
            return (0, int(match.group(1)))

        match = re.match(r'^(\d+)_', x)
        if match:
            return (1, int(match.group(1)))

        return (2, float("inf"))

    slide_files = [(os.path.join(folder, f), f) for f in slide_pdfs]
    qb_files = [(os.path.join(folder, "QB", f), f) for f in qb_pdfs]

    all_files = slide_files + qb_files

    all_files.sort(key=lambda item: sort_key(item[1]))

    if len(all_files) < 2:
        print("Not enough PDFs to merge.")
        return

    if not output_name:
        output_name = "merged.pdf"
    if not output_name.lower().endswith(".pdf"):
        output_name += ".pdf"

    output_path = get_unique_output_path(folder, output_name)
    merger = PdfMerger()

    print("\nMerging Order:")
    for path, name in all_files:
        print(f" - {name}")
        merger.append(path)

    merger.write(output_path)
    merger.close()
    print(f"\nMerged PDF created -> {output_path}")

def ask_and_merge_pdfs(folder, output_name=None):
    values = dotenv_values(ENV_FILE) if os.path.exists(ENV_FILE) else {}
    pref = values.get("MERGE_PDFS", None)
    if pref == "-1":
        return

    print("\nSelect Merge Scope:")
    print("1. Combine Slides only")
    print("2. Combine Slides AND Question Banks (QB)")
    print("3. Do not merge")
    scope_choice = input("Select option: ").strip()

    if scope_choice == "3":
        return

    include_qb = scope_choice == "2"

    if pref == "1":
        merge(folder, include_qb, output_name)
        keep_only_merged(folder, include_qb)
        return

    print("\nMerge selected PDFs into a single file?")
    print("1. Always")
    print("2. Yes")
    print("3. No")
    print("4. Don't ask again (always no)")
    choice = input("Select option: ").strip()

    if choice in ("1", "2"):
        merge(folder, include_qb, output_name)
        keep_only_merged(folder, include_qb)
        if choice == "1":
            set_key(ENV_FILE, "MERGE_PDFS", "1")
        else:
            set_key(ENV_FILE, "MERGE_PDFS", "0")
    elif choice == "3":
        set_key(ENV_FILE, "MERGE_PDFS", "0")
    elif choice == "4":
        set_key(ENV_FILE, "MERGE_PDFS", "-1")

def delete_non_merged(folder, include_qb):
    # Delete slides (pattern {index}_Topic.pdf)
    for filename in os.listdir(folder):
        if filename.endswith(".pdf") and re.match(r'^\d+_', filename) and "merged" not in filename.lower():
            filepath = os.path.join(folder, filename)
            os.remove(filepath)
            print(f"Deleted file: {filepath}")

    if include_qb:
        qb_folder = os.path.join(folder, "QB")
        if os.path.exists(qb_folder):
            for filename in os.listdir(qb_folder):
                if filename.endswith(".pdf"):
                    filepath = os.path.join(qb_folder, filename)
                    os.remove(filepath)
                    print(f"Deleted file: {filepath}")

def keep_only_merged(folder, include_qb):
    values = dotenv_values(ENV_FILE) if os.path.exists(ENV_FILE) else {}
    pref = values.get("KEEP_ONLY_MERGED", None)
    if pref == "1":
        delete_non_merged(folder, include_qb)
        return
    if pref == "-1":
        return
    print("\nKeep only merged PDF? (Source files will be deleted)")
    print("1. Always")
    print("2. Yes")
    print("3. No")
    print("4. Don't ask again (always no)")
    choice = input("Select option: ").strip()
    if choice == "1":
        delete_non_merged(folder, include_qb)
        set_key(ENV_FILE, "KEEP_ONLY_MERGED", "1")
    elif choice == "2":
        delete_non_merged(folder, include_qb)
        set_key(ENV_FILE, "KEEP_ONLY_MERGED", "0")
    elif choice == "3":
        set_key(ENV_FILE, "KEEP_ONLY_MERGED", "0")
    elif choice == "4":
        set_key(ENV_FILE, "KEEP_ONLY_MERGED", "-1")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge PDFs in a folder")
    parser.add_argument("--folder", required=True, help="Folder containing PDF files")
    parser.add_argument("--output", help="Output PDF name (optional)")
    args = parser.parse_args()
    ask_and_merge_pdfs(args.folder, args.output)
