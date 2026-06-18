"""Streamlit-Oberfläche – Betriebsauswertung EDEKA-Markt.

Screens: Markt-Überblick → Abteilung → Warengruppe → Artikel,
Querschnitt Verfügbarkeit, Historie/Anomalie, Empfehlungs-Panel.

Grundsatz: KEINE erfundenen Daten. Fehlt eine Quelle, erscheint ein klarer
Leerzustand statt leerer/fake Diagramme. Artikel-/Bestands-Features bleiben
dezent inaktiv ("Datei laden"), bis die Daten da sind.
"""
from __future__ import annotations

from pathlib import Path
import streamlit as st

from core import db, theme
from core.formatting import euro, percent, de_number
from config import INCOMING_DIR
import analysis as A
import recommend as R
import export_html

st.set_page_config(page_title="Betriebsauswertung", page_icon="📊", layout="wide")
st.markdown(theme.base_css(), unsafe_allow_html=True)
C = theme.COLORS


# ----------------------------------------------------------------------------- UI-Bausteine
def header(title: str, sub: str = ""):
    st.markdown(
        f'<div class="diwa-header"><h1>{title}</h1>'
        f'<div class="sub">{sub}</div></div>', unsafe_allow_html=True)


def chip(text: str, kind: str = "neutral") -> str:
    return f'<span class="chip chip-{kind}">{text}</span>'


def yoy_chip(yoy) -> str:
    state = theme.ampel(yoy)
    kind = {"green": "green", "amber": "amber", "red": "red", "neutral": "neutral"}[state]
    return chip(f"{theme.ampel_emoji(state)} {percent(yoy, with_sign=True)}", kind)


def kpi(col, label: str, value: str, sub: str = ""):
    col.markdown(
        f'<div class="diwa-card"><div class="diwa-kpi-label">{label}</div>'
        f'<div class="diwa-kpi-value">{value}</div>'
        f'<div style="color:{C["text_secondary"]};font-size:.85rem">{sub}</div></div>',
        unsafe_allow_html=True)


def empty_state(title: str, msg: str, icon: str = "📂"):
    st.markdown(
        f'<div class="diwa-empty"><div class="icon">{icon}</div>'
        f'<h3>{title}</h3><div>{msg}</div></div>', unsafe_allow_html=True)


def render_recs(recs, limit: int = 6):
    if not recs:
        st.caption("Keine Empfehlungen (zu wenig Vergleichsdaten).")
        return
    kindmap = {"Treiber": "green", "Risiko": "red", "Stabil": "blue", "Prüfen": "amber"}
    for r in recs[:limit]:
        k = kindmap.get(r.kategorie, "neutral")
        cav = f'<div style="color:{C["text_secondary"]};font-size:.8rem">⚠ {r.caveat}</div>' if r.caveat else ""
        st.markdown(
            f'<div class="diwa-card">{chip(r.kategorie, k)} '
            f'<b>{r.ebene}</b><br><span>{r.lesart}</span><br>'
            f'<b>Maßnahme:</b> {r.massnahme}{cav}</div>', unsafe_allow_html=True)


# ----------------------------------------------------------------------------- State
def go(level: str, **kw):
    st.session_state.level = level
    st.session_state.update(kw)


ss = st.session_state
ss.setdefault("level", "markt")
ss.setdefault("abteilung", None)
ss.setdefault("warengruppe", None)


# ----------------------------------------------------------------------------- DB & Sidebar
con = db.connect()
has_umsatz = db.has_data(con, "fact_umsatz_woche")
has_artikel = db.has_data(con, "fact_artikel_woche")
has_bestand = db.has_data(con, "fact_bestand")

