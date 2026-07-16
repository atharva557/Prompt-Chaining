import streamlit as st

def inject_custom_css():
    """Inject the app theme CSS (Tokyo Night — blue accent on deep blue-black)."""
    st.markdown("""
    <style>
    /* ═══════════════════════════════════════════════════════
       PROMPTCHAIN — Tokyo Night Theme
       Deep blue-black background (#1a1b26), blue accent (#7aa2f7),
       pill buttons, centered content column.
       ═══════════════════════════════════════════════════════ */

    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=JetBrains+Mono:wght@400;500&display=swap');

    /* ── Root Variables ── */
    :root {
        --pc-bg: #1a1b26;
        --pc-bg-secondary: #16161e;   /* darker — sidebar + code blocks */
        --pc-surface: #24283b;        /* raised surfaces: cards, inputs, buttons */
        --pc-surface-hover: #2f3549;
        --pc-border: #343a52;
        --pc-border-strong: #545c7e;
        --pc-text: #dde3f7;
        --pc-text-muted: #9aa3cc;
        --pc-accent: #7aa2f7;
        --pc-accent-hover: #6b8de0;
        --pc-success: #9ece6a;
        --pc-warning: #e0af68;
        --pc-error: #f7768e;
        /* Legacy aliases kept for components that reference them */
        --pc-primary: #7aa2f7;
        --pc-primary-light: #89b4fa;
        --pc-primary-glow: rgba(122, 162, 247, 0.25);
    }

    /* ── Layout: centered content column ── */
    .block-container {
        max-width: 52rem !important;
        margin: 0 auto;
        padding-top: 2.5rem !important;
    }

    /* ── Typography ── */
    .stApp {
        font-family: 'Inter', sans-serif !important;
        color: var(--pc-text);
    }

    h1, h2 {
        font-family: 'Source Serif 4', Georgia, serif !important;
        font-weight: 600 !important;
        letter-spacing: -0.01em !important;
        color: var(--pc-text) !important;
    }

    h3, h4, h5, h6 {
        font-family: 'Inter', sans-serif !important;
        font-weight: 600 !important;
        color: var(--pc-text) !important;
    }

    code, pre, .stCodeBlock {
        font-family: 'JetBrains Mono', monospace !important;
    }

    /* ── Sidebar ── */
    section[data-testid="stSidebar"] {
        background: var(--pc-bg-secondary) !important;
        border-right: 1px solid var(--pc-border) !important;
    }

    section[data-testid="stSidebar"] .stMarkdown h1 {
        font-family: 'Source Serif 4', Georgia, serif !important;
        font-size: 1.4rem !important;
        color: var(--pc-text) !important;
    }

    /* ── Buttons: pill-shaped, flat ── */
    .stButton > button {
        border-radius: 999px !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 500 !important;
        font-size: 0.9rem !important;
        padding: 0.5rem 1.4rem !important;
        background: var(--pc-surface) !important;
        color: var(--pc-text) !important;
        border: 1px solid var(--pc-border) !important;
        transition: background 0.15s ease, border-color 0.15s ease !important;
        box-shadow: none !important;
    }

    .stButton > button:hover {
        background: var(--pc-surface-hover) !important;
        border-color: var(--pc-border-strong) !important;
    }

    .stButton > button[kind="primary"] {
        background: var(--pc-accent) !important;
        border: 1px solid var(--pc-accent) !important;
        color: #1a1b26 !important;   /* dark — readable on the light-blue accent */
        font-weight: 600 !important;
    }

    .stButton > button[kind="primary"]:hover {
        background: var(--pc-accent-hover) !important;
        border-color: var(--pc-accent-hover) !important;
    }

    .stButton > button:disabled {
        opacity: 0.45 !important;
    }

    /* ── Inputs ── */
    .stTextArea textarea,
    .stTextInput input {
        border-radius: 12px !important;
        border: 1px solid var(--pc-border) !important;
        background: var(--pc-surface) !important;
        color: var(--pc-text) !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 0.92rem !important;
        transition: border-color 0.15s ease !important;
    }

    .stTextArea textarea:focus,
    .stTextInput input:focus {
        border-color: var(--pc-accent) !important;
        box-shadow: 0 0 0 1px var(--pc-accent) !important;
    }

    .stSelectbox > div > div {
        border-radius: 12px !important;
        border: 1px solid var(--pc-border) !important;
        background: var(--pc-surface) !important;
    }

    .stSelectbox > div > div:hover {
        border-color: var(--pc-border-strong) !important;
    }

    /* Sliders are themed natively via [theme] primaryColor in
       .streamlit/config.toml (same #7aa2f7 as --pc-accent). Do NOT re-color
       them with a nested-div selector: it repaints the whole track solid and
       kills the filled-vs-unfilled gradient. */

    /* ── Expanders ── */
    [data-testid="stExpander"] {
        border: 1px solid var(--pc-border) !important;
        border-radius: 12px !important;
        background: var(--pc-surface) !important;
    }

    /* ── Code Blocks ── */
    .stCodeBlock,
    [data-testid="stCode"],
    [data-testid="stCodeBlock"] {
        border-radius: 12px !important;
        border: 1px solid var(--pc-border) !important;
        background: var(--pc-bg-secondary) !important;
        overflow: hidden !important;
    }

    /* Constrain very long output to a scrollable pane and make it readable */
    .stCodeBlock pre,
    [data-testid="stCode"] pre,
    [data-testid="stCodeBlock"] pre {
        max-height: 60vh !important;
        overflow: auto !important;
        background: var(--pc-bg-secondary) !important;
        padding: 0.9rem 1rem !important;
        margin: 0 !important;
    }

    .stCodeBlock code,
    [data-testid="stCode"] code,
    [data-testid="stCodeBlock"] code {
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 0.82rem !important;
        line-height: 1.6 !important;
    }

    /* Line-number gutter: muted and given a little breathing room */
    [data-testid="stCode"] pre code .comment,
    [data-testid="stCodeBlock"] .line-number {
        color: var(--pc-text-muted) !important;
    }

    /* Code panel header bar (language badge + line count) */
    .pc-code-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: var(--pc-surface);
        border: 1px solid var(--pc-border);
        border-radius: 10px;
        padding: 0.4rem 0.9rem;
        margin: 0.3rem 0 0.45rem 0;
    }
    .pc-code-lang {
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.72rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--pc-accent);
    }
    .pc-code-lines {
        font-family: 'Inter', sans-serif;
        font-size: 0.75rem;
        color: var(--pc-text-muted);
    }

    /* ── Step Progress Indicator ── */
    .step-indicator {
        display: flex;
        justify-content: center;
        align-items: center;
        padding: 0.5rem 0 1rem 0;
        margin-bottom: 1.5rem;
    }

    .step-item {
        display: flex;
        align-items: center;
        gap: 0.45rem;
        padding: 0.35rem 0.9rem;
        border-radius: 999px;
        font-family: 'Inter', sans-serif;
        font-size: 0.82rem;
        font-weight: 500;
        color: var(--pc-text-muted);
        transition: all 0.2s ease;
    }

    .step-item.active {
        background: var(--pc-primary-glow);
        color: var(--pc-accent);
        border: 1px solid rgba(122, 162, 247, 0.45);
    }

    .step-item.completed {
        color: var(--pc-text);
    }

    .step-connector {
        width: 28px;
        height: 1px;
        background: var(--pc-border);
        margin: 0 0.2rem;
    }

    .step-connector.completed {
        background: var(--pc-border-strong);
    }

    .step-number {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 20px;
        height: 20px;
        border-radius: 50%;
        font-size: 0.7rem;
        font-weight: 600;
        border: 1px solid currentColor;
    }

    .step-item.completed .step-number {
        background: var(--pc-surface);
        border-color: var(--pc-border-strong);
        color: var(--pc-text-muted);
    }

    .step-item.active .step-number {
        background: var(--pc-accent);
        border-color: var(--pc-accent);
        color: #1a1b26;   /* dark on the light-blue accent, like primary buttons */
    }

    /* ── Status Messages ── */
    .status-message {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.7rem 1.1rem;
        border-radius: 12px;
        margin: 0.5rem 0;
        font-family: 'Inter', sans-serif;
        font-size: 0.9rem;
        border: 1px solid var(--pc-border);
        background: var(--pc-surface);
    }

    .status-running { color: var(--pc-text); }
    .status-success { color: var(--pc-success); }
    .status-error   { color: var(--pc-error); }
    .status-warning { color: var(--pc-warning); }

    /* ── Connection Badge ── */
    .connection-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.25rem 0.7rem;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 500;
        font-family: 'Inter', sans-serif;
        border: 1px solid var(--pc-border);
        background: var(--pc-surface);
    }

    .connection-badge.connected { color: var(--pc-success); }
    .connection-badge.disconnected { color: var(--pc-error); }

    /* ── Divider ── */
    .pc-divider {
        border: none;
        height: 1px;
        background: var(--pc-border);
        margin: 1.25rem 0;
    }

    /* ── Cards ── */
    .glass-card {
        background: var(--pc-surface);
        border: 1px solid var(--pc-border);
        border-radius: 12px;
        padding: 1.25rem;
        margin-bottom: 1rem;
    }

    /* ── Spinner ── */
    @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }

    .spinner {
        display: inline-block;
        width: 14px;
        height: 14px;
        border: 2px solid var(--pc-border-strong);
        border-top-color: var(--pc-accent);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
    }

    /* ── Sidebar section headings ── */
    .pc-sidebar-heading {
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--pc-text-muted);
        margin: 0.2rem 0 0.45rem 0;
    }

    /* ── Sidebar history list ── */
    /* Open buttons: quiet, left-aligned rows that light up on hover */
    section[data-testid="stSidebar"] [class*="st-key-hist_"] button {
        justify-content: flex-start !important;
        text-align: left !important;
        background: transparent !important;
        border-color: transparent !important;
        border-radius: 10px !important;
        padding: 0.3rem 0.7rem !important;
    }
    section[data-testid="stSidebar"] [class*="st-key-hist_"] button:hover {
        background: var(--pc-surface) !important;
        border-color: var(--pc-border) !important;
    }
    /* The button's inner flex wrapper centers its content by default */
    section[data-testid="stSidebar"] [class*="st-key-hist_"] button > div {
        justify-content: flex-start !important;
    }
    section[data-testid="stSidebar"] [class*="st-key-hist_"] button p {
        font-size: 0.8rem !important;
        text-align: left !important;
        width: 100%;
    }
    /* Delete buttons: ghost ✕ that turns red on hover */
    section[data-testid="stSidebar"] [class*="st-key-histdel_"] button {
        background: transparent !important;
        border-color: transparent !important;
        color: var(--pc-text-muted) !important;
        padding: 0.3rem 0.45rem !important;
    }
    section[data-testid="stSidebar"] [class*="st-key-histdel_"] button:hover {
        color: var(--pc-error) !important;
        background: rgba(247, 118, 142, 0.12) !important;
        border-color: transparent !important;
    }

    /* ── Chat messages: raised cards instead of bare text ── */
    [data-testid="stChatMessage"] {
        background: var(--pc-surface);
        border: 1px solid var(--pc-border);
        border-radius: 14px;
        padding: 0.85rem 1rem;
        margin-bottom: 0.4rem;
    }

    /* ── Model Info Card ── */
    .model-info {
        background: var(--pc-surface);
        border: 1px solid var(--pc-border);
        border-radius: 10px;
        padding: 0.55rem 0.8rem;
        margin: 0.4rem 0;
        font-size: 0.8rem;
    }

    .model-info .label {
        color: var(--pc-text-muted);
        font-size: 0.68rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 0.15rem;
    }

    .model-info .value {
        color: var(--pc-text);
        font-weight: 500;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.78rem;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    /* ── Scrollbar ── */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: var(--pc-border-strong); border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: var(--pc-text-muted); }

    /* ── Hide Streamlit Defaults ── */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    header[data-testid="stHeader"] { background: transparent !important; }

    /* Hide the "Deploy" button and the dev toolbar actions */
    [data-testid="stAppDeployButton"],
    .stDeployButton,
    [data-testid="stToolbarActions"] { display: none !important; }
</style>
    """, unsafe_allow_html=True)


