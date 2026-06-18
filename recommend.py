"""Empfehlungs-Schicht.

(1) Regelbasiert – nachvollziehbar, priorisiert, immer mit Daten-Caveat.
(2) Optionaler LLM-Layer (Claude) – bekommt die vorberechneten Signale als
    strukturierte Fakten und formuliert ein Klartext-Summary. Das LLM rechnet
    NICHT selbst. Standardmäßig AUS (nur aktiv, wenn ANTHROPIC_API_KEY gesetzt).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from config import YOY_THRESHOLD, ANTHROPIC_API_KEY_ENV, LLM_MODEL
from core.formatting import euro, percent


@dataclass
class Recommendation:
    prioritaet: int          # 1 = höchste
    kategorie: str           # 'Treiber' | 'Risiko' | 'Stabil' | 'Prüfen'
    ebene: str               # z. B. Abteilungs-/WG-Name
    lesart: str              # Was sagen die Zahlen?
    massnahme: str           # Was tun?
    caveat: str = ""         # Daten-Vorbehalt


def _has_qty(row) -> bool:
    m, mvj = row.get("menge"), row.get("menge_vj")
    return m is not None and mvj is not None and not (np.isnan(m) or np.isnan(mvj))


def recommend_row(row: dict, ebene_label: str, span_avg: float | None,
                  luecke_wochen: float | None = None) -> Recommendation:
    """Regelwerk für EINE Zeile (Abteilung/Warengruppe/Artikel)."""
    yoy = row.get("yoy")
    spanne = row.get("spanne")
    name = row.get(ebene_label, "?")

    if yoy is None:
        return Recommendation(
            3, "Prüfen", name,
            "Kein Vorjahreswert für diesen Zeitraum vorhanden.",
            "Sobald Historie wächst, automatisch bewertet.",
            "YoY nicht berechenbar.")

    sp_ok = (spanne is not None and span_avg is not None and spanne >= span_avg)

    # Wachstum
    if yoy >= YOY_THRESHOLD:
        if sp_ok:
            return Recommendation(
                2, "Treiber", name,
                f"Wächst {percent(yoy, with_sign=True)} bei überdurchschnittlicher Spanne.",
                "Treiber fördern: Fläche, Zweitplatzierung, Aktion.")
        return Recommendation(
            2, "Treiber", name,
            f"Wächst {percent(yoy, with_sign=True)}, aber dünne Spanne.",
            "Kalkulation prüfen – Wachstum ja, Marge sichern.")

    # Stabil
    if -YOY_THRESHOLD < yoy < YOY_THRESHOLD:
        return Recommendation(4, "Stabil", name,
                              f"Stabil ({percent(yoy, with_sign=True)}).",
                              "Beobachten, kein akuter Handlungsbedarf.")

    # Rückgang (yoy <= -threshold)
    luecke = luecke_wochen is not None and luecke_wochen > 0
    has_decomp = (row.get("effekt_preis") is not None
                  and row.get("effekt_menge") is not None
                  and not np.isnan(row.get("effekt_preis"))
                  and not np.isnan(row.get("effekt_menge")))
    if has_decomp:
        eff_preis = abs(row.get("effekt_preis") or 0)
        eff_menge = abs(row.get("effekt_menge") or 0)
        if luecke and eff_menge >= eff_preis:
            return Recommendation(
                1, "Risiko", name,
                f"Rückgang {percent(yoy, with_sign=True)}, v. a. Mengenverlust, "
                f"zugleich Bestandslücke in {int(luecke_wochen)} Wochen.",
                "Ursache wahrscheinlich Verfügbarkeit → Bestellmenge/Disposition prüfen.",
                "Verfügbarkeits-Overlay aktiv.")
        if eff_preis > eff_menge:
            return Recommendation(
                1, "Risiko", name,
                f"Rückgang {percent(yoy, with_sign=True)}, v. a. über den Preis.",
                "Marktthema → Frequenz/Eigenmarke sichern, Preislage prüfen.")
        return Recommendation(
            1, "Risiko", name,
            f"Rückgang {percent(yoy, with_sign=True)}, echter Mengenverlust.",
            "Verfügbarkeit, Preislage ggü. Discount, Platzierung prüfen.")

    # Rückgang ohne Preis/Mengen-Zerlegung (z. B. Abteilungsebene: gemischte
    # Einheiten -> Zerlegung nicht sinnvoll) bzw. Menge unterdrückt/nicht geliefert.
    caveat = ("Mengen gemischt/unterdrückt – Preis-/Mengenzerlegung erst auf "
              "Warengruppen-/Artikelebene aussagekräftig.")
    if luecke:
        return Recommendation(
            1, "Risiko", name,
            f"Rückgang {percent(yoy, with_sign=True)}, zugleich Bestandslücke "
            f"in {int(luecke_wochen)} Wochen.",
            "Verfügbarkeit prüfen (Bestellmenge/Disposition); ins Warengruppen-/"
            "Artikel-Drilldown gehen.", caveat)
    return Recommendation(
        2, "Prüfen", name,
        f"Rückläufig {percent(yoy, with_sign=True)}.",
        "Ins Warengruppen-/Artikel-Drilldown gehen: Preis vs. Menge, Verfügbarkeit.",
        caveat)


def recommend_table(df, ebene_label: str, bestand_col: str | None = None) -> list[Recommendation]:
    """Empfehlungen für eine ganze Ebene, nach Priorität sortiert."""
    if df is None or len(df) == 0:
        return []
    span_avg = df["spanne"].median() if "spanne" in df.columns else None
    recs = []
    for _, r in df.iterrows():
        row = r.to_dict()
        lw = row.get(bestand_col) if bestand_col else None
        recs.append(recommend_row(row, ebene_label, span_avg, lw))
    recs.sort(key=lambda x: (x.prioritaet, -abs(0)))
    return recs


# --- Optionaler LLM-Layer ------------------------------------------------------

def llm_available() -> bool:
    return bool(os.environ.get(ANTHROPIC_API_KEY_ENV))


def _signals_payload(totals: dict, top_pos, top_neg, ebene: str) -> dict:
    def slim(df):
        if df is None or len(df) == 0:
            return []
        keep = [c for c in ["abteilung", "warengruppe", "umsatz", "yoy",
                            "spanne", "delta_umsatz", "treiber"] if c in df.columns]
        return df[keep].head(8).round(4).to_dict("records")
    return {
        "ebene": ebene,
        "summe_umsatz": round(float(totals.get("umsatz") or 0), 2),
        "summe_yoy": totals.get("yoy"),
        "top_gewinner": slim(top_pos),
        "top_verlierer": slim(top_neg),
    }


def llm_summary(totals: dict, top_pos, top_neg, ebene: str = "Markt") -> str | None:
    """Klartext-Management-Summary aus vorberechneten Signalen (kein Selbstrechnen).

    Sendet AUSSCHLIESSLICH aggregierte, anonyme Kennzahlen – keine Rohdaten.
    Liefert None, wenn kein API-Key gesetzt ist (Layer standardmäßig aus).
    """
    if not llm_available():
        return None
    try:
        import anthropic
    except ImportError:
        return None
    payload = _signals_payload(totals, top_pos, top_neg, ebene)
    client = anthropic.Anthropic(api_key=os.environ[ANTHROPIC_API_KEY_ENV])
    prompt = (
        "Du bist Controlling-Assistenz für einen EDEKA-Markt. Dir werden FERTIG "
        "BERECHNETE Kennzahlen übergeben. Rechne nichts selbst, interpretiere nur. "
        "Schreibe ein priorisiertes, knappes Management-Summary auf Deutsch "
        "(max. 6 Bullet-Punkte): wichtigste Treiber, Risiken, konkrete nächste "
        "Schritte. Nenne Zahlen aus den Fakten, erfinde keine.\n\n"
        f"FAKTEN (JSON):\n{payload}"
    )
    msg = client.messages.create(
        model=LLM_MODEL, max_tokens=700,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
