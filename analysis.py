"""Analyse-Schicht – deterministisch, von der UI getrennt.

Liest aus DuckDB und liefert Kennzahlen & Signale je Ebene
(Markt / Abteilung / Warengruppe / Artikel):
  Umsatz, YoY, Spanne, Rohertrag-YoY, Anteil an der übergeordneten Ebene,
  Preis×Menge-Zerlegung, Pareto, Abschriften, Anomalie ("vs. erwartet"),
  Verfügbarkeits-Join.

Alle Quotienten werden NEU gerechnet (nie summiert) – siehe core.datarules.
"""
from __future__ import annotations

import pandas as pd
import numpy as np

from core import datarules as dr
from config import (YOY_THRESHOLD, ANOMALY_SIGMA, ANOMALY_MIN_WEEKS,
                    ANOMALY_BASELINE_WEEKS)

ADD = dr.ADDITIVE_METRICS


# --- Rahmendaten ---------------------------------------------------------------

def available_gjs(con) -> list[int]:
    rows = con.execute(
        "SELECT DISTINCT gj FROM fact_umsatz_woche ORDER BY gj"
    ).fetchall()
    return [r[0] for r in rows]


def market_name(con) -> str | None:
    r = con.execute("SELECT markt FROM fact_umsatz_woche LIMIT 1").fetchone()
    return r[0] if r else None


def kw_bounds(con, gj: int) -> tuple[int, int]:
    r = con.execute(
        "SELECT MIN(kw), MAX(kw) FROM fact_umsatz_woche WHERE gj=?", [gj]
    ).fetchone()
    return (r[0] or 0, r[1] or 0)


# --- Aggregations-Kern ---------------------------------------------------------

def _agg_block(con, gj: int, bis_kw: int, group_cols: list[str],
               where: str = "", params: list | None = None) -> pd.DataFrame:
    """Additive Kennzahlen je group_cols für ein GJ bis bis_kw.

    SUM(menge) ignoriert NULL automatisch; um '*' nicht als 0 zu zählen,
    setzen wir menge auf NULL, wenn KEINE einzige echte Menge vorlag.
    """
    params = params or []
    sums = ", ".join([f"SUM({m}) AS {m}" for m in ADD])
    cnts = ", ".join([f"COUNT({m}) AS _n_{m}" for m in dr.SUPPRESSIBLE_METRICS])
    select_prefix = (", ".join(group_cols) + ", ") if group_cols else ""
    group_by = f"GROUP BY {', '.join(group_cols)}" if group_cols else ""
    sql = f"""
        SELECT {select_prefix}{sums}, {cnts}
        FROM fact_umsatz_woche
        WHERE gj = ? AND kw <= ? {where}
        {group_by}
    """
    df = con.execute(sql, [gj, bis_kw] + params).df()
    # Mengen ohne jede echte Beobachtung -> NA (nicht 0)
    for m in dr.SUPPRESSIBLE_METRICS:
        df.loc[df[f"_n_{m}"] == 0, m] = np.nan
        df.drop(columns=[f"_n_{m}"], inplace=True)
    return df


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Quotienten ergänzen: Spanne, Ø-Preis, Ø-Bon."""
    df = df.copy()
    df["spanne"] = df.apply(lambda r: dr.span(r["warenrohgewinn"], r["umsatz"]), axis=1)
    df["avg_preis"] = df.apply(lambda r: dr.avg_price(r["umsatz"], r["menge"]), axis=1)
    df["avg_bon"] = df.apply(lambda r: dr.avg_bon(r["umsatz"], r["kunden"]), axis=1)
    return df


def _join_prev(cur: pd.DataFrame, prev: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Aktuelles GJ mit Vorjahr verbinden und YoY-Kennzahlen rechnen."""
    p = prev[keys + ["umsatz", "warenrohgewinn", "menge", "kunden"]].rename(
        columns={"umsatz": "umsatz_vj", "warenrohgewinn": "wrg_vj",
                 "menge": "menge_vj", "kunden": "kunden_vj"})
    out = cur.merge(p, on=keys, how="left")
    out["yoy"] = out.apply(lambda r: dr.yoy(r["umsatz"], r["umsatz_vj"]), axis=1)
    out["rohertrag_yoy"] = out.apply(
        lambda r: dr.yoy(r["warenrohgewinn"], r["wrg_vj"]), axis=1)
    out["spanne_vj"] = out.apply(lambda r: dr.span(r["wrg_vj"], r["umsatz_vj"]), axis=1)
    out["delta_umsatz"] = out["umsatz"] - out["umsatz_vj"]
    return out


