import os
import re
import subprocess

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

def _yt_dlp_available():
    try:
        result = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False

def _aria2c_available():
    try:
        result = subprocess.run(["aria2c", "--version"], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False

def _download_with_ytdlp(url, output_path, extra_args=None):
    if _aria2c_available():
        cmd = [
            "yt-dlp",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "--format-sort", "res,fps,vbr,abr",
            "-o", output_path,
            "--no-playlist",
            "--downloader", "aria2c",
            "--downloader-args", "aria2c:-x16 -s16 -k5M --min-split-size=5M",
        ]
    else:
        cmd = [
            "yt-dlp",
            "-f", "bestvideo[proto=dash][ext=mp4]+bestaudio[proto=dash][ext=m4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "--format-sort", "res,fps,vbr,abr",
            "-o", output_path,
            "--no-playlist",
            "--concurrent-fragments", "16",
            "--buffer-size", "16K",
        ]
    if extra_args:
        cmd += extra_args
    cmd.append(url)
    try:
        result = subprocess.run(cmd, timeout=600)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print("yt-dlp timed out.")
        return False
    except Exception as e:
        print(f"yt-dlp error: {e}")
        return False

def intercept_and_download_vimeo(page, vimeo_id, output_path):
    captured = {"url": None}

    def handle_response(response):
        url = response.url
        if captured["url"]:
            return
        if ("vimeocdn" in url or "vimeo.com" in url) and vimeo_id in url:
            if ".m3u8" in url:
                captured["url"] = url
            elif ".mp4" in url:
                captured["url"] = url

    page.on("response", handle_response)

    player_url = f"https://player.vimeo.com/video/{vimeo_id}?autoplay=1&muted=1"
    try:
        page.evaluate(f"""
            (() => {{
                const old = document.getElementById('_vimeo_intercept_frame');
                if (old) old.remove();
                const iframe = document.createElement('iframe');
                iframe.id = '_vimeo_intercept_frame';
                iframe.src = '{player_url}';
                iframe.allow = 'autoplay';
                iframe.style.cssText = 'width:1px;height:1px;position:absolute;opacity:0;';
                document.body.appendChild(iframe);
            }})()
        """)
        page.wait_for_timeout(6000)
    except Exception as e:
        print(f"Intercept iframe inject error: {e}")

    page.remove_listener("response", handle_response)

    page.evaluate("(() => { const f = document.getElementById('_vimeo_intercept_frame'); if(f) f.remove(); })()")

    if not captured["url"]:
        return False

    print(f"Intercepted stream URL, downloading via yt-dlp...")
    referer = f"https://player.vimeo.com/video/{vimeo_id}"
    return _download_with_ytdlp(
        captured["url"],
        output_path,
        extra_args=["--add-header", f"Referer:{referer}"]
    )

def download_av_summaries(page, course_name, unit_name, downloaded_urls, topic=None):
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

    # Count existing files to determine the next global sequence number for this folder
    existing_count = len([f for f in os.listdir(folder) if f.lower().endswith(".mp4")])
    # topic_counter tracks how many videos have been saved for the current topic (for _2, _3 suffixes)
    topic_counter = existing_count + 1

    ytdlp_ok = _yt_dlp_available()
    if not ytdlp_ok:
        print("WARNING: yt-dlp not found. Install with: pip install yt-dlp")
        print("All Vimeo videos will be skipped.")

    def _make_av_filename(topic_name, counter, total_on_page):
        """Build a filename: TopicName.mp4 if only 1 video, else TopicName_2.mp4, TopicName_3.mp4 …"""
        safe_topic = sanitize(topic_name) if topic_name else f"AV_Summary"
        if total_on_page == 1:
            base = safe_topic
        else:
            # First video keeps bare topic name, subsequent ones get _2, _3, ...
            suffix = "" if counter == 1 else f"_{counter}"
            base = f"{safe_topic}{suffix}"
        # Ensure uniqueness in folder
        return get_unique_filename(folder, base, ".mp4")

    page_video_counter = 0  # how many videos downloaded on this page so far

    for vid_id in vimeo_ids:
        if vid_id in downloaded_urls:
            print(f"Already downloaded Vimeo {vid_id}, skipping.")
            continue
        if not ytdlp_ok:
            print(f"Skipping Vimeo {vid_id} (yt-dlp unavailable).")
            continue
        page_video_counter += 1
        print(f"\nDownloading Vimeo {vid_id}...")
        filename = _make_av_filename(topic, page_video_counter, total)
        filepath = os.path.join(folder, filename)

        vimeo_url = f"https://vimeo.com/{vid_id}"
        success = _download_with_ytdlp(vimeo_url, filepath)

        if not success:
            print(f"Direct Vimeo URL failed (domain-locked). Trying page intercept...")
            success = intercept_and_download_vimeo(page, vid_id, filepath)

        if success and os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            print(f"Saved -> {filepath}")
            downloaded_urls.add(vid_id)
        else:
            print(f"Could not download Vimeo {vid_id}.")
            if os.path.exists(filepath):
                os.remove(filepath)
            page_video_counter -= 1  # don't count failed downloads

    for url in direct_mp4_urls:
        if url in downloaded_urls:
            continue
        page_video_counter += 1
        print(f"\nDownloading: {url}")
        try:
            resp = page.request.get(url)
            if resp.status != 200:
                print(f"Failed ({resp.status})")
                page_video_counter -= 1
                continue
            filename = _make_av_filename(topic, page_video_counter, total)
            filepath = os.path.join(folder, filename)
            with open(filepath, "wb") as f:
                f.write(resp.body())
            print(f"Saved -> {filepath}")
            downloaded_urls.add(url)
        except Exception as e:
            print(f"Error downloading {url}: {e}")
            page_video_counter -= 1

def get_page_topic(page):
    selectors = [
        ".coursecontent-header h3",
        ".coursecontent-header h4",
        ".coursecontent-header h2",
        ".coursecontent-header h1",
        ".coursecontent-body h3",
        ".coursecontent-body h4",
        ".coursecontent-body h2",
        "#coursecontentarea h3",
        "#coursecontentarea h4",
        "#coursecontentarea h2",
        ".slide-title",
        ".content-title",
    ]
    blacklist = {"profile", "back to units", "my courses", "home", "logout", "settings"}
    for sel in selectors:
        try:
            els = page.locator(sel)
            for j in range(els.count()):
                el = els.nth(j)
                if not el.is_visible():
                    continue
                text = el.inner_text().strip()
                if not text or len(text) < 3:
                    continue
                if text.lower() in blacklist:
                    continue
                if any(b in text.lower() for b in blacklist):
                    continue
                return sanitize(text)
        except Exception:
            continue

    try:
        title_tag = page.title()
        if title_tag and len(title_tag) > 2:
            parts = re.split(r"[|\-]", title_tag)
            for part in parts:
                candidate = sanitize(part.strip())
                if not candidate or len(candidate) < 3:
                    continue
                low = candidate.lower()
                if any(b in low for b in ("pesu", "academy", "profile", "login")):
                    continue
                return candidate
    except Exception:
        pass

    return ""

def get_unique_filename(folder, base_name, ext):
    candidate = f"{base_name}{ext}"
    counter = 1
    while os.path.exists(os.path.join(folder, candidate)):
        candidate = f"{base_name}[{counter}]{ext}"
        counter += 1
    return candidate

def _extract_direct_pdf_url(iframe_url):
    import urllib.parse
    patterns = [
        r"[?&]file=([^&]+)",
        r"[?&]url=([^&]+)",
        r"[?&]src=([^&]+)",
        r"/viewerng/viewer\?file=([^&]+)",
        r"viewer\.html\?file=([^&]+)",
    ]
    for pat in patterns:
        m = re.search(pat, iframe_url)
        if m:
            candidate = m.group(1)
            candidate = urllib.parse.unquote(candidate)
            if candidate.startswith("http"):
                return candidate
            if candidate.startswith("/"):
                return "https://www.pesuacademy.com" + candidate
    return None

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
    next_number = max(existing) + 1 if existing else 1

    topic = topic_override
    if topic:
        topic = sanitize(topic)
        if "Back to Units" in topic:
            topic = None

    for i in range(count):
        item = items.nth(i)
        onclick = item.get_attribute("onclick")
        urls = []

        if onclick and "loadIframe" in onclick:
            raw_urls = re.findall(r"loadIframe\('([^']+)", onclick)
            for raw in raw_urls:
                iframe_url = raw if raw.startswith("http") else "https://www.pesuacademy.com" + raw
                direct = _extract_direct_pdf_url(iframe_url)
                if direct:
                    urls.append(direct)
                else:
                    urls.append(iframe_url)

        elif onclick and "downloadcoursedoc" in onclick:
            matches = re.findall(r"downloadcoursedoc\('([^']+)'", onclick)
            if matches:
                urls = [f"https://www.pesuacademy.com/Academy/a/referenceMeterials/downloadslidecoursedoc/{m}" for m in matches]

        if not urls:
            continue

        for file_url in urls:
            file_url = file_url.split("#")[0]
            if file_url in downloaded_urls:
                continue
            print(f"\nDownloading: {file_url}")
            response = page.request.get(file_url)
            if response.status != 200:
                print(f"Failed ({response.status})")
                continue

            content_type = response.headers.get("content-type", "").lower()
            body = response.body()

            if b"%PDF" not in body[:10] and "pdf" not in content_type and b"PK" not in body[:4] and "zip" not in content_type and "officedocument" not in content_type:
                text = body.decode("utf-8", errors="ignore")
                pdf_link_match = re.search(r'(https?://[^\s"\']+\.pdf[^\s"\']*)', text)
                if pdf_link_match:
                    fallback_url = pdf_link_match.group(1)
                    print(f"Response was HTML; found PDF link: {fallback_url}")
                    resp2 = page.request.get(fallback_url)
                    if resp2.status == 200:
                        body = resp2.body()
                        content_type = resp2.headers.get("content-type", "").lower()
                    else:
                        print(f"Fallback PDF fetch failed ({resp2.status}), skipping.")
                        continue
                else:
                    print(f"Response is not a valid document (content-type: {content_type}). Skipping.")
                    continue

            if b"PK" in body[:4] or "officedocument.presentationml" in content_type or "powerpoint" in content_type:
                ext = ".pptx"
            elif "officedocument.wordprocessingml" in content_type:
                ext = ".docx"
            else:
                ext = ".pdf"

            if category == "Slide":
                safe_topic = sanitize(topic) if topic else "Unknown"
                base_name = f"Slide_{next_number:03d}_{safe_topic}"
            elif category == "QB" and topic:
                base_name = f"QB_{next_number:03d}_{sanitize(topic)}"
            elif category == "Note" and topic:
                base_name = f"Note_{next_number:03d}_{sanitize(topic)}"
            else:
                base_name = f"{category}_{next_number:03d}"

            filename = get_unique_filename(folder, base_name, ext)
            filepath = os.path.join(folder, filename)
            with open(filepath, "wb") as f:
                f.write(body)
            print(f"Saved -> {filepath}")
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

        topic = get_page_topic(page)

        if not topic:
            url_slug = current_url.rstrip("/").split("/")[-1]
            url_slug = re.sub(r"%20|[_\-]+", " ", url_slug)
            candidate = sanitize(url_slug).strip()
            if candidate and "Back to Units" not in candidate and len(candidate) > 2:
                topic = candidate

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
                download_av_summaries(page, course_name, unit_name, downloaded_urls, topic=topic)

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
