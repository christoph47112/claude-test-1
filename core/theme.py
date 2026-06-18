"""DiWa-Designsystem: Farbpalette + CSS für Streamlit und HTML-Export."""
from __future__ import annotations

COLORS = {
    "primary": "#1565c0",
    "primary_light": "#1976d2",
    "deep": "#0d3f7a",
    "text": "#15233a",
    "text_secondary": "#5b6b85",
    "bg": "#f4f6fa",
    "card": "#ffffff",
    "line": "#e3e8f0",
    # Diagnosefarben
    "green": "#2e7d32", "green_bg": "#e3f3e4",
    "amber": "#e67e00", "amber_bg": "#fde9d0",
    "red": "#c92020", "red_bg": "#fde0e0",
    "blue_bg": "#d6e4f5",
}


def ampel(yoy: float | None, threshold: float = 0.02) -> str:
    """YoY-Ampel: 'green' | 'amber' | 'red' | 'neutral'."""
    if yoy is None:
        return "neutral"
    if yoy >= threshold:
        return "green"
    if yoy <= -threshold:
        return "red"
    return "amber"


def ampel_emoji(state: str) -> str:
    return {"green": "🟢", "amber": "🟡", "red": "🔴", "neutral": "⚪"}.get(state, "⚪")


def base_css() -> str:
    c = COLORS
    return f"""
<style>
:root {{
  --primary:{c['primary']}; --deep:{c['deep']}; --text:{c['text']};
  --text2:{c['text_secondary']}; --bg:{c['bg']}; --card:{c['card']};
  --line:{c['line']};
}}
html, body, [class*="css"] {{ color:{c['text']}; }}
.stApp {{ background:{c['bg']}; }}
.block-container {{ padding-top:1.2rem; }}
/* Kopf als blauer Verlauf */
.diwa-header {{
  background:linear-gradient(110deg,{c['deep']} 0%,{c['primary']} 60%,{c['primary_light']} 100%);
  color:#fff; padding:18px 22px; border-radius:14px; margin-bottom:18px;
  box-shadow:0 6px 18px rgba(13,63,122,.18);
}}
.diwa-header h1 {{ margin:0; font-size:1.5rem; font-weight:700; }}
.diwa-header .sub {{ opacity:.9; font-size:.9rem; margin-top:4px; }}
/* Karten */
.diwa-card {{
  background:{c['card']}; border:1px solid {c['line']}; border-radius:14px;
  padding:16px 18px; box-shadow:0 2px 10px rgba(21,35,58,.05); margin-bottom:14px;
}}
.diwa-kpi-label {{ color:{c['text_secondary']}; font-size:.8rem; text-transform:uppercase; letter-spacing:.04em; }}
.diwa-kpi-value {{ font-size:1.6rem; font-weight:700; font-variant-numeric:tabular-nums; }}
/* Chips / Badges */
.chip {{ display:inline-block; padding:2px 10px; border-radius:999px; font-size:.8rem;
        font-weight:600; font-variant-numeric:tabular-nums; }}
.chip-green {{ background:{c['green_bg']}; color:{c['green']}; }}
.chip-amber {{ background:{c['amber_bg']}; color:{c['amber']}; }}
.chip-red   {{ background:{c['red_bg']};   color:{c['red']}; }}
.chip-blue  {{ background:{c['blue_bg']};  color:{c['deep']}; }}
.chip-neutral {{ background:{c['line']}; color:{c['text_secondary']}; }}
/* Leerzustand */
.diwa-empty {{
  background:{c['card']}; border:1px dashed {c['line']}; border-radius:14px;
  padding:34px; text-align:center; color:{c['text_secondary']};
}}
.diwa-empty .icon {{ font-size:2.2rem; }}
.diwa-empty h3 {{ color:{c['text']}; margin:.4rem 0; }}
table {{ font-variant-numeric:tabular-nums; }}
</style>
"""
