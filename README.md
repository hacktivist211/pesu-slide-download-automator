# PESU Academy Automator

A Playwright-based command-line automation tool for downloading course resources from the PESU Academy student portal.

The automator logs into PESU Academy, lets you choose a semester/course/unit, walks through the content pages of the selected unit, downloads the available learning resources, and optionally converts and merges downloaded Office documents/PDFs into organized PDF collections.

Supported resource categories:

- AV Summaries / course videos
- Slides
- Notes
- Question Banks (QB)
- QA

The project is designed around the PESU Academy web interface and therefore depends on the portal's current page structure, authenticated session behavior, and resource delivery mechanisms.

---

## 1. Features

### Course and semester selection

The program can inspect the PESU Academy course list and available semesters and lets you select the semester interactively or through the CLI.

Supported download modes are:

1. Single unit
2. Multiple units from the same course
3. Multiple courses with multiple units

The same browser session is reused while processing the selected work items where possible.

### Resource selection

At startup, the program can ask independently whether to download:

- AV Summaries
- Notes
- Question Banks
- QA

These choices can also be controlled completely from CLI flags, allowing the program to run without those interactive questions.

Slides are part of the normal unit download workflow and are downloaded when the unit content is processed.

### Topic-aware filenames

Downloaded resources are named using the current content topic, rather than only the course name and a numeric topic identifier.

Examples:

```text
001_Introduction to Database Management.pdf
001_Note_Introduction to Database Management.pdf
001_QB_Introduction to Database Management.pdf
001_QA_Introduction to Database Management.pdf
```

When a content page contains multiple files of the same category, an additional counter is appended:

```text
001_Introduction to Database Management_1.pdf
001_Introduction to Database Management_2.pdf
```

Invalid filename characters are sanitized before the file is written.

### Authenticated Vimeo/AV Summary handling

AV Summary videos are handled as authenticated portal content rather than assuming that a public Vimeo URL is sufficient.

The current downloader is designed to:

- preserve the complete embedded Vimeo player URL when available;
- preserve Vimeo privacy parameters contained in the embedded URL;
- forward the PESU page as the request referrer;
- reuse browser Vimeo cookies when available;
- prefer separate best video and audio streams up to 1080p when FFmpeg is available;
- inspect captured HLS manifests and prefer a master playlist instead of blindly selecting the first manifest encountered;
- fall back to captured/direct media sources when possible;
- validate completed video files before accepting them.

The actual maximum quality remains dependent on what the authenticated PESU/Vimeo player exposes to the browser session.

### Integrity checks

Downloaded files are checked before they are treated as successful downloads.

The project validates PDF, PPTX, DOCX, and MP4 files using the integrity helpers. Files that fail structural checks can be moved to a `_corrupted` quarantine directory with a reason recorded in `_quarantine_log.txt`.

### Checkpoint/resume support

The main program maintains a `.pesu_checkpoint.json` file while processing work.

When the program is interrupted or encounters an exception, downloaded URL information and topic progress are saved. Running with `--resume` allows the checkpoint to be loaded and previously completed work to be skipped where the checkpoint contains matching entries.

### PDF conversion

PPTX and DOCX resources can be converted to PDF after the browser download phase.

The conversion helper uses `online2pdf.com` and can process files in batches. If a batch stalls, the batch is bisected and retried in smaller groups.

### PDF merging

Slides, Notes, QB, and QA are merged independently.

Typical output names are:

```text
merged.pdf
Notes/merged_notes.pdf
QB/merged_qb.pdf
QA/merged_qa.pdf
```

Merge behavior can be controlled interactively or through saved preferences in `.env`.

### Persistent preferences

The project uses `.env` for credentials, download location, debug mode, merge preferences, and source-file retention preferences.

---

# 2. Requirements

## 2.1 Operating system

The project is primarily intended for Windows desktop usage because the normal workflow launches a visible Chromium browser and the examples use Windows paths.

Linux/macOS may work with appropriate adjustments, but they are not the primary documented environment.

## 2.2 Python

Use Python 3.10 or newer.

The codebase uses modern Python typing syntax such as:

```python
list[str]
str | None
```

and uses `argparse.BooleanOptionalAction`, so an older Python installation should not be assumed to work.

Verify your Python installation:

