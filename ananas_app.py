from flask import Flask, Response
import requests
import xml.etree.ElementTree as ET
import os

app = Flask(__name__)

from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation
from io import BytesIO
import zipfile

RAZMENA_URL = "https://www.elementa.rs/download/razmena.xml"
RAZMENA_FIELDS = (
    "ArtikalID", "Sifra", "Naziv", "JM", "MPCena",
    "VPLager", "MPLager", "MSLager", "PDV", "Opis",
    "MPAkcija", "MPAkcijado", "MPAkcijaStaracena",
    "MPAkcijaRabat", "Pakovanje", "VidljivZa", "Garancija",
    "Uvoznik", "Proizvodjac", "ZemljaPorekla", "ZemljaUvoza",
    "Barcode", "Duzina", "Visina", "Sirina", "Masa",
)
IMPORTER = "Elementa d.o.o., Subotica"

def description_with_characteristics(art):
    import re
    description = (art.get("Opis") or "").strip()
    # Source descriptions sometimes have HTML breaks, sometimes literal line breaks.
    description = re.sub(r"<br\s*/?>", "\n", description, flags=re.IGNORECASE)
    description = description.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    characteristics = art.find("Karakteristike")
    if characteristics is not None:
        for characteristic in characteristics.findall("Karakteristika"):
            name = (characteristic.get("NazivKarakteristike") or "").strip()
            value = (characteristic.get("Vrednost") or "").strip()
            if not name or not value or value == "-":
                continue
            lines.append(f"• {name}: {value}")
    if lines:
        return (description + "\n\n" if description else "") + "Tehnički podaci:\n" + "\n".join(lines)
    return description

def brand_from_characteristics(art):
    characteristics = art.find("Karakteristike")
    if characteristics is not None:
        for characteristic in characteristics.findall("Karakteristika"):
            name = (characteristic.get("NazivKarakteristike") or "").strip().casefold()
            value = (characteristic.get("Vrednost") or "").strip()
            if name in ("brend", "brand", "marka", "robna marka") and value and value != "-":
                return value
    return "Elementa"

ACTION_DATES_URL = "https://raw.githubusercontent.com/elementasu-webshop/elementa-klaviyo-feed/main/akcije_datumi.json"

def get_action_dates():
    response = requests.get(ACTION_DATES_URL, timeout=15, headers={"User-Agent": "Elementa-Ananas-Feed/1.0"})
    response.raise_for_status()
    return response.json()

def make_razmena():
    response = requests.get(
        RAZMENA_URL,
        timeout=120,
        headers={"User-Agent": "Elementa-Partner-XML/1.0", "Accept": "application/xml,*/*"},
    )
    response.raise_for_status()
    content = response.content
    if zipfile.is_zipfile(BytesIO(content)):
        with zipfile.ZipFile(BytesIO(content)) as archive:
            xml_files = [name for name in archive.namelist() if name.lower().endswith(".xml")]
            if not xml_files:
                raise ValueError("Source archive has no XML")
            content = archive.read(xml_files[0])
    source_root = ET.fromstring(content)
    action_dates = get_action_dates()
    out = ET.Element("root")
    articles = ET.SubElement(out, "Artikli")
    cdata_values = {}
    source_count = 0
    filtered_count = 0
    for art in source_root.iter("Art"):
        source_count += 1
        if art.get("Uvoznik", "").strip() != IMPORTER:
            continue
        if art.get("VidljivZa", "").strip() not in ("MP", "VPMP"):
            continue
        if "outlet" in (art.get("Naziv") or "").casefold():
            continue
        try:
            price = Decimal((art.get("MPCena") or "").strip().replace(",", "."))
        except InvalidOperation:
            continue
        if not price.is_finite() or price <= Decimal("800"):
            continue
        filtered_count += 1
        art_id = art.get("ArtikalID", "").strip()
        item = ET.SubElement(articles, "Art")
        for field in RAZMENA_FIELDS:
            if field == "VPLager":
                stock = Decimal("0")
                for warehouse in ("VPLager", "MPLager", "MSLager"):
                    value = (art.get(warehouse) or "0").strip().replace(",", ".")
                    try:
                        stock += Decimal(value or "0")
                    except InvalidOperation:
                        raise ValueError(f"Invalid {warehouse} value for ArtikalID={art_id}")
                number = format(stock, "f")
                if "." in number:
                    number = number.rstrip("0").rstrip(".")
                ET.SubElement(item, "Kolicina").text = number
            elif field in ("MPLager", "MSLager"):
                continue
            elif field in art.attrib:
                ET.SubElement(item, field).text = (
                    description_with_characteristics(art) if field == "Opis" else art.attrib[field]
                )
        if (art.get("MPAkcija") or "").strip().casefold() in ("true", "1", "da", "yes"):
            first_seen = action_dates.get(art_id) or datetime.now(ZoneInfo("Europe/Belgrade")).date().isoformat()
            ET.SubElement(item, "MPAkcijaOd").text = datetime.strptime(first_seen, "%Y-%m-%d").strftime("%d/%m/%Y")
            ET.SubElement(item, "MPAkcijaNovacena").text = (art.get("MPCena") or "").strip()
        ET.SubElement(item, "Brand").text = brand_from_characteristics(art)
        ET.SubElement(item, "slika").text = (
            f"https://www.elementa.rs/images/products/{art_id}/original/1.jpg"
        )
    app.logger.info("Ananas source razmena.xml: %d articles; after filters: %d", source_count, filtered_count)
    # Serialize all direct Art child element values as CDATA, including empty values.
    for item in articles.findall("Art"):
        for child in item:
            marker = f"__ANANAS_CDATA_{len(cdata_values)}__"
            cdata_values[marker] = child.text or ""
            child.text = marker
    ET.indent(out, space="  ")  # Human-readable XML source with one tag per line.
    result = ET.tostring(out, encoding="utf-8", xml_declaration=True)
    # Replace all CDATA placeholders in one pass; repeated bytes.replace
    # over the whole feed causes worker timeouts on large catalogs.
    import re
    def insert_cdata(match):
        value = cdata_values[match.group().decode("ascii")]
        safe = value.replace("]]>", "]]]]><![CDATA[>")
        return ("<![CDATA[" + safe + "]]>").encode("utf-8")
    result = re.sub(rb"__ANANAS_CDATA_[0-9]+__", insert_cdata, result)
    return result

@app.get("/razmena.xml")
def razmena_xml():
    try:
        xml_content = make_razmena()
    except Exception:
        app.logger.exception("Failed to generate Elementa partner XML")
        return Response("Source XML temporarily unavailable", status=503, mimetype="text/plain")
    result = Response(xml_content, mimetype="application/xml")
    result.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return result

