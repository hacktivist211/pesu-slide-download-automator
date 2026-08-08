"""
main.py – Entry point for the PESU Academy Automator.

Supports:
  - Single unit download
  - Multiple units (same course)
  - Multiple courses × multiple units
  - Resume from checkpoint after failure
  - CLI flags to skip interactive prompts
"""

import argparse
import getpass
import json
import logging
import os
import sys

from playwright.sync_api import sync_playwright, TimeoutError

from automate import (
    login,
    get_all_courses,
    get_all_units,
    get_available_semesters,
    select_semester,
    navigate_through_pages,
    open_first_slide,
    sanitize,
)
from config import Config
from debugging import enable_debug
from file_conversion import convert_pptx_to_pdf
from merge import ask_and_merge_pdfs

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------

CHECKPOINT_FILE = ".pesu_checkpoint.json"


def load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_checkpoint(data: dict) -> None:
    try:
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning("Could not save checkpoint: %s", e)


def clear_checkpoint() -> None:
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def get_credentials(args) -> tuple[str, str]:
    ENV_FILE = Config.get_env_file()

    # CLI flags override everything
    if args.username and args.password:
        return args.username, args.password

    Config.load_env()
    username = Config.get_username()
    password = Config.get_password()
    dont_ask = Config.get_dont_ask_again()

    if dont_ask and (not username or username == "NOT_SET" or not password or password == "NOT_SET"):
        username = input("Enter Username (SRN / PRN): ")
        password = getpass.getpass("Enter PESU Password: ")
    elif not dont_ask:
        if not username or username == "NOT_SET":
            username = input("Enter Username (SRN / PRN): ")
        if not password or password == "NOT_SET":
            password = getpass.getpass("Enter PESU Password: ")

    if not os.path.exists(ENV_FILE):
        choice = input(
            "\nSave credentials locally?\n1. Yes\n2. No\n3. Don't ask again\nSelect Option: "
        ).strip()
        if choice == "1":
            Config.set_credentials(username, password)
        elif choice == "3":
            Config.clear_credentials()
            Config.set_dont_ask_again(True)

    return username, password


# ---------------------------------------------------------------------------
# Download-option helpers
# ---------------------------------------------------------------------------

def get_download_options(args) -> tuple[bool, bool, bool]:
    """Return (fetch_videos, fetch_notes, fetch_qb) from CLI args or prompts."""
    if args.videos is not None and args.notes is not None and args.qb is not None:
        return args.videos, args.notes, args.qb

    fetch_videos = args.videos if args.videos is not None else (
        input("\nDownload AV Summaries (Videos)? (y/n): ").strip().lower() == "y"
    )
    fetch_notes = args.notes if args.notes is not None else (
        input("Download Notes? (y/n): ").strip().lower() == "y"
    )
    fetch_qb = args.qb if args.qb is not None else (
        input("Download Question Banks (QB)? (y/n): ").strip().lower() == "y"
    )
    return fetch_videos, fetch_notes, fetch_qb


# ---------------------------------------------------------------------------
# Selection helpers
# ---------------------------------------------------------------------------

def _pick_indices(prompt: str, items: list[str]) -> list[int]:
    """Print a numbered list and return 0-based indices from user input."""
    for i, name in enumerate(items, 1):
        print(f"  {i}. {name}")
    raw = input(prompt).strip()
    return [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]


def select_semester_interactive(page, args) -> str | None:
    """
    Returns the semester label the user picked, or None to leave the
    default (current) semester as-is.
    """
    semesters = get_available_semesters(page)
    if not semesters:
        return None

    if args.semester:
        if select_semester(page, args.semester):
            return args.semester
        logger.warning("Falling back to default semester.")
        return None

    print("\nAvailable Semesters:")
    for i, s in enumerate(semesters, 1):
        print(f"  {i}. {s}")
    choice = input("\nEnter semester number (Enter to keep current): ").strip()
    if not choice.isdigit():
        return None
    idx = int(choice) - 1
    if not (0 <= idx < len(semesters)):
        return None
    label = semesters[idx]
    select_semester(page, label)
    return label