```bat
python --version
```

Recommended output format:

```text
Python 3.10.x
```

or newer.

## 2.3 Python packages

The project uses these Python dependencies:

- `playwright`
- `python-dotenv`
- `PyPDF2`

`yt-dlp` is used by the AV Summary downloader as an external executable/program and should be installed separately so that `yt-dlp` is available from the command line.

`ffmpeg` is strongly recommended for high-quality Vimeo downloads because Vimeo may provide video and audio as separate streams. Without FFmpeg, the code falls back to a single muxed stream when possible and cannot guarantee 1080p.

`aria2c` is optional. When available, the downloader can use it for faster segmented downloads.

The Office-to-PDF conversion stage uses `online2pdf.com` through Playwright; it does not require LibreOffice for the implemented conversion path.

---

# 3. Installation on Windows

## 3.1 Clone or copy the project

Place the entire project in a directory such as:

```text
C:\Users\<username>\OneDrive\Desktop\pesu-slide-download-automator
```

The project should contain files similar to:

```text
pesu-slide-download-automator/
├── automate.py
├── config.py
├── debugging.py
├── file_conversion.py
├── integrity.py
├── main.py
├── merge.py
├── README.md
└── requirements.txt
```

Additional files such as `.env`, `.pesu_checkpoint.json`, `__pycache__`, `_debug`, and downloaded course folders may appear during execution.

## 3.2 Open a terminal in the project directory

For Command Prompt:

```bat
cd /d "C:\Users\<username>\OneDrive\Desktop\pesu-slide-download-automator"
```

For PowerShell:

```powershell
Set-Location "C:\Users\<username>\OneDrive\Desktop\pesu-slide-download-automator"
```

## 3.3 Create a virtual environment

Recommended:

```bat
python -m venv .venv
```

Activate it in Command Prompt:

```bat
.venv\Scripts\activate
```

Activate it in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

After activation, your prompt should show the environment name, for example:

```text
(.venv) C:\Users\<username>\...>
```

## 3.4 Upgrade pip

```bat
python -m pip install --upgrade pip
```

## 3.5 Install Python dependencies

If `requirements.txt` is present:

```bat
python -m pip install -r requirements.txt
```

If you need to install the core dependencies directly:

```bat
python -m pip install playwright python-dotenv PyPDF2
```

## 3.6 Install the Playwright browser

The project launches Chromium through Playwright. After installing the Python package, install the required browser:

```bat
python -m playwright install chromium
```

If Playwright reports a browser dependency problem, rerun the command above from the same active virtual environment.

## 3.7 Install yt-dlp

The AV Summary downloader calls `yt-dlp` as a command-line executable.

Verify it:

```bat
yt-dlp --version
```

If it is not found, install yt-dlp using your preferred supported Windows installation method and make sure the executable is available in `PATH`.

The program explicitly checks whether `yt-dlp` is callable before attempting Vimeo downloads.

## 3.8 Install FFmpeg

Verify:

```bat
ffmpeg -version
```

For Vimeo sources that expose separate video and audio tracks, FFmpeg is required for reliable stream combination. The downloader detects FFmpeg and changes its format-selection behavior accordingly.

If:

```text
'ffmpeg' is not recognized as an internal or external command
```

then FFmpeg is not available on `PATH`.

After installing it, open a new terminal and verify again:

```bat
ffmpeg -version
```

## 3.9 Optional: install aria2c

Verify:

```bat
aria2c --version
```

It is optional. If unavailable, the downloader falls back to yt-dlp's concurrent fragment handling.

---

# 4. Credentials and `.env`

The application can read PESU credentials from `.env` or prompt for them interactively.

Recognized credential keys are:

```dotenv
USERNAME=your_srn_or_prn
PASSWORD=your_pesu_password
```

Do not commit `.env` to Git or share it with anyone. It contains sensitive login information.

The configuration system also supports:

```dotenv
DONT_ASK_AGAIN=0
DOWNLOAD_DIR=
DEBUG=0
```

`config.py` loads `.env`, provides getters/setters for these values, and treats `NOT_SET` as an unset credential value. fileciteturn5file1L500-L566

If `.env` does not exist, the application can ask whether credentials should be saved locally.

The program also supports explicit CLI credentials:

