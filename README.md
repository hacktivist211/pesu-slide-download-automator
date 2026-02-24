# PESU Academy Automator

## Project Overview

The **PESU Academy Automator** is a rigorously engineered Python framework designed to streamline the extraction, conversion, and organization of academic resources from the PESU Academy portal. This utility eliminates the manual overhead of navigating complex web structures, providing a unified pipeline for high-fidelity content acquisition and post-processing.

---

## Core Functionalities

### 1. Automated Content Acquisition

The system utilizes `Playwright` for high-precision browser automation to handle the portal's dynamic interface.

* **Session Management**: Securely authenticates user credentials and maintains session persistence using `.env` configurations.
* **Intelligent Navigation**: Programmatically traverses course hierarchies, selecting specific units and iterating through slide-based content.
* **Multi-Format Extraction**: Simultaneously identifies and retrieves Presentation Slides, Supplementary Notes, and Question Banks (QB).
* **AV Summary Resolution**: Implements a custom logic to resolve and download direct MP4 streams and Vimeo-hosted video content.

### 2. Batch Presentation Conversion

To ensure document portability, the tool features a dedicated conversion module for transforming proprietary slide formats.

* **Cloud-Based Conversion**: Leverages the iLovePDF engine via headless browser sessions to convert `.pptx` files to standardized `.pdf`.
* **Batch Optimization**: Processes files in configurable batches (defaulting to 3) to optimize throughput while respecting service constraints.
* **Archive Management**: Automatically extracts and flattens ZIP archives downloaded during the conversion process.

### 3. PDF Consolidation and Management

The merging module provides sophisticated file-handling to organize all downloaded assets into a professional document structure.

* **Linear Merging**: Sequentially combines PDFs based on numerical topic ordering derived from file names.
* **Dynamic Scope Control**: Allows users to define whether the final output should include only slides or integrate relevant Question Banks.
* **Storage Optimization**: Offers automated cleanup options to delete source files post-merge, maintaining a clean workspace.

---

## Technical Architecture

| Component | Module | Primary Responsibility |
| --- | --- | --- |
| **Orchestrator** | `main.py` | Manages execution flow, user input, and session lifecycle. |
| **Automation Engine** | `automate.py` | Handles DOM interaction, login sequences, and scraping. |
| **Conversion Logic** | `file_conversion.py` | Manages PPTX-to-PDF transformations and ZIP extraction. |
| **PDF Processor** | `merge.py` | Executes PDF merging and source file cleanup. |
| **Configuration** | `config.py` | Persists credentials and user preferences across sessions. |
| **Debugging** | `debugging.py` | Provides hooks for console, network, and DOM event logging. |

---

## Program Output and Artifacts

Upon successful execution, the system generates a structured directory named according to the course and unit. The final artifacts include:

* **Merged PDF Document**: A single file (e.g., `merged.pdf`) containing all processed slides in chronological order.
* **AV Summaries**: A subfolder containing downloaded video content named sequentially.
* **Supplementary Material**: Organized subdirectories for Notes and Question Banks if selected during the prompt.
* **Configuration State**: An updated `.env` file reflecting your saved credentials and process preferences (e.g., `MERGE_PDFS=1`).

Would you like me to generate a `requirements.txt` file or a setup script to initialize this environment?