def select_work_items(page, args) -> tuple[list[tuple[str, str]], str | None]:
    """
    Returns (work_items, semester_label).
    work_items is a list of (course_name, unit_name) pairs to process.
    Respects --multi CLI flag or prompts interactively.
    """
    semester_label = select_semester_interactive(page, args)

    # Determine mode
    if args.multi:
        mode = args.multi  # "single" | "multi_unit" | "multi_course"
    else:
        print("\nSelect download mode:")
        print("  1. Single unit")
        print("  2. Multiple units (same course)")
        print("  3. Multiple courses and units")
        choice = input("Select option: ").strip()
        mode = {"1": "single", "2": "multi_unit", "3": "multi_course"}.get(choice, "single")

    all_courses = get_all_courses(page)
    work_items: list[tuple[str, str]] = []

    if mode == "single":
        print("\nAvailable Courses:")
        c_indices = _pick_indices("\nEnter course number: ", all_courses)
        if not c_indices:
            logger.error("No course selected.")
            sys.exit(1)
        c_idx = c_indices[0]
        course_name = sanitize(all_courses[c_idx])

        # Click the course row to load units
        rows = page.locator("table.table.table-hover tbody tr")
        rows.nth(c_idx).click()
        page.wait_for_load_state("networkidle")

        all_units = get_all_units(page)
        print("\nAvailable Units:")
        u_indices = _pick_indices("\nEnter unit number: ", all_units)
        if not u_indices:
            logger.error("No unit selected.")
            sys.exit(1)
        unit_name = sanitize(all_units[u_indices[0]])
        work_items.append((course_name, unit_name))

    elif mode == "multi_unit":
        print("\nAvailable Courses:")
        c_indices = _pick_indices("\nEnter course number: ", all_courses)
        if not c_indices:
            logger.error("No course selected.")
            sys.exit(1)
        c_idx = c_indices[0]
        course_name = sanitize(all_courses[c_idx])

        rows = page.locator("table.table.table-hover tbody tr")
        rows.nth(c_idx).click()
        page.wait_for_load_state("networkidle")

        all_units = get_all_units(page)
        print("\nAvailable Units:")
        u_indices = _pick_indices("\nEnter unit numbers (comma-separated): ", all_units)
        for u_idx in u_indices:
            work_items.append((course_name, sanitize(all_units[u_idx])))

    elif mode == "multi_course":
        print("\nAvailable Courses:")
        c_indices = _pick_indices("\nEnter course numbers (comma-separated): ", all_courses)
        rows = page.locator("table.table.table-hover tbody tr")

        for c_idx in c_indices:
            course_name = sanitize(all_courses[c_idx])

            # Navigate to course to list units
            rows.nth(c_idx).click()
            page.wait_for_load_state("networkidle")

            all_units = get_all_units(page)
            print(f"\nUnits for '{course_name}':")
            u_indices = _pick_indices("  Enter unit numbers (comma-separated): ", all_units)
            for u_idx in u_indices:
                work_items.append((course_name, sanitize(all_units[u_idx])))

            # Go back to course list
            page.go_back()
            page.wait_for_load_state("networkidle")
            if semester_label:
                select_semester(page, semester_label)

    return work_items, semester_label


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="PESU Academy Automator")
    p.add_argument("--username", "-u", help="SRN / PRN")
    p.add_argument("--password", "-p", help="PESU password")
    p.add_argument("--videos", action=argparse.BooleanOptionalAction, default=None, help="Download AV Summaries")
    p.add_argument("--notes", action=argparse.BooleanOptionalAction, default=None, help="Download Notes")
    p.add_argument("--qb", action=argparse.BooleanOptionalAction, default=None, help="Download Question Banks")
    p.add_argument("--merge", action=argparse.BooleanOptionalAction, default=None, help="Merge PDFs after download")
    p.add_argument("--multi", choices=["single", "multi_unit", "multi_course"], default=None, help="Selection mode")
    p.add_argument("--debug", action="store_true", help="Enable debug logging and Playwright hooks")
    p.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    p.add_argument("--download-dir", dest="download_dir", help="Override download directory")
    p.add_argument("--semester", help="Semester label to select, e.g. 'Sem-4' (default: current)")
    return p


