"""CLI: Export-Dateien -> DuckDB (normalisiert, idempotent).

Aufrufe
-------
  python ingest.py <UMSATZ.xlsx> [--bis-kw N]
        Umsatz-Export einlesen (Schema bekannt). Gibt Plausibilität aus
        (Umsatz je GJ bis KW N).

  python ingest.py <DATEI.xlsx> --quelle artikel|bestand [--inspect]
        Noch zu bestätigende Quellen. --inspect zeigt die echten Spalten und
        heuristische Mapping-Vorschläge, OHNE zu laden. Mapping in mapping.yaml
        pflegen, dann ohne --inspect erneut aufrufen.

  python ingest.py --status
        Zeigt, was bereits in der DB liegt (ingest_log).

Die Quelle wird bei .xlsx automatisch erkannt (Blatt 'Kreuztabelle' = Umsatz),
sonst über --quelle steuern.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from core import db
from core import loaders
from core.formatting import euro


def _detect_source(path: Path) -> str:
    try:
        xls = pd.ExcelFile(path)
        if loaders.UMSATZ_SHEET in xls.sheet_names:
            return "umsatz"
    except Exception:
        pass
    return "unknown"


def ingest_umsatz(path: Path, bis_kw: int | None) -> None:
    print(f"› Lese Umsatz-Export: {path.name}")
    res = loaders.load_umsatz(path, bis_kw=bis_kw)
    print(f"  Markt erkannt (rechteste Wertespalte): '{res.markt}'")
    print(f"  Eingelesene Wochen-Zeilen normalisiert auf "
          f"{len(res.frame):,} (Abteilung×WG×GJ×KW)".replace(",", "."))
    if bis_kw is None:
        print(f"  Letzte abgeschlossene KW (automatisch): {res.kw_reason}")
    print(f"  Vergleichszeitraum: bis einschließlich KW {res.kw_max} "
          f"(über alle GJ identisch)")
    print("\n  Plausibilität – Umsatz je Geschäftsjahr (GJ, KW 1..%d):" % res.kw_max)
    for gj, row in res.plausi.iterrows():
        print(f"    GJ {gj}:  {euro(row['umsatz_summe'], 2)}")

    con = db.connect()
    db.upsert_umsatz(con, res.frame)
    db.log_ingest(con, "umsatz", path, res.markt, res.gj_range[0],
                  res.gj_range[1], res.kw_max, len(res.frame), res.kw_max)
    con.close()
    print("\n✓ In DuckDB gespeichert (idempotent). Start der Oberfläche: "
          "streamlit run app.py")


def ingest_mapped(path: Path, quelle: str, inspect: bool, markt: str) -> None:
    if inspect:
        rep = loaders.build_mapping_report(quelle, path)
        print(f"› Spalten-Inspektion '{quelle}': {path.name}\n")
        print("  Gefundene Spalten:")
        for c in rep.found_columns:
            print(f"    - {c}")
        print("\n  Bereits gemappt (mapping.yaml):")
        for k, v in (rep.mapped or {}).items():
            print(f"    {k:14s} <- {v}")
        print("\n  Vorschläge (bitte in mapping.yaml bestätigen):")
        for k, v in (rep.suggestions or {}).items():
            print(f"    {k:14s} ?  {v}")
        if rep.missing_required:
            print("\n  ⚠ Pflichtfelder ohne Zuordnung:", ", ".join(rep.missing_required))
            print("    -> in mapping.yaml unter columns: ergänzen, dann erneut laden.")
        else:
            print("\n  ✓ Alle Pflichtfelder zuordenbar – ohne --inspect laden.")
        return

    loader = loaders.load_artikel if quelle == "artikel" else loaders.load_bestand
    frame, rep = loader(path, markt=markt)
    if not rep.ready:
        print(f"✗ Lädt nicht: Pflichtfelder fehlen: {', '.join(rep.missing_required)}")
        print("  Bitte mapping.yaml ergänzen (oder zuerst --inspect ausführen).")
        sys.exit(2)
    con = db.connect()
    if quelle == "artikel":
        db.upsert_artikel(con, frame)
    else:
        db.upsert_bestand(con, frame)
    gj_min = int(frame["gj"].min()); gj_max = int(frame["gj"].max())
    kw_max = int(frame["kw"].max())
    db.log_ingest(con, quelle, path, markt, gj_min, gj_max, kw_max, len(frame), kw_max)
    con.close()
    print(f"✓ {quelle}: {len(frame):,} Zeilen gespeichert (idempotent).".replace(",", "."))


def show_status() -> None:
    con = db.connect()
    counts = db.table_counts(con)
    print("DB-Status:")
    for t, n in counts.items():
        print(f"  {t:22s} {n:>12,} Zeilen".replace(",", "."))
    log = con.execute("SELECT quelle, datei, geladen_am, markt, gj_min, gj_max, "
                      "kw_max, n_zeilen FROM ingest_log ORDER BY geladen_am DESC "
                      "LIMIT 15").df()
    con.close()
    if len(log):
        print("\nLetzte Importe:")
        print(log.to_string(index=False))
    else:
        print("\nNoch nichts geladen.")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Betriebsauswertung – Ingestion")
    ap.add_argument("datei", nargs="?", help="Pfad zur Export-Datei (.xlsx)")
    ap.add_argument("--quelle", choices=["umsatz", "artikel", "bestand"],
                    help="Quelle erzwingen (sonst Auto-Erkennung).")
    ap.add_argument("--bis-kw", type=int, default=None,
                    help="Nur KW <= N (laufende Woche ausschließen).")
    ap.add_argument("--inspect", action="store_true",
                    help="Nur Spalten + Mapping-Vorschläge anzeigen (artikel/bestand).")
    ap.add_argument("--markt", default=None,
                    help="Marktname für artikel/bestand (sonst aus DB übernommen).")
    ap.add_argument("--status", action="store_true", help="DB-Status anzeigen.")
    args = ap.parse_args(argv)

    if args.status:
        show_status(); return
    if not args.datei:
        ap.error("Bitte eine Datei angeben (oder --status).")
    path = Path(args.datei)
    if not path.exists():
        ap.error(f"Datei nicht gefunden: {path}")

    quelle = args.quelle or _detect_source(path)
    if quelle == "umsatz":
        ingest_umsatz(path, args.bis_kw)
    elif quelle in ("artikel", "bestand"):
        markt = args.markt
        if not markt:
            con = db.connect()
            r = con.execute("SELECT markt FROM fact_umsatz_woche LIMIT 1").fetchone()
            con.close()
            markt = r[0] if r else "Unbekannt"
        ingest_mapped(path, quelle, args.inspect, markt)
    else:
        ap.error("Quelle nicht erkannt. Bitte --quelle artikel|bestand angeben.")


if __name__ == "__main__":
    main()
