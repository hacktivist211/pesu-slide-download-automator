import os
import re
import subprocess
import logging
import time

from playwright.sync_api import Page

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize(name: str) -> str:
    cleaned = re.sub(r"[^\w\- ]", "", name)
    return re.sub(r"\s+", " ", cleaned).strip()


def get_unique_filename(folder: str, base_name: str, ext: str) -> str:
    candidate = f"{base_name}{ext}"
    counter = 1
    while os.path.exists(os.path.join(folder, candidate)):
        candidate = f"{base_name}_{counter}{ext}"
        counter += 1
    return candidate


# ---------------------------------------------------------------------------
# Login / Navigation
# ---------------------------------------------------------------------------

def login(page: Page, username: str, password: str) -> None:
    page.goto("https://www.pesuacademy.com/Academy/")
    page.fill("#j_scriptusername", username)
    page.fill("input[name='j_password']", password)
    page.click("button.btn.btn-lg.btn-primary.btn-block")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    logger.info("Logged in successfully.")


def get_all_courses(page: Page) -> list[str]:
    """Return list of course names without clicking anything."""
    page.wait_for_selector("span.menu-name:has-text('My Courses')", timeout=15000)
    page.click("span.menu-name:has-text('My Courses')")
    page.wait_for_selector("table.table.table-hover", timeout=15000)
    rows = page.locator("table.table.table-hover tbody tr")
    count = rows.count()
    courses = []
    for i in range(count):
        title = rows.nth(i).locator("td:nth-child(2)").inner_text().strip()
        courses.append(title)
    return courses


def select_course(page: Page) -> str:
    """Interactive single-course selection (legacy path)."""
    courses = get_all_courses(page)
    print("\nAvailable Courses:")
    for idx, course in enumerate(courses, 1):
        print(f"  {idx}. {course}")
    choice = int(input("\nEnter course number: "))
    rows = page.locator("table.table.table-hover tbody tr")
    rows.nth(choice - 1).click()
    course_name = sanitize(courses[choice - 1])
    logger.info("Opening course: %s", course_name)
    return course_name


def select_courses_multi(page: Page) -> list[str]:
    """Let user pick one or more courses (comma-separated)."""
    courses = get_all_courses(page)
    print("\nAvailable Courses:")
    for idx, c in enumerate(courses, 1):
        print(f"  {idx}. {c}")
    raw = input("\nEnter course numbers (comma-separated, e.g. 1,3): ").strip()
    indices = [int(x.strip()) - 1 for x in raw.split(",")]
    return [sanitize(courses[i]) for i in indices], indices


def get_all_units(page: Page) -> list[str]:
    page.wait_for_selector("#courselistunit li", timeout=15000)
    units = page.locator("#courselistunit li a")
    count = units.count()
    return [units.nth(i).inner_text().strip() for i in range(count)]


def select_unit(page: Page) -> str:
    """Interactive single-unit selection (legacy path)."""
    names = get_all_units(page)
    print("\nAvailable Units:")
    for idx, name in enumerate(names, 1):
        print(f"  {idx}. {name}")
    choice = int(input("\nEnter unit number: "))
    page.locator("#courselistunit li a").nth(choice - 1).click()
    unit_name = sanitize(names[choice - 1])
    logger.info("Opening unit: %s", unit_name)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    return unit_name


def select_units_multi(page: Page) -> list[str]:
    """Let user pick one or more units (comma-separated)."""
    names = get_all_units(page)
    print("\nAvailable Units:")
    for idx, name in enumerate(names, 1):
        print(f"  {idx}. {name}")
    raw = input("\nEnter unit numbers (comma-separated, e.g. 1,2): ").strip()
    indices = [int(x.strip()) - 1 for x in raw.split(",")]
    return [sanitize(names[i]) for i in indices], indices


def open_first_slide(page: Page) -> None:
    page.wait_for_selector("span.pesu-icon-presentation-graphs", timeout=15000)
    page.locator("a:has(span.pesu-icon-presentation-graphs)").first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    logger.debug("Clicked first slide entry.")


# ---------------------------------------------------------------------------
# yt-dlp video download (ffmpeg removed)
# ---------------------------------------------------------------------------