def render_step_indicator(current_step: int):
    """Render the step progress indicator at the top of the page."""
    steps = ["Task", "Review", "Generate", "Output"]

    html_parts = ['<div class="step-indicator">']

    for i, label in enumerate(steps):
        if i < current_step:
            state = "completed"
            number_content = "&#10003;"
        elif i == current_step:
            state = "active"
            number_content = str(i + 1)
        else:
            state = ""
            number_content = str(i + 1)

        html_parts.append(
            f'<div class="step-item {state}">'
            f'<span class="step-number">{number_content}</span>'
            f'{label}</div>'
        )

        if i < len(steps) - 1:
            conn_state = "completed" if i < current_step else ""
            html_parts.append(f'<div class="step-connector {conn_state}"></div>')

    html_parts.append('</div>')

    st.markdown(''.join(html_parts), unsafe_allow_html=True)


def render_status_message(message: str, status: str = "running"):
    """
    Render a styled status message.
    status: 'running', 'success', 'error', 'warning'
    """
    icons = {
        "running": '<span class="spinner"></span>',
        "success": "&#10003;",
        "error": "&#10005;",
        "warning": "!"
    }
    icon = icons.get(status, "")
    st.markdown(
        f'<div class="status-message status-{status}">{icon} {message}</div>',
        unsafe_allow_html=True
    )


