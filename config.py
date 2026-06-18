"""Zentrale Konfiguration & Pfade für das Betriebsauswertungs-Tool.

Alle Pfade sind relativ zum Projektverzeichnis. Es werden ausschließlich
lokale Dateien verwendet – nichts wird an externe Dienste gesendet
(Ausnahme: optionaler, standardmäßig abgeschalteter LLM-Layer, der nur
aggregierte Kennzahlen versendet, siehe recommend.py).
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# DuckDB-Datei – die wachsende Historie. Bewusst außerhalb der Versionskontrolle.
DB_DIR = PROJECT_ROOT / "db"
DB_PATH = Path(os.environ.get("EDEKA_DB_PATH", DB_DIR / "betrieb.duckdb"))

# Ablageort für gelieferte Export-Dateien (Drop-Zone).
DATA_DIR = PROJECT_ROOT / "data"
INCOMING_DIR = DATA_DIR / "incoming"

# Spalten-Mapping für die noch zu bestätigenden Quellen (Artikel, Bestand).
MAPPING_PATH = PROJECT_ROOT / "mapping.yaml"

# Analyse-Schwellwerte (zentral, damit Regeln & UI konsistent sind).
YOY_THRESHOLD = 0.02          # ±2 % Grenze für Wachstum/Rückgang
ANOMALY_SIGMA = 2.0           # Abweichung in Std.-Abw. für Anomalie-Flag
ANOMALY_MIN_WEEKS = 6         # Mindesthistorie, bevor "vs. erwartet" berechnet wird
ANOMALY_BASELINE_WEEKS = 12   # gleitender Mittelwert über bis zu N letzte KW

# Optionaler LLM-Layer
ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"
LLM_MODEL = os.environ.get("EDEKA_LLM_MODEL", "claude-sonnet-4-6")

for _d in (DB_DIR, DATA_DIR, INCOMING_DIR):
    _d.mkdir(parents=True, exist_ok=True)
