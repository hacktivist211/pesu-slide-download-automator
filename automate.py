import os
import re
import json

ENV_FILE = ".env"
downloaded_urls = set()

def sanitize(name: str):
    return re.sub(r"[^\w\- ]", "", name).strip()

def login(page, username, password):
    page.goto("https://www.pesuacademy.com/Academy/")
    page.fill("#j_scriptusername", username)
    page.fill("input[name='j_password']", password)
    page.click("button.btn.btn-lg.btn-primary.btn-block")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    print("Logged in successfully.")

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

def open_first_slide(page):
    page.wait_for_selector("span.pesu-icon-presentation-graphs", timeout=15000)
    page.locator("a:has(span.pesu-icon-presentation-graphs)").first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    print("Clicked first slide entry.")

def get_vimeo_direct_url(page, vimeo_id):
    player_url = f"https://player.vimeo.com/video/{vimeo_id}"
    try:
        resp = page.request.get(player_url)
        if resp.status != 200:
            print(f"Failed to fetch Vimeo player page: Status {resp.status}")
            return None
        
        html_text = resp.text()
        
        # Extract the JSON config embedded in the page script
        # The config usually looks like: var config = {"request":{...}}; or similar
        match = re.search(r'var\s+config\s*=\s*(\{.*?\});', html_text, re.DOTALL)
        if not match:
            # Try another pattern often used: window.playerConfig = ...
            match = re.search(r'window\.playerConfig\s*=\s*(\{.*?\});', html_text, re.DOTALL)
        
        if not match:
            print("Could not find config JSON in Vimeo response.")
            return None

        config_str = match.group(1)
        # The JSON is often massive, we need to parse it carefully.
        # Since regex might cut off early due to nested braces, a direct json.loads might fail.
        # But usually, the 'request' key is early or we can just regex for the url inside the string.
        
        # Safer approach: find the 'progressive' list inside the string or parse properly
        try:
            # Attempt to parse the JSON (it might be cut off, so we try...catch)
            # But actually, usually we can just regex the mp4 URLs directly from the text
            # Pattern: "url":"https://..."
            urls = re.findall(r'"url"\s*:\s*"(https://[^"]+\.mp4[^"]*)"', config_str)
            if urls:
                # Prioritize highest quality (usually largest file or highest dimensions in metadata, 
                # but simply picking the last one or one with '1080' or '720' is a heuristic)
                # Let's just return the first valid mp4 found, or try to find the highest res.
                # Without full metadata parsing, we look for resolution keywords.
                
                best_url = None
                for u in urls:
                    if "1080" in u: best_url = u; break
                    if "720" in u: best_url = u; break
                    if "540" in u: best_url = u; break
                
                return best_url or urls[0]
        except Exception:
            pass

        # Fallback to HLS if no MP4 found
        hls_match = re.search(r'"url"\s*:\s*"(https://[^"]+\.m3u8[^"]*)"', config_str)
        if hls_match:
            return hls_match.group(1)

        return None

    except Exception as e:
        print(f"Error parsing Vimeo response: {e}")
        return None

