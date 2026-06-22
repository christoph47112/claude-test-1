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
4. **Zukunfts-Aktion ist NICHT in der App.** Bewusste Entscheidung: Die App
   kennt die kommende Aktion nicht und warnt nicht. Folge: Für einen Watchlist-
   Artikel, der nächste Woche zufällig in Aktion ist, zeigt die App die
   **Normal-Wetter-Erwartung**; den Aktions-Schub rechnet der Nutzer aus
   Erfahrung selbst drauf (passt zu „kein Bestell-Ersatz").
5. **Historische Aktion nur im Maschinenraum.** Sie erscheint in **keinem
   Screen**, dient ausschließlich dazu, alte Aktionswochen aus der Lernbasis
   auszuschließen. Variante A: gelieferte historische Aktionsliste (sauber).
   Variante B: keine Datei → Aktionswochen werden als statistische Ausreißer
   erkannt und ausgeschlossen (gröber). → offener Punkt.
6. **Watchlist wird vom Tool VORGESCHLAGEN, nicht vom Nutzer definiert.** Für
   jeden Artikel wird die Wetter-Sensitivität (Korrelation Tagesabsatz ×
   Temperatur, nur Nicht-Aktions-Tage) berechnet, nach Stärke sortiert und als
   fertige Liste zur **einmaligen Freigabe per Haken** vorgelegt. Kein Vorwissen
   nötig.
7. **2-Tage-Vorlauf.** Passt zum Bestellrhythmus (Mo→Mi, Di→Do, Mi→Fr, Sa→Di);
   2-Tage-Wettervorhersagen sind verlässlich.
8. **Datenschutz.** Wetterdaten (Historie + Vorhersage) werden extern zur
   Markt-PLZ geholt; **Verkaufsdaten verlassen den Rechner nicht.**

## Daten-Contract (neue Quellen – Details in `mapping.yaml`)

| Quelle | Pflichtfelder | Körnung | Zweck |
|---|---|---|---|
| **4 Tagesabsatz** | `artikel_id`, `datum`, `menge` | täglich, mehrjährig | Wetter-Hebel lernen |
| **5 Aktionskalender** | `datum`/KW, `aktion_flag` | täglich/wöchentlich, **Vergangenheit + Zukunft** | Aktionswochen ausschließen (Vergangenheit) + kommende Aktion flaggen (Zukunft) |
| **6 Prognose-Konfig** | `markt_plz`, Watchlist | einmalig | Wetterbezug + faktor-sensible Artikel |
| Wetter | — | täglich | extern geholt, lokal verarbeitet |

## Offene Punkte (vor Baubeginn Phase C zu klären)

- [x] **Zukunfts-Aktion:** bewusst **nicht** in der App. Nutzer überrechnet selbst.
- [x] **Watchlist-Mechanik:** Tool schlägt vor (Korrelation) + einmalige Freigabe.
      Nutzer muss nichts vordefinieren.
- [ ] **Historische Aktion – Reinigung der Lernbasis:** Variante A (gelieferte
      historische Aktionsliste, sauber) **oder** Variante B (ohne Datei,
      Ausreißer-Erkennung, gröber)? → entscheiden.
- [ ] **Tiefe der Tageshistorie** (1 / 2 / 3+ Jahre) – je mehr, desto stabiler
      die Wetter-Sensitivität.
- [ ] **Markt-PLZ** eintragen (`mapping.yaml` → `prognose.markt_plz`).

## Phasen-Übersicht

| Phase | Inhalt | Status |
|---|---|---|
| **A** | Gerüst + Umsatz-Auswertung (Markt→Abteilung→WG, Empfehlungen, HTML-Export) | ✅ fertig |
| **B** | Artikel-Umsatz (Quelle 2) + Bestand/Verfügbarkeit (Quelle 3) → Artikel-Drilldown + Verfügbarkeits-Overlay | ⏳ wartet auf Dateien |
| **C** | Tagesabsatz (4) + Aktion (5) + Wetter → Watchlist-Vorschau für Normal-Wochen | 🧭 spezifiziert, wartet auf Daten & Freigabe offener Punkte |
