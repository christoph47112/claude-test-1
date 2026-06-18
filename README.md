# Betriebsauswertungs-Tool – EDEKA-Markt

Wiederverwendbares, tiefes Betriebsauswertungs-Tool für **einen** Markt. Baut aus
wöchentlichen Datenexporten eine **Historie** auf und lässt von
**Markt → Abteilung → Warengruppe → Artikel** durchklicken – inkl.
Verfügbarkeits-/Bestands-Overlay und regelbasierten Empfehlungen.

Architektur: **Python** (Ingestion → DuckDB → Analyse → Empfehlung → Darstellung),
Oberfläche **Streamlit**, zusätzlich **self-contained HTML-Export**, optionaler
(abschaltbarer) **LLM-Layer**.

> **Datenschutz:** Alle Marktdaten werden ausschließlich **lokal** verarbeitet.
> Nichts wird an externe Dienste gesendet – Ausnahme: der **optionale**,
> standardmäßig **abgeschaltete** LLM-Layer, der nur **aggregierte, anonyme
> Kennzahlen** (keine Rohdaten) versendet, und nur wenn ein API-Key gesetzt ist.

---

## Status der Datenquellen

| Quelle | Status | Was passiert |
|---|---|---|
| **1. Umsatz-Export** (SAP BO, Blatt `Kreuztabelle`) | **Schema bekannt, fertig** | Wird voll eingelesen, GJ-/KW-Logik aktiv |
| **2. Artikel-Umsatz** | Loader + Contract bereit (Schema kommt noch) | Mapping in `mapping.yaml` bestätigen, dann einlesen |
| **3. Bestand/Verfügbarkeit** | Loader + Contract bereit (Schema kommt noch) | Mapping in `mapping.yaml` bestätigen, dann einlesen |

Solange eine Quelle fehlt, zeigt die Oberfläche einen **klaren Leerzustand**
(„Datei laden"), keine erfundenen Zahlen.

---

## Installation

```bash
pip install -r requirements.txt
```

## Bedienung

**1) Umsatz-Export einlesen** (Schema bekannt):

```bash
python ingest.py <UMSATZ.xlsx>            # alle vollständigen Wochen
python ingest.py <UMSATZ.xlsx> --bis-kw 24  # nur bis KW 24 (laufende Woche ausschließen)
```

Gibt eine **Plausibilitätsausgabe** aus (Umsatz je Geschäftsjahr, KW 1…bis-kw) und
erkennt den Marktnamen automatisch (rechteste Wertespalte).

**2) Oberfläche starten:**

```bash
streamlit run app.py
```

**3) Artikel-/Bestandsdatei vorbereiten** (sobald geliefert):

```bash
# Spalten ansehen + Mapping-Vorschläge erhalten (lädt NICHT):
python ingest.py <DATEI.xlsx> --quelle artikel --inspect
python ingest.py <DATEI.xlsx> --quelle bestand --inspect
# Mapping in mapping.yaml bestätigen, dann laden:
python ingest.py <DATEI.xlsx> --quelle artikel
python ingest.py <DATEI.xlsx> --quelle bestand
```

**DB-Status ansehen:**

```bash
python ingest.py --status
```

## Datei-Ablageort

Exporte in `data/incoming/` ablegen. Die DuckDB-Historie liegt unter
`db/betrieb.duckdb` (nicht versioniert). HTML-Reports landen in `exports/`.

---

## Datenregeln (Kurzfassung – Details in CLAUDE.md)

1. **Jahreswechselwoche KW 01:** Zeilen mit `Monat=='DEZ' AND Woche=='01'` gehören
   zum **Folge-Geschäftsjahr** (`GJ = Jahr + 1`). Sonst dreht sich der
   Jahresvergleich im Vorzeichen.
2. **Laufende Woche ausschließen:** Nur vollständige Wochen vergleichen,
   über alle Jahre denselben KW-Bereich (`--bis-kw N`).
3. **Unterdrückte Mengen (`*`):** als „nicht verfügbar" behandeln, **nie als 0**.
4. **Verhältniszahlen neu rechnen, nie summieren:** Spanne = Warenrohgewinn ÷ Umsatz,
   Ø-Preis = Umsatz ÷ Menge, Ø-Bon = Umsatz ÷ Kunden.

---

## Projektstruktur

```
ingest.py        CLI: Dateien -> DuckDB (normalisiert, idempotent)
analysis.py      Kennzahlen/Signale je Ebene (deterministisch)
recommend.py     Regelbasierte Empfehlungen + optionaler LLM-Layer
app.py           Streamlit-Oberfläche (alle Screens + Leerzustände)
export_html.py   Self-contained HTML-Snapshot
mapping.yaml     Spalten-Mapping & Feld-Contract (Quelle 2 & 3)
config.py        Pfade & Schwellwerte
core/            db.py · datarules.py · loaders.py · formatting.py · theme.py
db/              DuckDB-Datei (lokal, nicht versioniert)
data/incoming/   Ablage der Export-Dateien
```

## Optionaler LLM-Layer

Standardmäßig aus. Aktivierung:

```bash
export ANTHROPIC_API_KEY=sk-...
# optional: export EDEKA_LLM_MODEL=claude-sonnet-4-6
```

Das LLM **rechnet nicht selbst** – es bekommt die vorberechneten Kennzahlen/Signale
und formuliert ein priorisiertes Klartext-Summary.

---

## Idempotenz / wachsende Historie

Jeder Wochenexport wird **idempotent** eingelesen: betroffene Schlüssel
(`Markt, Abteilung, Warengruppe, GJ, KW`) werden zuerst entfernt und neu
eingefügt. Erneutes Einlesen desselben Zeitraums verdoppelt nichts; neue Wochen
erweitern die Historie – ohne Codeänderung.
