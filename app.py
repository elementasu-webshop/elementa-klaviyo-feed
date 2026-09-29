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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
