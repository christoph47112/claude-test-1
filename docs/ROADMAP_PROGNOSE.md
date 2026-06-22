# Roadmap & Daten-Contract – Prognose-Ausbau (Phase C)

> Dieses Dokument hält das Ergebnis der `/grilling`-Session fest: **was die App
> können soll, was sie bewusst NICHT tut, und welche Daten dafür nötig sind.**
> Es ist die Entscheidungsgrundlage, bevor Code für Phase C entsteht.

## Kernzweck (geschärft)

Das Tool soll **eine** Frage zuverlässig beantworten und in Handlung übersetzen:

> „Liegt ein Bereich bei uns hinten – und was soll ich tun?"
> ergänzt um: „Worauf muss ich mich nächste Woche bei **wetter-/faktor-abhängigen
> Artikeln** einstellen?"

Es ist **kein** Bestell-Ersatz. Die Vorausschau ist eine **schmale Watchlist**
für die paar Dutzend Artikel, deren Absatz wirklich an äußeren Faktoren hängt
(Wasser, Eis, Grillfleisch, Erdbeeren, Salat, Kohlensäure …). Der normale
Bestellprozess bleibt unberührt.

## Bewusst verworfen / abgegrenzt

| Idee | Entscheidung | Grund |
|---|---|---|
| Vergleich mit **anderen Märkten / Branche** | **verworfen** | Keine Datenquelle – Umsatz-Export enthält nur den eigenen Markt + Regions**summe** (`Gesamtergebnis`), kein Pro-Markt-Benchmark. |
| Messlatte „hinten" | **Eigenes Vorjahr + selbst gesetzte Zielspannen** | Daten vorhanden, ehrlich rechenbar. |
| Wetter-Prognose für **alle** Artikel | **verworfen** | Zu viele Vorschläge, im 2-Tage-Bestelltakt nicht reviewbar. |
| Aktion als **Modellfaktor** | **verworfen** | Stattdessen Aktion = **Ausschluss-Filter** (siehe unten) – einfacher, robuster. |

## Designentscheidungen der Prognose (Phase C)

1. **Tagesgenauigkeit.** Wetterwirkung ist ein Tages-/Wochenend-Phänomen. Der
   wöchentliche Umsatz-Export reicht dafür **nicht** – es braucht **Tagesabsatz
   (Menge)** für die Watchlist-Artikel.
2. **Normal-Wochen-Prognose.** Die Normal-Erwartung wird **ausschließlich aus
   Nicht-Aktions-Wochen** gelernt. Aktionswochen werden **ausgeschlossen**, nicht
   eingemittelt (4-Wochen-Glättung entfernt nur Zufallsrauschen, **nicht** den
   systematischen Aktions-Ausschlag).
3. **Analog-Wetter-Methode.** Statt schwerem Modell auf dünner Historie:
   historische Tage mit **ähnlicher Temperatur/Wetterlage** heranziehen und
   schauen, was lief – verglichen wird nur gegen **Nicht-Aktions-Tage**.
4. **Aktion in der Zukunft = Stopp-Signal.** Steht für einen Watchlist-Artikel
   nächste Woche eine Aktion an, gibt das Tool **keine Wetterzahl**, sondern
   flaggt „Aktion → manuell disponieren".
5. **2-Tage-Vorlauf.** Passt zum Bestellrhythmus (Mo→Mi, Di→Do, Mi→Fr, Sa→Di);
   2-Tage-Wettervorhersagen sind verlässlich.
6. **Datenschutz.** Wetterdaten (Historie + Vorhersage) werden extern zur
   Markt-PLZ geholt; **Verkaufsdaten verlassen den Rechner nicht.**

## Daten-Contract (neue Quellen – Details in `mapping.yaml`)

| Quelle | Pflichtfelder | Körnung | Zweck |
|---|---|---|---|
| **4 Tagesabsatz** | `artikel_id`, `datum`, `menge` | täglich, mehrjährig | Wetter-Hebel lernen |
| **5 Aktionskalender** | `datum`/KW, `aktion_flag` | täglich/wöchentlich, **Vergangenheit + Zukunft** | Aktionswochen ausschließen (Vergangenheit) + kommende Aktion flaggen (Zukunft) |
| **6 Prognose-Konfig** | `markt_plz`, Watchlist | einmalig | Wetterbezug + faktor-sensible Artikel |
| Wetter | — | täglich | extern geholt, lokal verarbeitet |

## Offene Punkte (vor Baubeginn Phase C zu klären)

- [ ] **Aktionsplan der Zukunft maschinenlesbar?** (Liste KW/Tag → Artikel/WG →
      Aktionsart, **nicht** PDF-Prospekt). Vergangenheit ist bestätigt.
- [ ] **Watchlist-Mechanik:** Auto-Flag aus Korrelation **+ einmalige Freigabe**
      (empfohlen, hält die Liste kurz) – bestätigen.
- [ ] **Tiefe der Tageshistorie** (1 / 2 / 3+ Jahre) – je mehr, desto stabiler
      die Wetter-Sensitivität.
- [ ] **Markt-PLZ** eintragen (`mapping.yaml` → `prognose.markt_plz`).

## Phasen-Übersicht

| Phase | Inhalt | Status |
|---|---|---|
| **A** | Gerüst + Umsatz-Auswertung (Markt→Abteilung→WG, Empfehlungen, HTML-Export) | ✅ fertig |
| **B** | Artikel-Umsatz (Quelle 2) + Bestand/Verfügbarkeit (Quelle 3) → Artikel-Drilldown + Verfügbarkeits-Overlay | ⏳ wartet auf Dateien |
| **C** | Tagesabsatz (4) + Aktion (5) + Wetter → Watchlist-Vorschau für Normal-Wochen | 🧭 spezifiziert, wartet auf Daten & Freigabe offener Punkte |
