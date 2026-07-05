import difflib
import io
import re
import zipfile
import streamlit as st
from pathlib import Path
from datetime import datetime

from core.api import rough_token_count
from core.config import save_config

# Refine sends system + prompt + full code + instruction; past this rough
# estimate the payload may bust smaller local context windows (8–16k).
REFINE_CONTEXT_WARN_TOKENS = 12_000

# Language detection mapping
LANGUAGE_EXTENSIONS = {
    "python": "py", "react": "jsx", "javascript": "js",
    "typescript": "ts", "tsx": "tsx", "jsx": "jsx",
    "html": "html", "css": "css", "sql": "sql",
    "rust": "rs", "go": "go", "java": "java",
    "c++": "cpp", "cpp": "cpp", "c#": "cs", "csharp": "cs",
    "ruby": "rb", "php": "php", "swift": "swift",
    "kotlin": "kt", "scala": "scala", "shell": "sh",
    "bash": "sh", "powershell": "ps1",
    "fastapi": "py", "flask": "py", "django": "py",
    "node": "js", "express": "js", "vue": "vue",
    "svelte": "svelte", "angular": "ts",
}

# Language display names for st.code()
LANGUAGE_DISPLAY = {
    "py": "python", "js": "javascript", "ts": "typescript",
    "jsx": "javascript", "tsx": "typescript", "html": "html",
    "css": "css", "sql": "sql", "rs": "rust", "go": "go",
    "java": "java", "cpp": "cpp", "cs": "csharp",
    "rb": "ruby", "php": "php", "swift": "swift",
    "kt": "kotlin", "sh": "bash", "ps1": "powershell",
    "vue": "javascript", "svelte": "javascript",
}

FENCE_RE = re.compile(r"```([\w+#.-]*)[ \t]*\n(.*?)```", re.DOTALL)

# A bare filename (with extension), optionally with a relative path —
# used to recognize file announcements like '**app.py**' or '### src/main.js'
FILENAME_RE = re.compile(r"[\w.][\w.\-/\\]*\.[A-Za-z0-9]{1,10}")


def extract_code(raw: str) -> tuple[str, str]:
    """
    Extract code from markdown fences, tolerating prose around the block.
    Returns (code, fence_language). If multiple fenced blocks exist, the
    largest one is used. If none exist, the raw text is returned as-is.
    """
    blocks = FENCE_RE.findall(raw)
    if blocks:
        lang, code = max(blocks, key=lambda b: len(b[1]))
        return code.strip(), lang.lower()
    return raw.strip(), ""


def _safe_relpath(name: str) -> str:
    """Normalize a model-supplied filename to a safe relative path
    (forward slashes, no absolute/parent segments)."""
    parts = [
        p for p in name.replace("\\", "/").split("/")
        if p and p not in (".", "..")
    ]
    return "/".join(parts)


def extract_files(raw: str) -> list[dict]:
    """
    Parse every fenced block into {"name": str | None, "lang": str, "code": str}.
    A filename is picked up when the last non-empty line before a fence is
    just a (possibly bold/backticked) filename — the way models usually
    announce multi-file output. Returns [] when the text has no fences.
    """
    files = []
    for m in FENCE_RE.finditer(raw):
        lang, code = m.group(1).lower(), m.group(2).strip()
        if not code:
            continue
        name = None
        preceding = raw[: m.start()].rstrip().splitlines()
        if preceding:
            candidate = preceding[-1].strip().strip("*_`#:— ").strip()
            if FILENAME_RE.fullmatch(candidate):
                name = _safe_relpath(candidate) or None
        files.append({"name": name, "lang": lang, "code": code})
    return files


def _resolve_filenames(files: list[dict], task: str) -> list[str]:
    """Give every block a unique filename: the announced one when present,
    otherwise file_N with a detected extension."""
    names: list[str] = []
    for i, f in enumerate(files):
        name = f["name"]
        if not name:
            ext = detect_language(task, f["code"], f["lang"])
            name = f"file_{i + 1}.{ext}"
        while name in names:  # duplicate announcements — keep both
            stem, dot, ext = name.rpartition(".")
            name = f"{stem}_{i + 1}{dot}{ext}" if dot else f"{name}_{i + 1}"
        names.append(name)
    return names


def detect_language(task: str, code: str, fence_lang: str = "") -> str:
    """
    Detect the programming language and return its file extension.
    Priority: code fence tag > task description keywords > code heuristics.
    """
    # The model's own fence tag is the most reliable signal
    if fence_lang:
        if fence_lang in LANGUAGE_EXTENSIONS:
            return LANGUAGE_EXTENSIONS[fence_lang]
        if fence_lang in LANGUAGE_DISPLAY:  # already an extension like "py"
            return fence_lang

    # Whole-word match so e.g. "go" doesn't fire inside "logo" or "good"
    task_lower = task.lower()
    for keyword, ext in LANGUAGE_EXTENSIONS.items():
        if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", task_lower):
            return ext

    # Check first line of code for shebangs or common patterns
    first_line = code.strip().split("\n")[0] if code.strip() else ""
    if first_line.startswith("#!/usr/bin/env python") or first_line.startswith("import ") or first_line.startswith("from "):
        return "py"
    if first_line.startswith("//") or "function " in first_line or "const " in first_line:
        return "js"
    if "<html" in code.lower() or "<!doctype" in code.lower():
        return "html"

    return "py"  # Default fallback