with st.sidebar:
    st.markdown("### 📊 Betriebsauswertung")
    markt = A.market_name(con) if has_umsatz else None
    st.caption(f"Markt: **{markt}**" if markt else "Markt: – (keine Daten)")

    st.markdown("#### Datenquellen")
    def src_line(ok, name, hint):
        st.markdown(("✅ " if ok else "⚪ ") + f"**{name}**" +
                    ("" if ok else f"<br><span style='color:{C['text_secondary']};font-size:.8rem'>{hint}</span>"),
                    unsafe_allow_html=True)
    src_line(has_umsatz, "Umsatz", "Export ablegen & einlesen")
    src_line(has_artikel, "Artikel-Umsatz", "Quelle 2 – Datei laden (inaktiv)")
    src_line(has_bestand, "Bestand/Verfügbarkeit", "Quelle 3 – Datei laden (inaktiv)")

    st.divider()
    gjs = A.available_gjs(con) if has_umsatz else []
    gj = prev_gj = bis_kw = None
    only = "Alle"
    if gjs:
        gj = st.selectbox("Geschäftsjahr", gjs, index=len(gjs) - 1)
        prev_candidates = [g for g in gjs if g < gj]
        prev_gj = st.selectbox("Vergleich (Vorjahr)", ["– kein Vergleich"] + prev_candidates,
                               index=(len(prev_candidates)) if prev_candidates else 0)
        prev_gj = None if prev_gj == "– kein Vergleich" else prev_gj
        kmin, kmax = A.kw_bounds(con, gj)
        bis_kw = st.slider("Bis Kalenderwoche (vollständige Wochen)", kmin, kmax, kmax)
        only = st.radio("Filter", ["Alle", "nur Plus", "nur Minus"], horizontal=True)
        if st.button("⬅ Zurück zum Markt-Überblick", use_container_width=True):
            go("markt")

    st.divider()
    st.markdown("#### Daten einlesen")
    st.caption(f"Export ablegen in `{INCOMING_DIR}` und einlesen mit:\n\n"
               "`python ingest.py <datei.xlsx>`")
    if R.llm_available():
        st.success("LLM-Layer aktiv (API-Key gesetzt).")
    else:
        st.caption("LLM-Summary: aus (kein API-Key).")


def apply_filter(df):
    if only == "nur Plus" and "yoy" in df.columns:
        return df[df["yoy"] > 0]
    if only == "nur Minus" and "yoy" in df.columns:
        return df[df["yoy"] < 0]
    return df


# ----------------------------------------------------------------------------- Kein-Daten-Leerzustand
if not has_umsatz:
    header("Betriebsauswertung", "Markt → Abteilung → Warengruppe → Artikel")
    empty_state(
        "Noch keine Daten geladen",
        f"Lege den Umsatz-Export (SAP BO, Blatt <b>Kreuztabelle</b>) in "
        f"<code>{INCOMING_DIR}</code> ab und lies ihn ein mit "
        f"<code>python ingest.py &lt;datei.xlsx&gt;</code>.<br>"
        "Danach erscheinen hier Markt-Überblick, Abteilungs-Drilldown und Empfehlungen.")
    st.stop()


