"""Tema vizuala: dark, corporate, curata. Culori doar unde au sens (prioritati, status).
Badge-uri si carduri HTML, zero emoji.

API identic cu versiunea light: inject_theme, priority_badge, priority_scale, status_badge,
rule_badge, source_badge, mode_badge, kpi_card, kpi_grid, section, flow.
Noi: stat_row, stage_footer, nav_item.
"""

import html

import streamlit as st

# ---------------------------------------------------------------------------
# Paleta dark
# ---------------------------------------------------------------------------
BG = "#0d1117"            # fundal pagina
SURFACE = "#161b22"       # carduri, sidebar
SURFACE_2 = "#1c232d"     # hover, randuri alternante
BORDER = "#263141"
TEXT = "#e6edf3"
MUTED = "#8b949e"
ACCENT = "#2f6feb"        # albastru, vizibil pe fundal inchis
ACCENT_SOFT = "rgba(47,111,235,.16)"
ACCENT_TEXT = "#79c0ff"
NAVY = "#1c232d"

# (fundal, text, punct) -- pe dark: fundal translucid, text deschis
PRIORITY = {
    "P1": ("rgba(248,81,73,.16)", "#ff7b72", "#f85149"),
    "P2": ("rgba(219,109,40,.16)", "#ffa657", "#db6d28"),
    "P3": ("rgba(210,153,34,.16)", "#e3b341", "#d29922"),
    "P4": ("rgba(63,185,80,.16)", "#56d364", "#3fb950"),
}

