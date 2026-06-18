"""DuckDB-Persistenz: Schema, Verbindung, idempotenter Upsert, ingest_log.

Tabellen
--------
fact_umsatz_woche : Wochenwerte je (Markt, Abteilung, Warengruppe, GJ, KW)
                    – additive Basis-Kennzahlen. Quotienten werden in der
                    Analyse neu gerechnet, nicht gespeichert.
fact_artikel_woche: Wochenwerte je Artikel (Quelle 2 – kommt noch).
fact_bestand      : Bestand/Verfügbarkeit je Artikel & Zeitpunkt (Quelle 3 – kommt noch).
dim_abteilung / dim_warengruppe / dim_artikel : Dimensionen.
ingest_log        : welche Datei wann mit welchem KW-Stand eingelesen wurde.

Idempotenz
----------
fact_umsatz_woche hat einen natürlichen Schlüssel
(markt, abteilung, warengruppe, gj, kw). Beim erneuten Einlesen desselben
Zeitraums werden betroffene Schlüssel zuerst gelöscht und dann neu
eingefügt -> Historie wächst, ohne zu verdoppeln.
"""
from __future__ import annotations

from pathlib import Path
import datetime as dt
import duckdb
import pandas as pd

from config import DB_PATH


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS dim_abteilung (
    abteilung VARCHAR PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS dim_warengruppe (
    warengruppe VARCHAR,
    abteilung   VARCHAR,
    PRIMARY KEY (warengruppe, abteilung)
);

CREATE TABLE IF NOT EXISTS dim_artikel (
    artikel_id   VARCHAR PRIMARY KEY,   -- Artikelnummer/GTIN (Join-Schlüssel)
    bezeichnung  VARCHAR,
    warengruppe  VARCHAR,
    abteilung    VARCHAR
);

CREATE TABLE IF NOT EXISTS fact_umsatz_woche (
    markt            VARCHAR,
    abteilung        VARCHAR,
    warengruppe      VARCHAR,
    gj               INTEGER,   -- Geschäftsjahr (KW-01-Regel angewandt)
    kw               INTEGER,   -- Kalenderwoche 1..52/53
    umsatz           DOUBLE,
    menge            DOUBLE,    -- NULL wenn unterdrückt ('*')
    kunden           DOUBLE,
    warenrohgewinn   DOUBLE,
    wareneinsatz     DOUBLE,
    umsatz_bio       DOUBLE,
    abschr_menge     DOUBLE,    -- NULL wenn unterdrückt
    vollabschr_menge DOUBLE,    -- NULL wenn unterdrückt
    PRIMARY KEY (markt, abteilung, warengruppe, gj, kw)
);

CREATE TABLE IF NOT EXISTS fact_artikel_woche (
    markt        VARCHAR,
    artikel_id   VARCHAR,
    bezeichnung  VARCHAR,
    warengruppe  VARCHAR,
    abteilung    VARCHAR,
    gj           INTEGER,
    kw           INTEGER,
    umsatz       DOUBLE,
    menge        DOUBLE,
    kunden       DOUBLE,
    rohertrag    DOUBLE,
    PRIMARY KEY (markt, artikel_id, gj, kw)
);

CREATE TABLE IF NOT EXISTS fact_bestand (
    markt        VARCHAR,
    artikel_id   VARCHAR,
    bezeichnung  VARCHAR,
    warengruppe  VARCHAR,
    abteilung    VARCHAR,
    gj           INTEGER,
    kw           INTEGER,
    bestand      DOUBLE,
    luecke_flag  BOOLEAN,   -- Regallücke / Nullbestand
    lost_sale    DOUBLE,    -- optional: geschätzter Lost-Sale / Negativbestand
    PRIMARY KEY (markt, artikel_id, gj, kw)
);

CREATE TABLE IF NOT EXISTS ingest_log (
    id          BIGINT,
    quelle      VARCHAR,   -- 'umsatz' | 'artikel' | 'bestand'
    datei       VARCHAR,
    geladen_am  TIMESTAMP,
    markt       VARCHAR,
    gj_min      INTEGER,
    gj_max      INTEGER,
    kw_max      INTEGER,
    n_zeilen    BIGINT,
    bis_kw      INTEGER
);
"""


def connect(db_path: Path | str = DB_PATH) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(db_path))
    con.execute(SCHEMA_SQL)
    return con


def _upsert(con, table: str, df: pd.DataFrame, key_cols: list[str]) -> None:
    """Idempotentes Einfügen: betroffene Schlüssel löschen, dann anhängen."""
    if df.empty:
        return
    con.register("_staging", df)
    # vorhandene Schlüssel-Kombinationen entfernen
    distinct_keys = df[key_cols].drop_duplicates()
    con.register("_keys", distinct_keys)
    on = " AND ".join([f"t.{k} = k.{k}" for k in key_cols])
    con.execute(
        f"DELETE FROM {table} t WHERE EXISTS "
        f"(SELECT 1 FROM _keys k WHERE {on})"
    )
    cols = ", ".join(df.columns)
    con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _staging")
    con.unregister("_staging")
    con.unregister("_keys")


def upsert_umsatz(con, df: pd.DataFrame) -> None:
    _upsert(con, "fact_umsatz_woche", df,
            ["markt", "abteilung", "warengruppe", "gj", "kw"])
    # Dimensionen aktualisieren
    con.execute("""
        INSERT INTO dim_abteilung
        SELECT DISTINCT abteilung FROM fact_umsatz_woche
        WHERE abteilung NOT IN (SELECT abteilung FROM dim_abteilung)
    """)
    con.execute("""
        INSERT INTO dim_warengruppe
        SELECT DISTINCT warengruppe, abteilung FROM fact_umsatz_woche f
        WHERE NOT EXISTS (SELECT 1 FROM dim_warengruppe d
                          WHERE d.warengruppe=f.warengruppe AND d.abteilung=f.abteilung)
    """)


def upsert_artikel(con, df: pd.DataFrame) -> None:
    _upsert(con, "fact_artikel_woche", df,
            ["markt", "artikel_id", "gj", "kw"])
    con.execute("""
        INSERT INTO dim_artikel
        SELECT DISTINCT artikel_id, first(bezeichnung), first(warengruppe), first(abteilung)
        FROM fact_artikel_woche f
        WHERE artikel_id NOT IN (SELECT artikel_id FROM dim_artikel)
        GROUP BY artikel_id
    """)


def upsert_bestand(con, df: pd.DataFrame) -> None:
    _upsert(con, "fact_bestand", df,
            ["markt", "artikel_id", "gj", "kw"])


def log_ingest(con, quelle, datei, markt, gj_min, gj_max, kw_max, n_zeilen, bis_kw):
    next_id = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM ingest_log").fetchone()[0]
    con.execute(
        "INSERT INTO ingest_log VALUES (?,?,?,?,?,?,?,?,?,?)",
        [next_id, quelle, str(datei), dt.datetime.now(), markt,
         gj_min, gj_max, kw_max, n_zeilen, bis_kw],
    )


# --- Status-/Verfügbarkeitsabfragen für die UI ---------------------------------

def table_counts(con) -> dict[str, int]:
    out = {}
    for t in ["fact_umsatz_woche", "fact_artikel_woche", "fact_bestand"]:
        try:
            out[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except duckdb.Error:
            out[t] = 0
    return out


def has_data(con, table: str) -> bool:
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0
    except duckdb.Error:
        return False