```bat
python main.py --username YOUR_SRN --password YOUR_PASSWORD
```

However, passing passwords directly on a command line can expose them through shell history or process inspection. Using the interactive password prompt or `.env` is preferable.

---

# 5. Basic Usage

The standard interactive launch is:

```bat
python main.py
```

The program will prompt for the resource categories first:

```text
Download AV Summaries (Videos)? (y/n):
Download Notes? (y/n):
Download Question Banks (QB)? (y/n):
Download QA? (y/n):
```

Then it logs into PESU Academy and presents the semester/course/unit selection interface.

The interactive workflow supports three download modes:

```text
Select download mode:
  1. Single unit
  2. Multiple units (same course)
  3. Multiple courses and units
```

These correspond to the internal modes:

```text
single
multi_unit
multi_course
```

---

# 6. Interactive Workflow

## Step 1: Select resources

Answer `y` or `n` for each category.

Example:

```text
Download AV Summaries (Videos)? (y/n): y
Download Notes? (y/n): y
Download Question Banks (QB)? (y/n): y
Download QA? (y/n): y
```

Slides are handled as part of the normal page-processing workflow.

## Step 2: Select semester

The program reads the available semester options from PESU Academy.

Example:

```text
Available Semesters:
  1. Sem-5
  2. Sem-4
  3. Sem-3
  4. Sem-2
  5. Sem-1

Enter semester number (Enter to keep current):
```

Press Enter to keep the portal's currently selected/default semester.

## Step 3: Select download mode

Choose one of the three modes.

### Single unit

Processes exactly one selected course/unit combination.

### Multiple units

Select one course and then enter several unit numbers separated by commas.

Example:

```text
Enter unit numbers (comma-separated): 1,2,4
```

### Multiple courses and units

Select multiple courses and specify the desired units for each course.

---

# 7. Command-Line Flags

Run:

```bat
python main.py --help
```

The current `main.py` defines the following arguments. fileciteturn5file0L291-L305

## `--username`, `-u`

PESU SRN/PRN.

Example:

```bat
python main.py --username PESU12345
```

## `--password`, `-p`

PESU password.

Example:

```bat
python main.py --username PESU12345 --password "your-password"
```

For security, avoid placing a real password in shell history when possible.

## `--videos` / `--no-videos`

Enable or disable AV Summary/video downloading.

Examples:

```bat
python main.py --videos
```

```bat
python main.py --no-videos
```

## `--notes` / `--no-notes`

Enable or disable Notes downloading.

Examples:

```bat
python main.py --notes
```

```bat
python main.py --no-notes
```

## `--qb` / `--no-qb`

Enable or disable Question Bank downloading.

Examples:

```bat
python main.py --qb
```

```bat
python main.py --no-qb
```

## `--qa` / `--no-qa`

Enable or disable QA downloading.

Examples:

```bat
python main.py --qa
```

```bat
python main.py --no-qa
```

## `--merge` / `--no-merge`

Controls PDF merging after downloads.

```bat
python main.py --merge
```

automatically merges eligible categories.

```bat
python main.py --no-merge
```

skips the merge stage.

If neither flag is specified, the program uses the saved merge preferences in `.env` or prompts interactively as applicable. The main program passes the resulting value to the merge subsystem after the browser is closed. fileciteturn5file0L396-L408

## `--multi`

Select a non-interactive download mode.

Accepted values:

```text
single
multi_unit
multi_course
```

Examples:

```bat
python main.py --multi single
```

```bat
python main.py --multi multi_unit
```

```bat
python main.py --multi multi_course
```

The current CLI mode controls the selection behavior, but course/unit selection still occurs through the program's normal input prompts unless further CLI automation is added.

## `--debug`

Enable verbose debugging and Playwright event hooks.

```bat
python main.py --debug
```

The debug helper registers listeners for browser console messages, requests, responses, page errors, DOMContentLoaded, and page load events. fileciteturn0file2L3-L9

Debug mode is useful when PESU changes its HTML structure or a resource unexpectedly disappears.

## `--resume`

Load the previously saved `.pesu_checkpoint.json` checkpoint.

```bat
python main.py --resume
```

This is intended for continuing interrupted or partially completed jobs.

The program stores downloaded URL information and completed topic keys while processing. fileciteturn5file0L321-L327

