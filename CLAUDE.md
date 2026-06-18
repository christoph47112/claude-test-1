# CLAUDE.md – Fallen & Logik (bitte vor Änderungen lesen)

Dieses Tool wertet Betriebsdaten EINES EDEKA-Markts aus. Die folgenden Regeln
sind die häufigsten Fehlerquellen. Sie sind zentral in `core/datarules.py`
implementiert – dort ändern, nicht verstreut in der UI.

## 1. Geschäftsjahr (GJ) & Jahreswechselwoche KW 01  ⚠ kritisch

Die Kalenderwoche über den Jahreswechsel wird im Umsatz-Export **nach
Kalendermonat gesplittet** abgelegt:

- **Dezember-Teil:** `Monat == 'DEZ'` **und** `Woche == '01'`
  → gehört zum **Folge-Geschäftsjahr** → `GJ = Jahr + 1`.
- **Januar-Teil:** `Monat == 'JAN'` und `Woche == '01'` → bleibt im selben Jahr → `GJ = Jahr`.
- Alle übrigen Zeilen: `GJ = Jahr`.

GJ 2025 KW 01 = (Dez-Teil aus Kalenderjahr 2024) **+** (Jan-Teil aus 2025).
Ohne diese Regel dreht sich der Jahresvergleich im Vorzeichen (Größenordnung
~144 T€). Implementiert in `datarules.compute_gj()`.

Hinweis: `Woche` ist im Export ein **nullgepolsterter String** (`'01'..'52'`),
`Jahr`/`Monat` ebenfalls Strings (`'2024'`, `'JAN'`). Beim Vergleich auf Int
casten (`'01' -> 1`), sonst greift die DEZ/KW01-Regel nicht.

## 2. Laufende Woche ausschließen

Nur **vollständige** Wochen vergleichen, über alle Jahre denselben KW-Bereich.
`--bis-kw N` setzt die Obergrenze; ohne Angabe wird die höchste vorhandene KW
des jüngsten GJ genommen. Die Analyse filtert konsequent `kw <= bis_kw`.

## 3. Unterdrückte Mengen (`*`)

`Menge`, `Abschr. Menge`, `Vollabschr. Menge` enthalten teils `*`
(schwellwertbedingt unterdrückt). `*` = **nicht verfügbar** → wird zu `NULL`,
**niemals als 0** summiert. `datarules.parse_number()` setzt `*`/Leerwerte auf
`None`. In der Aggregation (`analysis._agg_block`) wird eine Menge nur dann zu
einem Zahlenwert, wenn **mindestens eine echte** Beobachtung vorlag – sonst `NULL`.
Preis-/Mengenzerlegung nur, wo echte Mengen in **beiden** Jahren vorliegen.

## 4. Verhältniszahlen NEU rechnen – nie summieren

Gespeichert werden nur **additive Basis-Kennzahlen** (Umsatz, Menge, Kunden,
Warenrohgewinn, Wareneinsatz, Umsatz Bio, Abschr./Vollabschr. Menge).
Quotienten werden bei jeder Aggregation neu abgeleitet:

- **Spanne** = Warenrohgewinn ÷ Umsatz  (`datarules.span`)
- **Ø-Preis** = Umsatz ÷ Menge          (`datarules.avg_price`, nur bei echter Menge)
- **Ø-Bon (D-Bon)** = Umsatz ÷ Kunden    (`datarules.avg_bon`)

Die im Export vorhandenen Spalten `D-Bon` und `Nettoertragssp.` werden **nicht**
eingelesen (würden bei Aggregation falsch summiert).

## 5. Marktspalte automatisch erkennen

Header: `Abteilung | Hauptwarengrp. | <Kennzahl> | Jahr | Monat | Woche | Gesamtergebnis | <Marktname>`.
Die **rechteste** Wertespalte ist der **Marktwert** (z. B. „Kaiser Matthias"),
nicht `Gesamtergebnis` (= regionale Summe, weicht real ab!). Auto-Erkennung in
`loaders.detect_market_column()` – Namen nicht hartkodieren.

Zeilenlogik: `Hauptwarengrp.=='Ergebnis'` = Abteilungssumme, `Abteilung=='Gesamtergebnis'`
= Marktsumme. Diese vor-aggregierten Zeilen werden bei der Ingestion **übersprungen**;
Abteilungs-/Markt-Summen rechnen wir selbst aus den Wochenzeilen (damit GJ-/KW-Regeln
korrekt greifen).

## 6. Join-Schlüssel Artikel ↔ Bestand

`artikel_id` (Artikelnummer/GTIN) ist der gemeinsame Schlüssel zwischen
Artikel-Umsatz (Quelle 2) und Bestand (Quelle 3). Vor dem Join bestätigen, dass
der Schlüssel in **beiden** Dateien identisch formatiert ist (GTIN vs. interne
Nr.). Bei Abweichung einen Mapping-/Cross-Reference-Schritt einplanen.

## 7. Idempotenz

`core/db._upsert()` löscht betroffene natürliche Schlüssel und fügt neu ein.
Erneutes Einlesen desselben Zeitraums verdoppelt nicht. Schlüssel:
`fact_umsatz_woche (markt, abteilung, warengruppe, gj, kw)`,
`fact_artikel_woche (markt, artikel_id, gj, kw)`,
`fact_bestand (markt, artikel_id, gj, kw)`.

## 8. Keine erfundenen Daten

Fehlt eine Quelle, zeigt die UI einen Leerzustand. Loader für noch nicht
gelieferte Quellen laden **nur**, wenn alle Pflichtfelder via `mapping.yaml`
zugeordnet sind (`MappingReport.ready`). Sonst Abbruch mit Hinweis.

## 9. Optionaler LLM-Layer

`recommend.llm_summary()` ist standardmäßig aus (nur aktiv mit
`ANTHROPIC_API_KEY`). Es werden ausschließlich **aggregierte, anonyme**
Kennzahlen gesendet, nie Rohdaten. Das LLM interpretiert nur – es rechnet nicht.

---

### Validierung (Stand der gelieferten Umsatz-Datei)

Plausibilität bis KW 24 (Umsatz je GJ): 2024 ≈ 5,29 Mio €, 2025 ≈ 5,36 Mio €,
2026 ≈ 5,52 Mio €. `Gesamtergebnis` ≠ Marktwert in einem Teil der Zeilen →
Marktspalte (rechts) ist maßgeblich.