def main() -> None:
    args = build_arg_parser().parse_args()
    setup_logging(debug=args.debug or Config.is_debug_enabled())

    if args.download_dir:
        try:
            Config.set_download_dir(args.download_dir)
        except ValueError as e:
            logger.error("%s", e)
            sys.exit(1)

    base_dir = Config.get_download_dir()

    # Load checkpoint for resume
    checkpoint = load_checkpoint() if args.resume else {}
    downloaded_urls: set[str] = set(checkpoint.get("downloaded_urls", []))

    username, password = get_credentials(args)
    fetch_videos, fetch_notes, fetch_qb = get_download_options(args)

    work_items: list[tuple[str, str]] = []  # populated inside playwright context
    semester_label: str | None = None

    while True:  # outer loop for "Did you miss anything?"
        completed_folders: list[tuple[str, str, str]] = []  # (course, unit, folder)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                context = browser.new_context()
                page = context.new_page()

                if args.debug or Config.is_debug_enabled():
                    enable_debug(page)

                login(page, username, password)

                if not work_items:
                    work_items, semester_label = select_work_items(page, args)

                topic_checkpoint: dict = checkpoint.get("topics", {})

                for course_name, unit_name in work_items:
                    pair_key = f"{course_name}|{unit_name}"
                    if checkpoint.get("completed", {}).get(pair_key):
                        logger.info("Skipping already-completed unit: %s / %s", course_name, unit_name)
                        continue

                    logger.info("=== Processing: %s / %s ===", course_name, unit_name)

                    # Navigate to the correct course & unit
                    _navigate_to_unit(page, course_name, unit_name, semester_label)

                    open_first_slide(page)
                    navigate_through_pages(
                        page, course_name, unit_name,
                        downloaded_urls,
                        fetch_videos, fetch_notes, fetch_qb,
                        base_dir=base_dir,
                        checkpoint=topic_checkpoint,
                    )

                    folder = os.path.join(base_dir, f"{course_name} {unit_name}")
                    completed_folders.append((course_name, unit_name, folder))

                    checkpoint["topics"] = topic_checkpoint
                    checkpoint["downloaded_urls"] = list(downloaded_urls)
                    save_checkpoint(checkpoint)

                browser.close()

        except TimeoutError:
            logger.error("Unstable internet connection. Try again later.")
            checkpoint["downloaded_urls"] = list(downloaded_urls)
            save_checkpoint(checkpoint)
        except KeyboardInterrupt:
            logger.info("Interrupted by user.")
            checkpoint["downloaded_urls"] = list(downloaded_urls)
            save_checkpoint(checkpoint)
        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)
            checkpoint["downloaded_urls"] = list(downloaded_urls)
            save_checkpoint(checkpoint)
        finally:
            try:
                browser.close()  # noqa: F821 – may already be closed
            except Exception:
                pass

        # Run conversion and merge AFTER the Playwright browser is fully closed
        for course_name, unit_name, folder in completed_folders:
            pair_key = f"{course_name}|{unit_name}"
            if checkpoint.get("completed", {}).get(pair_key):
                continue
            logger.info("=== Converting & merging: %s / %s ===", course_name, unit_name)
            convert_pptx_to_pdf(folder)
            ask_and_merge_pdfs(folder, skip_prompt=args.merge)

            if "completed" not in checkpoint:
                checkpoint["completed"] = {}
            checkpoint["completed"][pair_key] = True
            save_checkpoint(checkpoint)

        # "Did you miss anything?" prompt
        print("\n" + "=" * 50)
        print("Did you miss anything?")
        print("  1. Yes – select more units/courses")
        print("  2. No  – exit")
        again = input("Select option: ").strip()
        if again == "1":
            work_items = []  # will re-prompt inside playwright
        else:
            break

    clear_checkpoint()
    logger.info("All done.")


def _navigate_to_unit(page, course_name: str, unit_name: str, semester_label: str | None = None) -> None:
    """
    Navigate to the My Courses page, click the matching course row, then the matching unit.
    This allows multi-course/unit looping without restarting the browser.
    Re-selects `semester_label` after landing on My Courses, since that page
    resets to the default (current) semester on every fresh navigation.
    """
    from playwright.sync_api import TimeoutError as PwTimeout

    # Go back to course list
    try:
        page.wait_for_selector("span.menu-name:has-text('My Courses')", timeout=10000)
        page.click("span.menu-name:has-text('My Courses')")
        page.wait_for_selector("table.table.table-hover", timeout=15000)
        if semester_label:
            select_semester(page, semester_label)
    except PwTimeout:
        pass  # already on courses page

    # Click matching course row
    rows = page.locator("table.table.table-hover tbody tr")
    count = rows.count()
    clicked_course = False
    for i in range(count):
        title = sanitize(rows.nth(i).locator("td:nth-child(2)").inner_text().strip())
        if title == course_name:
            rows.nth(i).click()
            page.wait_for_load_state("networkidle")
            clicked_course = True
            break

    if not clicked_course:
        logger.warning("Course '%s' not found in course list.", course_name)
        return

    # Wait for unit list to actually render before reading it
    try:
        page.wait_for_selector("#courselistunit li a", timeout=15000)
    except PwTimeout:
        logger.warning("Unit list did not appear for course '%s'.", course_name)
        return

    units = page.locator("#courselistunit li a")
    unit_count = units.count()
    for i in range(unit_count):
        raw = units.nth(i).inner_text().strip()
        if sanitize(raw) == unit_name:
            units.nth(i).click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(800)
            return

    logger.warning("Unit '%s' not found in course '%s'.", unit_name, course_name)


if __name__ == "__main__":
    main()
