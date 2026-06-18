"""Loader: Export-Dateien -> normalisierte DataFrames für DuckDB.

UmsatzLoader   : Schema VOLLSTÄNDIG BEKANNT (SAP BO 'Kreuztabelle'). Fest gebaut.
ArtikelLoader  : Schema kommt noch -> Spalten über mapping.yaml zuordenbar.
BestandLoader  : Schema kommt noch -> Spalten über mapping.yaml zuordenbar.

Die noch nicht gelieferten Loader klopfen KEINE exakten Spaltennamen fest:
sie lesen ein Mapping (Anzeigespalte -> internes Feld) aus mapping.yaml und
melden, welche Pflichtfelder noch nicht zugeordnet sind ("Contract").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import datetime as dt
import yaml
import pandas as pd
import numpy as np

from core import datarules as dr
from config import MAPPING_PATH


# ---------------------------------------------------------------------------
# 1) Umsatz-Export – bekannt
# ---------------------------------------------------------------------------

UMSATZ_SHEET = "Kreuztabelle"
# Fixe Header-Reihenfolge laut Schema (Kennzahl-Spalte trägt keinen Header):
#   Abteilung | Hauptwarengrp. | <Kennzahl> | Jahr | Monat | Woche | Gesamtergebnis | <Marktname>
SUMMARY_HAUPTWG = "Ergebnis"           # Abteilungssumme
SUMMARY_ABTEILUNG = "Gesamtergebnis"   # Marktsumme


@dataclass
class UmsatzResult:
    frame: pd.DataFrame
    markt: str
    gj_range: tuple[int, int]
    kw_max: int           # tatsächlich verwendeter Vergleichs-Endpunkt
    n_input_rows: int
    plausi: pd.DataFrame  # Umsatz je GJ x (<=bis_kw)
    kw_max_data: int = 0  # höchste KW im jüngsten GJ (vor bis_kw-Filter)
    kw_reason: str = ""   # Begründung der automatischen KW-Wahl


def last_complete_kw(latest_gj: int, kw_max_latest: int,
                     today: "dt.date | None" = None) -> tuple[int, str]:
    """Letzte ABGESCHLOSSENE KW bestimmen (laufende Woche ausschließen).

    Heuristik, deterministisch aus Daten + Kalender:
      - Liegt die höchste vorhandene KW im aktuell laufenden Geschäftsjahr UND
        ist sie >= der aktuellen ISO-Kalenderwoche, gilt sie als laufend
        (unvollständig) -> bis_kw = kw_max_latest - 1.
      - Sonst ist der Export bereits sauber abgeschlossen -> bis_kw = kw_max_latest.
    Über --bis-kw jederzeit übersteuerbar.
    """
    today = today or dt.date.today()
    iso = today.isocalendar()
    # GJ "heute": DEZ/KW01-Sonderfall greift nur in der Jahreswechselwoche.
    cur_gj = iso.year
    if iso.week == 1 and today.month == 12:
        cur_gj = today.year + 1
    if latest_gj >= cur_gj and kw_max_latest >= iso.week and kw_max_latest > 1:
        return kw_max_latest - 1, (
            f"KW {kw_max_latest} entspricht der laufenden Woche "
            f"(heute KW {iso.week}/{cur_gj}) -> ausgeschlossen, "
            f"Vergleich bis KW {kw_max_latest - 1}.")
    return kw_max_latest, (
        f"Export endet mit abgeschlossener KW {kw_max_latest} -> "
        f"Vergleich bis KW {kw_max_latest}.")


def detect_market_column(header_row: list) -> int:
    """Rechteste Wertespalte = Marktwert. Auto-Erkennung (nicht hartkodiert)."""
    return len(header_row) - 1


def load_umsatz(path: str | Path, bis_kw: int | None = None) -> UmsatzResult:
    """Liest den Umsatz-Export und normalisiert ihn auf fact_umsatz_woche-Form.

    bis_kw: nur KW <= bis_kw übernehmen (laufende Woche ausschließen).
            None -> alle vorhandenen Wochen (max KW des jüngsten GJ).
    """
    raw = pd.read_excel(path, sheet_name=UMSATZ_SHEET, header=None)
    header = list(raw.iloc[0].values)
    markt_col = detect_market_column(header)
    markt_name = str(header[markt_col]).strip()

    df = raw.iloc[1:].copy()
    df.columns = ["abteilung", "hauptwarengrp", "kennzahl", "jahr",
                  "monat", "woche", "gesamt", "markt_val"][: df.shape[1]]
    n_input = len(df)

    # Nur granulare Wochenzeilen: gefülltes Jahr/Woche, echte Warengruppe.
    mask = (
        df["jahr"].notna() & df["woche"].notna()
        & df["hauptwarengrp"].notna()
        & (df["hauptwarengrp"].astype(str).str.strip() != SUMMARY_HAUPTWG)
        & (df["abteilung"].astype(str).str.strip() != SUMMARY_ABTEILUNG)
    )
    g = df[mask].copy()

    g["gj"] = dr.compute_gj(g["jahr"], g["monat"], g["woche"])
    g["kw"] = pd.to_numeric(g["woche"], errors="coerce").astype("Int64")
    g["wert"] = dr.parse_number_series(g["markt_val"])  # '*' -> NaN
    g["kennzahl_intern"] = g["kennzahl"].map(dr.KENNZAHL_MAP)

    # Long -> Wide: je (Abteilung, WG, GJ, KW) eine Zeile mit allen Kennzahlen.
    # Verhältniszahlen (d_bon, nettoertragssp) NICHT übernehmen -> neu rechnen.
    keep = dr.ADDITIVE_METRICS
    g = g[g["kennzahl_intern"].isin(keep)]

    wide = (
        g.pivot_table(
            index=["abteilung", "hauptwarengrp", "gj", "kw"],
            columns="kennzahl_intern",
            values="wert",
            aggfunc="sum",   # additiv; Monats-Split derselben KW wird summiert
        )
        .reset_index()
        .rename(columns={"hauptwarengrp": "warengruppe"})
    )
    wide.columns.name = None
    for m in keep:
        if m not in wide.columns:
            wide[m] = np.nan
    wide["markt"] = markt_name

    # bis_kw bestimmen / anwenden
    latest_gj = int(wide["gj"].max())
    kw_max_latest = int(wide[wide["gj"] == latest_gj]["kw"].max())
    auto_kw, kw_reason = last_complete_kw(latest_gj, kw_max_latest)
    if bis_kw is None:
        bis_kw = auto_kw
    wide = wide[wide["kw"] <= bis_kw].copy()

    wide["gj"] = wide["gj"].astype("Int64").astype(int)
    wide["kw"] = wide["kw"].astype("Int64").astype(int)

    cols = ["markt", "abteilung", "warengruppe", "gj", "kw"] + keep
    frame = wide[cols].sort_values(["gj", "kw", "abteilung", "warengruppe"])

    plausi = (
        frame.groupby("gj")["umsatz"].sum().round(2).rename("umsatz_summe").to_frame()
    )
    gj_min, gj_max = int(frame["gj"].min()), int(frame["gj"].max())
    return UmsatzResult(
        frame=frame, markt=markt_name, gj_range=(gj_min, gj_max),
        kw_max=bis_kw, n_input_rows=n_input, plausi=plausi,
        kw_max_data=kw_max_latest, kw_reason=kw_reason,
    )


# ---------------------------------------------------------------------------
# 2)/3) Mapping-getriebene Loader – Schema kommt noch
# ---------------------------------------------------------------------------

def load_mapping() -> dict:
    if not Path(MAPPING_PATH).exists():
        return {}
    with open(MAPPING_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@dataclass
class MappingReport:
    """Ergebnis des Mapping-Abgleichs für eine noch zu bestätigende Quelle."""
    quelle: str
    found_columns: list[str]
    mapped: dict[str, str]          # internes_feld -> reale_spalte
    missing_required: list[str]     # Pflichtfelder ohne Zuordnung
    suggestions: dict[str, str] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return not self.missing_required


def _suggest(internal: str, columns: list[str]) -> str | None:
    """Heuristischer Spaltenvorschlag anhand von Stichwörtern."""
    hints = {
        "artikel_id": ["artikelnummer", "artikel-nr", "artikelnr", "gtin", "ean", "nummer"],
        "bezeichnung": ["bezeichnung", "artikel", "name", "text"],
        "warengruppe": ["warengruppe", "wg", "hauptwarengrp"],
        "abteilung": ["abteilung"],
        "jahr": ["jahr", "year"],
        "monat": ["monat", "month"],
        "woche": ["woche", "kw", "week"],
        "datum": ["datum", "date"],
        "umsatz": ["umsatz", "wert", "sales"],
        "menge": ["menge", "stück", "stk", "qty"],
        "kunden": ["kunden", "bon"],
        "rohertrag": ["rohertrag", "rohgewinn", "spanne", "ertrag"],
        "bestand": ["bestand", "stock", "vorrat"],
        "luecke_flag": ["lücke", "luecke", "null", "leer", "gap"],
        "lost_sale": ["lost", "negativ", "fehlmenge"],
    }
    keys = hints.get(internal, [internal])
    low = {c.lower(): c for c in columns}
    for col_low, col in low.items():
        if any(h in col_low for h in keys):
            return col
    return None


def inspect_columns(path: str | Path, sheet=0) -> list[str]:
    df = pd.read_excel(path, sheet_name=sheet, nrows=5)
    return [str(c) for c in df.columns]


def build_mapping_report(quelle: str, path: str | Path) -> MappingReport:
    """Spalten einer gelieferten Datei inspizieren und gegen den Contract mappen."""
    mp = load_mapping().get(quelle, {})
    required = mp.get("required_fields", [])
    explicit = mp.get("columns", {})  # internes_feld -> reale_spalte (manuell gepflegt)
    cols = inspect_columns(path, mp.get("sheet", 0))

    mapped, suggestions, missing = {}, {}, []
    contract = required + mp.get("optional_fields", [])
    for internal in contract:
        if internal in explicit and explicit[internal] in cols:
            mapped[internal] = explicit[internal]
        else:
            guess = _suggest(internal, cols)
            if guess:
                suggestions[internal] = guess
            if internal in required and internal not in mapped:
                missing.append(internal)
    return MappingReport(quelle, cols, mapped, missing, suggestions)


def _resolve_columns(quelle: str, df: pd.DataFrame) -> dict[str, str]:
    """Internes Feld -> reale Spalte, aus mapping.yaml + Heuristik."""
    mp = load_mapping().get(quelle, {})
    explicit = mp.get("columns", {})
    contract = mp.get("required_fields", []) + mp.get("optional_fields", [])
    cols = [str(c) for c in df.columns]
    resolved = {}
    for internal in contract:
        if internal in explicit and explicit[internal] in cols:
            resolved[internal] = explicit[internal]
        else:
            guess = _suggest(internal, cols)
            if guess:
                resolved[internal] = guess
    return resolved


def _derive_gj_kw(df: pd.DataFrame, cols: dict[str, str]) -> pd.DataFrame:
    """GJ/KW aus Jahr/Monat/Woche ODER aus einem Datum ableiten (KW-01-Regel)."""
    out = df.copy()
    if {"jahr", "woche"} <= cols.keys():
        monat = out[cols["monat"]] if "monat" in cols else pd.Series([""] * len(out))
        out["gj"] = dr.compute_gj(out[cols["jahr"]], monat, out[cols["woche"]])
        out["kw"] = pd.to_numeric(out[cols["woche"]], errors="coerce").astype("Int64")
    elif "datum" in cols:
        d = pd.to_datetime(out[cols["datum"]], errors="coerce")
        iso = d.dt.isocalendar()
        # ISO-Jahr ~ GJ; KW-01-DEZ-Sonderfall greift hier über ISO-Jahr automatisch.
        out["gj"] = iso["year"].astype("Int64")
        out["kw"] = iso["week"].astype("Int64")
    else:
        out["gj"] = pd.NA
        out["kw"] = pd.NA
    return out


def load_artikel(path: str | Path, markt: str) -> tuple[pd.DataFrame, MappingReport]:
    """Artikel-Umsatz-Export laden (mapping-getrieben). Liefert (frame, report)."""
    report = build_mapping_report("artikel", path)
    if not report.ready:
        return pd.DataFrame(), report
    mp = load_mapping().get("artikel", {})
    df = pd.read_excel(path, sheet_name=mp.get("sheet", 0))
    cols = _resolve_columns("artikel", df)
    df = _derive_gj_kw(df, cols)
    out = pd.DataFrame({
        "markt": markt,
        "artikel_id": df[cols["artikel_id"]].astype(str).str.strip(),
        "bezeichnung": df[cols["bezeichnung"]] if "bezeichnung" in cols else None,
        "warengruppe": df[cols["warengruppe"]] if "warengruppe" in cols else None,
        "abteilung": df[cols["abteilung"]] if "abteilung" in cols else None,
        "gj": df["gj"], "kw": df["kw"],
        "umsatz": dr.parse_number_series(df[cols["umsatz"]]) if "umsatz" in cols else np.nan,
        "menge": dr.parse_number_series(df[cols["menge"]]) if "menge" in cols else np.nan,
        "kunden": dr.parse_number_series(df[cols["kunden"]]) if "kunden" in cols else np.nan,
        "rohertrag": dr.parse_number_series(df[cols["rohertrag"]]) if "rohertrag" in cols else np.nan,
    })
    out = (out.dropna(subset=["gj", "kw"])
              .groupby(["markt", "artikel_id", "bezeichnung", "warengruppe",
                        "abteilung", "gj", "kw"], dropna=False)
              .sum(min_count=1).reset_index())
    out["gj"] = out["gj"].astype(int); out["kw"] = out["kw"].astype(int)
    return out, report


def load_bestand(path: str | Path, markt: str) -> tuple[pd.DataFrame, MappingReport]:
    """Bestand/Verfügbarkeit laden (mapping-getrieben). Liefert (frame, report)."""
    report = build_mapping_report("bestand", path)
    if not report.ready:
        return pd.DataFrame(), report
    mp = load_mapping().get("bestand", {})
    df = pd.read_excel(path, sheet_name=mp.get("sheet", 0))
    cols = _resolve_columns("bestand", df)
    df = _derive_gj_kw(df, cols)
    bestand = dr.parse_number_series(df[cols["bestand"]]) if "bestand" in cols else np.nan
    if "luecke_flag" in cols:
        luecke = df[cols["luecke_flag"]].astype(str).str.lower().isin(
            ["1", "true", "ja", "x", "lücke", "luecke"])
    else:
        luecke = (bestand <= 0)  # Fallback: Nullbestand = Lücke
    out = pd.DataFrame({
        "markt": markt,
        "artikel_id": df[cols["artikel_id"]].astype(str).str.strip(),
        "bezeichnung": df[cols["bezeichnung"]] if "bezeichnung" in cols else None,
        "warengruppe": df[cols["warengruppe"]] if "warengruppe" in cols else None,
        "abteilung": df[cols["abteilung"]] if "abteilung" in cols else None,
        "gj": df["gj"], "kw": df["kw"],
        "bestand": bestand,
        "luecke_flag": luecke,
        "lost_sale": dr.parse_number_series(df[cols["lost_sale"]]) if "lost_sale" in cols else np.nan,
    })
    out = out.dropna(subset=["gj", "kw"])
    out["gj"] = out["gj"].astype(int); out["kw"] = out["kw"].astype(int)
    return out, report