def _yt_dlp_available() -> bool:
    try:
        result = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def _aria2c_available() -> bool:
    try:
        result = subprocess.run(["aria2c", "--version"], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def _download_with_ytdlp(url: str, output_path: str, extra_args: list | None = None, retries: int = 3) -> bool:
    """Download via yt-dlp with automatic retries. Always outputs .mp4."""
    if _aria2c_available():
        base_cmd = [
            "yt-dlp",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "--format-sort", "+res,+fps,+vbr,+abr",
            "-o", output_path,
            "--no-playlist",
            "--downloader", "aria2c",
            "--downloader-args", "aria2c:-x16 -s16 -k5M --min-split-size=5M",
        ]
    else:
        base_cmd = [
            "yt-dlp",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "--format-sort", "+res,+fps,+vbr,+abr",
            "-o", output_path,
            "--no-playlist",
            "--concurrent-fragments", "16",
            "--buffer-size", "16K",
        ]
    if extra_args:
        base_cmd += extra_args
    base_cmd.append(url)

    for attempt in range(1, retries + 1):
        try:
            logger.debug("yt-dlp attempt %d/%d for %s", attempt, retries, url[:80])
            result = subprocess.run(base_cmd, timeout=900)
            if result.returncode == 0:
                return True
            logger.warning("yt-dlp exited with code %d (attempt %d)", result.returncode, attempt)
        except subprocess.TimeoutExpired:
            logger.warning("yt-dlp timed out (attempt %d)", attempt)
        except Exception as e:
            logger.error("yt-dlp error: %s", e)
        if attempt < retries:
            time.sleep(3)
    return False


def intercept_and_download_vimeo(page: Page, vimeo_id: str, output_path: str) -> bool:
    """Intercept Vimeo stream URLs and download exclusively via yt-dlp."""
    if not _yt_dlp_available():
        logger.error("yt-dlp is not available. Cannot download Vimeo video.")
        return False

    captured: dict[str, str | None] = {"m3u8": None, "mpd": None, "mp4": None}
    referer = f"https://player.vimeo.com/video/{vimeo_id}"
    origin = "https://player.vimeo.com"

    def handle_response(response):
        url = response.url
        if "vimeocdn" not in url and "vimeo.com" not in url:
            return
        if ".m3u8" in url and not captured["m3u8"]:
            if "/sep/" not in url and not re.search(r"seg-\d+", url):
                captured["m3u8"] = url
                logger.debug("Intercepted HLS: %s", url[:90])
        elif ".mpd" in url and not captured["mpd"]:
            captured["mpd"] = url
            logger.debug("Intercepted DASH: %s", url[:90])
        elif ".mp4" in url and not captured["mp4"] and "fragment" not in url:
            captured["mp4"] = url
            logger.debug("Intercepted MP4: %s", url[:90])

    page.on("response", handle_response)
    player_url = f"https://player.vimeo.com/video/{vimeo_id}?autoplay=1&muted=1&quality=1080p"
    try:
        page.evaluate(f"""
            (() => {{
                const old = document.getElementById('_vimeo_intercept_frame');
                if (old) old.remove();
                const iframe = document.createElement('iframe');
                iframe.id = '_vimeo_intercept_frame';
                iframe.src = '{player_url}';
                iframe.allow = 'autoplay; fullscreen';
                iframe.style.cssText = 'width:640px;height:360px;position:absolute;left:-9999px;top:0;';
                document.body.appendChild(iframe);
            }})()
        """)
        for _ in range(30):
            if captured["m3u8"] or captured["mpd"] or captured["mp4"]:
                break
            page.wait_for_timeout(500)
    except Exception as e:
        logger.error("Intercept iframe error: %s", e)

    page.remove_listener("response", handle_response)
    page.evaluate("(() => { const f = document.getElementById('_vimeo_intercept_frame'); if(f) f.remove(); })()")

    stream_url = captured["m3u8"] or captured["mpd"] or captured["mp4"]

    # If no stream intercepted, fall back to yt-dlp on the Vimeo page URL directly
    if not stream_url:
        logger.warning("No stream intercepted for Vimeo %s; trying yt-dlp direct URL.", vimeo_id)
        stream_url = f"https://vimeo.com/{vimeo_id}"

    extra_args = [
        "--add-header", f"Referer:{referer}",
        "--add-header", f"Origin:{origin}",
    ]
    logger.info("Downloading Vimeo %s via yt-dlp...", vimeo_id)
    return _download_with_ytdlp(stream_url, output_path, extra_args=extra_args, retries=3)


# ---------------------------------------------------------------------------
# Topic extraction
# ---------------------------------------------------------------------------

_BLACKLIST_WORDS = {
    "profile", "back to units", "my courses", "mycourses", "home",
    "logout", "settings", "pesu", "academy", "login",
    "slides", "notes", "question bank", "qb", "av summary",
    "live videos", "class", "content",
}


def _is_blacklisted(text: str) -> bool:
    low = text.lower().strip()
    return low in _BLACKLIST_WORDS or any(b in low for b in _BLACKLIST_WORDS)


def get_page_topic(page: Page) -> str:
    """
    Priority:
    1. Sidebar active item (most reliable for PESU)
    2. Breadcrumb / navigation path
    3. Page header (h1/h2/h3)
    """
    # 1. Sidebar active item
    for sel in ["#courselistunit li.active a", "#courselistunit li.active", ".topic-list li.active a"]:
        try:
            el = page.locator(sel).first
            if el.count() > 0:
                text = el.inner_text().strip()
                if text and len(text) >= 3 and not _is_blacklisted(text):
                    return sanitize(text)
        except Exception:
            continue

    # 2. Breadcrumb
    for sel in [".breadcrumb li:last-child", ".breadcrumb li.active", "nav[aria-label='breadcrumb'] li:last-child"]:
        try:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible():
                text = el.inner_text().strip()
                if text and len(text) >= 3 and not _is_blacklisted(text):
                    return sanitize(text)
        except Exception:
            continue

    # 3. Headers
    for sel in [
        ".coursecontent-header h3", ".coursecontent-header h2",
        "#coursecontentarea h3", "#coursecontentarea h2",
        "h1", "h2", "h3", ".page-header", ".panel-title", "#heading",
    ]:
        try:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible():
                text = el.inner_text().strip()
                if text and len(text) >= 3 and not _is_blacklisted(text):
                    return sanitize(text)
        except Exception:
            continue

    return ""


# ---------------------------------------------------------------------------
# AV Summary download
# ---------------------------------------------------------------------------

def download_av_summaries(
    page: Page,
    course_name: str,
    unit_name: str,
    downloaded_urls: set,
    topic: str | None = None,
    topic_index: int = 0,
    base_dir: str = "",
) -> None:
    page.wait_for_timeout(800)
    av_tab = page.locator("text='AV Summary'").first
    if not av_tab.is_visible():
        return
    av_tab.click()
    page.wait_for_timeout(1500)

    vimeo_ids: list[str] = []
    direct_mp4_urls: list[str] = []

    iframe_elements = page.locator("iframe")
    for i in range(iframe_elements.count()):
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
    logger.info("Found %d AV Summary file(s).", total)

    root = base_dir if base_dir else os.getcwd()
    folder = os.path.join(root, f"{course_name} {unit_name}", "AV_Summaries")
    os.makedirs(folder, exist_ok=True)

    safe_topic = sanitize(topic) if topic else f"{course_name}_Topic_{topic_index}"
    if not topic:
        logger.warning("Topic extraction failed for video, using fallback: %s", safe_topic)

    def _make_av_filename(counter: int) -> str:
        return safe_topic if total == 1 else f"{safe_topic}_{counter}"

    page_video_counter = 0

    for vid_id in vimeo_ids:
        if vid_id in downloaded_urls:
            logger.info("Already downloaded Vimeo %s, skipping.", vid_id)
            continue
        if not _yt_dlp_available():
            logger.warning("yt-dlp not available. Skipping Vimeo %s.", vid_id)
            continue

        page_video_counter += 1
        logger.info("Downloading Vimeo %s...", vid_id)
        base_name = _make_av_filename(page_video_counter)
        filename = get_unique_filename(folder, base_name, ".mp4")
        filepath = os.path.join(folder, filename)

        success = intercept_and_download_vimeo(page, vid_id, filepath)

        if success and os.path.exists(filepath) and os.path.getsize(filepath) > 1024:
            logger.info("Saved -> %s", filepath)
            downloaded_urls.add(vid_id)
        else:
            logger.error("Could not download Vimeo %s or file corrupted.", vid_id)
            if os.path.exists(filepath):
                os.remove(filepath)
            page_video_counter -= 1

    for url in direct_mp4_urls:
        if url in downloaded_urls:
            continue
        page_video_counter += 1
        logger.info("Downloading direct MP4: %s", url)
        try:
            resp = page.request.get(url)
            if resp.status != 200:
                logger.warning("Failed (%d): %s", resp.status, url)
                page_video_counter -= 1
                continue

            base_name = _make_av_filename(page_video_counter)
            filename = get_unique_filename(folder, base_name, ".mp4")
            filepath = os.path.join(folder, filename)

            with open(filepath, "wb") as f:
                f.write(resp.body())

            if os.path.getsize(filepath) < 1024:
                logger.warning("File too small, possibly corrupted: %s", filepath)
                os.remove(filepath)
                page_video_counter -= 1
            else:
                logger.info("Saved -> %s", filepath)
                downloaded_urls.add(url)
        except Exception as e:
            logger.error("Error downloading %s: %s", url, e)
            page_video_counter -= 1


# ---------------------------------------------------------------------------
# Document (Slide / Note / QB) download
# ---------------------------------------------------------------------------

def _extract_direct_pdf_url(iframe_url: str) -> str | None:
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
            candidate = urllib.parse.unquote(m.group(1))
            if candidate.startswith("http"):
                return candidate
            if candidate.startswith("/"):
                return "https://www.pesuacademy.com" + candidate
    return None


def download_content(
    page: Page,
    course_name: str,
    unit_name: str,
    downloaded_urls: set,
    category: str = "Slide",
    topic_override: str | None = None,
    topic_index: int = 0,
    base_dir: str = "",
) -> None:
    page.wait_for_timeout(800)

    tab_map = {"Slide": "Slides", "QB": "QB", "Note": "Notes"}
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

    logger.info("Found %d %s file(s).", count, category)

    root = base_dir if base_dir else os.getcwd()
    unit_root = os.path.join(root, f"{course_name} {unit_name}")
    if category in ("QB", "Note"):
        subfolder_name = "QB" if category == "QB" else "Notes"
        folder = os.path.join(unit_root, subfolder_name)
    else:
        folder = unit_root

    os.makedirs(folder, exist_ok=True)

    safe_topic = sanitize(topic_override) if topic_override else f"{course_name}_Topic_{topic_index}"
    if not topic_override:
        logger.warning("Topic extraction failed for %s, using fallback: %s", category, safe_topic)

    file_counter = 1

    for i in range(count):
        item = items.nth(i)
        onclick = item.get_attribute("onclick")
        urls: list[str] = []

        if onclick and "loadIframe" in onclick:
            raw_urls = re.findall(r"loadIframe\('([^']+)", onclick)
            for raw in raw_urls:
                iframe_url = raw if raw.startswith("http") else "https://www.pesuacademy.com" + raw
                direct = _extract_direct_pdf_url(iframe_url)
                urls.append(direct if direct else iframe_url)

        elif onclick and "downloadcoursedoc" in onclick:
            matches = re.findall(r"downloadcoursedoc\('([^']+)'", onclick)
            if matches:
                urls = [
                    f"https://www.pesuacademy.com/Academy/a/referenceMeterials/downloadslidecoursedoc/{m}"
                    for m in matches
                ]

        if not urls:
            continue

        for file_url in urls:
            file_url = file_url.split("#")[0]
            if file_url in downloaded_urls:
                continue
            logger.info("Downloading: %s", file_url)
            response = page.request.get(file_url)
            if response.status != 200:
                logger.warning("Failed (%d): %s", response.status, file_url)
                continue

            content_type = response.headers.get("content-type", "").lower()
            body = response.body()

            if (
                b"%PDF" not in body[:10]
                and "pdf" not in content_type
                and b"PK" not in body[:4]
                and "zip" not in content_type
                and "officedocument" not in content_type
            ):
                text = body.decode("utf-8", errors="ignore")
                pdf_link_match = re.search(r'(https?://[^\s"\']+\.pdf[^\s"\']*)', text)
                if pdf_link_match:
                    fallback_url = pdf_link_match.group(1)
                    logger.info("Response was HTML; found PDF link: %s", fallback_url)
                    resp2 = page.request.get(fallback_url)
                    if resp2.status == 200:
                        body = resp2.body()
                        content_type = resp2.headers.get("content-type", "").lower()
                    else:
                        logger.warning("Fallback PDF fetch failed (%d), skipping.", resp2.status)
                        continue
                else:
                    logger.warning("Response is not a valid document (content-type: %s). Skipping.", content_type)
                    continue

            if b"PK" in body[:4] or "officedocument.presentationml" in content_type or "powerpoint" in content_type:
                ext = ".pptx"
            elif "officedocument.wordprocessingml" in content_type:
                ext = ".docx"
            else:
                ext = ".pdf"

            if category == "Slide":
                suffix = "" if count == 1 else f"_{file_counter}"
                base_name = f"{topic_index:03d}_{safe_topic}{suffix}"
            elif category == "QB":
                base_name = f"QB_{topic_index:03d}_{safe_topic}"
            elif category == "Note":
                base_name = f"Note_{topic_index:03d}_{safe_topic}"
            else:
                base_name = f"{category}_{topic_index:03d}"

            filename = get_unique_filename(folder, base_name, ext)
            filepath = os.path.join(folder, filename)
            with open(filepath, "wb") as f:
                f.write(body)

            valid = (ext == ".pdf" and body[:4] == b"%PDF") or (ext in (".pptx", ".docx") and body[:2] == b"PK")
            if not valid:
                os.remove(filepath)
                logger.error("File failed validation and was deleted: %s", filename)
                continue

            logger.info("Saved -> %s", filepath)
            downloaded_urls.add(file_url)
            file_counter += 1
            page.wait_for_timeout(300)


# ---------------------------------------------------------------------------
# Page navigation loop
# ---------------------------------------------------------------------------

def navigate_through_pages(
    page: Page,
    course_name: str,
    unit_name: str,
    downloaded_urls: set,
    fetch_videos: bool,
    fetch_notes: bool,
    fetch_qb: bool,
    base_dir: str = "",
    checkpoint: dict | None = None,
) -> None:
    """
    Iterate through all content pages for a unit.
    `checkpoint` is a mutable dict: {topic_key: bool}. Already-completed topics are skipped.
    """
    if checkpoint is None:
        checkpoint = {}

    last_url = None
    last_button_label = None
    stuck_count = 0
    MAX_STUCK = 3
    topic_index = 0

    while True:
        page.wait_for_selector(".coursecontent-navigation-area a.pull-right", timeout=15000)
        next_button = page.locator(".coursecontent-navigation-area a.pull-right")
        label = next_button.inner_text().strip()
        current_url = page.url

        topic = get_page_topic(page)
        if not topic:
            topic = f"{course_name}_Topic_{topic_index + 1}"
            logger.warning("Topic name not found, using fallback: %s", topic)

        topic_index += 1
        checkpoint_key = f"{course_name}|{unit_name}|{topic_index}"
        logger.info("Current Page (%d): %s", topic_index, topic)

        if current_url == last_url and label == last_button_label:
            stuck_count += 1
            logger.warning("Page did not change (stuck %d/%d)", stuck_count, MAX_STUCK)
            if stuck_count >= MAX_STUCK:
                logger.error("Navigation appears stuck. Stopping.")
                break
        else:
            stuck_count = 0
            last_url = current_url
            last_button_label = label

            if checkpoint.get(checkpoint_key):
                logger.info("Skipping already-completed topic: %s", topic)
            else:
                if fetch_videos:
                    download_av_summaries(page, course_name, unit_name, downloaded_urls, topic=topic, topic_index=topic_index, base_dir=base_dir)

                download_content(page, course_name, unit_name, downloaded_urls, "Slide", topic_override=topic, topic_index=topic_index, base_dir=base_dir)

                if fetch_notes:
                    download_content(page, course_name, unit_name, downloaded_urls, "Note", topic_override=topic, topic_index=topic_index, base_dir=base_dir)

                if fetch_qb:
                    download_content(page, course_name, unit_name, downloaded_urls, "QB", topic_override=topic, topic_index=topic_index, base_dir=base_dir)

                checkpoint[checkpoint_key] = True

        if "Back to Units" in label:
            logger.info("Reached 'Back to Units'. Stopping navigation.")
            break

        next_button.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(800)

    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)