def download_av_summaries(page, course_name, unit_name, downloaded_urls):
    page.wait_for_timeout(800)
    av_tab = page.locator("text='AV Summary'").first
    if not av_tab.is_visible():
        return
    av_tab.click()
    page.wait_for_timeout(1500)

    vimeo_ids = []
    direct_mp4_urls = []

    iframe_elements = page.locator("iframe")
    iframe_count = iframe_elements.count()
    for i in range(iframe_count):
        src = iframe_elements.nth(i).get_attribute("src") or ""
        vimeo_match = re.search(r"vimeo\.com/video/(\d+)", src)
        if vimeo_match:
            vid_id = vimeo_match.group(1)
            if vid_id not in vimeo_ids:
                vimeo_ids.append(vid_id)
        elif ".mp4" in src:
            url = src if src.startswith("http") else "https://www.pesuacademy.com" + src
            if url not in downloaded_urls:
                direct_mp4_urls.append(url)

    video_elements = page.locator("video source, video[src]")
    for i in range(video_elements.count()):
        src = video_elements.nth(i).get_attribute("src") or ""
        if src and src not in downloaded_urls:
            url = src if src.startswith("http") else "https://www.pesuacademy.com" + src
            direct_mp4_urls.append(url)

    page_html = page.content()
    for vid_id in re.findall(r"vimeo\.com/video/(\d+)", page_html):
        if vid_id not in vimeo_ids:
            vimeo_ids.append(vid_id)

    if not vimeo_ids and not direct_mp4_urls:
        return

    total = len(vimeo_ids) + len(direct_mp4_urls)
    print(f"\nFound {total} AV Summary file(s).")

    folder = os.path.join(f"{course_name} {unit_name}", "AV_Summaries")
    os.makedirs(folder, exist_ok=True)

    existing = []
    for f in os.listdir(folder):
        match = re.search(r'\d+', f)
        if match:
            existing.append(int(match.group()))
    next_number = max(existing) + 1 if existing else 1

    for vid_id in vimeo_ids:
        print(f"\nResolving Vimeo video {vid_id}...")
        direct_url = get_vimeo_direct_url(page, vid_id)
        if not direct_url:
            print(f"Could not resolve direct URL for Vimeo {vid_id}, skipping.")
            continue
        if direct_url in downloaded_urls:
            print(f"Already downloaded, skipping.")
            continue
        print(f"Downloading: {direct_url}")
        try:
            resp = page.request.get(direct_url)
            if resp.status != 200:
                print(f"Failed ({resp.status})")
                continue
            filename = f"AV_{next_number}.mp4"
            filepath = os.path.join(folder, filename)
            with open(filepath, "wb") as f:
                f.write(resp.body())
            print(f"Saved → {filepath}")
            downloaded_urls.add(direct_url)
            downloaded_urls.add(vid_id)
            next_number += 1
        except Exception as e:
            print(f"Error downloading Vimeo {vid_id}: {e}")

    for url in direct_mp4_urls:
        if url in downloaded_urls:
            continue
        print(f"\nDownloading: {url}")
        try:
            resp = page.request.get(url)
            if resp.status != 200:
                print(f"Failed ({resp.status})")
                continue
            filename = f"AV_{next_number}.mp4"
            filepath = os.path.join(folder, filename)
            with open(filepath, "wb") as f:
                f.write(resp.body())
            print(f"Saved → {filepath}")
            downloaded_urls.add(url)
            next_number += 1
        except Exception as e:
            print(f"Error downloading {url}: {e}")