def suggest_filename(task: str, extension: str) -> str:
    """Generate a suggested filename from the task description."""
    # Clean up the task text
    cleaned = task.lower().strip()

    # Remove common filler words
    filler = ["a", "an", "the", "that", "which", "with", "for", "and", "or",
              "to", "in", "on", "at", "by", "is", "it", "of", "make", "create",
              "build", "write", "generate", "implement", "develop"]

    words = re.sub(r'[^a-z0-9\s]', '', cleaned).split()
    words = [w for w in words if w not in filler and len(w) > 1]

    # Take first 4 meaningful words
    name_parts = words[:4]

    if not name_parts:
        name_parts = ["generated_code"]

    filename = "_".join(name_parts)
    return f"{filename}.{extension}"


def _revert_code():
    """on_click: restore the newest entry of the version stack as the
    current code (the discarded current version is not kept)."""
    versions = st.session_state.get("code_versions") or []
    if versions:
        st.session_state["generated_code"] = versions.pop()


def render_code_output():
    """
    Render the final output page: prompt and code side by side,
    with save / copy / regenerate / refine actions.
    Returns:
        'start_over' if user clicks Start over,
        'regenerate' if user wants to re-run the coder with the edited prompt,
        'refine' if user wants a follow-up pass over the current code
            (instruction stored in st.session_state['refine_instruction']),
        None otherwise.
    """
    st.markdown("## Result")

    raw = st.session_state.get("generated_code", "")
    task = st.session_state.get("task_description", "")
    config = st.session_state.get("config", {})

    # Extract code from markdown fences (handles prose around the block)
    code, fence_lang = extract_code(raw)
    # All fenced blocks — more than one means multi-file output
    files = extract_files(raw)
    multi = len(files) > 1

    # Detect language (of the largest block)
    extension = detect_language(task, code, fence_lang)
    lang_display = LANGUAGE_DISPLAY.get(extension, "text")

    # ── Original idea (read-only) — the task typed in step 1, shown above the
    # refined prompt for reference (mirrors the prompt-review step) ──
    with st.expander("Original task", expanded=False):
        st.markdown(f"```\n{task}\n```")

    # ── Prompt (editable) — secondary on the output page, so it's tucked into
    # an expander to give the code the full content width ──
    with st.expander("📝 Prompt sent to the Coder — edit & regenerate", expanded=False):
        edited_prompt = st.text_area(
            "Prompt sent to the Coder",
            value=st.session_state.get("generated_prompt", ""),
            height=300,
            key="output_prompt_area",
            label_visibility="collapsed",
        )
        regenerate = st.button(
            "Regenerate code with this prompt",
            key="regenerate_code_btn",
            use_container_width=True,
        )

    if regenerate:
        st.session_state["generated_prompt"] = edited_prompt
        return "regenerate"

    # ── Code — single block full-width, or one tab per file ──
    if multi:
        filenames = _resolve_filenames(files, task)
        st.markdown(
            '<div class="pc-code-header">'
            f'<span class="pc-code-lang">{len(files)} files</span>'
            f'<span class="pc-code-lines">'
            f'{sum(f["code"].count(chr(10)) + 1 for f in files)} lines</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        for tab, f in zip(st.tabs(filenames), files):
            with tab:
                f_ext = detect_language(task, f["code"], f["lang"])
                st.code(
                    f["code"],
                    language=LANGUAGE_DISPLAY.get(f_ext, "text"),
                    line_numbers=True,
                )
    else:
        filenames = []
        line_count = code.count("\n") + 1 if code.strip() else 0
        st.markdown(
            '<div class="pc-code-header">'
            f'<span class="pc-code-lang">{lang_display}</span>'
            f'<span class="pc-code-lines">{line_count} lines</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.code(code, language=lang_display, line_numbers=True)
    st.caption("Copy with the icon in the code block's top-right corner, or use **Download** below.")

    # ── Previous versions: diff of the last refine/regenerate + revert ──
    versions = st.session_state.get("code_versions") or []
    if versions:
        with st.expander(f"Previous versions ({len(versions)})", expanded=False):
            prev_code, _ = extract_code(versions[-1])
            diff_text = "\n".join(
                difflib.unified_diff(
                    prev_code.splitlines(),
                    code.splitlines(),
                    fromfile="previous version",
                    tofile="current version",
                    lineterm="",
                )
            )
            if diff_text:
                st.code(diff_text, language="diff")
            else:
                st.caption("No differences from the previous version.")
            st.button(
                "Revert to previous version",
                key="revert_code_btn",
                on_click=_revert_code,
                help="Discard the current code and restore the version above",
            )

    # ── Refine: follow-up instruction sent with the current code ──
    st.markdown("#### Refine")
    refine_text = st.text_area(
        "Follow-up instruction",
        placeholder=(
            "e.g., Make the board bigger, add a restart button, "
            "fix the score reset bug"
        ),
        height=80,
        key="refine_instruction_area",
        label_visibility="collapsed",
    )
    # Context guard: refine resends the whole prompt + code, which can
    # silently overflow a small local context window (the model then
    # "refines" code it never fully saw)
    est_tokens = rough_token_count(
        st.session_state.get("coder_system", ""),
        st.session_state.get("generated_prompt", ""),
        raw,
        refine_text or "",
    )
    st.caption(
        f"Refine sends the prompt + current code + instruction: "
        f"~{est_tokens:,} tokens (rough estimate)."
    )
    if est_tokens > REFINE_CONTEXT_WARN_TOKENS:
        st.warning(
            f"This refine payload is large (~{est_tokens:,} tokens) and may "
            "exceed smaller local context windows — the model would silently "
            "see truncated code. Consider **Regenerate** with an edited "
            "prompt instead."
        )

    refine_clicked = st.button(
        "Refine code",
        key="refine_code_btn",
        disabled=(not refine_text or not refine_text.strip()),
        help=(
            "Sends the current code plus this instruction back to the "
            "Coder, which edits in place instead of starting over"
        ),
    )

    if refine_clicked and refine_text and refine_text.strip():
        st.session_state["refine_instruction"] = refine_text.strip()
        return "refine"

    # ── Filename & Save ──
    st.markdown("---")

    suggested = suggest_filename(task, extension)

    if multi:
        # Filenames come from the files themselves; only the folder is asked
        output_folder = st.text_input(
            "Output folder",
            value=config.get("output_folder", "./output"),
            key="output_folder_display",
        )
        filename = ""
    else:
        col_name, col_folder = st.columns([1, 1])
        with col_name:
            filename = st.text_input(
                "Filename",
                value=suggested,
                key="output_filename"
            )
        with col_folder:
            output_folder = st.text_input(
                "Output folder",
                value=config.get("output_folder", "./output"),
                key="output_folder_display"
            )

    # ── Action Buttons ──
    # (Copy lives on the code block itself — the icon in its top-right.)
    col1, col2, col3 = st.columns(3)

    with col1:
        save_clicked = st.button(
            "Save all files" if multi else "Save file",
            key="save_file_btn",
            type="primary",
            use_container_width=True
        )

    with col2:
        # Browser-side download — works even when the app runs on
        # another machine, where "Save file" only writes server-side
        if multi:
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for name, f in zip(filenames, files):
                    zf.writestr(name, f["code"])
            st.download_button(
                "Download all (.zip)",
                data=zip_buf.getvalue(),
                file_name=suggest_filename(task, "zip"),
                mime="application/zip",
                key="download_code_btn",
                use_container_width=True,
            )
        else:
            st.download_button(
                "Download",
                data=code,
                file_name=filename or suggested,
                mime="text/plain",
                key="download_code_btn",
                use_container_width=True,
            )

    with col3:
        start_over = st.button(
            "Start over",
            key="start_over_btn",
            use_container_width=True
        )

    # ── Handle Save ──
    if save_clicked:
        try:
            folder = Path(output_folder)
            # Add timestamp prefix to avoid overwrites
            timestamp = datetime.now().strftime("%Y_%m_%d_%H%M%S")

            if multi:
                # All files land in one timestamped subfolder, preserving
                # any relative paths the model announced
                run_folder = folder / f"{timestamp}_{suggested.rsplit('.', 1)[0]}"
                for name, f in zip(filenames, files):
                    filepath = run_folder / name
                    filepath.parent.mkdir(parents=True, exist_ok=True)
                    filepath.write_text(f["code"], encoding="utf-8")
                st.success(f"Saved {len(files)} files to `{run_folder}`")
            else:
                folder.mkdir(parents=True, exist_ok=True)
                filepath = folder / f"{timestamp}_{filename}"
                filepath.write_text(code, encoding="utf-8")
                st.success(f"Saved to `{filepath}`")

            # Persist a changed output folder for future sessions
            if output_folder != config.get("output_folder"):
                config["output_folder"] = output_folder
                save_config(config)
                st.session_state["config"] = config
        except Exception as e:
            st.error(f"Failed to save: {str(e)}")

    if start_over:
        return "start_over"

    return None
