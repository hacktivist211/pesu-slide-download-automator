import argparse
import logging
import os
import shutil
import zipfile
from collections import defaultdict

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeoutError

from integrity import check_office_zip, quarantine

logger = logging.getLogger(__name__)

CONVERT_URLS = {
    ".pptx": "https://online2pdf.com/convert-pptx-to-pdf",
    ".docx": "https://online2pdf.com/convert-docx-to-pdf",
}
BATCH_SIZE = 30


def unzip_and_flatten(zip_path: str, destination: str) -> None:
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


def delete_source_files(files: list[str]) -> None:
    for f in files:
        try:
            os.remove(f)
            logger.debug("Deleted: %s", os.path.basename(f))
        except Exception as e:
            logger.error("Error deleting %s: %s", os.path.basename(f), e)


def get_batches(files: list[str], batch_size: int = BATCH_SIZE):
    for i in range(0, len(files), batch_size):
        yield files[i: i + batch_size]


def collect_files(folder: str, ext: str) -> list[str]:
    found: list[str] = []
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(ext):
                found.append(os.path.join(root, f))
    return found


def filter_convertible(files: list[str], ext: str) -> list[str]:
    ok: list[str] = []
    for f in files:
        if check_office_zip(f):
            ok.append(f)
        else:
            quarantine(f, f"corrupt {ext.lstrip('.')}, excluded before online2pdf upload")
    return ok


def _click_convert(page) -> None:
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

    try:
        label = page.locator("label", has_text="Convert files separately").first
        if label.is_visible():
            label.click()
            logger.info("Mode set via label click.")
            return True
    except Exception as e:
        logger.debug("Mode strategy 2 failed: %s", e)

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


def convert_batch_with_online2pdf(files: list[str], ext: str) -> None:
    folder = os.path.dirname(files[0])
    multiple = len(files) > 1
    url = CONVERT_URLS[ext]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        logger.info("Opening %s (%d file(s))...", url, len(files))
        page.goto(url, timeout=60_000)
        page.wait_for_load_state("networkidle")

        logger.info("Uploading %d file(s)...", len(files))
        upload_input = page.locator("input[type='file']").first
        upload_input.set_input_files(files)

        page.wait_for_selector(
            "table#files tr, #fileGroups .filerow, .filerow, tr.filerow, "
            "input[type='submit'][value='Convert'], button:has-text('Convert')",
            timeout=120_000,
        )
        page.wait_for_timeout(800)

        if multiple:
            if not _set_mode_separately(page):
                logger.warning(
                    "Could not set 'Convert files separately' — "
                    "proceeding with default (Merge files). "
                    "All files will be merged into one PDF."
                )
            page.wait_for_timeout(300)

        timeout_ms = min(max(60_000, 20_000 * len(files)), 300_000)
        logger.info("Clicking Convert, waiting up to %ds for download...", timeout_ms // 1000)
        try:
            with page.expect_download(timeout=timeout_ms) as dl_info:
                _click_convert(page)
        except PwTimeoutError:
            logger.error(
                "online2pdf did not respond within %ds for batch of %d file(s). "
                "This usually means one of the files can't be converted.",
                timeout_ms // 1000, len(files),
            )
            browser.close()
            _handle_conversion_stall(files, ext)
            return

        download = dl_info.value
        downloaded_path = os.path.join(folder, download.suggested_filename)
        download.save_as(downloaded_path)
        logger.info("Downloaded: %s", downloaded_path)

        browser.close()

    if downloaded_path.lower().endswith(".zip"):
        logger.info("Extracting ZIP...")
        unzip_and_flatten(downloaded_path, folder)
    else:
        logger.info("Single PDF saved: %s", os.path.basename(downloaded_path))

    delete_source_files(files)


def _handle_conversion_stall(files: list[str], ext: str) -> None:
    if len(files) == 1:
        quarantine(files[0], f"online2pdf hung on this file, not convertible")
        return

    mid = len(files) // 2
    logger.warning("Bisecting stalled batch of %d into two halves.", len(files))
    convert_batch_with_online2pdf(files[:mid], ext)
    convert_batch_with_online2pdf(files[mid:], ext)


def convert_files_to_pdf(folder: str, ext: str) -> None:
    logger.info("Scanning folder tree for %s files: %s", ext, folder)

    if not os.path.exists(folder) or not os.path.isdir(folder):
        logger.error("Directory not found: %s", folder)
        return

    all_files = collect_files(folder, ext)

    if not all_files:
        logger.info("No %s files found under: %s", ext, folder)
        return

    all_files = filter_convertible(all_files, ext)

    if not all_files:
        logger.warning("All %s files under %s failed integrity checks, nothing to convert.", ext, folder)
        return

    by_dir: dict[str, list[str]] = defaultdict(list)
    for path in all_files:
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
            convert_batch_with_online2pdf(batch, ext)

    logger.info("All %s files converted successfully.", ext)


def convert_pptx_to_pdf(folder: str) -> None:
    for ext in CONVERT_URLS:
        convert_files_to_pdf(folder, ext)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Convert PPTX/DOCX to PDF using online2pdf.com")
    parser.add_argument("--folder", "--f", dest="folder", required=True, help="Root folder path")
    args = parser.parse_args()

    if not os.path.isdir(args.folder):
        logger.error("Directory not found: %s", args.folder)
        raise SystemExit(1)

    convert_pptx_to_pdf(args.folder)