## `--download-dir`

Change the root directory used for downloaded resources.

Example:

```bat
python main.py --download-dir "D:\PESU Downloads"
```

The supplied path must already exist. `config.py` validates the directory and creates it only when the configured directory path is non-empty and valid according to its implementation. fileciteturn5file1L578-L591

## `--semester`

Select a semester by label rather than interactively choosing a number.

Example:

```bat
python main.py --semester "Sem-4"
```

The value must match an available PESU semester label. `main.py` passes the selected label to the semester-selection logic. fileciteturn5file0L167-L193

---

# 8. Useful CLI Examples

## Download everything interactively

```bat
python main.py
```

## Download without AV Summary videos

```bat
python main.py --no-videos
```

## Download Notes, QB, and QA but skip videos and merging

```bat
python main.py --no-videos --notes --qb --qa --no-merge
```

## Force automatic merging

```bat
python main.py --merge
```

## Select a semester and use multi-unit mode

```bat
python main.py --semester "Sem-4" --multi multi_unit
```

## Enable debugging

```bat
python main.py --debug
```

## Resume an interrupted operation

```bat
python main.py --resume
```

## Specify a separate download directory

```bat
python main.py --download-dir "D:\PESU Downloads"
```

## Fully specify resource choices from the CLI

```bat
python main.py --no-videos --notes --qb --qa --merge
```

When all four resource flags are specified, the program does not need to ask the four resource-selection questions. The download option parser returns those explicit values directly. fileciteturn5file0L130-L152

---

# 9. Output Structure

A typical processed unit is stored under the configured download root as:

```text
<download-root>/
└── Database Management System Unit 1 Introduction to Database Management and SQL/
    ├── 001_Introduction to Database Management and SQL.pdf
    ├── 002_Advanced SQL.pdf
    ├── ...
    ├── merged.pdf
    │
    ├── Notes/
    │   ├── 001_Note_Introduction to Database Management and SQL.pdf
    │   ├── 002_Note_Advanced SQL.pdf
    │   └── merged_notes.pdf
    │
    ├── QB/
    │   ├── 001_QB_Introduction to Database Management and SQL.pdf
    │   ├── 002_QB_Advanced SQL.pdf
    │   └── merged_qb.pdf
    │
    ├── QA/
    │   ├── 001_QA_Introduction to Database Management and SQL.pdf
    │   ├── 002_QA_Advanced SQL.pdf
    │   └── merged_qa.pdf
    │
    └── AV_Summaries/
        ├── 001_Introduction to Database Management and SQL.mp4
        ├── 002_Advanced SQL.mp4
        └── ...
```

The exact folder/file names depend on the course, unit, topic titles, available resources, and configured merge behavior.

The current document downloader writes Slides into the unit root and places QB, Notes, and QA in their corresponding subdirectories. fileciteturn6file0L63-L112

The AV Summary downloader uses an `AV_Summaries` directory below the unit folder. fileciteturn5file2L925-L940

---

# 10. How the Downloader Works

At a high level, the workflow is:

```text
Start main.py
    |
    v
Load configuration / credentials
    |
    v
Launch Chromium with Playwright
    |
    v
Login to PESU Academy
    |
    v
Select semester
    |
    v
Select course + unit(s)
    |
    v
Open the first content page
    |
    v
For each topic/content page:
    |
    +--> identify topic title
    |
    +--> optionally download AV Summary videos
    |
    +--> download Slides
    |
    +--> optionally download Notes
    |
    +--> optionally download QB
    |
    +--> optionally download QA
    |
    +--> record checkpoint
    |
    v
Close browser
    |
    v
Convert PPTX/DOCX resources to PDF
    |
    v
Merge Slides / Notes / QB / QA according to preferences
    |
    v
Ask whether another course/unit should be processed
    |
    v
Exit and clear completed checkpoint
```

The main program intentionally performs conversion and merging only after the Playwright browser has been closed. fileciteturn5file0L331-L408

---

# 11. Topic Navigation and Naming

The automator processes an individual unit as a sequence of content pages.

For each page, it attempts to determine the actual current topic before downloading resources. The current navigation loop then passes the extracted topic to all relevant download functions. fileciteturn6file2L723-L808

The document naming logic prefixes the topic number and category:

