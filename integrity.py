import logging
import os
import shutil
import subprocess
import zipfile

logger = logging.getLogger(__name__)


def check_pdf(path: str) -> bool:
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader
    try:
        reader = PdfReader(path)
        if len(reader.pages) == 0:
            return False
        reader.pages[0].extract_text()
        return True
    except Exception as e:
        logger.error("PDF integrity check failed for %s: %s", path, e)
        return False


def check_office_zip(path: str) -> bool:
    if not zipfile.is_zipfile(path):
        logger.error("Not a valid zip container: %s", path)
        return False
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad is not None:
                logger.error("Corrupt member '%s' in %s", bad, path)
                return False
            names = zf.namelist()
            if "[Content_Types].xml" not in names:
                logger.error("Missing [Content_Types].xml, not a valid Office file: %s", path)
                return False
        return True
    except zipfile.BadZipFile as e:
        logger.error("Bad zip %s: %s", path, e)
        return False
    except Exception as e:
        logger.error("Integrity check failed for %s: %s", path, e)
        return False


def _ffprobe_available() -> bool:
    try:
        result = subprocess.run(["ffprobe", "-version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def check_video(path: str) -> bool:
    if not _ffprobe_available():
        logger.warning("ffprobe not available, skipping video integrity check: %s", path)
        return True
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            logger.error("ffprobe rejected file %s: %s", path, result.stderr.strip())
            return False
        duration = float(result.stdout.strip())
        return duration > 0
    except Exception as e:
        logger.error("Video integrity check failed for %s: %s", path, e)
        return False


EXT_CHECKS = {
    ".pdf": check_pdf,
    ".pptx": check_office_zip,
    ".docx": check_office_zip,
    ".mp4": check_video,
}


def verify_file(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    check = EXT_CHECKS.get(ext)
    if check is None:
        return True
    return check(path)


def quarantine(path: str, reason: str) -> str:
    folder = os.path.dirname(path)
    qdir = os.path.join(folder, "_corrupted")
    os.makedirs(qdir, exist_ok=True)
    dest = os.path.join(qdir, os.path.basename(path))
    counter = 1
    base, ext = os.path.splitext(dest)
    while os.path.exists(dest):
        dest = f"{base}_{counter}{ext}"
        counter += 1
    shutil.move(path, dest)
    logfile = os.path.join(qdir, "_quarantine_log.txt")
    with open(logfile, "a", encoding="utf-8") as f:
        f.write(f"{os.path.basename(dest)}\t{reason}\n")
    logger.error("Quarantined: %s (%s)", os.path.basename(dest), reason)
    return dest