def get_page_topic(page):
    selectors = [
        ".coursecontent-header h3",
        ".coursecontent-header h4",
        ".coursecontent-header h2",
        ".slide-title",
        ".content-title",
        "h3.title",
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible():
                text = el.inner_text().strip()
                if text and "Back to Units" not in text:
                    return sanitize(text)
        except Exception:
            continue
    return ""

def get_unique_filename(folder, base_name, ext):
    candidate = f"{base_name}{ext}"
    counter = 1
    while os.path.exists(os.path.join(folder, candidate)):
        candidate = f"{base_name}[{counter}]{ext}"
        counter += 1
    return candidate

def download_content(page, course_name, unit_name, downloaded_urls, category="Slide", topic_override=None):
    page.wait_for_timeout(800)

    tab_map = {
        "Slide": "Slides",
        "QB": "QB",
        "Note": "Notes",
    }
    tab_label = tab_map.get(category, category)

    tab_element = page.locator(f"text='{tab_label}'").first
    if not tab_element.is_visible():
        return
    tab_element.click()
    page.wait_for_timeout(1000)

    items = page.locator("[onclick*='loadIframe'], [onclick*='downloadcoursedoc']")
    count = items.count()
    if count == 0:
        return

    print(f"\nFound {count} {category} file(s).")

    if category in ("QB", "Note"):
        subfolder_name = "QB" if category == "QB" else "Notes"
        folder = os.path.join(f"{course_name} {unit_name}", subfolder_name)
    else:
        folder = f"{course_name} {unit_name}"

    os.makedirs(folder, exist_ok=True)

    existing = []
    for f in os.listdir(folder):
        if f.startswith(category):
            match = re.search(r'\d+', f)
            if match:
                existing.append(int(match.group()))
    next_number = max(existing) + 1 if existing else 101

    topic = topic_override
    
    # Sanitation for topic to be used in filename
    if topic:
        topic = sanitize(topic)
        if "Back to Units" in topic:
            topic = None # Reset if invalid

    for i in range(count):
        item = items.nth(i)
        onclick = item.get_attribute("onclick")
        urls = []
        is_case2 = False
        if onclick and "loadIframe" in onclick:
            urls = re.findall(r"loadIframe\('([^']+)", onclick)
        elif onclick and "downloadcoursedoc" in onclick:
            matches = re.findall(r"downloadcoursedoc\('([^']+)'", onclick)
            if matches:
                urls = [f"/Academy/a/referenceMeterials/downloadslidecoursedoc/{m}" for m in matches]
                is_case2 = True
        if not urls:
            continue
        for url in urls:
            file_url = "https://www.pesuacademy.com" + url
            file_url = file_url.split("#")[0]
            if file_url in downloaded_urls:
                continue
            print(f"\nDownloading: {file_url}")
            response = page.request.get(file_url)
            if response.status != 200:
                print(f"Failed ({response.status})")
                continue
            if is_case2 and category == "Slide":
                ext = ".pptx"
            else:
                ext = ".pdf"
            
            if category == "Slide" and topic:
                base_name = f"Slide_{topic}" if count == 1 else f"Slide_{topic}_{next_number}"
            else:
                base_name = f"{category}_{next_number}"
            
            filename = get_unique_filename(folder, base_name, ext)
            filepath = os.path.join(folder, filename)
            with open(filepath, "wb") as f:
                f.write(response.body())
            print(f"Saved → {filepath}")
            downloaded_urls.add(file_url)
            next_number += 1
            page.wait_for_timeout(300)

def navigate_through_pages(page, course_name, unit_name, downloaded_urls, fetch_videos, fetch_notes, fetch_qb):
    last_url = None
    last_button_label = None
    stuck_count = 0
    MAX_STUCK = 3

    while True:
        page.wait_for_selector(".coursecontent-navigation-area a.pull-right", timeout=15000)
        next_button = page.locator(".coursecontent-navigation-area a.pull-right")
        label = next_button.inner_text().strip()
        current_url = page.url
        
        # Determine topic for file naming
        # Try to get topic from page header first
        topic = get_page_topic(page)
        
        # If header fails, use the navigation button text (cleaned) as it usually represents current topic
        # But we skip this if the label is 'Back to Units' as it's not a topic
        if not topic and "Back to Units" not in label:
             cleaned_label = label.replace("→", "").strip()
             topic = sanitize(cleaned_label)

        print(f"\nCurrent Page: {topic if topic else 'Unknown Topic'}")

        if current_url == last_url and label == last_button_label:
            stuck_count += 1
            print(f"Page did not change (stuck {stuck_count}/{MAX_STUCK})")
            if stuck_count >= MAX_STUCK:
                print("Navigation appears stuck. Stopping.")
                break
        else:
            stuck_count = 0
            last_url = current_url
            last_button_label = label

            if fetch_videos:
                download_av_summaries(page, course_name, unit_name, downloaded_urls)

            download_content(page, course_name, unit_name, downloaded_urls, "Slide", topic_override=topic)

            if fetch_notes:
                download_content(page, course_name, unit_name, downloaded_urls, "Note")

            if fetch_qb:
                download_content(page, course_name, unit_name, downloaded_urls, "QB")

        if "Back to Units" in label:
            print("Reached 'Back to Units'. Stopping navigation.")
            break

        next_button.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(800)

    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)