```text
Slides: 001_<topic>
Notes:  001_Note_<topic>
QB:     001_QB_<topic>
QA:     001_QA_<topic>
```

This naming scheme is generated before the downloaded file is validated and written to disk. fileciteturn6file0L182-L210

The topic extractor explicitly rejects common resource-tab labels such as `FAQs`, `Slides`, `Notes`, `QB`, `QA`, `AV Summary`, and similar navigation text. It also attempts to distinguish the main-content breadcrumb from the left navigation's `My Courses` entry. fileciteturn5file2L1183-L1254

If extraction still fails, the current navigation logic has a numeric fallback such as `Database Management System Topic 1`. A fallback is logged as a warning so that topic extraction failures can be diagnosed instead of being silent.

---

# 12. AV Summary / Video Pipeline

The AV Summary downloader looks for Vimeo iframe sources and direct MP4 sources in the content page.

For Vimeo content it records both the Vimeo ID and the original embedded player source where available. This is important for embedded/unlisted content because the original player URL can contain parameters required for access. fileciteturn5file2L1512-L1548

The current pipeline can then:

1. preserve the complete player URL;
2. attempt yt-dlp resolution at up to 1080p;
3. reuse browser-derived Vimeo cookies;
4. capture HLS/DASH/media requests in the authenticated browser;
5. inspect HLS manifests;
6. prefer a master playlist;
7. request high-quality video/audio through yt-dlp;
8. validate the resulting MP4.

The quality-selection logic explicitly prefers separate best video and audio streams no higher than 1080p when FFmpeg is available. fileciteturn5file2L833-L917

When FFmpeg is unavailable, the downloader warns that 1080p cannot be guaranteed when Vimeo exposes separate streams. fileciteturn5file2L845-L864

### Video quality troubleshooting

Check:

```bat
yt-dlp --version
ffmpeg -version
```

Then run:

```bat
python main.py --debug
```

Debug mode can reveal the browser requests and responses generated by the Vimeo embed.

If the portal can play a video but the downloader cannot retrieve it, the issue may be related to authenticated/private Vimeo delivery, a portal-side change, or a delivery mechanism that does not expose a downloadable manifest to the browser automation.

---

# 13. PDF Conversion

The conversion stage scans the selected unit folder recursively for `.pptx` and `.docx` files.

PPTX files are sent to:

```text
https://online2pdf.com/convert-pptx-to-pdf
```

and DOCX files are sent to:

```text
https://online2pdf.com/convert-docx-to-pdf
```

The conversion helper works in batches of up to 30 files. It tries to configure the online converter for separate output files, then extracts the returned ZIP when applicable. fileciteturn6file1L338-L342 fileciteturn6file1L480-L542

The conversion step first checks Office-file ZIP integrity before uploading files. Corrupt Office containers are excluded and quarantined. fileciteturn6file1L395-L402

### Important privacy consideration

PPTX/DOCX files processed through this conversion stage are uploaded to the third-party online conversion service used by the implementation. Do not use the automated conversion path for documents that you are not permitted to upload to a third party.

---

# 14. PDF Merging

The merge subsystem treats each resource category independently:

```text
Slides -> unit root
Notes  -> unit root/Notes
QB     -> unit root/QB
QA     -> unit root/QA
```

The implementation stores independent merge preferences:

```dotenv
MERGE_SLIDES=
MERGE_NOTES=
MERGE_QB=
MERGE_QA=
```

and independent source-retention preferences:

```dotenv
KEEP_ONLY_MERGED_SLIDES=
KEEP_ONLY_MERGED_NOTES=
KEEP_ONLY_MERGED_QB=
KEEP_ONLY_MERGED_QA=
```

The current merge subsystem supports the following interactive choices:

```text
1. Always (save preference)
2. Yes
3. No
4. Never ask again
```

For source-file retention it uses the same four-choice structure, with option 1 meaning keep only the merged PDF automatically. fileciteturn5file3L1739-L1807

The PDF merger orders files primarily by their leading numeric prefix, which keeps topic order stable for names such as `001_...`, `002_...`, and so on. fileciteturn5file3L1662-L1678

---

# 15. Saved Preferences in `.env`

The following keys are used by the current implementation.

## Credentials