# --- Ebene 1: Markt-Überblick (alle Abteilungen) -------------------------------

def market_overview(con, gj: int, bis_kw: int, prev_gj: int | None) -> pd.DataFrame:
    cur = _enrich(_agg_block(con, gj, bis_kw, ["abteilung"]))
    if prev_gj is not None:
        prev = _enrich(_agg_block(con, prev_gj, bis_kw, ["abteilung"]))
        cur = _join_prev(cur, prev, ["abteilung"])
    else:
        for col in ["umsatz_vj", "yoy", "rohertrag_yoy", "spanne_vj", "delta_umsatz"]:
            cur[col] = np.nan
    total = cur["umsatz"].sum()
    cur["anteil"] = cur["umsatz"] / total if total else np.nan
    return cur.sort_values("umsatz", ascending=False)


def market_totals(con, gj: int, bis_kw: int, prev_gj: int | None) -> dict:
    cur = _enrich(_agg_block(con, gj, bis_kw, []))
    row = cur.iloc[0].to_dict() if len(cur) else {m: np.nan for m in ADD}
    if prev_gj is not None:
        prev = _agg_block(con, prev_gj, bis_kw, [])
        prow = prev.iloc[0].to_dict() if len(prev) else {}
        row["umsatz_vj"] = prow.get("umsatz", np.nan)
        row["wrg_vj"] = prow.get("warenrohgewinn", np.nan)
        row["yoy"] = dr.yoy(row.get("umsatz"), row.get("umsatz_vj"))
        row["rohertrag_yoy"] = dr.yoy(row.get("warenrohgewinn"), row.get("wrg_vj"))
    return row


# --- Ebene 2: Abteilung -> Warengruppen ----------------------------------------

def department_detail(con, abteilung: str, gj: int, bis_kw: int,
                      prev_gj: int | None) -> pd.DataFrame:
    cur = _enrich(_agg_block(con, gj, bis_kw, ["warengruppe"],
                             "AND abteilung = ?", [abteilung]))
    if prev_gj is not None:
        prev = _enrich(_agg_block(con, prev_gj, bis_kw, ["warengruppe"],
                                  "AND abteilung = ?", [abteilung]))
        cur = _join_prev(cur, prev, ["warengruppe"])
        cur = _decompose(cur)
    total = cur["umsatz"].sum()
    cur["anteil"] = cur["umsatz"] / total if total else np.nan
    return cur.sort_values("umsatz", ascending=False)


def _decompose(df: pd.DataFrame) -> pd.DataFrame:
    """Preis × Menge × Käufer-Zerlegung (nur wo echte Menge in beiden Jahren).

    ΔUmsatz ≈ ΔMenge·Preis_vj + ΔPreis·Menge  (additiv zerlegt).
    Liefert effekt_menge / effekt_preis (in €) und 'treiber' ('preis'|'menge').
    """
    df = df.copy()
    p_cur = df["umsatz"] / df["menge"].replace(0, np.nan)
    p_vj = df["umsatz_vj"] / df["menge_vj"].replace(0, np.nan)
    d_menge = df["menge"] - df["menge_vj"]
    d_preis = p_cur - p_vj
    df["effekt_menge"] = d_menge * p_vj
    df["effekt_preis"] = d_preis * df["menge"]
    has_qty = df["menge"].notna() & df["menge_vj"].notna()
    df["menge_verfuegbar"] = has_qty
    df["treiber"] = np.where(
        ~has_qty, "unbekannt",
        np.where(df["effekt_preis"].abs() > df["effekt_menge"].abs(), "preis", "menge"))
    return df