# ----------------------------------------------------------------------------- SCREEN 1: Markt-Überblick
def screen_markt():
    header(f"Markt-Überblick · {markt}",
           f"GJ {gj}" + (f" vs. {prev_gj}" if prev_gj else "") + f" · bis KW {bis_kw}")
    t = A.market_totals(con, gj, bis_kw, prev_gj)
    cols = st.columns(4)
    kpi(cols[0], "Umsatz", euro(t.get("umsatz")),
        ("VJ " + euro(t.get("umsatz_vj"))) if prev_gj else "")
    kpi(cols[1], "YoY", percent(t.get("yoy"), with_sign=True) if prev_gj else "–")
    sp = t.get("spanne")
    kpi(cols[2], "Spanne", percent(sp) if sp is not None else "–")
    kpi(cols[3], "Rohertrag YoY",
        percent(t.get("rohertrag_yoy"), with_sign=True) if prev_gj else "–")

    ov = A.market_overview(con, gj, bis_kw, prev_gj)
    ovf = apply_filter(ov)

    st.markdown("#### Abteilungen")
    st.caption("Klick auf eine Abteilung öffnet den Drilldown.")
    hdr = st.columns([3, 2, 2, 2, 2, 2])
    for c, h in zip(hdr, ["Abteilung", "Umsatz", "YoY", "Spanne", "Anteil", ""]):
        c.markdown(f"**{h}**")
    for _, r in ovf.iterrows():
        c = st.columns([3, 2, 2, 2, 2, 2])
        c[0].write(r["abteilung"])
        c[1].markdown(euro(r["umsatz"]))
        c[2].markdown(yoy_chip(r.get("yoy")), unsafe_allow_html=True)
        c[3].markdown(percent(r.get("spanne")) if r.get("spanne") is not None else "–")
        c[4].markdown(percent(r.get("anteil")))
        if c[5].button("Drilldown ▸", key=f"ab_{r['abteilung']}"):
            go("abteilung", abteilung=r["abteilung"])
            st.rerun()

    st.divider()
    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### Was treibt die Veränderung? (Pareto)")
        if prev_gj:
            pos, neg = A.pareto_mover(ov, "delta_umsatz", 6)
            cc = st.columns(2)
            cc[0].caption("Top-Treiber +")
            cc[0].dataframe(pos[["abteilung", "delta_umsatz"]].rename(
                columns={"delta_umsatz": "Δ Umsatz €"}), hide_index=True, use_container_width=True)
            cc[1].caption("Top-Belastung −")
            cc[1].dataframe(neg[["abteilung", "delta_umsatz"]].rename(
                columns={"delta_umsatz": "Δ Umsatz €"}), hide_index=True, use_container_width=True)
        else:
            st.caption("Vergleichsjahr wählen, um Treiber/Belastung zu sehen.")
    with right:
        st.markdown("#### Empfehlungen")
        render_recs(R.recommend_table(ov, "abteilung"))

    st.divider()
    _export_and_llm(ov, t, "Markt")


# ----------------------------------------------------------------------------- SCREEN 2: Abteilung
def screen_abteilung():
    ab = ss.abteilung
    header(f"Abteilung · {ab}",
           f"GJ {gj}" + (f" vs. {prev_gj}" if prev_gj else "") + f" · bis KW {bis_kw}")
    dd = A.department_detail(con, ab, gj, bis_kw, prev_gj)
    if dd.empty:
        empty_state("Keine Warengruppen", "Für diese Abteilung liegen keine Daten vor.")
        return
    tot_um = dd["umsatz"].sum()
    tot_vj = dd["umsatz_vj"].sum() if "umsatz_vj" in dd else None
    from core.datarules import yoy as _yoy, span as _span
    cols = st.columns(4)
    kpi(cols[0], "Umsatz", euro(tot_um))
    kpi(cols[1], "YoY", percent(_yoy(tot_um, tot_vj), with_sign=True) if prev_gj else "–")
    kpi(cols[2], "Spanne", percent(_span(dd["warenrohgewinn"].sum(), tot_um)))
    kpi(cols[3], "Warengruppen", de_number(len(dd)))

    # Auto-Insight
    if prev_gj:
        pos, neg = A.pareto_mover(dd, "delta_umsatz", 1)
        ins = []
        if not pos.empty:
            ins.append(f"Stärkster Treiber: **{pos.iloc[0]['warengruppe']}** "
                       f"({euro(pos.iloc[0]['delta_umsatz'])}).")
        if not neg.empty:
            ins.append(f"Größte Belastung: **{neg.iloc[0]['warengruppe']}** "
                       f"({euro(neg.iloc[0]['delta_umsatz'])}).")
        if ins:
            st.info(" ".join(ins))

    ddf = apply_filter(dd)
    st.markdown("#### Warengruppen")
    hdr = st.columns([3, 2, 2, 2, 3, 2])
    for c, h in zip(hdr, ["Warengruppe", "Umsatz", "YoY", "Spanne", "Lesart (Preis/Menge)", ""]):
        c.markdown(f"**{h}**")
    span_avg = dd["spanne"].median()
    for _, r in ddf.iterrows():
        c = st.columns([3, 2, 2, 2, 3, 2])
        c[0].write(r["warengruppe"])
        c[1].markdown(euro(r["umsatz"]))
        c[2].markdown(yoy_chip(r.get("yoy")), unsafe_allow_html=True)
        c[3].markdown(percent(r.get("spanne")) if r.get("spanne") is not None else "–")
        treiber = r.get("treiber", "unbekannt")
        lese = {"preis": "Preis-getrieben", "menge": "Mengen-getrieben",
                "unbekannt": "Menge n. v."}.get(treiber, treiber)
        c[4].markdown(chip(lese, "blue" if treiber != "unbekannt" else "neutral"),
                      unsafe_allow_html=True)
        if c[5].button("Artikel ▸", key=f"wg_{r['warengruppe']}"):
            go("warengruppe", warengruppe=r["warengruppe"])
            st.rerun()

    st.divider()
    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### Trend (Wochenverlauf Umsatz)")
        _trend_chart(ab, None)
    with right:
        st.markdown("#### Empfehlungen")
        render_recs(R.recommend_table(dd, "warengruppe"))

    st.divider()
    st.markdown("#### Anomalien (diese KW vs. erwartet)")
    an = A.anomaly_table(con, gj, bis_kw, ab)
    if an.empty:
        st.caption("Noch zu wenig Wochenhistorie für ein verlässliches Anomalie-Signal.")
    else:
        an2 = an.copy()
        an2["umsatz"] = an2["umsatz"].map(lambda v: euro(v))
        an2["erwartet"] = an2["erwartet"].map(lambda v: euro(v))
        an2["abweichung"] = an2["abweichung"].map(lambda v: euro(v))
        st.dataframe(an2[["warengruppe", "umsatz", "erwartet", "abweichung", "anomalie"]],
                     hide_index=True, use_container_width=True)


