import os
import re
import subprocess
import logging
import time

from playwright.sync_api import Page

from integrity import verify_file, quarantine

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


def _ensure_my_courses_page(page: Page) -> None:
    table = page.locator("table.table.table-hover")
    if table.count() > 0 and table.first.is_visible():
        return
    page.wait_for_selector("span.menu-name:has-text('My Courses')", timeout=15000)
    page.click("span.menu-name:has-text('My Courses')")
    page.wait_for_selector("table.table.table-hover", timeout=15000)


def get_all_courses(page: Page) -> list[str]:
    """Return list of course names, navigating to My Courses only if needed."""
    _ensure_my_courses_page(page)
    rows = page.locator("table.table.table-hover tbody tr")
    count = rows.count()
    courses = []
    for i in range(count):
        title = rows.nth(i).locator("td:nth-child(2)").inner_text().strip()
        courses.append(title)
    return courses


def _find_semester_select(page: Page):
    selects = page.locator("select")
    count = selects.count()
    for i in range(count):
        sel = selects.nth(i)
        opts = sel.locator("option")
        texts = [opts.nth(j).inner_text().strip() for j in range(opts.count())]
        if any(t.lower().startswith("sem-") for t in texts):
            return sel
    return None


def get_available_semesters(page: Page) -> list[str]:
    _ensure_my_courses_page(page)
    select = _find_semester_select(page)
    if select is None:
        logger.warning("Semester dropdown not found on My Courses page.")
        return []
    opts = select.locator("option")
    return [opts.nth(i).inner_text().strip() for i in range(opts.count())]


def select_semester(page: Page, semester_label: str) -> bool:
    select = _find_semester_select(page)
    if select is None:
        logger.error("Semester dropdown not found, cannot switch to '%s'.", semester_label)
        return False

    opts = select.locator("option")
    matched = None
    for i in range(opts.count()):
        text = opts.nth(i).inner_text().strip()
        if text.lower() == semester_label.strip().lower():
            matched = text
            break

    if not matched:
        logger.error("Semester '%s' not in dropdown options.", semester_label)
        return False

    select.select_option(label=matched)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    page.wait_for_selector("table.table.table-hover", timeout=15000)
    logger.info("Switched to semester: %s", matched)
    return True


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
# yt-dlp video download
# ---------------------------------------------------------------------------