# --- Ebene 3: Warengruppe -> Artikel (Quelle 2) + Verfügbarkeit (Quelle 3) -----

def warengruppe_artikel(con, warengruppe: str, gj: int, bis_kw: int,
                        prev_gj: int | None, with_bestand: bool = False) -> pd.DataFrame:
    if con.execute("SELECT COUNT(*) FROM fact_artikel_woche").fetchone()[0] == 0:
        return pd.DataFrame()
    cur = con.execute("""
        SELECT artikel_id, any_value(bezeichnung) AS bezeichnung,
               SUM(umsatz) AS umsatz, SUM(menge) AS menge,
               SUM(kunden) AS kunden, SUM(rohertrag) AS rohertrag
        FROM fact_artikel_woche
        WHERE warengruppe = ? AND gj = ? AND kw <= ?
        GROUP BY artikel_id
    """, [warengruppe, gj, bis_kw]).df()
    if prev_gj is not None:
        prev = con.execute("""
            SELECT artikel_id, SUM(umsatz) AS umsatz_vj, SUM(menge) AS menge_vj
            FROM fact_artikel_woche
            WHERE warengruppe = ? AND gj = ? AND kw <= ?
            GROUP BY artikel_id
        """, [warengruppe, prev_gj, bis_kw]).df()
        cur = cur.merge(prev, on="artikel_id", how="outer")
        cur["yoy"] = cur.apply(lambda r: dr.yoy(r.get("umsatz"), r.get("umsatz_vj")), axis=1)
        cur["delta_umsatz"] = cur["umsatz"].fillna(0) - cur["umsatz_vj"].fillna(0)
    if with_bestand:
        cur = attach_bestand(con, cur, gj, bis_kw)
    return cur.sort_values("umsatz", ascending=False, na_position="last")


def attach_bestand(con, artikel_df: pd.DataFrame, gj: int, bis_kw: int) -> pd.DataFrame:
    """Verfügbarkeits-Overlay je Artikel anfügen (Lücken-Wochen, Ø-Bestand)."""
    if con.execute("SELECT COUNT(*) FROM fact_bestand").fetchone()[0] == 0:
        artikel_df["luecke_wochen"] = np.nan
        artikel_df["bestand_avg"] = np.nan
        return artikel_df
    b = con.execute("""
        SELECT artikel_id,
               SUM(CASE WHEN luecke_flag THEN 1 ELSE 0 END) AS luecke_wochen,
               AVG(bestand) AS bestand_avg
        FROM fact_bestand WHERE gj = ? AND kw <= ?
        GROUP BY artikel_id
    """, [gj, bis_kw]).df()
    return artikel_df.merge(b, on="artikel_id", how="left")


