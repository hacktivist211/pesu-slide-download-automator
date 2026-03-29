from playwright.sync_api import sync_playwright, TimeoutError
from dotenv import load_dotenv
import os
import getpass
from automate import (login, navigate_through_pages,
    open_first_slide, select_course, select_unit)
from file_conversion import convert_pptx_to_pdf
from merge import ask_and_merge_pdfs

ENV_FILE = ".env"

downloaded_urls = set()

def main():
    if os.path.exists(ENV_FILE):
        load_dotenv(ENV_FILE)
        dont_ask_again = os.getenv("DONT_ASK_AGAIN", "0")
        username = os.getenv("USERNAME")
        password = os.getenv("PASSWORD")
        if dont_ask_again == "1" and (username == "NOT_SET" or password == "NOT_SET"):
            username = input("Enter Username (SRN / PRN): ")
            password = getpass.getpass("Enter Pesu Password: ")
        elif dont_ask_again != "1":
            username = username or input("Enter Username (SRN / PRN): ")
            password = password or getpass.getpass("Enter Pesu Password: ")
    else:
        username = input("Enter Username (SRN / PRN): ")
        password = getpass.getpass("Enter Pesu Password: ")
        choice = input(
            "\nSave credentials locally?\n1. Yes\n2. No\n3. Don't ask again\n"
            "Select Option: "
        ).strip().lower()
        if choice == "1":
            with open(ENV_FILE, "w") as f:
                f.write("USERNAME={}\nPASSWORD={}\nDONT_ASK_AGAIN=0\n".format(username, password))
        elif choice == "3":
            with open(ENV_FILE, "w") as f:
                f.write("USERNAME=NOT_SET\nPASSWORD=NOT_SET\nDONT_ASK_AGAIN=1\n")

    vid_choice = input("\nDownload AV Summaries (Videos)? (y/n): ").strip().lower()
    fetch_videos = vid_choice == "y"

    notes_choice = input("Download Notes? (y/n): ").strip().lower()
    fetch_notes = notes_choice == "y"

    qb_choice = input("Download Question Banks (QB)? (y/n): ").strip().lower()
    fetch_qb = qb_choice == "y"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            login(page, username, password)
            course_name = select_course(page)
            unit_name = select_unit(page)
            open_first_slide(page)
            navigate_through_pages(page, course_name, unit_name, downloaded_urls, fetch_videos, fetch_notes, fetch_qb)
            folder = "{} {}".format(course_name, unit_name)
        convert_pptx_to_pdf(folder)
        ask_and_merge_pdfs(folder)
    except TimeoutError:
        print("\nUnstable internet connection. Try again later.")
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as exc:
        print("\nAn unexpected error occurred: {}".format(exc))
    finally:
        try:
            browser.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
