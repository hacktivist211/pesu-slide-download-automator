"""
merge.py – Merge PDFs per category (Slides, Notes, QB) independently.

Each category is prompted (or preference-checked) separately.
  - Slides  → merged inside <unit_root>/
  - Notes   → merged inside <unit_root>/Notes/
  - QB      → merged inside <unit_root>/QB/
"""

import argparse
import logging
import os
import re

from PyPDF2 import PdfMerger
from dotenv import set_key, dotenv_values

logger = logging.getLogger(__name__)

ENV_FILE = ".env"

# ---------------------------------------------------------------------------
# Preference keys per category
# ---------------------------------------------------------------------------
_PREF_KEYS = {
    "slides": "MERGE_SLIDES",
    "notes":  "MERGE_NOTES",
    "qb":     "MERGE_QB",
}
_KEEP_KEYS = {
    "slides": "KEEP_ONLY_MERGED_SLIDES",
    "notes":  "KEEP_ONLY_MERGED_NOTES",
    "qb":     "KEEP_ONLY_MERGED_QB",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sort_key(filename: str) -> tuple:
    m = re.match(r"^QB_(\d+)_", filename)
    if m:
        return (0, int(m.group(1)))
    m = re.match(r"^Note_(\d+)_", filename)
    if m:
        return (1, int(m.group(1)))
    m = re.match(r"^(\d+)_", filename)
    if m:
        return (2, int(m.group(1)))
    return (3, float("inf"))


def get_unique_output_path(folder: str, base_name: str) -> str:
    name, ext = os.path.splitext(base_name)
    ext = ext or ".pdf"
    candidate = f"{name}{ext}"
    counter = 1
    while os.path.exists(os.path.join(folder, candidate)):
        candidate = f"{name}_{counter}{ext}"
        counter += 1
    return os.path.join(folder, candidate)


def _collect_pdfs(folder: str, exclude_prefix: str = "merged") -> list[str]:
    """Return sorted list of PDF paths in `folder`, excluding already-merged files."""
    if not os.path.isdir(folder):
        return []
    files = [
        f for f in os.listdir(folder)
        if f.lower().endswith(".pdf") and not f.lower().startswith(exclude_prefix)
    ]
    files.sort(key=_sort_key)
    return [os.path.join(folder, f) for f in files]


def _merge_files(pdf_paths: list[str], output_path: str) -> bool:
    if len(pdf_paths) < 2:
        logger.warning("Not enough PDFs to merge (need ≥ 2).")
        return False

    logger.info("Merging order:")
    for p in pdf_paths:
        logger.info("  - %s", os.path.basename(p))

    merger = PdfMerger()
    for p in pdf_paths:
        merger.append(p)
    merger.write(output_path)
    merger.close()
    logger.info("Merged PDF created -> %s", output_path)
    return True


def _delete_source_pdfs(pdf_paths: list[str]) -> None:
    for path in pdf_paths:
        try:
            os.remove(path)
            logger.debug("Deleted source: %s", path)
        except Exception as e:
            logger.error("Could not delete %s: %s", path, e)


# ---------------------------------------------------------------------------
# Per-category merge logic
# ---------------------------------------------------------------------------

def _get_pref(values: dict, category: str) -> str | None:
    return values.get(_PREF_KEYS[category])


def _ask_category_merge(
    category: str,
    folder: str,
    values: dict,
    output_name: str = "merged.pdf",
) -> None:
    """Handle merge prompt + execution for a single category."""
    pref = _get_pref(values, category)

    if pref == "-1":
        return  # "never ask again"

    pdf_paths = _collect_pdfs(folder)
    if not pdf_paths:
        logger.info("No PDFs found in %s for category '%s'. Skipping.", folder, category)
        return

    if pref == "1":
        # "always merge" saved preference
        output_path = get_unique_output_path(folder, output_name)
        if _merge_files(pdf_paths, output_path):
            _maybe_delete_sources(category, pdf_paths, values)
        return

    print(f"\n[{category.upper()}] Merge {len(pdf_paths)} PDF(s) in '{folder}'?")
    print("  1. Always (save preference)")
    print("  2. Yes")
    print("  3. No")
    print("  4. Never ask again for this category")
    choice = input("Select option: ").strip()

    if choice in ("1", "2"):
        output_path = get_unique_output_path(folder, output_name)
        if _merge_files(pdf_paths, output_path):
            _maybe_delete_sources(category, pdf_paths, values)
        if choice == "1":
            set_key(ENV_FILE, _PREF_KEYS[category], "1")
        else:
            set_key(ENV_FILE, _PREF_KEYS[category], "0")
    elif choice == "3":
        set_key(ENV_FILE, _PREF_KEYS[category], "0")
    elif choice == "4":
        set_key(ENV_FILE, _PREF_KEYS[category], "-1")


def _maybe_delete_sources(category: str, pdf_paths: list[str], values: dict) -> None:
    keep_pref = values.get(_KEEP_KEYS[category])
    if keep_pref == "1":
        _delete_source_pdfs(pdf_paths)
        return
    if keep_pref == "-1":
        return

    print(f"\n[{category.upper()}] Keep only the merged PDF? (Source files will be deleted)")
    print("  1. Always")
    print("  2. Yes")
    print("  3. No")
    print("  4. Never ask again")
    choice = input("Select option: ").strip()
    if choice in ("1", "2"):
        _delete_source_pdfs(pdf_paths)
        if choice == "1":
            set_key(ENV_FILE, _KEEP_KEYS[category], "1")
        else:
            set_key(ENV_FILE, _KEEP_KEYS[category], "0")
    elif choice == "3":
        set_key(ENV_FILE, _KEEP_KEYS[category], "0")
    elif choice == "4":
        set_key(ENV_FILE, _KEEP_KEYS[category], "-1")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ask_and_merge_pdfs(
    unit_folder: str,
    output_name: str | None = None,
    skip_prompt: bool | None = None,
) -> None:
    """
    Prompt (or auto-merge if skip_prompt=True) for each of:
      - Slides  (unit_folder/*.pdf)
      - Notes   (unit_folder/Notes/*.pdf)
      - QB      (unit_folder/QB/*.pdf)

    `skip_prompt=True`  → merge all categories automatically
    `skip_prompt=False` → skip all (useful when --no-merge is passed)
    `skip_prompt=None`  → use saved preferences / interactive prompts
    """
    if skip_prompt is False:
        return

    if not os.path.isdir(unit_folder):
        logger.warning("Unit folder not found: %s", unit_folder)
        return

    values = dotenv_values(ENV_FILE) if os.path.exists(ENV_FILE) else {}

    categories = [
        ("slides", unit_folder,                             output_name or "merged.pdf"),
        ("notes",  os.path.join(unit_folder, "Notes"),      "merged_notes.pdf"),
        ("qb",     os.path.join(unit_folder, "QB"),         "merged_qb.pdf"),
    ]

    for category, folder, out_name in categories:
        if not os.path.isdir(folder):
            continue  # subfolder doesn't exist; nothing to merge

        if skip_prompt is True:
            # Auto-merge without asking
            pdf_paths = _collect_pdfs(folder)
            if len(pdf_paths) >= 2:
                output_path = get_unique_output_path(folder, out_name)
                _merge_files(pdf_paths, output_path)
        else:
            _ask_category_merge(category, folder, values, out_name)


# ---------------------------------------------------------------------------
# Direct-merge helper (no prompts, used programmatically)
# ---------------------------------------------------------------------------

def merge(folder: str, output_name: str | None = None) -> None:
    """Merge all PDFs in `folder` into a single file (no prompts)."""
    pdf_paths = _collect_pdfs(folder)
    if not pdf_paths:
        logger.warning("No PDFs found in: %s", folder)
        return
    out_name = output_name or "merged.pdf"
    if not out_name.lower().endswith(".pdf"):
        out_name += ".pdf"
    output_path = get_unique_output_path(folder, out_name)
    _merge_files(pdf_paths, output_path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Merge PDFs in a unit folder (Slides, Notes, QB)")
    parser.add_argument("--folder", required=True, help="Unit folder path")
    parser.add_argument("--output", help="Output PDF base name (optional)")
    parser.add_argument("--auto", action="store_true", help="Merge all categories without prompting")
    args = parser.parse_args()

    ask_and_merge_pdfs(args.folder, output_name=args.output, skip_prompt=True if args.auto else None)
