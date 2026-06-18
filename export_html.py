"""Self-contained HTML-Snapshot der aktuellen Markt-Sicht.

Kein CDN, kein localStorage, kein externes Asset – eine einzelne .html-Datei,
die offline auf Handy/Desktop lesbar ist und an Kollegen weitergegeben werden
kann. Nur aggregierte Kennzahlen, lokal erzeugt.
"""
from __future__ import annotations

from pathlib import Path
import datetime as dt
import html

from core import theme
from core.formatting import euro, percent
import analysis as A
import recommend as R
from config import PROJECT_ROOT

C = theme.COLORS


def _chip(text, kind):
    return f'<span class="chip chip-{kind}">{html.escape(str(text))}</span>'


def _yoy_chip(yoy):
    state = theme.ampel(yoy)
    return _chip(f"{theme.ampel_emoji(state)} {percent(yoy, with_sign=True)}",
                 state if state != "neutral" else "neutral")


def build_snapshot(con, gj: int, bis_kw: int, prev_gj: int | None,
                   out_dir: Path | None = None) -> str:
    markt = A.market_name(con) or "Markt"
    totals = A.market_totals(con, gj, bis_kw, prev_gj)
    ov = A.market_overview(con, gj, bis_kw, prev_gj)
    recs = R.recommend_table(ov, "abteilung")

    rows = ""
    for _, r in ov.iterrows():
        rows += (
            f"<tr><td>{html.escape(str(r['abteilung']))}</td>"
            f"<td class='num'>{euro(r['umsatz'])}</td>"
            f"<td>{_yoy_chip(r.get('yoy'))}</td>"
            f"<td class='num'>{percent(r.get('spanne')) if r.get('spanne') is not None else '–'}</td>"
            f"<td class='num'>{percent(r.get('anteil'))}</td></tr>")

    rec_html = ""
    kindmap = {"Treiber": "green", "Risiko": "red", "Stabil": "blue", "Prüfen": "amber"}
    for rec in recs[:8]:
        k = kindmap.get(rec.kategorie, "neutral")
        cav = f"<div class='cav'>⚠ {html.escape(rec.caveat)}</div>" if rec.caveat else ""
        rec_html += (
            f"<div class='card'>{_chip(rec.kategorie, k)} <b>{html.escape(rec.ebene)}</b>"
            f"<div>{html.escape(rec.lesart)}</div>"
            f"<div><b>Maßnahme:</b> {html.escape(rec.massnahme)}</div>{cav}</div>")

    cmp = f"vs. GJ {prev_gj}" if prev_gj else "ohne Vorjahresvergleich"
    now = dt.datetime.now().strftime("%d.%m.%Y %H:%M")
    page = f"""<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Betriebsauswertung {html.escape(markt)} – GJ {gj}</title>
{theme.base_css().replace('.stApp', 'body')}
<style>
body{{font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;background:{C['bg']};
     margin:0;padding:18px;max-width:1000px;margin:auto;}}
table{{width:100%;border-collapse:collapse;background:{C['card']};border-radius:12px;overflow:hidden;}}
th,td{{padding:9px 12px;text-align:left;border-bottom:1px solid {C['line']};}}
th{{background:{C['blue_bg']};color:{C['deep']};}}
td.num{{text-align:right;font-variant-numeric:tabular-nums;}}
.kpis{{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0;}}
.kpi{{flex:1;min-width:150px;}} .cav{{color:{C['text_secondary']};font-size:.8rem;}}
.card{{margin-bottom:10px;}}
</style></head><body>
<div class="diwa-header"><h1>Betriebsauswertung · {html.escape(markt)}</h1>
<div class="sub">GJ {gj} {cmp} · bis KW {bis_kw} · erstellt {now}</div></div>
<div class="kpis">
  <div class="diwa-card kpi"><div class="diwa-kpi-label">Umsatz</div>
    <div class="diwa-kpi-value">{euro(totals.get('umsatz'))}</div></div>
  <div class="diwa-card kpi"><div class="diwa-kpi-label">YoY</div>
    <div class="diwa-kpi-value">{percent(totals.get('yoy'), with_sign=True) if prev_gj else '–'}</div></div>
  <div class="diwa-card kpi"><div class="diwa-kpi-label">Spanne</div>
    <div class="diwa-kpi-value">{percent(totals.get('spanne')) if totals.get('spanne') is not None else '–'}</div></div>
  <div class="diwa-card kpi"><div class="diwa-kpi-label">Rohertrag YoY</div>
    <div class="diwa-kpi-value">{percent(totals.get('rohertrag_yoy'), with_sign=True) if prev_gj else '–'}</div></div>
</div>
<div class="diwa-card"><h3>Abteilungen</h3>
<table><thead><tr><th>Abteilung</th><th>Umsatz</th><th>YoY</th><th>Spanne</th><th>Anteil</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<div class="diwa-card"><h3>Empfehlungen</h3>{rec_html}</div>
<div class="cav">Self-contained Snapshot · nur aggregierte Kennzahlen · lokal erzeugt.</div>
</body></html>"""

    out_dir = out_dir or PROJECT_ROOT / "exports"
    out_dir.mkdir(exist_ok=True)
    fname = out_dir / f"report_{markt.replace(' ', '_')}_GJ{gj}_KW{bis_kw}.html"
    fname.write_text(page, encoding="utf-8")
    return str(fname)
