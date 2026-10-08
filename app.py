from flask import Flask, Response
import requests
import xml.etree.ElementTree as ET
import os

app = Flask(__name__)

SOURCE_URL = "https://www.elementa.rs/index/eponuda-xml"

def get_text(node, tag):
    child = node.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()

def get_image(product):
    image = product.find("product_image_url")
    if image is not None and image.text:
        return image.text.strip()

    images = product.find("product_image_urls")
    if images is not None:
        image = images.find("product_image_url")
        if image is not None and image.text:
            return image.text.strip()

    return ""

def add(parent, tag, value):
    element = ET.SubElement(parent, tag)
    element.text = value or ""

@app.get("/")
def home():
    return Response(
        "Elementa Klaviyo feed is available at /klaviyo.xml",
        mimetype="text/plain",
    )

@app.get("/klaviyo.xml")
def klaviyo_xml():
    response = requests.get(
        SOURCE_URL,
        timeout=30,
        headers={"User-Agent": "Elementa-Klaviyo-Feed/1.0"},
    )
    response.raise_for_status()

    source_root = ET.fromstring(response.content)
    output_root = ET.Element("items")

    for product in source_root.findall(".//product"):
        product_mpn = get_text(product, "product_mpn")
        if not product_mpn:
            continue

        item = ET.SubElement(output_root, "item")
        add(item, "id", product_mpn)
        add(item, "title", get_text(product, "product_name"))
        add(item, "description", get_text(product, "product_description"))
        add(item, "link", get_text(product, "product_url"))
        add(item, "image_link", get_image(product))
        add(item, "price", get_text(product, "product_price"))
        add(item, "inventory_quantity", get_text(product, "product_stock"))
        add(item, "categories", get_text(product, "product_category"))

    xml_bytes = ET.tostring(
        output_root,
        encoding="utf-8",
        xml_declaration=True,
    )

    result = Response(xml_bytes, mimetype="application/xml")
    result.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return result


# Elementa -> partner platform feed. This endpoint reads the source anew
# on every request, independent of the Klaviyo endpoint above.
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
    "Barcode",
)
IMPORTER = "Elementa d.o.o., Subotica"

def description_with_characteristics(art):
    description = (art.get("Opis") or "").strip()
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
        # Preserve real line breaks in XML and HTML breaks for platform display.
        return (description + "<br/>\n" if description else "") + "<br/>\n".join(lines)
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
    for art in source_root.iter("Art"):
        if art.get("Uvoznik", "").strip() != IMPORTER:
            continue
        if art.get("VidljivZa", "").strip() not in ("MP", "VPMP"):
            continue
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
            if art_id in action_dates:
                ET.SubElement(item, "MPAkcijaOd").text = action_dates[art_id]
            ET.SubElement(item, "MPAkcijaNovacena").text = (art.get("MPCena") or "").strip()
        ET.SubElement(item, "Brand").text = brand_from_characteristics(art)
        ET.SubElement(item, "slika").text = (
            f"https://www.elementa.rs/images/products/{art_id}/original/1.jpg"
        )
    return ET.tostring(out, encoding="utf-8", xml_declaration=True)

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

def validate_source():
    response = requests.get(
        SOURCE_URL,
        timeout=30,
        headers={"User-Agent": "Elementa-Klaviyo-Feed/1.0"},
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)
    count = len(root.findall(".//product"))
    print(f"Elementa source check OK - products found: {count}", flush=True)

validate_source()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