def render_glass_card(content: str):
    """Wrap content in a bordered card."""
    st.markdown(f'<div class="glass-card">{content}</div>', unsafe_allow_html=True)


def render_connection_badge(connected: bool, reason: str = ""):
    """Render a connection status badge. `reason` becomes a hover tooltip
    (e.g. why an endpoint is disconnected)."""
    title = f' title="{reason}"' if reason else ""
    if connected:
        st.markdown(
            f'<div class="connection-badge connected"{title}>● Connected</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            f'<div class="connection-badge disconnected"{title}>● Disconnected</div>',
            unsafe_allow_html=True
        )


def render_model_info(label: str, model_name: str):
    """Render a model info card in the sidebar."""
    display_name = model_name if model_name else "Not selected"
    st.markdown(
        f'<div class="model-info">'
        f'<div class="label">{label}</div>'
        f'<div class="value">{display_name}</div>'
        f'</div>',
        unsafe_allow_html=True
    )


def render_divider():
    """Render a styled divider."""
    st.markdown('<hr class="pc-divider">', unsafe_allow_html=True)


def render_sidebar_heading(text: str):
    """Small uppercase section label for the sidebar (History, Endpoints…)."""
    st.markdown(
        f'<div class="pc-sidebar-heading">{text}</div>', unsafe_allow_html=True
    )


def logo_html(variant: str = "sidebar") -> str:
    """The PromptChain wordmark with a chain-link mark (inline SVG, themed via
    var(--pc-accent)). variant: 'sidebar' (small, left) or 'hero' (large,
    centered)."""
    if variant == "hero":
        svg_size, word_size, justify, margin = "2.6rem", "2.9rem", "center", "0 0 0.6rem"
    else:
        svg_size, word_size, justify, margin = "1.5rem", "1.4rem", "flex-start", "0.1rem 0 0.5rem"
    return (
        f'<div style="display:flex;align-items:center;justify-content:{justify};'
        f'gap:0.6rem;margin:{margin};">'
        f'<svg viewBox="0 0 24 24" fill="none" stroke-width="2.2" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true" '
        f'style="width:{svg_size};height:{svg_size};stroke:var(--pc-accent);flex-shrink:0;">'
        f'<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
        f'<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>'
        f'</svg>'
        f'<span style="font-family:\'Source Serif 4\',Georgia,serif;font-weight:600;'
        f'color:var(--pc-text);font-size:{word_size};letter-spacing:-0.01em;line-height:1;">'
        f'PromptChain</span></div>'
    )