def availability_cross_section(con, gj: int, bis_kw: int, prev_gj: int | None) -> pd.DataFrame:
    """Querschnitt: Artikel mit Umsatzrückgang UND gleichzeitiger Bestandslücke."""
    if (con.execute("SELECT COUNT(*) FROM fact_artikel_woche").fetchone()[0] == 0
            or con.execute("SELECT COUNT(*) FROM fact_bestand").fetchone()[0] == 0
            or prev_gj is None):
        return pd.DataFrame()
    cur = con.execute("""
        SELECT a.artikel_id, any_value(a.bezeichnung) AS bezeichnung,
               any_value(a.warengruppe) AS warengruppe,
               SUM(a.umsatz) AS umsatz
        FROM fact_artikel_woche a WHERE a.gj=? AND a.kw<=? GROUP BY a.artikel_id
    """, [gj, bis_kw]).df()
    prev = con.execute("""
        SELECT artikel_id, SUM(umsatz) AS umsatz_vj
        FROM fact_artikel_woche WHERE gj=? AND kw<=? GROUP BY artikel_id
    """, [prev_gj, bis_kw]).df()
    b = con.execute("""
        SELECT artikel_id, SUM(CASE WHEN luecke_flag THEN 1 ELSE 0 END) AS luecke_wochen
        FROM fact_bestand WHERE gj=? AND kw<=? GROUP BY artikel_id
    """, [gj, bis_kw]).df()
    df = cur.merge(prev, on="artikel_id", how="left").merge(b, on="artikel_id", how="left")
    df["yoy"] = df.apply(lambda r: dr.yoy(r.get("umsatz"), r.get("umsatz_vj")), axis=1)
    mask = (df["yoy"] < -YOY_THRESHOLD) & (df["luecke_wochen"].fillna(0) > 0)
    return df[mask].sort_values("luecke_wochen", ascending=False)


# --- Historie: Wochenreihe, "vs. erwartet", Anomalie ---------------------------

def weekly_series(con, gj: int, abteilung: str | None = None,
                  warengruppe: str | None = None, metric: str = "umsatz") -> pd.DataFrame:
    where, params = "gj = ?", [gj]
    if abteilung:
        where += " AND abteilung = ?"; params.append(abteilung)
    if warengruppe:
        where += " AND warengruppe = ?"; params.append(warengruppe)
    return con.execute(
        f"SELECT kw, SUM({metric}) AS wert FROM fact_umsatz_woche "
        f"WHERE {where} GROUP BY kw ORDER BY kw", params).df()


def anomaly_table(con, gj: int, bis_kw: int, abteilung: str | None = None) -> pd.DataFrame:
    """'Diese KW vs. erwartet' je Warengruppe – gleitender Ø der letzten KW.

    Liefert nur Zeilen, sobald genug Historie vorliegt (ANOMALY_MIN_WEEKS).
    """
    where, params = "gj = ?", [gj]
    if abteilung:
        where += " AND abteilung = ?"; params.append(abteilung)
    s = con.execute(
        f"SELECT warengruppe, kw, SUM(umsatz) AS umsatz FROM fact_umsatz_woche "
        f"WHERE {where} GROUP BY warengruppe, kw ORDER BY warengruppe, kw", params).df()
    if s.empty:
        return pd.DataFrame()
    out = []
    for wg, grp in s.groupby("warengruppe"):
        grp = grp.sort_values("kw")
        cur = grp[grp["kw"] == bis_kw]
        if cur.empty:
            continue
        hist = grp[grp["kw"] < bis_kw].tail(ANOMALY_BASELINE_WEEKS)
        if len(hist) < ANOMALY_MIN_WEEKS:
            continue
        mu, sd = hist["umsatz"].mean(), hist["umsatz"].std(ddof=0)
        val = float(cur["umsatz"].iloc[0])
        z = (val - mu) / sd if sd and sd > 0 else 0.0
        out.append({
            "warengruppe": wg, "kw": bis_kw, "umsatz": val, "erwartet": mu,
            "abweichung": val - mu, "z": z,
            "anomalie": abs(z) >= ANOMALY_SIGMA,
        })
    res = pd.DataFrame(out)
    return res.sort_values("z") if not res.empty else res


# --- Pareto: was treibt die Veränderung (80/20) --------------------------------

def pareto_mover(df: pd.DataFrame, value_col: str = "delta_umsatz",
                 top: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Top-Treiber nach |Δ|. Liefert (gewinner, verlierer)."""
    if value_col not in df.columns:
        return pd.DataFrame(), pd.DataFrame()
    d = df.dropna(subset=[value_col])
    pos = d[d[value_col] > 0].sort_values(value_col, ascending=False).head(top)
    neg = d[d[value_col] < 0].sort_values(value_col).head(top)
    return pos, neg