```dotenv
USERNAME=
PASSWORD=
DONT_ASK_AGAIN=0
```

## Download location

```dotenv
DOWNLOAD_DIR=
```

An empty `DOWNLOAD_DIR` causes the current working directory to be used. A configured directory is created/used as the download root according to the configuration implementation. fileciteturn5file1L579-L585

## Debugging

```dotenv
DEBUG=0
```

Use:

```dotenv
DEBUG=1
```

to enable debug logging even when `--debug` is not supplied.

## Merge preferences

```dotenv
MERGE_SLIDES=
MERGE_NOTES=
MERGE_QB=
MERGE_QA=
```

## Keep-only-merged preferences

```dotenv
KEEP_ONLY_MERGED_SLIDES=
KEEP_ONLY_MERGED_NOTES=
KEEP_ONLY_MERGED_QB=
KEEP_ONLY_MERGED_QA=
```

Preference values used by the merge subsystem are:

```text
1   = always apply the action
0   = do not auto-apply; normal interactive preference state
-1  = never ask again for that category
```

The exact interactive state is maintained by the merge module.

---

# 16. Checkpoint System

The checkpoint file is:

```text
.pesu_checkpoint.json
```

The main program tracks at least:

- downloaded resource identifiers/URLs;
- topic-level progress;
- completed course/unit pairs.

When `--resume` is used, these values are loaded before processing begins. fileciteturn5file0L62-L85 fileciteturn5file0L313-L327

A normal successful run clears the checkpoint at the end.

If the process is interrupted, the checkpoint can remain available for a subsequent `--resume` run.

### Resetting a stuck job

If you intentionally want a completely fresh run and do not want previously recorded checkpoint state to influence processing, delete:

```text
.pesu_checkpoint.json
```

before starting again.

Do this only when you are certain you no longer need the saved progress.

---

# 17. Debugging

## Normal logging

The default logging level is `INFO`.

Example:

```text
10:34:05 [INFO] automate: Current Page (1): Introduction to Machine Learning
```

## Debug logging

Run:

```bat
python main.py --debug
```

The project can also enable debugging with:

```dotenv
DEBUG=1
```

The debugging helper hooks into Playwright page events including browser requests, responses, console output, navigation events, and page errors. fileciteturn0file2L3-L9

## Useful failure patterns

### `yt-dlp is not available`

Verify:

```bat
yt-dlp --version
```

### `ffmpeg is not available`

Verify:

```bat
ffmpeg -version
```

### Topic names are wrong

Run with:

```bat
python main.py --debug
```

and inspect the logged current topic and browser content structure. The topic extractor is intentionally restrictive about UI labels because values such as `FAQs` or `Slides` are resource tabs and not actual topics.

### Browser/page structure changed

PESU Academy page selectors are embedded in the automation code. A redesign of the site can therefore break selection, navigation, topic extraction, tab detection, or resource discovery.

The first diagnostic step should be:

```bat
python main.py --debug
```

### Downloaded document is quarantined

Inspect the `_corrupted` directory inside the relevant folder.

The integrity subsystem can write a quarantine log named:

```text
_quarantine_log.txt
```

with the source filename and reason for quarantine. fileciteturn5file1L97-L112

### Online PDF conversion fails

The conversion system validates Office files before upload and can split stalled batches into smaller batches. A persistent failure for a particular file can result in that file being quarantined rather than blocking all other conversions. fileciteturn6file1L395-L402 fileciteturn6file1L545-L553

---

# 18. Security and Privacy

## PESU credentials

Treat `.env` as a secret file.

Do not:

- commit `.env` to Git;
- paste your password into public issue trackers;
- upload `.env` to ChatGPT, GitHub, Discord, or other public channels;
- share terminal screenshots containing your credentials.

## Third-party PDF conversion

The implemented Office-to-PDF conversion path uploads documents to an external online conversion site. Confirm that this is acceptable for the material you are processing before enabling conversion.

## Browser session

The automator uses an authenticated Playwright browser session to access PESU Academy resources. It does not replace the requirement for a valid PESU account.

## Respect portal access controls

Use the tool only with your own authorized PESU Academy account and only for content you are entitled to access.

---

# 19. Recommended First Run

For the first test after installation, use a small unit and avoid downloading everything at once.

Recommended sequence:

```bat
python --version
python -m playwright --version
yt-dlp --version
ffmpeg -version
```

Then:

```bat
python main.py --no-videos --no-merge --debug
```

This is useful for confirming that login, course selection, unit navigation, topic extraction, and document downloads work correctly before adding the heavier video pipeline and merge stage.

Once the document path is confirmed:

```bat
python main.py --videos --notes --qb --qa --debug
```

For normal usage after the configuration is stable, the simple form is:

```bat
python main.py
```

---

# 20. Direct Module Usage

Most users should use `main.py`.

The other modules are implementation components:

```text
main.py
    Entry point and orchestration

automate.py
    PESU login, course/unit navigation, topic extraction,
    resource downloads, Vimeo handling

config.py
    .env configuration and credential/download settings

debugging.py
    Playwright debugging hooks

file_conversion.py
    PPTX/DOCX -> PDF conversion

integrity.py
    PDF/Office/video integrity checks and quarantine

merge.py
    Category-wise PDF merge and merge preferences
```

`main.py` imports the major operations from these modules and controls the overall run lifecycle. fileciteturn5file0L20-L42

---

# 21. Project Maintenance

Because PESU Academy is a web application, selectors and page behavior can change without notice.

When maintaining the project, pay particular attention to:

- course-table selectors;
- semester dropdown detection;
- unit-list selectors;
- content navigation selectors;
- breadcrumb/topic extraction;
- resource-tab labels;
- `onclick` attributes used to expose document URLs;
- Vimeo iframe/player URLs;
- online2pdf page structure.

The document downloader currently identifies resource entries through elements containing `loadIframe` or `downloadcoursedoc` in their `onclick` attributes. fileciteturn6file0L84-L89 fileciteturn6file0L121-L134

If PESU changes those attributes, resource discovery may need to be updated.

---

# 22. Limitations

The project has several practical limitations:

1. It depends on the current PESU Academy HTML/page structure.
2. A valid authenticated PESU session is required.
3. Video quality is limited by the streams actually exposed to the authenticated embedded Vimeo player.
4. 1080p video/audio combination may require FFmpeg.
5. Some Vimeo assets may use delivery mechanisms that do not expose a downloadable manifest to the browser automation.
6. PPTX/DOCX conversion relies on an external online service.
7. CLI mode selection does not currently encode course/unit numbers directly; those selections remain interactive even when `--multi` is supplied.
8. The site may require different behavior after authentication, session expiration, unexpected network failures, or front-end changes.

---

# 23. Quick Reference

## Standard interactive run

```bat
python main.py
```

## Help

```bat
python main.py --help
```

## Debug

```bat
python main.py --debug
```

## Resume

```bat
python main.py --resume
```

## Skip videos

```bat
python main.py --no-videos
```

## Skip Notes

```bat
python main.py --no-notes
```

## Skip QB

```bat
python main.py --no-qb
```

## Skip QA

```bat
python main.py --no-qa
```

## Force merge

```bat
python main.py --merge
```

## Disable merge

```bat
python main.py --no-merge
```

## Choose semester

```bat
python main.py --semester "Sem-4"
```

## Set download directory

```bat
python main.py --download-dir "D:\PESU Downloads"
```

## Multi-unit mode

```bat
python main.py --multi multi_unit
```

## Multi-course mode

```bat
python main.py --multi multi_course
```

## Verify external tools

```bat
yt-dlp --version
ffmpeg -version
aria2c --version
```

---

# 24. License

See the repository's `LICENSE` file for the project's license terms.

---

# 25. Final Checklist

Before running the automator, verify:

```text
[ ] Python 3.10+ installed
[ ] Virtual environment activated
[ ] Python dependencies installed
[ ] Playwright Chromium installed
[ ] PESU credentials available
[ ] yt-dlp available on PATH
[ ] FFmpeg available on PATH for high-quality video/audio downloads
[ ] Optional aria2c available if desired
[ ] .env is protected and not committed publicly
[ ] Download directory has sufficient free space
[ ] Third-party PDF conversion is acceptable for the documents being processed
```

Then run:

```bat
python main.py
```

For the first diagnostic run, use:

```bat
python main.py --no-videos --no-merge --debug
```

Once the document workflow is confirmed, enable AV Summaries and merging as needed.
