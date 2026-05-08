"""
file_conversion.py – Convert all .pptx files in a course directory tree to PDF.

Scans recursively so that root/, root/Notes/, and root/QB/ are all covered.
Uses online2pdf.com in batches of up to 30 files (free tier limit).

Mode behaviour:
  - 1 file  → "Merge files" mode  → single PDF downloaded directly.
  - 2+ files → "Convert files separately" mode → ZIP downloaded, extracted in-place.

The download is triggered automatically by online2pdf after conversion completes;
there is no separate download-link step. We therefore wrap the Convert click
inside expect_download() so Playwright catches the automatic download.
"""

import argparse
import logging
import os
import shutil
import zipfile
from collections import defaultdict

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

ONLINE2PDF_URL = "https://online2pdf.com/convert-pptx-to-pdf"
BATCH_SIZE = 30  # online2pdf free tier limit


# ---------------------------------------------------------------------------
# ZIP / cleanup helpers
# ---------------------------------------------------------------------------

def unzip_and_flatten(zip_path: str, destination: str) -> None:
    """Extract all files from a ZIP into destination, then remove the ZIP."""
    extract_dir = os.path.join(destination, "_unzipped_temp")
    os.makedirs(extract_dir, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)

        for root, _, files in os.walk(extract_dir):
            for f in files:
                src = os.path.join(root, f)
                dst = os.path.join(destination, f)
                if os.path.exists(dst):
                    base, ext = os.path.splitext(f)
                    counter = 1
                    while os.path.exists(dst):
                        dst = os.path.join(destination, f"{base}_{counter}{ext}")
                        counter += 1
                shutil.move(src, dst)
                logger.debug("Extracted: %s", os.path.basename(dst))

        os.remove(zip_path)
        shutil.rmtree(extract_dir)
        logger.debug("Cleaned up ZIP and temp folder.")
    except Exception as e:
        logger.error("Error extracting ZIP %s: %s", zip_path, e)


def delete_pptx_files(files: list[str]) -> None:
    for f in files:
        try:
            os.remove(f)
            logger.debug("Deleted: %s", os.path.basename(f))
        except Exception as e:
            logger.error("Error deleting %s: %s", os.path.basename(f), e)


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

def get_batches(files: list[str], batch_size: int = BATCH_SIZE):
    for i in range(0, len(files), batch_size):
        yield files[i: i + batch_size]


def collect_pptx_files(folder: str) -> list[str]:
    found: list[str] = []
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(".pptx"):
                found.append(os.path.join(root, f))
    return found


# ---------------------------------------------------------------------------
# online2pdf.com converter
# ---------------------------------------------------------------------------

def _click_convert(page) -> None:
    """Click the Convert button via JS, trying several selectors."""
    page.evaluate("""
        () => {
            const btn =
                document.querySelector('input[type="submit"][value="Convert"]') ||
                Array.from(document.querySelectorAll('input[type="submit"]'))
                    .find(b => b.value.trim().toLowerCase() === 'convert') ||
                Array.from(document.querySelectorAll('button'))
                    .find(b => b.textContent.trim().toLowerCase() === 'convert') ||
                document.querySelector('button[type="submit"]');
            if (btn) btn.click();
        }
    """)


def _set_mode_separately(page) -> bool:
    """
    Switch the Mode dropdown to 'Convert files separately'.
    Returns True if successful.
    """
    # Strategy 1: <select> with an option whose text includes 'separately'
    try:
        result = page.evaluate("""
            () => {
                for (const sel of document.querySelectorAll('select')) {
                    const opt = Array.from(sel.options)
                        .find(o => o.text.toLowerCase().includes('separately'));
                    if (opt) {
                        sel.value = opt.value;
                        sel.dispatchEvent(new Event('change', { bubbles: true }));
                        return 'select:' + opt.value;
                    }
                }
                return null;
            }
        """)
        if result:
            logger.info("Mode set via <select>: %s", result)
            return True
    except Exception as e:
        logger.debug("Mode strategy 1 failed: %s", e)

    # Strategy 2: visible <label> containing the text
    try:
        label = page.locator("label", has_text="Convert files separately").first
        if label.is_visible():
            label.click()
            logger.info("Mode set via label click.")
            return True
    except Exception as e:
        logger.debug("Mode strategy 2 failed: %s", e)

    # Strategy 3: radio button with a value hinting at split/separate
    try:
        radio = page.locator(
            "input[type='radio'][value*='split'], input[type='radio'][value*='separate']"
        ).first
        if radio.count() > 0:
            radio.click()
            logger.info("Mode set via radio button.")
            return True
    except Exception as e:
        logger.debug("Mode strategy 3 failed: %s", e)

    # Strategy 4: JS text-walk click
    try:
        page.evaluate("""
            () => {
                const el = Array.from(document.querySelectorAll('*')).find(e =>
                    e.children.length === 0 &&
                    e.textContent.trim().toLowerCase() === 'convert files separately'
                );
                if (el) el.click();
            }
        """)
        logger.info("Mode set via JS text click (best-effort).")
        return True
    except Exception as e:
        logger.debug("Mode strategy 4 failed: %s", e)

    return False