# ----------------------------------------------------------------------------- SCREEN 3: Warengruppe → Artikel
def screen_warengruppe():
    wg = ss.warengruppe
    header(f"Warengruppe · {wg}", f"GJ {gj}" + (f" vs. {prev_gj}" if prev_gj else ""))
    st.markdown("#### Trend (Wochenverlauf Umsatz)")
    _trend_chart(ss.abteilung, wg)

    st.divider()
    st.markdown("#### Top-Mover-Artikel")
    if not has_artikel:
        empty_state(
            "Artikel-Drilldown inaktiv",
            "Die Quelle <b>Artikel-Umsatz</b> (Quelle 2) ist noch nicht geladen.<br>"
            "Spalten prüfen mit <code>python ingest.py &lt;datei.xlsx&gt; --quelle artikel --inspect</code>, "
            "Mapping in <code>mapping.yaml</code> bestätigen, dann einlesen.",
            icon="🧾")
        return
    art = A.warengruppe_artikel(con, wg, gj, bis_kw, prev_gj, with_bestand=has_bestand)
    if art.empty:
        empty_state("Keine Artikel", "Für diese Warengruppe liegen keine Artikeldaten vor.")
        return
    show_cols = ["artikel_id", "bezeichnung", "umsatz", "yoy"]
    rename = {"artikel_id": "Artikel", "bezeichnung": "Bezeichnung",
              "umsatz": "Umsatz", "yoy": "YoY"}
    if has_bestand:
        show_cols += ["luecke_wochen", "bestand_avg"]
        rename |= {"luecke_wochen": "Lücken-Wochen", "bestand_avg": "Ø Bestand"}
    else:
        st.caption("Verfügbarkeits-Spalte inaktiv – Bestandsdatei (Quelle 3) noch nicht geladen.")
    disp = art[show_cols].rename(columns=rename)
    st.dataframe(disp, hide_index=True, use_container_width=True)


