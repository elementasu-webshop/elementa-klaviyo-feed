"""Persist the first date each active promotion is observed.

Runs hourly via GitHub Actions. Dates are Europe/Belgrade local dates.
Only active products with importer Elementa and visibility MP/VPMP are tracked.
"""
import json
import os
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo
import zipfile
import xml.etree.ElementTree as ET
import requests

SOURCE = "https://www.elementa.rs/download/razmena.xml"
STATE = "akcije_datumi.json"
ACTIVE = {"true", "1", "da", "yes"}

def main():
    response = requests.get(SOURCE, timeout=120, headers={"User-Agent":"Elementa-Ananas-Action-Tracker/1.0"})
    response.raise_for_status()
    data = response.content
    if zipfile.is_zipfile(BytesIO(data)):
        with zipfile.ZipFile(BytesIO(data)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".xml")]
            if not names:
                raise ValueError("No XML in source ZIP")
            data = z.read(names[0])
    root = ET.fromstring(data)
    try:
        with open(STATE, encoding="utf-8") as f:
            old = json.load(f)
    except FileNotFoundError:
        old = {}
    today = datetime.now(ZoneInfo("Europe/Belgrade")).date().isoformat()
    current = {}
    for art in root.iter("Art"):
        if art.get("Uvoznik", "").strip() != "Elementa d.o.o., Subotica":
            continue
        if art.get("VidljivZa", "").strip() not in ("MP", "VPMP"):
            continue
        if (art.get("MPAkcija") or "").strip().casefold() not in ACTIVE:
            continue
        key = art.get("ArtikalID", "").strip()
        if key:
            current[key] = old.get(key, today)
    if old != current:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
    print(f"Active promotions: {len(current)}, new today: {sum(v == today and k not in old for k,v in current.items())}")

if __name__ == "__main__":
    main()