def _yt_dlp_available() -> bool:
    try:
        result = subprocess.run(
            ["yt-dlp", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _ffmpeg_available() -> bool:
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _aria2c_available() -> bool:
    try:
        result = subprocess.run(
            ["aria2c", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _download_with_ytdlp(
    url: str,
    output_path: str,
    extra_args: list | None = None,
    retries: int = 3,
    prefer_1080: bool = True,
) -> bool:
    """Download using yt-dlp, preferring the highest available quality up to 1080p."""
    if not _yt_dlp_available():
        logger.error("yt-dlp is not available.")
        return False

    ffmpeg_ok = _ffmpeg_available()

    if prefer_1080 and ffmpeg_ok:
        # Ask yt-dlp for separate best video/audio streams and sort toward 1080p.
        # The /best fallback also handles muxed progressive sources.
        format_selector = (
            "bv*[height<=1080]+ba/"
            "bv*[height<=1080]/"
            "b[height<=1080]/b"
        )
        sort_expr = "res:1080,fps,vbr,abr"
    elif prefer_1080 and not ffmpeg_ok:
        # Without ffmpeg, do not pretend that a video+audio merge can be done.
        # Prefer a single muxed stream and warn that 1080 cannot be guaranteed.
        logger.warning(
            "ffmpeg is not available. Downloading a single muxed stream; "
            "1080p cannot be guaranteed when Vimeo provides separate audio/video."
        )
        format_selector = "b[height<=1080]/b"
        sort_expr = "res:1080,fps,vbr,abr"
    else:
        format_selector = "b"
        sort_expr = "res,fps,vbr,abr"

    base_cmd = [
        "yt-dlp",
        "-f", format_selector,
        "-S", sort_expr,
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--no-part",
        "--no-warnings",
        "-o", output_path,
    ]

    if _aria2c_available():
        base_cmd += [
            "--downloader", "aria2c",
            "--downloader-args", "aria2c:-x16 -s16 -k5M --min-split-size=5M",
        ]
    else:
        base_cmd += [
            "--concurrent-fragments", "16",
            "--buffer-size", "16K",
        ]

    if extra_args:
        base_cmd += extra_args
    base_cmd.append(url)

    for attempt in range(1, retries + 1):
        try:
            logger.debug(
                "yt-dlp attempt %d/%d for %s",
                attempt,
                retries,
                url[:180],
            )
            result = subprocess.run(base_cmd, timeout=900)
            if result.returncode == 0 and os.path.exists(output_path):
                return True
            logger.warning(
                "yt-dlp exited with code %d (attempt %d)",
                result.returncode,
                attempt,
            )
        except subprocess.TimeoutExpired:
            logger.warning("yt-dlp timed out (attempt %d)", attempt)
        except Exception as e:
            logger.error("yt-dlp error: %s", e)
        if attempt < retries:
            time.sleep(3)
    return False


def _browser_vimeo_cookie_header(page: Page) -> str:
    """Return browser cookies relevant to Vimeo as a Cookie header."""
    try:
        cookies = page.context.cookies([
            "https://player.vimeo.com/",
            "https://vimeo.com/",
        ])
        pairs = []
        for cookie in cookies:
            name = cookie.get("name")
            value = cookie.get("value")
            if name and value:
                pairs.append(f"{name}={value}")
        return "; ".join(pairs)
    except Exception as e:
        logger.debug("Could not collect browser Vimeo cookies: %s", e)
        return ""


def _with_autoplay(url: str) -> str:
    """Add autoplay/muted parameters without destroying Vimeo privacy parameters."""
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

    try:
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.setdefault("autoplay", "1")
        query.setdefault("muted", "1")
        query.setdefault("playsinline", "1")
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    except Exception:
        return url


def _select_best_hls_manifest(
    page: Page,
    urls: list[str],
    cookie_header: str,
) -> str | None:
    """Return the most useful HLS URL, preferring a master playlist."""
    masters: list[str] = []
    candidates: list[str] = []

    headers = {"Referer": page.url, "Origin": "https://www.pesuacademy.com"}
    if cookie_header:
        headers["Cookie"] = cookie_header

    seen = set()
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            response = page.request.get(url, headers=headers, timeout=30_000)
            if response.status != 200:
                continue
            body = response.body().decode("utf-8", errors="ignore")
            candidates.append(url)
            if "#EXT-X-STREAM-INF" in body:
                masters.append(url)
                logger.debug("Detected HLS master playlist: %s", url[:180])
        except Exception as e:
            logger.debug("Could not inspect HLS manifest %s: %s", url[:150], e)

    if masters:
        # Prefer URLs which themselves look like master playlists.
        masters.sort(key=lambda u: ("master" not in u.lower(), "playlist" not in u.lower()))
        return masters[0]

    if candidates:
        # Prefer an obvious high-quality rendition when only media playlists were
        # exposed. Otherwise use the first stable non-segment manifest.
        quality_scores = []
        for u in candidates:
            low = u.lower()
            score = 0
            if "1080" in low:
                score += 100
            elif "720" in low:
                score += 80
            elif "540" in low:
                score += 60
            elif "360" in low:
                score += 40
            elif "240" in low:
                score += 20
            quality_scores.append((score, u))
        quality_scores.sort(reverse=True)
        return quality_scores[0][1]

    return None


def _select_best_mpd(page: Page, urls: list[str]) -> str | None:
    """Prefer a DASH manifest over media fragments."""
    for url in urls:
        if url:
            return url
    return None


def intercept_and_download_vimeo(
    page: Page,
    vimeo_id: str,
    output_path: str,
    player_url: str | None = None,
) -> bool:
    """Download a PESU-embedded Vimeo video at the highest available quality up to 1080p."""
    if not _yt_dlp_available():
        logger.error("yt-dlp is not available. Cannot download Vimeo video.")
        return False

    exact_player_url = player_url or f"https://player.vimeo.com/video/{vimeo_id}"
    exact_player_url = _with_autoplay(exact_player_url)
    referer = page.url
    origin = "https://www.pesuacademy.com"
    cookie_header = _browser_vimeo_cookie_header(page)

    common_headers = [
        "--add-header", f"Referer:{referer}",
        "--add-header", f"Origin:{origin}",
    ]
    if cookie_header:
        common_headers += ["--add-header", f"Cookie:{cookie_header}"]

    # First let yt-dlp resolve the complete embedded player URL. This is
    # particularly important for unlisted/private Vimeo videos because the
    # privacy hash in ?h=... must be preserved.
    logger.info("Trying Vimeo player URL with quality selection: %s", exact_player_url[:180])
    if _download_with_ytdlp(
        exact_player_url,
        output_path,
        extra_args=common_headers,
        retries=2,
        prefer_1080=True,
    ):
        return True

    # If yt-dlp cannot resolve the player directly, drive the embedded player
    # in the authenticated browser and capture ALL manifest requests. The old
    # code took the first .m3u8 it saw, which can be a 240p rendition playlist.
    captured_hls: list[str] = []
    captured_mpd: list[str] = []
    captured_mp4: list[str] = []

    def handle_response(response):
        url = response.url
        lower = url.lower()

        if "vimeocdn" not in lower and "vimeo.com" not in lower:
            return

        if ".m3u8" in lower:
            if "/seg-" not in lower and ".ts" not in lower:
                if url not in captured_hls:
                    captured_hls.append(url)
                    logger.debug("Captured Vimeo HLS manifest: %s", url[:220])
        elif ".mpd" in lower:
            if url not in captured_mpd:
                captured_mpd.append(url)
                logger.debug("Captured Vimeo DASH manifest: %s", url[:220])
        elif ".mp4" in lower and "fragment" not in lower:
            if url not in captured_mp4:
                captured_mp4.append(url)
                logger.debug("Captured Vimeo MP4: %s", url[:220])

    page.on("response", handle_response)
    try:
        page.evaluate(
            """
            (playerUrl) => {
                const old = document.getElementById('_vimeo_intercept_frame');
                if (old) old.remove();

                const iframe = document.createElement('iframe');
                iframe.id = '_vimeo_intercept_frame';
                iframe.src = playerUrl;
                iframe.allow = 'autoplay; fullscreen; picture-in-picture';
                iframe.setAttribute('allowfullscreen', '');
                iframe.style.cssText =
                    'width:960px;height:540px;position:absolute;left:-9999px;top:0;border:0;';
                document.body.appendChild(iframe);

                setTimeout(() => {
                    try {
                        const win = iframe.contentWindow;
                        if (win) win.postMessage({method:'play'}, '*');
                    } catch (_) {}
                }, 2500);
            }
            """,
            exact_player_url,
        )

        # Give the actual embedded player enough time to request its manifest.
        for _ in range(50):
            if captured_hls or captured_mpd or captured_mp4:
                # Do not stop immediately: another manifest may be the master.
                page.wait_for_timeout(400)
            else:
                page.wait_for_timeout(500)
    except Exception as e:
        logger.debug("Vimeo iframe interception error for %s: %s", vimeo_id, e)
    finally:
        page.remove_listener("response", handle_response)
        try:
            page.evaluate(
                """
                () => {
                    const f = document.getElementById('_vimeo_intercept_frame');
                    if (f) f.remove();
                }
                """
            )
        except Exception:
            pass

    # Prefer a master HLS playlist; this prevents accidentally selecting a
    # fixed 240p rendition just because it happened to load first.
    hls_url = _select_best_hls_manifest(page, captured_hls, cookie_header)
    mpd_url = _select_best_mpd(page, captured_mpd)

    stream_url = hls_url or mpd_url
    if stream_url:
        logger.info(
            "Downloading Vimeo %s from selected manifest (highest available quality up to 1080p)...",
            vimeo_id,
        )
        if _download_with_ytdlp(
            stream_url,
            output_path,
            extra_args=common_headers,
            retries=3,
            prefer_1080=True,
        ):
            return True

    # A direct MP4 may already be the portal's selected high-quality source.
    if captured_mp4:
        logger.info("Trying captured Vimeo MP4 source for %s...", vimeo_id)
        for mp4_url in captured_mp4:
            if _download_with_ytdlp(
                mp4_url,
                output_path,
                extra_args=common_headers,
                retries=2,
                prefer_1080=False,
            ):
                return True

    logger.error(
        "Unable to download Vimeo %s from the authenticated PESU player. "
        "The portal may be using a protected/DRM delivery path, or the browser session "
        "did not expose a downloadable manifest.",
        vimeo_id,
    )
    return False


# ---------------------------------------------------------------------------
# Topic extraction
# ---------------------------------------------------------------------------

_BLACKLIST_WORDS = {
    "my courses", "mycourses", "back to units", "home", "logout", "settings",
    "slides", "notes", "question bank", "question banks", "qb", "qa",
    "av summary", "av summaries", "live videos", "assignments", "forums",
    "mcqs", "references", "faqs", "faq", "item cursor pointer",
    "cursor pointer",
}

_UI_NOISE_EXACT = {
    "profile", "pesu", "academy", "login", "next", "previous", "back",
    "continue", "open", "content", "class", "course", "unit", "units",
    "cursor", "pointer",
}


def _is_blacklisted(text: str) -> bool:
    low = text.lower().strip()
    return not low or low in _BLACKLIST_WORDS or low in _UI_NOISE_EXACT


def _looks_like_topic(text: str) -> bool:
    if not text:
        return False

    low = re.sub(r"\s+", " ", text).strip().lower()
    if _is_blacklisted(low):
        return False

    if low.startswith(("unit ", "topic ", "page ", "slide ")):
        return False

    if re.fullmatch(r"(?:topic|page|slide)\s*[-#]?\s*\d+", low):
        return False

    if low in {
        "next", "previous", "back", "continue", "open", "back to units",
        "faqs", "faq", "slides", "notes", "qb", "qa", "av summary",
        "live videos", "assignments", "forums", "mcqs", "references",
    }:
        return False

    return 3 <= len(low) <= 200 and bool(re.search(r"[a-zA-Z0-9]", low))


def _clean_topic_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\u200b", " ").replace("\ufeff", " ")
    text = re.sub(r"\s+", " ", text).strip()

    if _is_blacklisted(text):
        return ""
    if len(text) < 3 or len(text) > 250:
        return ""
    if not re.search(r"[A-Za-z0-9]", text):
        return ""

    return sanitize(text)


def _topic_candidate_is_ui(text: str) -> bool:
    low = re.sub(r"\s+", " ", text).strip().lower()
    return low in {
        "my courses", "home", "online payments", "student grievance redressal system",
        "time table", "neft/rtgs details", "bank consent", "my attendance", "results",
        "seating info", "video archives", "my quizzes", "entrance exam", "calender",
        "announcements", "user vehicle", "my profile", "backlog registration",
        "my projects/publications", "mentor mentee", "hall ticket",
        "av summary", "live videos", "slides", "notes", "forums", "assignments",
        "qb", "qa", "mcqs", "faqs", "references",
    }


def _extract_topic_from_top_breadcrumb_region(page: Page, course_name: str) -> str:
    """
    PESU renders the breadcrumb above the resource tabs.

    The critical distinction is positional: the left sidebar also contains
    'My Courses', while the real breadcrumb is in the main content area around
    the top of the page, above the Slides/Notes/QB/QA/FAQ tabs.

    This function therefore finds the MAIN-AREA 'My Courses' element and then
    collects visible leaf text on the same horizontal row. The right-most valid
    item after the course name is the current topic.
    """
    anchor = re.sub(r"\s+", " ", course_name or "").strip().lower()
    anchor_tail = anchor.split(":", 1)[-1].strip() if ":" in anchor else anchor

    try:
        result = page.evaluate(
            """
            ({courseName, courseTail}) => {
                const visible = (el) => {
                    if (!el) return false;
                    const cs = getComputedStyle(el);
                    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                };

                const compact = (s) => (s || '')
                    .replace(/[\\u200B\\uFEFF]/g, ' ')
                    .replace(/\\s+/g, ' ')
                    .trim();

                const leafs = Array.from(document.querySelectorAll('a,span,li,div,p,strong,b'))
                    .filter(el => visible(el) && el.children.length === 0)
                    .map(el => {
                        const r = el.getBoundingClientRect();
                        return {
                            el,
                            text: compact(el.innerText || el.textContent || ''),
                            top: r.top,
                            left: r.left,
                            right: r.right,
                            width: r.width,
                            height: r.height
                        };
                    })
                    .filter(x => x.text.length >= 2 && x.text.length <= 220);

                // Locate visible main-content 'My Courses' occurrences.
                const myCourses = leafs
                    .filter(x => x.text.toLowerCase() === 'my courses')
                    .filter(x => x.left >= 220)
                    .filter(x => x.top >= 90 && x.top <= 240)
                    .sort((a,b) => (a.top - b.top) || (a.left - b.left));

                for (const mc of myCourses) {
                    const sameRow = leafs
                        .filter(x => x.left >= mc.left - 5)
                        .filter(x => Math.abs(x.top - mc.top) <= Math.max(12, mc.height * 0.9))
                        .filter(x => x.top < 205)
                        .filter(x => x.left < window.innerWidth - 20)
                        .sort((a,b) => a.left - b.left);

                    const courseIndex = sameRow.findIndex(x => {
                        const t = x.text.toLowerCase();
                        return (
                            (courseName && t.includes(courseName)) ||
                            (courseTail && t.includes(courseTail)) ||
                            /:\\s*/.test(t) && t.length > 8
                        );
                    });

                    const useful = sameRow.filter(x => {
                        const t = x.text.toLowerCase();
                        if (t === 'my courses') return true;
                        if (/^(slides|notes|qb|qa|faqs|references|assignments|forums|mcqs|av summary|live videos)$/.test(t)) return false;
                        return true;
                    });

                    if (courseIndex >= 0) {
                        const after = sameRow.slice(courseIndex + 1)
                            .filter(x => x.text && !/^(>|›|»|->)$/.test(x.text));
                        if (after.length) {
                            return {
                                mode: 'same_row_after_course',
                                values: after.map(x => x.text),
                                geometry: after.map(x => ({top:x.top,left:x.left,right:x.right}))
                            };
                        }
                    }

                    if (useful.length >= 3) {
                        return {
                            mode: 'same_row',
                            values: useful.map(x => x.text),
                            geometry: useful.map(x => ({top:x.top,left:x.left,right:x.right}))
                        };
                    }
                }

                return null;
            }
            """,
            {"courseName": anchor, "courseTail": anchor_tail},
        )

        if not result:
            return ""

        values = result.get("values") or []
        cleaned = []
        for value in values:
            c = _clean_topic_text(value)
            if c and not _topic_candidate_is_ui(c) and _looks_like_topic(c):
                cleaned.append(c)

        # The topic is the last valid item in the breadcrumb row.
        if cleaned:
            candidate = cleaned[-1]
            logger.debug(
                "Breadcrumb row candidate(s): %s -> selected: %s",
                cleaned,
                candidate,
            )
            return candidate

    except Exception as e:
        logger.debug("Top breadcrumb region extraction failed: %s", e)

    return ""


def _extract_topic_from_breadcrumb_container(page: Page, course_name: str) -> str:
    """Secondary breadcrumb extraction using explicit breadcrumb-like containers."""
    anchor = re.sub(r"\s+", " ", course_name or "").strip().lower()
    anchor_tail = anchor.split(":", 1)[-1].strip() if ":" in anchor else anchor

    selectors = [
        "nav[aria-label*='breadcrumb' i]",
        ".breadcrumb",
        "ul.breadcrumb",
        "ol.breadcrumb",
        "[class*='breadcrumb' i]",
        "[id*='breadcrumb' i]",
        ".page-breadcrumb",
        ".pesu-breadcrumb",
    ]

    for selector in selectors:
        try:
            elements = page.locator(selector)
            for i in range(elements.count()):
                el = elements.nth(i)
                if not el.is_visible():
                    continue

                raw = re.sub(r"\s+", " ", el.inner_text()).strip()
                if "my courses" not in raw.lower():
                    continue

                parts = [
                    p.strip()
                    for p in re.split(r"\s*(?:>|›|»|→)\s*", raw)
                    if p.strip()
                ]

                course_pos = -1
                for idx, part in enumerate(parts):
                    low = part.lower()
                    if (anchor and anchor in low) or (anchor_tail and anchor_tail in low):
                        course_pos = idx

                if course_pos >= 0:
                    for part in reversed(parts[course_pos + 1:]):
                        candidate = _clean_topic_text(part)
                        if candidate and _looks_like_topic(candidate) and not _topic_candidate_is_ui(candidate):
                            return candidate
        except Exception:
            continue

    return ""


def _extract_topic_from_title_like_elements(page: Page) -> str:
    """Last-resort search for a real title in the content area only."""
    selectors = [
        "#coursecontentarea h1", "#coursecontentarea h2", "#coursecontentarea h3",
        ".course-content h1", ".course-content h2", ".course-content h3",
        ".coursecontent h1", ".coursecontent h2", ".coursecontent h3",
        ".main-content h1", ".main-content h2", ".main-content h3",
        ".topic-title", ".content-title", ".page-title",
    ]

    for selector in selectors:
        try:
            elements = page.locator(selector)
            for i in range(min(elements.count(), 10)):
                text = elements.nth(i).inner_text().strip().split("\n")[0].strip()
                candidate = _clean_topic_text(text)
                if candidate and _looks_like_topic(candidate) and not _topic_candidate_is_ui(candidate):
                    return candidate
        except Exception:
            continue

    return ""


def _dump_topic_debug_html(page: Page, reason: str = "") -> None:
    try:
        os.makedirs("_debug", exist_ok=True)
        path = os.path.join("_debug", f"topic_extraction_failed_{int(time.time())}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(page.content())
        logger.warning("Topic extraction failed (%s); dumped page HTML to %s", reason, path)
    except Exception as e:
        logger.debug("Could not dump topic debug HTML: %s", e)


def get_page_topic(page: Page, course_name: str = "") -> str:
    """Extract the actual PESU topic, never a resource-tab label."""
    topic = _extract_topic_from_top_breadcrumb_region(page, course_name)
    if topic:
        return topic

    topic = _extract_topic_from_breadcrumb_container(page, course_name)
    if topic:
        return topic

    topic = _extract_topic_from_title_like_elements(page)
    if topic:
        return topic

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
    vimeo_sources: dict[str, str] = {}
    direct_mp4_urls: list[str] = []

    iframe_elements = page.locator("iframe")
    for i in range(iframe_elements.count()):
        src = iframe_elements.nth(i).get_attribute("src") or ""
        vimeo_match = re.search(r"(?:player\.)?vimeo\.com/video/(\d+)", src)
        if vimeo_match:
            vid_id = vimeo_match.group(1)
            if vid_id not in vimeo_ids:
                vimeo_ids.append(vid_id)
            vimeo_sources.setdefault(vid_id, src)
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
    for m in re.finditer(r'((?:https?:)?//(?:player\.)?vimeo\.com/video/(\d+)[^"\'\s<>]*)', page_html):
        src = m.group(1)
        if src.startswith("//"):
            src = "https:" + src
        vid_id = m.group(2)
        if vid_id not in vimeo_ids:
            vimeo_ids.append(vid_id)
        vimeo_sources.setdefault(vid_id, src)

    if not vimeo_ids and not direct_mp4_urls:
        return

    total = len(vimeo_ids) + len(direct_mp4_urls)
    logger.info("Found %d AV Summary file(s).", total)

    root = base_dir if base_dir else os.getcwd()
    folder = os.path.join(root, f"{course_name} {unit_name}", "AV_Summaries")
    os.makedirs(folder, exist_ok=True)

    def _truncate(s: str, n: int = 120) -> str:
        return s[:n].strip()

    safe_topic_raw = topic if topic else f"{course_name}_Topic_{topic_index}"
    safe_topic = sanitize(safe_topic_raw)
    safe_topic = _truncate(safe_topic, 120)
    if not safe_topic:
        safe_topic = f"Topic_{topic_index}"
    if not topic:
        logger.warning("Topic extraction failed for video, using fallback: %s", safe_topic)
    else:
        logger.info("Using topic title for filename: %s", safe_topic)

    prefix = f"{topic_index:03d}_{safe_topic}"

    def _make_av_filename(counter: int) -> str:
        return prefix if total == 1 else f"{prefix}_{counter}"

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

        player_src = vimeo_sources.get(vid_id) or f"https://player.vimeo.com/video/{vid_id}"
        success = intercept_and_download_vimeo(page, vid_id, filepath, player_url=player_src)

        if success and os.path.exists(filepath) and os.path.getsize(filepath) > 1024:
            if not verify_file(filepath):
                quarantine(filepath, "vimeo download failed video integrity check")
                page_video_counter -= 1
                continue
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
            elif not verify_file(filepath):
                quarantine(filepath, "direct mp4 download failed video integrity check")
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

    tab_map = {"Slide": "Slides", "QB": "QB", "Note": "Notes", "QA": "QA"}
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
    SUBFOLDERS = {"QB": "QB", "Note": "Notes", "QA": "QA"}
    if category in SUBFOLDERS:
        folder = os.path.join(unit_root, SUBFOLDERS[category])
    else:
        folder = unit_root

    os.makedirs(folder, exist_ok=True)

    def _truncate_content(s: str, n: int = 120) -> str:
        return s[:n].strip()

    safe_topic_raw = topic_override if topic_override else f"{course_name}_Topic_{topic_index}"
    safe_topic = sanitize(safe_topic_raw)
    safe_topic = _truncate_content(safe_topic, 120)
    if not safe_topic:
        safe_topic = f"Topic_{topic_index}"
    if not topic_override:
        logger.warning("Topic extraction failed for %s, using fallback: %s", category, safe_topic)
    else:
        logger.info("Using topic title for filename: %s", safe_topic)

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

            # Naming: 001_Actual Topic Title (+ counter if multiple files per page)
            if category == "Slide":
                base_name = f"{topic_index:03d}_{safe_topic}" if count == 1 else f"{topic_index:03d}_{safe_topic}_{file_counter}"
            elif category == "QB":
                base_name = f"{topic_index:03d}_QB_{safe_topic}" if count == 1 else f"{topic_index:03d}_QB_{safe_topic}_{file_counter}"
            elif category == "Note":
                base_name = f"{topic_index:03d}_Note_{safe_topic}" if count == 1 else f"{topic_index:03d}_Note_{safe_topic}_{file_counter}"
            else:
                base_name = f"{topic_index:03d}_{category}_{safe_topic}" if count == 1 else f"{topic_index:03d}_{category}_{safe_topic}_{file_counter}"

            filename = get_unique_filename(folder, base_name, ext)
            filepath = os.path.join(folder, filename)
            with open(filepath, "wb") as f:
                f.write(body)

            valid = (ext == ".pdf" and body[:4] == b"%PDF") or (ext in (".pptx", ".docx") and body[:2] == b"PK")
            if not valid:
                os.remove(filepath)
                logger.error("File failed magic-byte validation and was deleted: %s", filename)
                continue

            if not verify_file(filepath):
                quarantine(filepath, "failed structural integrity check on download")
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
    fetch_qa: bool = False,
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
        # Wait for the main content area to be present
        try:
            page.wait_for_selector("#coursecontentarea, .course-content, .coursecontent, .main-content", timeout=5000)
        except Exception:
            pass  # proceed anyway
        topic = get_page_topic(page, course_name=course_name)
        if not topic:
            # Dump what's actually on the page so we can iterate the selector
            try:
                snippet = page.evaluate(
                    r"""
                    () => {
                        const main = document.querySelector('#coursecontentarea, .course-content, .coursecontent, .main-content, #content');
                        const txt = (main || document.body).innerText || '';
                        return txt.replace(/\s+/g, ' ').trim().substring(0, 250);
                    }
                    """
                )
            except Exception:
                snippet = ""
            topic = sanitize(f"{course_name} Topic {topic_index + 1}")
            logger.warning("Topic name not found, using fallback: %s", topic)
            if snippet:
                logger.warning("Page snippet (first 250 chars): %s", snippet)

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

                if fetch_qa:
                    download_content(page, course_name, unit_name, downloaded_urls, "QA", topic_override=topic, topic_index=topic_index, base_dir=base_dir)

                checkpoint[checkpoint_key] = True

        if "Back to Units" in label:
            logger.info("Reached 'Back to Units'. Stopping navigation.")
            break

        next_button.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(800)

    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)