# ----------------------------------------------------------------------------- Querschnitt Verfügbarkeit
def screen_verfuegbarkeit():
    header("Querschnitt · Verfügbarkeit", "Umsatzrückgang UND gleichzeitige Bestandslücke")
    if not (has_artikel and has_bestand):
        empty_state(
            "Verfügbarkeits-Sicht inaktiv",
            "Diese Sicht verknüpft <b>Artikel-Umsatz</b> (Quelle 2) mit "
            "<b>Bestand/Verfügbarkeit</b> (Quelle 3) über die Artikelnummer/GTIN.<br>"
            "Beide Dateien laden, dann werden Artikel mit Minus + Regallücke gelistet.",
            icon="🔌")
        return
    cs = A.availability_cross_section(con, gj, bis_kw, prev_gj)
    if cs.empty:
        st.success("Kein Artikel mit gleichzeitigem Umsatzminus und Bestandslücke gefunden.")
        return
    disp = cs[["artikel_id", "bezeichnung", "warengruppe", "umsatz", "yoy", "luecke_wochen"]]
    st.dataframe(disp.rename(columns={"luecke_wochen": "Lücken-Wochen"}),
                 hide_index=True, use_container_width=True)


# ----------------------------------------------------------------------------- Historie
def screen_historie():
    header("Historie & Anomalien", f"GJ {gj} · bis KW {bis_kw}")
    _trend_chart(None, None)
    st.divider()
    st.markdown("#### Anomalie-Liste (Markt)")
    an = A.anomaly_table(con, gj, bis_kw, None)
    if an.empty:
        st.caption("Noch zu wenig Wochenhistorie. Mit jedem neuen Wochenexport wächst die Basis.")
    else:
        flagged = an[an["anomalie"]]
        st.dataframe(
            (flagged if not flagged.empty else an).assign(
                umsatz=lambda d: d["umsatz"].map(euro),
                erwartet=lambda d: d["erwartet"].map(euro),
                abweichung=lambda d: d["abweichung"].map(euro),
            )[["warengruppe", "umsatz", "erwartet", "abweichung", "anomalie"]],
            hide_index=True, use_container_width=True)


# ----------------------------------------------------------------------------- Hilfen: Trend & Export
def _trend_chart(abteilung, warengruppe):
    import pandas as pd
    cur = A.weekly_series(con, gj, abteilung, warengruppe).rename(columns={"wert": f"GJ {gj}"})
    merged = cur.set_index("kw")
    if prev_gj:
        vj = A.weekly_series(con, prev_gj, abteilung, warengruppe).rename(
            columns={"wert": f"GJ {prev_gj}"}).set_index("kw")
        merged = merged.join(vj, how="outer")
    merged = merged[merged.index <= bis_kw]
    if merged.empty:
        st.caption("Keine Wochenwerte im gewählten Zeitraum.")
        return
    st.line_chart(merged)


def _export_and_llm(ov, totals, ebene):
    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("⤓ Report exportieren (HTML)", use_container_width=True):
            path = export_html.build_snapshot(con, gj, bis_kw, prev_gj)
            with open(path, "rb") as fh:
                st.download_button("HTML-Snapshot herunterladen", fh.read(),
                                   file_name=Path(path).name, mime="text/html",
                                   use_container_width=True)
    with c2:
        if R.llm_available():
            with st.expander("🧠 LLM-Management-Summary (optional)"):
                if st.button("Summary erzeugen"):
                    pos, neg = A.pareto_mover(ov, "delta_umsatz", 6)
                    txt = R.llm_summary(totals, pos, neg, ebene)
                    st.write(txt or "Kein Summary verfügbar.")
        else:
            st.caption("Optionaler LLM-Layer aus (kein API-Key). Regelbasierte "
                       "Empfehlungen sind oben bereits aktiv.")


# ----------------------------------------------------------------------------- Navigation Tabs + Router
nav = st.columns(4)
if nav[0].button("🏪 Markt", use_container_width=True):
    go("markt"); st.rerun()
if nav[1].button("📈 Historie", use_container_width=True):
    go("historie"); st.rerun()
if nav[2].button("🧾 Verfügbarkeit", use_container_width=True):
    go("verfuegbarkeit"); st.rerun()
nav[3].caption(f"Ebene: {ss.level}")

level = ss.level
if level == "markt":
    screen_markt()
elif level == "abteilung":
    screen_abteilung()
elif level == "warengruppe":
    screen_warengruppe()
elif level == "verfuegbarkeit":
    screen_verfuegbarkeit()
elif level == "historie":
    screen_historie()

con.close()