def convert_batch_with_online2pdf(pptx_files: list[str]) -> None:
    """
    Upload a batch of .pptx files to online2pdf.com and download the result.

    Confirmed flow (from screenshots):
      1. Fresh page loads — just a file picker, no list yet.
      2. Upload files via the file input — the page renders the file list,
         Mode dropdown, and Convert button (does NOT auto-submit).
      3. Set Mode to 'Convert files separately' (for multiple files).
      4. Click Convert — page switches to processing screen and download
         fires automatically when done.

    expect_download() wraps the Convert click so Playwright catches the
    automatic download without needing a separate download-link click.
    """
    folder = os.path.dirname(pptx_files[0])
    multiple = len(pptx_files) > 1

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        # ── 1. Load the page ──────────────────────────────────────────────
        logger.info("Opening online2pdf.com (%d file(s))...", len(pptx_files))
        page.goto(ONLINE2PDF_URL, timeout=60_000)
        page.wait_for_load_state("networkidle")

        # ── 2. Upload files ───────────────────────────────────────────────
        logger.info("Uploading %d file(s)...", len(pptx_files))
        upload_input = page.locator("input[type='file']").first
        upload_input.set_input_files(pptx_files)

        # Wait for the file list to appear (Mode dropdown + Convert button visible)
        page.wait_for_selector(
            "table#files tr, #fileGroups .filerow, .filerow, tr.filerow, "
            "input[type='submit'][value='Convert'], button:has-text('Convert')",
            timeout=120_000,
        )
        page.wait_for_timeout(800)  # brief settle for all rows to render

        # ── 3. Set mode to 'Convert files separately' ─────────────────────
        if multiple:
            if not _set_mode_separately(page):
                logger.warning(
                    "Could not set 'Convert files separately' — "
                    "proceeding with default (Merge files). "
                    "All files will be merged into one PDF."
                )
            page.wait_for_timeout(300)

        # ── 4. Click Convert — download fires automatically after processing
        logger.info("Clicking Convert and waiting for automatic download...")
        with page.expect_download(timeout=600_000) as dl_info:
            _click_convert(page)

        # ── 5. Save the downloaded file ───────────────────────────────────
        download = dl_info.value
        downloaded_path = os.path.join(folder, download.suggested_filename)
        download.save_as(downloaded_path)
        logger.info("Downloaded: %s", downloaded_path)

        browser.close()

    # ── 5. Post-processing ────────────────────────────────────────────────
    if downloaded_path.lower().endswith(".zip"):
        logger.info("Extracting ZIP...")
        unzip_and_flatten(downloaded_path, folder)
    else:
        logger.info("Single PDF saved: %s", os.path.basename(downloaded_path))

    delete_pptx_files(pptx_files)


# ---------------------------------------------------------------------------
# Main conversion controller
# ---------------------------------------------------------------------------

def convert_pptx_to_pdf(folder: str) -> None:
    """
    Recursively scan `folder` for .pptx files and convert them to PDF
    using online2pdf.com in batches of up to 30, grouped by directory.
    """
    logger.info("Scanning folder tree for .pptx files: %s", folder)

    if not os.path.exists(folder) or not os.path.isdir(folder):
        logger.error("Directory not found: %s", folder)
        return

    all_pptx = collect_pptx_files(folder)

    if not all_pptx:
        logger.info("No PPTX files found under: %s", folder)
        return

    by_dir: dict[str, list[str]] = defaultdict(list)
    for path in all_pptx:
        by_dir[os.path.dirname(path)].append(path)

    total_batches = sum(len(list(get_batches(files))) for files in by_dir.values())
    batch_num = 0

    for dir_path, files in by_dir.items():
        for batch in get_batches(files):
            batch_num += 1
            logger.info(
                "Batch %d/%d | folder: %s | %d file(s)",
                batch_num, total_batches, dir_path, len(batch),
            )
            convert_batch_with_online2pdf(batch)

    logger.info("All PPTX files converted successfully.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Convert PPTX to PDF using online2pdf.com")
    parser.add_argument("--folder", "--f", dest="folder", required=True, help="Root folder path")
    args = parser.parse_args()

    if not os.path.isdir(args.folder):
        logger.error("Directory not found: %s", args.folder)
        raise SystemExit(1)

    convert_pptx_to_pdf(args.folder)
