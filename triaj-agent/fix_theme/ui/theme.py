"""Tema vizuala: calda, bej/cream, friendly. Badge-uri si carduri HTML, zero emoji.
Prioritatile au culori fixe doar unde conteaza (aprobari); restul interfetei e neutru si cald."""

import html

import streamlit as st

# ---------------------------------------------------------------------------
# Paleta calda (bej / cream)
# ---------------------------------------------------------------------------
BG = "#faf8f4"            # crem foarte deschis
SURFACE = "#fffefb"       # alb cald
BORDER = "#e8e2d9"        # bej deschis
TEXT = "#2d2420"          # maro inchis, nu negru pur
MUTED = "#8c7d72"         # maro gri
ACCENT = "#7c6f5e"        # maro cald (butoane, accente)
ACCENT_SOFT = "#f2ede6"   # bej soft pentru taguri
NAVY = "#3d3530"          # maro inchis in loc de bleumarin

PRIORITY = {   # (fundal, text, punct)
    "P1": ("#fde8e8", "#9b1c1c", "#e02424"),
    "P2": ("#feecdc", "#8a2c0d", "#f97316"),
    "P3": ("#fdf6b2", "#723b13", "#e3a008"),
    "P4": ("#def7ec", "#03543f", "#0e9f6e"),
}

MAIN_CSS = """
<style>
/* ── Baza ─────────────────────────────────────────── */
.stApp { background: %(bg)s; color: %(text)s; }
.block-container { max-width: 1180px; padding-top: 2.2rem; padding-bottom: 4rem; }
h1 { font-weight: 750 !important; letter-spacing: -0.02em; color: %(text)s; }
h2, h3 { font-weight: 700 !important; letter-spacing: -0.01em; color: %(text)s; }
p, li { line-height: 1.55; }

/* ── Sidebar ──────────────────────────────────────── */
section[data-testid="stSidebar"] { background: %(surface)s; border-right: 1px solid %(border)s; }

/* ── Inputuri ─────────────────────────────────────── */
.stTextInput input, .stTextArea textarea {
    background: %(surface)s !important; border-radius: 10px !important;
}
.stTextArea textarea:focus, .stTextInput input:focus {
    border-color: %(accent)s !important; box-shadow: 0 0 0 3px rgba(15,143,127,.15) !important;
}

/* ── Butoane ──────────────────────────────────────── */
.stButton > button, .stFormSubmitButton > button { border-radius: 10px !important; font-weight: 600 !important; }
.stButton > button[kind="primary"], .stFormSubmitButton > button {
    background: %(accent)s !important; border: none !important; color: #fff !important;
    box-shadow: 0 2px 8px rgba(15,143,127,.25);
}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button:hover { background: #0b7568 !important; }
.stButton > button:disabled, .stFormSubmitButton > button:disabled { opacity: .45 !important; box-shadow: none !important; cursor: not-allowed; }

/* ── Containere cu bordura = carduri ──────────────── */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: %(surface)s; border-radius: 14px !important; border-color: %(border)s !important;
    box-shadow: 0 1px 2px rgba(15,23,42,.04), 0 4px 14px rgba(15,23,42,.04);
}

/* ── st.metric (unde mai e folosit): etichete intregi, fara „...” ── */
div[data-testid="stMetric"] {
    background: %(surface)s; border: 1px solid %(border)s; border-radius: 12px; padding: 14px 16px;
}
div[data-testid="stMetricLabel"], div[data-testid="stMetricLabel"] p, div[data-testid="stMetric"] label {
    white-space: normal !important; overflow: visible !important; text-overflow: clip !important;
    color: %(muted)s !important; font-size: 12.5px !important; line-height: 1.3 !important;
}
div[data-testid="stMetricValue"] { white-space: normal !important; overflow: visible !important; }

/* ── Carduri KPI proprii ──────────────────────────── */
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin: 6px 0 18px; }
.kpi {
    background: %(surface)s; border: 1px solid %(border)s; border-radius: 14px; padding: 16px 18px 14px;
    box-shadow: 0 1px 2px rgba(15,23,42,.04); position: relative; overflow: hidden;
}
.kpi::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: var(--tone); }
.kpi .label { font-size: 13px; font-weight: 600; color: %(text)s; margin-bottom: 6px; }
.kpi .value { font-size: 30px; font-weight: 750; color: var(--tone); letter-spacing: -0.02em; line-height: 1.1; }
.kpi .value small { font-size: 15px; font-weight: 600; color: %(muted)s; margin-left: 2px; }
.kpi .hint { font-size: 12.5px; color: %(muted)s; margin-top: 8px; line-height: 1.4; }
.kpi.hero { background: linear-gradient(135deg, #e6f6f3 0%%, #ffffff 70%%); }
.kpi.hero .value { font-size: 40px; }

.section-title { display: flex; align-items: baseline; gap: 10px; margin: 26px 0 4px; }
.section-title h3 { margin: 0 !important; font-size: 1.25rem; }
.section-title .tag {
    font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase;
    padding: 3px 8px; border-radius: 6px; background: %(accent_soft)s; color: %(accent)s;
}
.section-title .tag.warn { background: #fef3c7; color: #92400e; }
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
.sb-auto     { background: #eaf0e6; color: #3d5c35; }
.sb-pending  { background: #f5eddb; color: #7a5a20; }
.sb-approved { background: #e8edf5; color: #3a4f6e; }
.sb-rejected { background: #f5e8e8; color: #7a3535; }
.sb-dup      { background: #eeebe6; color: #5c5248; }
.rule-badge  { background: #eeebe6; color: #5c5248; font-weight: 500; }
.src-badge   { background: #e8edf5; color: #3a4f6e; }
.mode-live   { background: #eaf0e6; color: #3d5c35; }
.mode-sim    { background: #f5eddb; color: #7a5a20; }

/* ── Scala de prioritati ──────────────────────────── */
.prio-scale { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; font-size: 12px; color: %(muted)s; }

/* ── Flux (pasi) ──────────────────────────────────── */
.flow { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 8px 0 6px; }
.flow .step {
    background: %(surface)s; border: 1px solid %(border)s; border-radius: 12px; padding: 12px 14px; position: relative;
}
.flow .step .n { font-size: 11px; font-weight: 700; color: %(accent)s; letter-spacing: .06em; }
.flow .step .t { font-weight: 700; font-size: 14px; margin: 2px 0 4px; color: %(text)s; }
.flow .step .d { font-size: 12.5px; color: %(muted)s; line-height: 1.4; }
.flow .step.dark { background: %(navy)s; border-color: %(navy)s; }
.flow .step.dark .t { color: #fff; } .flow .step.dark .d { color: #cbd5e1; } .flow .step.dark .n { color: #5eead4; }
@media (max-width: 760px) { .flow { grid-template-columns: 1fr 1fr; } }

/* ── Liste compacte de tichete ────────────────────── */
.tk-row { display: grid; grid-template-columns: 92px 62px 1fr 170px 120px; gap: 10px; align-items: center;
          padding: 9px 4px; border-bottom: 1px solid #eef2f6; font-size: 14px; }
.tk-row:last-child { border-bottom: none; }
.tk-row code { font-size: 12.5px; }
.tk-row .muted { color: %(muted)s; font-size: 12.5px; }
@media (max-width: 760px) { .tk-row { grid-template-columns: 80px 56px 1fr; } .tk-row .hide-sm { display: none; } }

.stAlert { border-radius: 12px !important; }
hr { border-color: %(border)s !important; }
</style>
"""


