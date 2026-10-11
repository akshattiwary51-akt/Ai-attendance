"""Design tokens and the single stylesheet for SnapClass.

Every colour, radius and shadow used by custom markup comes from the CSS variables defined here, so the
light and dark themes stay consistent on every page. Streamlit's own widgets follow the matching palette in
``.streamlit/config.toml`` - keep the two in step.
"""
from __future__ import annotations

import streamlit as st

LIGHT = {
    "bg": "#F8FAFC", "surface": "#FFFFFF", "surface-2": "#F1F5F9", "text": "#0F172A", "muted": "#475569", "border": "#E2E8F0",
    "primary": "#4F46E5", "primary-strong": "#4338CA", "primary-soft": "#EEF2FF", "on-primary": "#FFFFFF",
    "violet": "#7C3AED", "accent": "#14B8A6", "accent-text": "#0F766E",
    "ok": "#15803D", "ok-bg": "#DCFCE7", "warn": "#B45309", "warn-bg": "#FEF3C7", "bad": "#B91C1C", "bad-bg": "#FEE2E2",
    "info": "#3730A3", "info-bg": "#E0E7FF", "neutral": "#475569", "neutral-bg": "#E2E8F0",
    "ok-solid": "#16A34A", "warn-solid": "#D97706", "bad-solid": "#DC2626", "track": "#E2E8F0",
    "focus": "#4F46E5", "shadow": "0 1px 2px rgba(15,23,42,.05), 0 1px 3px rgba(15,23,42,.06)",
    "shadow-lg": "0 8px 24px rgba(79,70,229,.18)",
}
DARK = {
    "bg": "#0B1120", "surface": "#111A2E", "surface-2": "#182036", "text": "#E2E8F0", "muted": "#94A3B8", "border": "#27324D",
    "primary": "#818CF8", "primary-strong": "#A5B4FC", "primary-soft": "#1E2547", "on-primary": "#0B1120",
    "violet": "#A78BFA", "accent": "#2DD4BF", "accent-text": "#5EEAD4",
    "ok": "#86EFAC", "ok-bg": "#12301F", "warn": "#FCD34D", "warn-bg": "#3A2C0A", "bad": "#FCA5A5", "bad-bg": "#3F1717",
    "info": "#C7D2FE", "info-bg": "#232C57", "neutral": "#CBD5E1", "neutral-bg": "#27324D",
    "ok-solid": "#4ADE80", "warn-solid": "#FBBF24", "bad-solid": "#F87171", "track": "#27324D",
    "focus": "#A5B4FC", "shadow": "0 1px 2px rgba(0,0,0,.4)", "shadow-lg": "0 8px 24px rgba(0,0,0,.45)",
}
FONT_URL = "https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap"
FONT_STACK = "'Plus Jakarta Sans', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"

# Chart colours are read by src/ui/charts.py so charts match the active theme.
CHART = {"light": {"ok": "#16A34A", "late": "#D97706", "bad": "#DC2626", "muted": "#94A3B8", "line": "#4F46E5", "accent": "#14B8A6"},
         "dark": {"ok": "#4ADE80", "late": "#FBBF24", "bad": "#F87171", "muted": "#64748B", "line": "#818CF8", "accent": "#2DD4BF"}}


def current_mode() -> str:
    """'dark' or 'light', from the theme the browser is actually showing (Streamlit setting or OS preference)."""
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # noqa: BLE001 - no browser context (tests, bare mode): default to light
        return "light"


def chart_colors() -> dict[str, str]:
    return CHART[current_mode()]


def _vars(tokens: dict[str, str]) -> str:
    return "".join(f"--sc-{k}:{v};" for k, v in tokens.items())


