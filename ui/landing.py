"""
PromptChain — Landing Page

Home screen with entry points into the three modes: the two-model
pipeline, and the direct chats with the Prompter / Coder models.
"""

import streamlit as st

from ui.styles import logo_html

_LANDING_CSS = """
<style>
.pc-hero {
    text-align: center;
    padding: 2.2rem 0 1.6rem 0;
}
.pc-hero h1 {
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 2.9rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--pc-text);
    margin: 0 0 0.6rem 0;
}
.pc-hero .tagline {
    color: var(--pc-text-muted);
    font-size: 1.02rem;
    line-height: 1.55;
    max-width: 37rem;
    margin: 0 auto;
}
.pc-mode-card {
    background: var(--pc-surface);
    border: 1px solid var(--pc-border);
    border-radius: 14px;
    padding: 1.3rem 1.15rem;
    /* Tall enough for the longest description at desktop widths, so the
       buttons under the four cards line up */
    min-height: 12.5rem;
    margin-bottom: 0.8rem;
    transition: border-color 0.15s ease, transform 0.15s ease,
                box-shadow 0.15s ease;
}
.pc-mode-card:hover {
    border-color: var(--pc-accent);
    transform: translateY(-2px);
    box-shadow: 0 8px 26px rgba(0, 0, 0, 0.3);
}
.pc-mode-card .icon { font-size: 1.5rem; }
.pc-mode-card h4 {
    margin: 0.5rem 0 0.4rem 0;
    font-size: 1.02rem;
}
.pc-mode-card p {
    color: var(--pc-text-muted);
    font-size: 0.85rem;
    line-height: 1.5;
    margin: 0;
}
.pc-how {
    display: flex;
    justify-content: center;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.45rem;
    color: var(--pc-text-muted);
    font-size: 0.84rem;
    padding: 1.4rem 0 0.3rem 0;
}
.pc-how b { color: var(--pc-text); font-weight: 500; }
</style>
"""


def _mode_card(icon: str, title: str, desc: str) -> str:
    return (
        f'<div class="pc-mode-card">'
        f'<div class="icon">{icon}</div>'
        f'<h4>{title}</h4>'
        f'<p>{desc}</p>'
        f'</div>'
    )


def render_landing(config: dict) -> str | None:
    """
    Render the landing page.
    Returns the page to navigate to ('pipeline', 'chat_prompter',
    'chat_coder') or None if no action was taken.
    """
    st.markdown(_LANDING_CSS, unsafe_allow_html=True)

    st.markdown(
        '<div class="pc-hero">'
        + logo_html("hero")
        + '<p class="tagline">Chain two LLMs — local or cloud: a small '
        'Prompter that refines your idea, and a larger Coder that turns it '
        'into working code, with a review step in between.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    action = None
    col1, col2, col3, col4 = st.columns(4, gap="medium")

    with col1:
        st.markdown(
            _mode_card(
                "🔗", "Pipeline",
                "Describe an idea, review the refined prompt, get a complete "
                "code file. The full two-model flow.",
            ),
            unsafe_allow_html=True,
        )
        if st.button(
            "Start building",
            key="landing_pipeline_btn",
            type="primary",
            use_container_width=True,
        ):
            action = "pipeline"

    with col2:
        st.markdown(
            _mode_card(
                "💬", "Prompter chat",
                "Talk directly to the Prompter model. Draft and iterate on "
                "prompts conversationally, no pipeline.",
            ),
            unsafe_allow_html=True,
        )
        if st.button(
            "Open chat",
            key="landing_chat_prompter_btn",
            use_container_width=True,
        ):
            action = "chat_prompter"

    with col3:
        st.markdown(
            _mode_card(
                "⌨️", "Coder chat",
                "Talk directly to the Coder model. Ask questions, get "
                "snippets, debug — like ChatGPT, but local.",
            ),
            unsafe_allow_html=True,
        )
        if st.button(
            "Open chat",
            key="landing_chat_coder_btn",
            use_container_width=True,
        ):
            action = "chat_coder"

    with col4:
        st.markdown(
            _mode_card(
                "📋", "Presets",
                "Browse and edit the system prompts each model uses — built-in "
                "library plus your own custom presets.",
            ),
            unsafe_allow_html=True,
        )
        if st.button(
            "Manage presets",
            key="landing_presets_btn",
            use_container_width=True,
        ):
            action = "presets"

    st.markdown(
        '<div class="pc-how">'
        '<b>1</b> Describe an idea → <b>2</b> Review the prompt → '
        '<b>3</b> VRAM swap → <b>4</b> Code streams in → <b>5</b> Save'
        '</div>',
        unsafe_allow_html=True,
    )

    from core.api import BACKEND_LABELS
    from core.config import get_role_endpoint

    def _role_summary(role: str) -> str:
        ep = get_role_endpoint(config, role)
        backend = BACKEND_LABELS.get(ep["backend"], ep["backend"])
        return f"`{ep['model'] or 'not set'}` on {backend}"

    st.caption(
        f"Prompter: {_role_summary('prompter')} · "
        f"Coder: {_role_summary('coder')}"
    )

    col_l, col_c, col_r = st.columns([2, 1, 2])
    with col_c:
        if st.button("⚙ Settings", key="landing_settings_btn", use_container_width=True):
            st.session_state["show_settings"] = True
            st.session_state["_settings_just_opened"] = True
            st.rerun()

    return action
