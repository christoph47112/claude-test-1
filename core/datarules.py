"""Kritische Datenregeln – an EINER Stelle, damit nichts auseinanderläuft.

Diese Regeln sind die häufigsten Fehlerquellen in der Auswertung. Wer hier
etwas ändert, sollte CLAUDE.md gelesen haben.

1. Geschäftsjahr (GJ) & Jahreswechselwoche KW 01
   Die Kalenderwoche über den Jahreswechsel wird im Export nach Kalendermonat
   gesplittet abgelegt:
     - Der Dezember-Teil erscheint als  Monat == 'DEZ'  mit  Woche == '01'
       und gehört zum FOLGE-Geschäftsjahr  -> GJ = Jahr + 1.
     - Der Januar-Teil erscheint als     Monat == 'JAN'  mit  Woche == '01'
       und bleibt im selben Jahr          -> GJ = Jahr.
   Alle übrigen Zeilen: GJ = Jahr.
   (Ohne diese Regel dreht sich der Jahresvergleich im Vorzeichen.)

2. Unterdrückte Mengen ('*')
   Menge / Abschr. Menge / Vollabschr. Menge können '*' enthalten
   (datenschutz-/schwellwertbedingt unterdrückt). '*' bedeutet
   "nicht verfügbar" und wird zu NULL – NIEMALS als 0 summiert.

3. Verhältniszahlen werden NEU gerechnet, nie summiert
   - Spanne          = Warenrohgewinn / Umsatz
   - Ø-Preis         = Umsatz / Menge          (nur wo echte Menge vorliegt)
   - Ø-Bon (D-Bon)   = Umsatz / Kunden
   Deshalb speichern wir nur additive Basis-Kennzahlen und leiten Quotienten
   bei jeder Aggregation neu ab.
"""
from __future__ import annotations

import re
import pandas as pd
import numpy as np

# Monatskürzel im Export -> Kalendermonatsnummer
MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "MÄR": 3, "APR": 4, "MAI": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OKT": 10, "NOV": 11, "DEZ": 12,
}

# Additive Basis-Kennzahlen (dürfen summiert werden).
ADDITIVE_METRICS = [
    "umsatz", "menge", "kunden", "warenrohgewinn",
    "wareneinsatz", "umsatz_bio", "abschr_menge", "vollabschr_menge",
]
# Mengen-Kennzahlen, die '*'-Unterdrückung tragen können.
SUPPRESSIBLE_METRICS = ["menge", "abschr_menge", "vollabschr_menge"]

# Anzeige-Name (Export) -> internes Feld
KENNZAHL_MAP = {
    "Umsatz": "umsatz",
    "Menge": "menge",
    "Kunden": "kunden",
    "D-Bon": "d_bon",                  # Verhältniszahl – wird neu gerechnet
    "Warenrohgewinn": "warenrohgewinn",
    "Nettoertragssp.": "nettoertragssp",  # Verhältniszahl – wird neu gerechnet
    "Abschr. Menge": "abschr_menge",
    "Vollabschr. Menge": "vollabschr_menge",
    "Wareneinsatz": "wareneinsatz",
    "Umsatz Bio": "umsatz_bio",
}


def parse_number(value) -> float | None:
    """Wandelt einen Zellenwert in float um.

    '*' (und Leerwerte) -> None  (= nicht verfügbar, NICHT 0).
    Unterstützt deutsche wie englische Dezimaltrennung defensiv.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if pd.isna(value):
            return None
        return float(value)
    s = str(value).strip()
    if s == "" or s == "*" or s.lower() in {"nan", "none"}:
        return None
    # reine Zahl?
    s = s.replace("\xa0", "").replace(" ", "")
    # deutsches Format 1.234,56 -> 1234.56
    if re.match(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$", s):
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_number_series(s: pd.Series) -> pd.Series:
    """Vektorisierte Variante von parse_number für eine ganze Spalte."""
    return s.map(parse_number).astype("float64")


def compute_gj(jahr: pd.Series, monat: pd.Series, woche: pd.Series) -> pd.Series:
    """Geschäftsjahr nach Regel 1 berechnen.

    jahr: int-fähig, monat: 'JAN'.., woche: '01'.. (oder int).
    """
    jahr_i = pd.to_numeric(jahr, errors="coerce").astype("Int64")
    monat_u = monat.astype(str).str.upper().str.strip()
    woche_i = pd.to_numeric(woche, errors="coerce").astype("Int64")
    is_dez_kw1 = (monat_u == "DEZ") & (woche_i == 1)
    return (jahr_i + is_dez_kw1.astype("Int64")).astype("Int64")


def span(warenrohgewinn, umsatz) -> float | None:
    """Spanne = Warenrohgewinn / Umsatz (als Anteil, z. B. 0.235)."""
    if umsatz in (None, 0) or warenrohgewinn is None or pd.isna(umsatz) or pd.isna(warenrohgewinn):
        return None
    if umsatz == 0:
        return None
    return float(warenrohgewinn) / float(umsatz)


def avg_price(umsatz, menge) -> float | None:
    """Ø-Preis = Umsatz / Menge (nur bei echter Menge)."""
    if menge in (None, 0) or umsatz is None or pd.isna(menge) or pd.isna(umsatz):
        return None
    if menge == 0:
        return None
    return float(umsatz) / float(menge)


def avg_bon(umsatz, kunden) -> float | None:
    """Ø-Bon = Umsatz / Kunden."""
    if kunden in (None, 0) or umsatz is None or pd.isna(kunden) or pd.isna(umsatz):
        return None
    if kunden == 0:
        return None
    return float(umsatz) / float(kunden)


def yoy(current, previous) -> float | None:
    """Year-over-Year-Veränderung als Anteil. None wenn Vorjahr fehlt/0."""
    if current is None or previous in (None, 0) or pd.isna(current) or pd.isna(previous):
        return None
    if previous == 0:
        return None
    return (float(current) - float(previous)) / float(previous)