STYLE = f"""
@import url('{FONT_URL}');
.stApp{{background:var(--sc-bg);color:var(--sc-text);font-family:{FONT_STACK};}}
.stApp, .stApp p, .stApp label, .stApp li, .stApp input, .stApp textarea, .stApp button{{font-family:{FONT_STACK};}}
.stApp [class*="material"], .stApp [data-testid="stIconMaterial"]{{font-family:'Material Symbols Rounded' !important;}}
[data-testid="stMainBlockContainer"]{{max-width:1180px;padding:2rem 2rem 4rem;}}
@media (max-width:640px){{[data-testid="stMainBlockContainer"]{{padding:1.25rem 1rem 3rem;}}}}
/* The top bar stays (it holds the sidebar toggle) but is transparent; the menu and deploy chrome are hidden. */
[data-testid="stHeader"]{{background:transparent;}}
[data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu, footer{{visibility:hidden;height:0;}}

/* Typography */
h1,h2,h3,h4{{color:var(--sc-text);letter-spacing:-.01em;}}
.stApp h1{{font-size:1.75rem;font-weight:700;line-height:1.2;padding:0;}}
.stApp h2{{font-size:1.25rem;font-weight:650;line-height:1.3;padding:.25rem 0 .5rem;}}
.stApp h3{{font-size:1.05rem;font-weight:650;padding:.25rem 0 .4rem;}}
.stApp [data-testid="stCaptionContainer"], .stApp [data-testid="stCaptionContainer"] *, .stApp small{{color:var(--sc-muted);opacity:1;}}
.sc-num{{font-variant-numeric:tabular-nums;}}

/* Focus: always visible for keyboard users */
.stApp :is(button,a,input,textarea,select,[role="tab"],[role="radio"],[role="switch"],[tabindex]):focus-visible{{
  outline:2px solid var(--sc-focus) !important;outline-offset:2px !important;}}

/* Buttons */
.stApp [data-testid^="stBaseButton-"]{{border-radius:10px;font-weight:600;min-height:2.5rem;transition:background-color .15s,border-color .15s,box-shadow .15s;}}
.stApp [data-testid="stBaseButton-primary"],.stApp [data-testid="stBaseButton-primaryFormSubmit"]{{
  background:var(--sc-primary);border:1px solid var(--sc-primary);color:var(--sc-on-primary);}}
.stApp [data-testid="stBaseButton-primary"]:hover,.stApp [data-testid="stBaseButton-primaryFormSubmit"]:hover{{
  background:var(--sc-primary-strong);border-color:var(--sc-primary-strong);color:var(--sc-on-primary);}}
.stApp [data-testid="stBaseButton-primary"] *,.stApp [data-testid="stBaseButton-primaryFormSubmit"] *{{color:inherit;}}
.stApp [data-testid="stBaseButton-secondary"],.stApp [data-testid="stBaseButton-secondaryFormSubmit"]{{
  background:var(--sc-surface);border:1px solid var(--sc-border);color:var(--sc-text);}}
.stApp [data-testid="stBaseButton-secondary"]:hover,.stApp [data-testid="stBaseButton-secondaryFormSubmit"]:hover{{
  border-color:var(--sc-primary);color:var(--sc-primary);background:var(--sc-primary-soft);}}
.stApp [data-testid="stBaseButton-tertiary"]{{color:var(--sc-muted);background:transparent;border:1px solid transparent;}}
.stApp [data-testid="stBaseButton-tertiary"]:hover{{color:var(--sc-primary);background:var(--sc-primary-soft);}}
.stApp [data-testid^="stBaseButton-"]:disabled{{opacity:.55;}}
.st-key-danger button,.stApp [class*="st-key-danger"] button{{background:var(--sc-bad-bg);border:1px solid var(--sc-bad);color:var(--sc-bad);}}
.stApp [class*="st-key-danger"] button:hover{{background:var(--sc-bad);color:#fff;border-color:var(--sc-bad);}}

/* Inputs */
.stApp [data-baseweb="input"],.stApp [data-baseweb="select"]>div,.stApp [data-baseweb="textarea"]{{border-radius:10px;}}
.stApp label p{{font-weight:600;font-size:.9rem;}}
.stApp [data-testid="stDataFrame"]{{border:1px solid var(--sc-border);border-radius:12px;overflow:hidden;}}
.stApp [data-testid="stExpander"]{{border:1px solid var(--sc-border);border-radius:12px;background:var(--sc-surface);}}
.stApp [data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"] > .sc-form-marker){{background:var(--sc-surface);}}
.stApp [data-baseweb="tab-list"]{{gap:.25rem;border-bottom:1px solid var(--sc-border);}}
.stApp [data-baseweb="tab"]{{font-weight:600;}}
.stApp [data-testid="stAlert"]{{border-radius:12px;}}

/* Sidebar shell */
[data-testid="stSidebar"]{{background:var(--sc-surface);border-right:1px solid var(--sc-border);}}
[data-testid="stSidebarContent"]{{padding-top:.5rem;}}
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"]{{padding:1rem .9rem 1.25rem;}}
.sc-brand{{display:flex;align-items:center;gap:.65rem;padding:.25rem .35rem 1rem;}}
[data-testid="stSidebar"] .st-key-nav_cta{{margin-bottom:.25rem;}}
.sc-brand svg{{flex:none;}}
.sc-brand-name{{font-weight:700;font-size:1.15rem;letter-spacing:-.02em;color:var(--sc-text);line-height:1.1;}}
.sc-brand-role{{font-size:.78rem;color:var(--sc-muted);}}
.sc-nav-label{{font-size:.78rem;font-weight:600;color:var(--sc-muted);padding:1rem .5rem .25rem;}}
[data-testid="stSidebar"] [class*="st-key-nav_"] [data-testid^="stBaseButton-"]{{
  justify-content:flex-start;width:100%;border-radius:10px;padding:.45rem .75rem;min-height:2.5rem;font-weight:550;
  background:transparent;border:1px solid transparent;color:var(--sc-muted);box-shadow:none;}}
[data-testid="stSidebar"] [class*="st-key-nav_"] [data-testid^="stBaseButton-"]:hover{{background:var(--sc-surface-2);color:var(--sc-text);}}
[data-testid="stSidebar"] [class*="st-key-nav_"] [data-testid="stBaseButton-primary"]{{
  background:var(--sc-primary-soft);color:var(--sc-primary);font-weight:700;box-shadow:inset 3px 0 0 var(--sc-primary);}}
[data-testid="stSidebar"] [class*="st-key-nav_"] [data-testid="stBaseButton-primary"]:hover{{background:var(--sc-primary-soft);color:var(--sc-primary);}}
[data-testid="stSidebar"] [class*="st-key-nav_"] button>div{{justify-content:flex-start;gap:.6rem;}}
[data-testid="stSidebar"] [class*="st-key-nav_"] button [data-testid="stMarkdownContainer"]{{flex:1;}}
[data-testid="stSidebar"] [class*="st-key-nav_"] button p{{text-align:left;}}
[data-testid="stSidebar"] .st-key-nav_cta [data-testid^="stBaseButton-"]{{justify-content:center;background:var(--sc-primary);color:var(--sc-on-primary);border-color:var(--sc-primary);font-weight:700;box-shadow:var(--sc-shadow);}}
[data-testid="stSidebar"] .st-key-nav_cta [data-testid^="stBaseButton-"]:hover{{background:var(--sc-primary-strong);color:var(--sc-on-primary);}}
[data-testid="stSidebar"] .st-key-nav_cta button>div{{justify-content:center;}}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{{gap:.2rem;}}
.sc-profile{{display:flex;align-items:center;gap:.65rem;padding:.65rem .5rem;border-top:1px solid var(--sc-border);margin:1rem 0 .5rem;}}
.sc-avatar{{width:2.25rem;height:2.25rem;border-radius:50%;background:var(--sc-primary-soft);color:var(--sc-primary);display:grid;place-items:center;font-weight:700;flex:none;}}
.sc-profile-name{{font-weight:650;font-size:.9rem;line-height:1.2;overflow-wrap:anywhere;}}
.sc-profile-role{{font-size:.78rem;color:var(--sc-muted);}}

/* Page header */
.sc-crumbs{{font-size:.82rem;color:var(--sc-muted);margin-bottom:.35rem;}}
.sc-crumbs span+span::before{{content:"/";margin:0 .45rem;opacity:.6;}}
.sc-page-title{{font-size:1.75rem;font-weight:700;letter-spacing:-.02em;line-height:1.2;margin:0;color:var(--sc-text);}}
.stApp .sc-page-desc{{color:var(--sc-muted);margin:.35rem 0 0;max-width:62ch;line-height:1.5;}}
.sc-page-head{{margin-bottom:1.25rem;}}
.sc-section-title{{font-size:1.05rem;font-weight:650;margin:1.5rem 0 .25rem;}}
.stApp .sc-section-desc{{color:var(--sc-muted);font-size:.9rem;margin:0 0 .75rem;}}

/* Cards */
.sc-card{{background:var(--sc-surface);color:var(--sc-text);border:1px solid var(--sc-border);border-radius:14px;padding:1.1rem 1.25rem;margin-bottom:.9rem;box-shadow:var(--sc-shadow);}}
.sc-card h3{{margin:0;padding:0;font-size:1.05rem;font-weight:650;color:var(--sc-text);}}
.sc-card-meta{{color:var(--sc-muted);font-size:.88rem;margin:.3rem 0 .7rem;}}
.sc-sub{{color:var(--sc-muted);font-size:.88rem;margin:.4rem 0;}}
.sc-sub a,.stApp .sc-card a{{color:inherit;text-decoration:none;}}
.sc-chip{{background:var(--sc-primary-soft);color:var(--sc-primary);padding:.1rem .5rem;border-radius:6px;font-weight:600;font-size:.82rem;}}
.sc-stat{{display:inline-block;background:var(--sc-surface-2);color:var(--sc-text);padding:.3rem .65rem;border-radius:8px;font-size:.85rem;margin:0 .4rem .35rem 0;}}
.sc-stat b{{font-variant-numeric:tabular-nums;}}
.sc-kpi{{min-height:7rem;background:var(--sc-surface);color:var(--sc-text);border:1px solid var(--sc-border);border-radius:14px;padding:1rem 1.15rem;margin-bottom:.75rem;box-shadow:var(--sc-shadow);height:calc(100% - .75rem);}}
.sc-kpi-label{{color:var(--sc-muted);font-size:.85rem;font-weight:550;}}
.sc-kpi-value{{font-size:1.9rem;font-weight:700;line-height:1.2;letter-spacing:-.02em;font-variant-numeric:tabular-nums;margin-top:.15rem;}}
.sc-kpi-hint{{color:var(--sc-muted);font-size:.82rem;margin-top:.15rem;}}

/* Status badges: colour plus a glyph and a word, never colour alone */
.sc-badge{{display:inline-flex;align-items:center;gap:.3rem;padding:.12rem .6rem;border-radius:999px;font-size:.8rem;font-weight:650;white-space:nowrap;}}
.sc-badge .sc-glyph{{font-size:.75rem;line-height:1;}}
.sc-ok{{background:var(--sc-ok-bg);color:var(--sc-ok);}} .sc-warn{{background:var(--sc-warn-bg);color:var(--sc-warn);}}
.sc-bad{{background:var(--sc-bad-bg);color:var(--sc-bad);}} .sc-muted{{background:var(--sc-neutral-bg);color:var(--sc-neutral);}}
.sc-info{{background:var(--sc-info-bg);color:var(--sc-info);}}
.sc-progress{{position:relative;height:8px;border-radius:999px;background:var(--sc-track);margin:.6rem 0;overflow:visible;}}
.sc-progress-fill{{height:100%;border-radius:999px;}}
.sc-progress-fill.sc-ok{{background:var(--sc-ok-solid);}} .sc-progress-fill.sc-bad{{background:var(--sc-bad-solid);}}
.sc-progress-target{{position:absolute;top:-4px;width:2px;height:16px;background:var(--sc-text);border-radius:1px;}}
.sc-empty{{margin-bottom:.75rem;border:1.5px dashed var(--sc-border);border-radius:14px;padding:2rem 1.5rem;text-align:center;color:var(--sc-muted);background:var(--sc-surface);}}
.sc-empty h4{{margin:0 0 .35rem;color:var(--sc-text);font-size:1rem;}} .sc-empty p{{margin:0;}}

/* Hero (the one expressive element: today's primary action) */
.stApp .st-key-hero{{background:linear-gradient(120deg,var(--sc-primary) 0%,var(--sc-violet) 100%);border-radius:18px;padding:1.5rem 1.75rem;box-shadow:var(--sc-shadow-lg);}}
.stApp .st-key-hero :is(h2,h3,p,span,div){{color:#fff;}}
.stApp .st-key-hero p{{opacity:.92;}}
.stApp .st-key-hero [data-testid="stBaseButton-primary"]{{background:#fff;color:#3730A3;border-color:#fff;}}
.stApp .st-key-hero [data-testid="stBaseButton-primary"] *{{color:#3730A3;}}
.stApp .st-key-hero [data-testid="stBaseButton-primary"]:hover{{background:#EEF2FF;}}
.sc-hero-title{{font-size:1.4rem;font-weight:700;letter-spacing:-.02em;margin:0 0 .25rem;}}
.sc-hero-body{{margin:0 0 .25rem;max-width:56ch;line-height:1.5;}}

/* Stepper */
.sc-steps{{display:flex;flex-wrap:wrap;gap:.5rem;list-style:none;margin:0 0 1.5rem;padding:0;}}
.sc-step{{flex:1 1 8.5rem;display:flex;align-items:center;gap:.6rem;padding:.65rem .8rem;border:1px solid var(--sc-border);border-radius:12px;background:var(--sc-surface);color:var(--sc-muted);min-width:0;}}
.sc-step-dot{{flex:none;width:1.65rem;height:1.65rem;border-radius:50%;display:grid;place-items:center;font-size:.8rem;font-weight:700;background:var(--sc-surface-2);color:var(--sc-muted);border:1px solid var(--sc-border);}}
.sc-step-label{{font-weight:600;font-size:.88rem;line-height:1.2;overflow-wrap:normal;word-break:normal;}}
.sc-step-state{{display:block;font-weight:500;font-size:.75rem;color:var(--sc-muted);}}
.sc-step.sc-done .sc-step-dot{{background:var(--sc-ok-solid);color:#fff;border-color:var(--sc-ok-solid);}}
.sc-step.sc-done{{color:var(--sc-text);}}
.sc-step.sc-current{{border-color:var(--sc-primary);background:var(--sc-primary-soft);color:var(--sc-text);box-shadow:0 0 0 1px var(--sc-primary);}}
.sc-step.sc-current .sc-step-dot{{background:var(--sc-primary);color:var(--sc-on-primary);border-color:var(--sc-primary);}}

/* Auth screens */
.sc-auth-brand{{display:flex;align-items:center;gap:.7rem;margin-bottom:1.25rem;}}
.sc-auth-panel{{background:linear-gradient(150deg,var(--sc-primary) 0%,var(--sc-violet) 100%);border-radius:18px;padding:2rem;color:#fff;min-height:100%;}}
.sc-auth-panel h2,.sc-auth-panel p,.sc-auth-panel li{{color:#fff;}}
.sc-auth-panel h2{{font-size:1.5rem;font-weight:700;letter-spacing:-.02em;padding:0;}}
.sc-auth-panel ul{{padding-left:1.1rem;line-height:1.7;}}
.sc-role-card{{background:var(--sc-surface);border:1px solid var(--sc-border);border-radius:16px;padding:1.5rem;box-shadow:var(--sc-shadow);height:100%;}}
.sc-role-title{{margin:.75rem 0 .25rem;font-size:1.15rem;font-weight:650;}} .sc-role-body{{color:var(--sc-muted);margin:0 0 .75rem;line-height:1.5;min-height:3rem;}}
.stApp [class*="st-key-role_"]{{background:var(--sc-surface);border-radius:16px;padding:.5rem;box-shadow:var(--sc-shadow);}}
.sc-icon-tile{{width:2.6rem;height:2.6rem;border-radius:12px;background:var(--sc-primary-soft);color:var(--sc-primary);display:grid;place-items:center;}}
.sc-note{{border:1px solid var(--sc-border);background:var(--sc-surface-2);border-radius:12px;padding:.85rem 1rem;font-size:.9rem;color:var(--sc-text);line-height:1.5;}}
.sc-summary{{display:flex;flex-wrap:wrap;gap:.5rem;margin:.25rem 0 1rem;}}

/* Reduced motion */
@media (prefers-reduced-motion: reduce){{*{{transition:none !important;animation:none !important;scroll-behavior:auto !important;}}}}
"""


def stylesheet(mode: str | None = None) -> str:
    mode = mode or current_mode()
    return f":root{{{_vars(DARK if mode == 'dark' else LIGHT)}}}" + STYLE


def apply_theme() -> None:
    """Inject the stylesheet once per rerun, in the theme the browser is showing."""
    st.markdown(f"<style>{stylesheet()}</style>", unsafe_allow_html=True)


def hide_sidebar() -> None:
    """Signed-out screens use the full width."""
    st.markdown('<style>[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"],[data-testid="stExpandSidebarButton"]{display:none !important;}</style>',
                unsafe_allow_html=True)
