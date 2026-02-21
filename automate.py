import os
import re

downloaded_urls = set()

def sanitize(name: str):
    return re.sub(r"[^\w\- ]", "", name).strip()

# 1. LOGIN
def login(page, username, password):
    page.goto("https://www.pesuacademy.com/Academy/")
    page.fill("#j_scriptusername", username)
    page.fill("input[name='j_password']", password)
    page.click("button.btn.btn-lg.btn-primary.btn-block")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    
    # Check for login error message
    error_div = page.locator("div.login-msg")
    if error_div.is_visible():
        error_text = error_div.inner_text().strip()
        raise ValueError(f"Login failed: {error_text}")
    
    print("Logged in successfully.")
    return True

# 2. SELECT COURSE
def select_course(page):
    page.wait_for_selector("span.menu-name:has-text('My Courses')", timeout=15000)
    page.click("span.menu-name:has-text('My Courses')")
    page.wait_for_selector("table.table.table-hover", timeout=15000)
    no_content = page.locator("h2:text('No subjects found')")

    rows = page.locator("table.table.table-hover tbody tr")
    count = rows.count()

    courses = []
    if no_content.is_visible():
        print("No courses found in this semester.")
    else:
        for i in range(count):
            title = rows.nth(i).locator("td:nth-child(2)").inner_text().strip()
            courses.append(title)

    print("\nAvailable Courses:")
    for index, course in enumerate(courses, 1):
        print(f"{index}. {course}")

    choice = int(input("\nEnter course number to open: "))
    selected_row = rows.nth(choice - 1)
    selected_row.click()

    course_name = sanitize(courses[choice - 1])
    print(f"Opening: {course_name}")

    return course_name

# 3. SELECT UNIT
def select_unit(page):
    page.wait_for_selector("#courselistunit li", timeout=15000)

    units = page.locator("#courselistunit li a")
    unit_count = units.count()

    names = []
    for i in range(unit_count):
        names.append(units.nth(i).inner_text().strip())

    print("\nAvailable Units:")
    for index, name in enumerate(names, 1):
        print(f"{index}. {name}")

    choice = int(input("\nEnter unit number to open: "))
    selected_unit = units.nth(choice - 1)

    unit_name = sanitize(names[choice - 1])
    selected_unit.click()

    print(f"Opening {unit_name}...")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)

    return unit_name

# 4. CLICK FIRST SLIDE
def open_first_slide(page):
    page.wait_for_selector("span.pesu-icon-presentation-graphs", timeout=15000)
    page.locator("a:has(span.pesu-icon-presentation-graphs)").first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    print("Clicked first slide entry.")

# 5. DOWNLOAD CONTENT
def download_slides(page, course_name, unit_name, downloaded_urls, category="Slide"):
    page.wait_for_timeout(800)
    
    if not page.locator(".link-preview").count():
        return

    slide_items = page.locator(".link-preview")
    slide_count = slide_items.count()
    print(f"\nFound {slide_count} {category} files.")

    folder = f"{course_name} {unit_name}"
    os.makedirs(folder, exist_ok=True)

    existing = []
    for f in os.listdir(folder):
        if f.startswith(category):
            match = re.search(r'\d+', f)
            if match:
                existing.append(int(match.group()))
    
    next_number = max(existing) + 1 if existing else 101

    for i in range(slide_count):
        item = slide_items.nth(i)

        link = item.locator("a")
        onclick = link.get_attribute("onclick") if link.count() else None
        urls = []
        is_case2 = False

        if onclick:
            urls = re.findall(r"loadIframe\('([^']+)", onclick)

        if not urls:
            onclick_div = item.get_attribute("onclick")
            if onclick_div:
                matches = re.findall(r"downloadcoursedoc\('([^']+)'", onclick_div)
                if matches:
                    urls = [f"/Academy/a/referenceMeterials/downloadslidecoursedoc/{m}" for m in matches]
                    is_case2 = True

        if not urls:
            print(f"Could not extract URL for {category}.")
            continue

        for url in urls:
            file_url = "https://www.pesuacademy.com" + url
            file_url = file_url.split("#")[0]

            if file_url in downloaded_urls:
                print(f"Skipping already downloaded: {file_url}")
                continue

            print(f"\nDownloading: {file_url}")
            response = page.request.get(file_url)
            if response.status != 200:
                print(f"Failed ({response.status})")
                continue

            ext = ".pptx" if is_case2 and category == "Slide" else ".pdf"
            filename = f"{category}_{next_number}{ext}"
            filepath = os.path.join(folder, filename)
            
            with open(filepath, "wb") as f:
                f.write(response.body())

            print(f"Saved → {filepath}")
            downloaded_urls.add(file_url)
            next_number += 1
            page.wait_for_timeout(300)

# 6. PAGE NAVIGATION
def navigate_through_pages(page, course_name, unit_name, downloaded_urls):
    target_tabs = [
        ("#contentType_1", "Note"),
        ("#contentType_2", "Slide"),
        ("#contentType_5", "QB")
    ]

    while True:
        page.wait_for_selector(".coursecontent-navigation-area a.pull-right", timeout=15000)
        next_button = page.locator(".coursecontent-navigation-area a.pull-right")
        label = next_button.inner_text().strip()
        print(f"\nCurrent button: {label}")

        for tab_id, category in target_tabs:
            tab_element = page.locator(tab_id)
            if tab_element.is_visible():
                tab_element.click()
                page.wait_for_timeout(600)
                download_slides(page, course_name, unit_name, downloaded_urls, category)

        if "Back to Units" in label:
            print("Reached 'Back to Units'. Stopping navigation.")
            break

        next_button.click()
        print("Clicked next… waiting for next page load")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(800)

    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)