MAIN_CSS = """
<style>
/* ── Baza ─────────────────────────────────────────── */
.stApp { background: %(bg)s; color: %(text)s; }
.block-container { max-width: 1180px; padding-top: 2.2rem; padding-bottom: 5.5rem; }
h1 { font-weight: 750 !important; letter-spacing: -0.02em; color: %(text)s; }
h2, h3 { font-weight: 700 !important; letter-spacing: -0.01em; color: %(text)s; }
p, li { line-height: 1.55; color: %(text)s; }
a { color: %(accent_text)s; }
code { background: %(surface2)s !important; color: %(accent_text)s !important;
       border: 1px solid %(border)s; border-radius: 6px; padding: 1px 5px; }

/* ── Sidebar ──────────────────────────────────────── */
section[data-testid="stSidebar"] { background: %(surface)s; border-right: 1px solid %(border)s; }
section[data-testid="stSidebar"] * { color: %(text)s; }
section[data-testid="stSidebar"] .stCaption, section[data-testid="stSidebar"] small { color: %(muted)s !important; }
/* eticheta de sectiune in sidebar */
.nav-label { font-size: 11px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase;
             color: %(muted)s; margin: 18px 0 8px; }
/* link-urile de navigare (st.page_link) ca randuri de workflow */
section[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"] {
    border-radius: 10px; padding: 9px 12px; margin-bottom: 3px; border: 1px solid transparent;
}
section[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"]:hover {
    background: %(surface2)s; border-color: %(border)s;
}

/* ── Inputuri ─────────────────────────────────────── */
.stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div,
.stNumberInput input {
    background: %(surface)s !important; color: %(text)s !important;
    border-color: %(border)s !important; border-radius: 10px !important;
}
.stTextArea textarea:focus, .stTextInput input:focus {
    border-color: %(accent)s !important; box-shadow: 0 0 0 3px %(accent_soft)s !important;
}
.stTextInput input::placeholder, .stTextArea textarea::placeholder { color: %(muted)s !important; }

/* ── Butoane ──────────────────────────────────────── */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {
    border-radius: 10px !important; font-weight: 600 !important;
    background: %(surface)s !important; color: %(text)s !important; border: 1px solid %(border)s !important;
}
.stButton > button:hover, .stFormSubmitButton > button:hover { border-color: %(accent)s !important; }
.stButton > button[kind="primary"], .stFormSubmitButton > button {
    background: %(accent)s !important; border-color: %(accent)s !important; color: #fff !important;
    box-shadow: 0 2px 10px rgba(47,111,235,.30);
}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button:hover { background: #1f5fd0 !important; }
.stButton > button:disabled, .stFormSubmitButton > button:disabled {
    opacity: .40 !important; box-shadow: none !important; cursor: not-allowed;
}

/* ── Containere cu bordura = carduri ──────────────── */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: %(surface)s; border-radius: 14px !important; border-color: %(border)s !important;
    box-shadow: 0 1px 2px rgba(0,0,0,.35), 0 6px 20px rgba(0,0,0,.25);
}

/* ── Tab-uri ──────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] { border-bottom: 1px solid %(border)s; gap: 6px; }
.stTabs [data-baseweb="tab"] { color: %(muted)s; }
.stTabs [aria-selected="true"] { color: %(text)s !important; }

/* ── st.metric ────────────────────────────────────── */
div[data-testid="stMetric"] {
    background: %(surface)s; border: 1px solid %(border)s; border-radius: 12px; padding: 14px 16px;
}
div[data-testid="stMetricLabel"], div[data-testid="stMetricLabel"] p, div[data-testid="stMetric"] label {
    white-space: normal !important; overflow: visible !important; text-overflow: clip !important;
    color: %(muted)s !important; font-size: 12.5px !important; line-height: 1.3 !important;
}
div[data-testid="stMetricValue"] { white-space: normal !important; overflow: visible !important; color: %(text)s; }

/* ── Carduri KPI proprii ──────────────────────────── */
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin: 6px 0 18px; }
.kpi {
    background: %(surface)s; border: 1px solid %(border)s; border-radius: 14px; padding: 16px 18px 14px;
    box-shadow: 0 1px 2px rgba(0,0,0,.30); position: relative; overflow: hidden;
}
.kpi::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: var(--tone); }
.kpi .label { font-size: 13px; font-weight: 600; color: %(text)s; margin-bottom: 6px; }
.kpi .value { font-size: 30px; font-weight: 700; color: %(text)s; letter-spacing: -0.02em; line-height: 1.1; }
.kpi .value small { font-size: 15px; font-weight: 600; color: %(muted)s; margin-left: 2px; }
.kpi .hint { font-size: 12.5px; color: %(muted)s; margin-top: 8px; line-height: 1.4; }
.kpi.hero { background: linear-gradient(135deg, rgba(47,111,235,.18) 0%%, %(surface)s 70%%); }
.kpi.hero .value { font-size: 40px; }

/* ── Rand de statistici (311 parsed · 0 still need parsing) ── */
.stat-row { display: flex; flex-wrap: wrap; gap: 28px; align-items: baseline;
            background: %(surface)s; border: 1px solid %(border)s; border-radius: 14px;
            padding: 16px 20px; margin: 6px 0 18px; }
.stat-row .stat { display: flex; align-items: baseline; gap: 8px; }
.stat-row .stat b { font-size: 24px; font-weight: 750; color: %(text)s; letter-spacing: -0.02em; }
.stat-row .stat span { font-size: 13px; color: %(muted)s; }
.stat-row .stat.accent b { color: %(accent_text)s; }

/* ── Titluri de sectiune ──────────────────────────── */
.section-title { display: flex; align-items: baseline; gap: 10px; margin: 26px 0 4px; }
.section-title h3 { margin: 0 !important; font-size: 1.25rem; }
.section-title .tag {
    font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase;
    padding: 3px 8px; border-radius: 6px; background: %(accent_soft)s; color: %(accent_text)s;
}
.section-title .tag.warn { background: rgba(210,153,34,.18); color: #e3b341; }
.section-sub { color: %(muted)s; font-size: 14px; margin: 0 0 8px; }

/* ── Badge-uri prioritate ─────────────────────────── */
.priority-badge {
    display: inline-flex; align-items: center; gap: 6px; padding: 3px 11px; border-radius: 999px;
    font-weight: 700; font-size: 12.5px; letter-spacing: .02em; white-space: nowrap;
}
.priority-badge .dot { width: 8px; height: 8px; border-radius: 50%%; display: inline-block; }
%(priority_css)s

/* ── Badge-uri status / regula / sursa ────────────── */
.status-badge, .rule-badge, .src-badge {
    display: inline-flex; align-items: center; gap: 5px; padding: 3px 10px; border-radius: 8px;
    font-size: 12px; font-weight: 600; white-space: nowrap;
}
.sb-auto     { background: rgba(63,185,80,.16);  color: #56d364; }
.sb-pending  { background: rgba(210,153,34,.16); color: #e3b341; }
.sb-approved { background: rgba(47,111,235,.18); color: #79c0ff; }
.sb-rejected { background: rgba(248,81,73,.16);  color: #ff7b72; }
.sb-dup      { background: rgba(139,148,158,.16); color: %(muted)s; }
.rule-badge  { background: rgba(139,148,158,.14); color: %(muted)s; font-weight: 500; }
.src-badge   { background: %(accent_soft)s; color: %(accent_text)s; }
.mode-live   { background: rgba(63,185,80,.16);  color: #56d364; }
.mode-sim    { background: rgba(210,153,34,.16); color: #e3b341; }

/* ── Scala de prioritati ──────────────────────────── */
.prio-scale { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; font-size: 12px; color: %(muted)s; }

/* ── Flux (pasi) ──────────────────────────────────── */
.flow { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 8px 0 6px; }
.flow .step {
    background: %(surface)s; border: 1px solid %(border)s; border-radius: 12px; padding: 12px 14px; position: relative;
}
.flow .step .n { font-size: 11px; font-weight: 700; color: %(accent_text)s; letter-spacing: .06em; }
.flow .step .t { font-weight: 700; font-size: 14px; margin: 2px 0 4px; color: %(text)s; }
.flow .step .d { font-size: 12.5px; color: %(muted)s; line-height: 1.4; }
.flow .step.dark { background: %(accent_soft)s; border-color: %(accent)s; }
.flow .step.dark .t { color: #fff; } .flow .step.dark .d { color: #c9d4e3; } .flow .step.dark .n { color: %(accent_text)s; }
@media (max-width: 760px) { .flow { grid-template-columns: 1fr 1fr; } }

/* ── Liste compacte de tichete ────────────────────── */
.tk-row { display: grid; grid-template-columns: 92px 62px 1fr 170px 120px; gap: 10px; align-items: center;
          padding: 9px 4px; border-bottom: 1px solid %(border)s; font-size: 14px; }
.tk-row:last-child { border-bottom: none; }
.tk-row code { font-size: 12.5px; }
.tk-row .muted { color: %(muted)s; font-size: 12.5px; }
@media (max-width: 760px) { .tk-row { grid-template-columns: 80px 56px 1fr; } .tk-row .hide-sm { display: none; } }

/* ── Bara de etapa, fixata jos ────────────────────── */
.stage-bar {
    position: fixed; left: 0; right: 0; bottom: 0; z-index: 99;
    background: %(surface)s; border-top: 1px solid %(border)s;
    padding: 12px 28px; display: flex; align-items: center; gap: 16px;
    box-shadow: 0 -4px 20px rgba(0,0,0,.35);
}
.stage-bar .st-title { font-weight: 700; font-size: 14px; color: %(text)s; }
.stage-bar .st-sub { font-size: 12.5px; color: %(muted)s; }

/* ── Tabele si alerte ─────────────────────────────── */
.stDataFrame, div[data-testid="stTable"] { border: 1px solid %(border)s; border-radius: 12px; }
.stAlert { border-radius: 12px !important; background: %(surface)s !important; border: 1px solid %(border)s !important; }
.stAlert p { color: %(text)s !important; }
hr { border-color: %(border)s !important; }
div[data-testid="stExpander"] { border: 1px solid %(border)s !important; border-radius: 12px !important;
                                background: %(surface)s !important; }
</style>
"""


