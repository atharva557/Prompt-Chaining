import streamlit as st

def inject_custom_css():
    """Inject the minimal dark theme CSS (ChatGPT / Claude inspired)."""
    st.markdown("""
    <style>
    /* ═══════════════════════════════════════════════════════
       PROMPTCHAIN — Minimal Dark Theme
       Warm neutral palette, serif display headings,
       pill buttons, centered content column.
       ═══════════════════════════════════════════════════════ */

    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=JetBrains+Mono:wght@400;500&display=swap');

    /* ── Root Variables ── */
    :root {
        --pc-bg: #262624;
        --pc-bg-secondary: #1f1e1d;
        --pc-surface: #30302e;
        --pc-surface-hover: #3a3a37;
        --pc-border: #3d3d3a;
        --pc-border-strong: #52524d;
        --pc-text: #eceae4;
        --pc-text-muted: #a3a094;
        --pc-accent: #d97757;
        --pc-accent-hover: #c4633f;
        --pc-success: #4ade80;
        --pc-warning: #fbbf24;
        --pc-error: #f87171;
        /* Legacy aliases kept for components that reference them */
        --pc-primary: #d97757;
        --pc-primary-light: #e89b7d;
        --pc-primary-glow: rgba(217, 119, 87, 0.25);
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
        color: #ffffff !important;
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

    .stSlider > div > div > div > div {
        background: var(--pc-accent) !important;
    }

    /* ── Expanders ── */
    [data-testid="stExpander"] {
        border: 1px solid var(--pc-border) !important;
        border-radius: 12px !important;
        background: var(--pc-surface) !important;
    }

    /* ── Code Blocks ── */
    .stCodeBlock {
        border-radius: 12px !important;
        border: 1px solid var(--pc-border) !important;
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
        background: rgba(217, 119, 87, 0.12);
        color: var(--pc-accent);
        border: 1px solid rgba(217, 119, 87, 0.35);
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
        color: #ffffff;
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


def render_connection_badge(connected: bool):
    """Render a connection status badge."""
    if connected:
        st.markdown(
            '<div class="connection-badge connected">● Connected</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            '<div class="connection-badge disconnected">● Disconnected</div>',
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