def _priority_css() -> str:
    return "\n".join(f".pb-{p} {{ background: {bg}; color: {fg}; }} .pb-{p} .dot {{ background: {dot}; }}"
                     for p, (bg, fg, dot) in PRIORITY.items())


def inject_theme():
    """Apeleaza o data per pagina, dupa st.set_page_config."""
    st.markdown(MAIN_CSS % {"bg": BG, "surface": SURFACE, "border": BORDER, "text": TEXT, "muted": MUTED,
                            "accent": ACCENT, "accent_soft": ACCENT_SOFT, "navy": NAVY,
                            "priority_css": _priority_css()}, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Badge-uri HTML
# ---------------------------------------------------------------------------

def priority_badge(p: str | None) -> str:
    if not p:
        return '<span class="priority-badge" style="background:#f1f5f9;color:#64748b;">—</span>'
    return f'<span class="priority-badge pb-{p}"><span class="dot"></span>{p}</span>'


def priority_scale() -> str:
    """Legenda P1..P4 (aceeasi ca in prezentare)."""
    names = {"P1": "critic", "P2": "ridicat", "P3": "mediu", "P4": "scazut"}
    return ('<div class="prio-scale">' + "".join(f"{priority_badge(p)}<span>{n}</span>" for p, n in names.items())
            + "</div>")


STATUS = {
    "received":         ("Primit",           "sb-pending"),
    "auto_routed":      ("Directionat automat", "sb-auto"),
    "pending_approval": ("Asteapta un om",   "sb-pending"),
    "approved":         ("Aprobat",          "sb-approved"),
    "rejected":         ("Respins",          "sb-rejected"),
    "duplicate":        ("Duplicat",         "sb-dup"),
}


def status_badge(status: str) -> str:
    text, cls = STATUS.get(status, (status, "sb-dup"))
    return f'<span class="status-badge {cls}">{text}</span>'


RULES = {
    "auto": "Automat",
    "p1_always_human": "P1 → om",
    "low_confidence": "Siguranta < 70%",
    "unknown_team": "Echipa necunoscuta",
    "team_category_mismatch": "Echipa ≠ categorie",
    "out_of_scope": "In afara domeniului IT",
    "weak_match": "Potrivire slaba",
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
# Carduri KPI si titluri de sectiune
# ---------------------------------------------------------------------------

TONES = {"teal": ACCENT, "navy": NAVY, "green": "#5a7a5a", "amber": "#b8860b", "red": "#9b3a3a",
         "blue": "#5a6e8c", "slate": "#8c7d72"}


def kpi_card(label: str, value, hint: str = "", tone: str = "teal", unit: str = "", hero: bool = False) -> str:
    v = "—" if value is None else html.escape(str(value))
    u = f"<small>{html.escape(unit)}</small>" if unit and value is not None else ""
    return (f'<div class="kpi{" hero" if hero else ""}" style="--tone:{TONES.get(tone, tone)}">'
            f'<div class="label">{html.escape(label)}</div><div class="value">{v}{u}</div>'
            f'{f"<div class=hint>{html.escape(hint)}</div>" if hint else ""}</div>')


def kpi_grid(cards: list[str]):
    st.markdown('<div class="kpi-grid">' + "".join(cards) + "</div>", unsafe_allow_html=True)


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
