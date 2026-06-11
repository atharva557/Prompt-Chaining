import json
import re
import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path
from datetime import datetime

from core.config import save_config

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


def render_copy_button(code: str):
    """Render a clipboard copy button using JavaScript Clipboard API."""
    # json.dumps produces a valid JS string literal, so the code can be
    # embedded directly without manual escaping or entity round-trips.
    # "</" is escaped so code containing "</script>" can't break out of
    # the script block ("<\/" is identical inside a JS string).
    escaped_code = json.dumps(code).replace("</", "<\\/")

    copy_html = f"""
    <div style="display:flex; justify-content:center;">
        <button id="copyBtn" onclick="copyCode()" style="
            background: #30302e;
            color: #eceae4;
            border: 1px solid #3d3d3a;
            padding: 0.5rem 1.4rem;
            border-radius: 999px;
            font-family: 'Inter', sans-serif;
            font-weight: 500;
            font-size: 0.9rem;
            cursor: pointer;
            width: 100%;
            transition: background 0.15s ease, border-color 0.15s ease;
        " onmouseover="this.style.background='#3a3a37'" onmouseout="this.style.background='#30302e'">Copy code</button>
    </div>
    <script>
    function copyCode() {{
        const code = {escaped_code};
        navigator.clipboard.writeText(code).then(() => {{
            const btn = document.getElementById('copyBtn');
            btn.textContent = 'Copied';
            btn.style.color = '#4ade80';
            btn.style.borderColor = '#4ade80';
            setTimeout(() => {{
                btn.textContent = 'Copy code';
                btn.style.color = '#eceae4';
                btn.style.borderColor = '#3d3d3a';
            }}, 2000);
        }}).catch(() => {{
            const btn = document.getElementById('copyBtn');
            btn.textContent = 'Copy failed';
            btn.style.color = '#f87171';
            setTimeout(() => {{
                btn.textContent = 'Copy code';
                btn.style.color = '#eceae4';
            }}, 2000);
        }});
    }}
    </script>
    """
    # components.html (not st.iframe) — available on all supported
    # Streamlit versions, and scripts execute inside the sandbox iframe.
    components.html(copy_html, height=50)


def render_code_output():
    """
    Render the final output page: prompt and code side by side,
    with save / copy / regenerate actions.
    Returns:
        'start_over' if user clicks Start over,
        'regenerate' if user wants to re-run the coder with the edited prompt,
        None otherwise.
    """
    st.markdown("## Result")

    raw = st.session_state.get("generated_code", "")
    task = st.session_state.get("task_description", "")
    config = st.session_state.get("config", {})

    # Extract code from markdown fences (handles prose around the block)
    code, fence_lang = extract_code(raw)

    # Detect language
    extension = detect_language(task, code, fence_lang)
    lang_display = LANGUAGE_DISPLAY.get(extension, "text")

    # ── Side-by-side: prompt (editable) | code ──
    col_prompt, col_code = st.columns([1, 1.3], gap="medium")

    with col_prompt:
        st.markdown("#### Prompt")
        edited_prompt = st.text_area(
            "Prompt sent to the Coder",
            value=st.session_state.get("generated_prompt", ""),
            height=420,
            key="output_prompt_area",
            label_visibility="collapsed",
        )
        regenerate = st.button(
            "Regenerate code with this prompt",
            key="regenerate_code_btn",
            use_container_width=True,
        )

    with col_code:
        st.markdown("#### Code")
        st.code(code, language=lang_display, line_numbers=True)

    if regenerate:
        st.session_state["generated_prompt"] = edited_prompt
        return "regenerate"

    # ── Filename & Save ──
    st.markdown("---")

    suggested = suggest_filename(task, extension)

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
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        save_clicked = st.button(
            "Save file",
            key="save_file_btn",
            type="primary",
            use_container_width=True
        )

    with col2:
        # Browser-side download — works even when the app runs on
        # another machine, where "Save file" only writes server-side
        st.download_button(
            "Download",
            data=code,
            file_name=filename or suggested,
            mime="text/plain",
            key="download_code_btn",
            use_container_width=True,
        )

    with col3:
        render_copy_button(code)

    with col4:
        start_over = st.button(
            "Start over",
            key="start_over_btn",
            use_container_width=True
        )

    # ── Handle Save ──
    if save_clicked:
        try:
            folder = Path(output_folder)
            folder.mkdir(parents=True, exist_ok=True)

            # Add timestamp prefix to avoid overwrites
            timestamp = datetime.now().strftime("%Y_%m_%d_%H%M%S")
            final_name = f"{timestamp}_{filename}"
            filepath = folder / final_name

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