def _priority_css() -> str:
    return "\n".join(f".pb-{p} {{ background: {bg}; color: {fg}; }} .pb-{p} .dot {{ background: {dot}; }}"
                     for p, (bg, fg, dot) in PRIORITY.items())


def inject_theme():
    """Apeleaza o data per pagina, dupa st.set_page_config."""
    st.markdown(MAIN_CSS % {"bg": BG, "surface": SURFACE, "surface2": SURFACE_2, "border": BORDER,
                            "text": TEXT, "muted": MUTED, "accent": ACCENT, "accent_soft": ACCENT_SOFT,
                            "accent_text": ACCENT_TEXT, "navy": NAVY,
                            "priority_css": _priority_css()}, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Badge-uri HTML
# ---------------------------------------------------------------------------

def priority_badge(p: str | None) -> str:
    if not p:
        return '<span class="priority-badge" style="background:rgba(139,148,158,.16);color:#8b949e;">—</span>'
    return f'<span class="priority-badge pb-{p}"><span class="dot"></span>{p}</span>'


def priority_scale() -> str:
    """Legenda P1..P4 (aceeasi ca in prezentare)."""
    names = {"P1": "critic", "P2": "ridicat", "P3": "mediu", "P4": "scazut"}
    return ('<div class="prio-scale">' + "".join(f"{priority_badge(p)}<span>{n}</span>" for p, n in names.items())
            + "</div>")


STATUS = {
    "received":         ("Primit",              "sb-pending"),
    "auto_routed":      ("Directionat automat",  "sb-auto"),
    "pending_approval": ("Asteapta un om",       "sb-pending"),
    "approved":         ("Aprobat",              "sb-approved"),
    "rejected":         ("Respins",              "sb-rejected"),
    "duplicate":        ("Duplicat",             "sb-dup"),
}


def status_badge(status: str) -> str:
    text, cls = STATUS.get(status, (status, "sb-dup"))
    return f'<span class="status-badge {cls}">{text}</span>'


RULES = {
    "auto": "Automat",
    "p1_always_human": "P1 → om",
    "low_confidence": "Siguranta < 70%",
    "out_of_scope": "In afara domeniului IT",
    "invalid_output": "Iesire invalida",
    "llm_unavailable": "LLM indisponibil",
    "duplicate": "Duplicat",
}


def rule_badge(rule: str | None) -> str:
    return f'<span class="rule-badge">{RULES.get(rule, rule or "—")}</span>'


def source_badge(text: str) -> str:
    return f'<span class="src-badge">{html.escape(text)}</span>'


def mode_badge(mode: str) -> str:
    live = mode == "live"
    return (f'<span class="status-badge {"mode-live" if live else "mode-sim"}">'
            f'{"Conectat la Jira" if live else "Mod simulare"}</span>')


# ---------------------------------------------------------------------------
# Carduri KPI, statistici si titluri de sectiune
# ---------------------------------------------------------------------------

TONES = {"teal": ACCENT, "navy": ACCENT, "green": "#3fb950", "amber": "#d29922", "red": "#f85149",
         "blue": ACCENT, "slate": MUTED}


def kpi_card(label: str, value, hint: str = "", tone: str = "blue", unit: str = "", hero: bool = False) -> str:
    v = "—" if value is None else html.escape(str(value))
    u = f"<small>{html.escape(unit)}</small>" if unit and value is not None else ""
    return (f'<div class="kpi{" hero" if hero else ""}" style="--tone:{TONES.get(tone, tone)}">'
            f'<div class="label">{html.escape(label)}</div><div class="value">{v}{u}</div>'
            f'{f"<div class=hint>{html.escape(hint)}</div>" if hint else ""}</div>')


def kpi_grid(cards: list[str]):
    st.markdown('<div class="kpi-grid">' + "".join(cards) + "</div>", unsafe_allow_html=True)


def stat_row(stats: list[tuple], accent_first: bool = True):
    """Rand compact de cifre: stat_row([(311, "clasificate"), (0, "in asteptare")])."""
    parts = []
    for i, (value, label) in enumerate(stats):
        cls = "stat accent" if (accent_first and i == 0) else "stat"
        parts.append(f'<div class="{cls}"><b>{html.escape(str(value))}</b>'
                     f'<span>{html.escape(label)}</span></div>')
    st.markdown('<div class="stat-row">' + "".join(parts) + "</div>", unsafe_allow_html=True)


def nav_label(text: str):
    """Eticheta de sectiune in sidebar (ex. „FLUXUL TAU DE TRIAJ")."""
    st.sidebar.markdown(f'<div class="nav-label">{html.escape(text)}</div>', unsafe_allow_html=True)


def stage_footer(title: str, subtitle: str = ""):
    """Bara fixata jos: stage_footer("Etapa 1 din 4: Trimite tichetul", "Munca salvata trece mai departe")."""
    sub = f'<span class="st-sub">{html.escape(subtitle)}</span>' if subtitle else ""
    st.markdown(f'<div class="stage-bar"><span class="st-title">{html.escape(title)}</span>{sub}</div>',
                unsafe_allow_html=True)


def section(title: str, subtitle: str = "", tag: str = "", warn: bool = False):
    t = f'<span class="tag{" warn" if warn else ""}">{html.escape(tag)}</span>' if tag else ""
    st.markdown(f'<div class="section-title"><h3>{html.escape(title)}</h3>{t}</div>'
                + (f'<p class="section-sub">{html.escape(subtitle)}</p>' if subtitle else ""),
                unsafe_allow_html=True)


def flow(steps: list[tuple[str, str, str, bool]]):
    """steps: (numar, titlu, descriere, inchis_la_culoare)."""
    st.markdown('<div class="flow">' + "".join(
        f'<div class="step{" dark" if dark else ""}"><div class="n">{html.escape(n)}</div>'
        f'<div class="t">{html.escape(t)}</div><div class="d">{html.escape(d)}</div></div>'
        for n, t, d, dark in steps) + "</div>", unsafe_allow_html=True)