"""Klaviyo XML feed from Elementa ePonuda; validates required product data."""

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse
import logging
import re
import xml.etree.ElementTree as ET

from flask import Flask, Response
import requests

app = Flask(__name__)
SOURCE_URL = "https://www.elementa.rs/index/eponuda-xml"


def get_text(node, tag):
    child = node.find(tag)
    return (child.text or "").strip() if child is not None else ""


def get_image(product):
    direct = get_text(product, "product_image_url")
    if direct:
        return direct
    images = product.find("product_image_urls")
    return get_text(images, "product_image_url") if images is not None else ""


def is_http_url(value):
    try:
        parsed = urlparse(value)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except ValueError:
        return False


def valid_price(value):
    """Check positive numeric prices, allowing common RSD/currency formatting."""
    normalized = re.sub(r"\s*(RSD|DIN|EUR|€|дин\.?)\s*", "", value, flags=re.I)
    normalized = normalized.replace("\xa0", "").replace(" ", "")
    if not re.fullmatch(r"[0-9.,]+", normalized):
        return False
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(".", "").replace(",", ".") if normalized.rfind(",") > normalized.rfind(".") else normalized.replace(",", "")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")
    try:
        return Decimal(normalized) > 0
    except InvalidOperation:
        return False


def valid_stock(value):
    try:
        stock = Decimal(value.strip())
        return stock.is_finite() and stock >= 0 and stock == stock.to_integral_value()
    except (InvalidOperation, ValueError):
        return False


def read_product(product):
    return {
        "id": get_text(product, "product_mpn"),
        "title": get_text(product, "product_name"),
        "description": get_text(product, "product_description"),
        "link": get_text(product, "product_url"),
        "image_link": get_image(product),
        "price": get_text(product, "product_price"),
        "inventory_quantity": get_text(product, "product_stock"),
        "categories": get_text(product, "product_category"),
    }


def invalid_reason(item):
    for key, value in item.items():
        if not value:
            return "missing_" + key
    if not is_http_url(item["link"]):
        return "invalid_link"
    if not is_http_url(item["image_link"]):
        return "invalid_image_link"
    if not valid_price(item["price"]):
        return "invalid_price"
    if not valid_stock(item["inventory_quantity"]):
        return "invalid_stock"
    return None


def add(parent, tag, value):
    ET.SubElement(parent, tag).text = value


@app.get("/")
def home():
    return Response("Elementa Klaviyo feed is available at /klaviyo.xml", mimetype="text/plain")


@app.get("/klaviyo.xml")
def klaviyo_xml():
    # Fetch the source for each request; do not reuse a previous snapshot.
    try:
        response = requests.get(
            SOURCE_URL,
            timeout=30,
            headers={"User-Agent": "Elementa-Klaviyo-Feed/1.0", "Cache-Control": "no-cache"},
        )
        response.raise_for_status()
        source_root = ET.fromstring(response.content)
    except (requests.RequestException, ET.ParseError) as exc:
        app.logger.error("Klaviyo source unavailable or invalid XML: %s", exc)
        return Response("Source XML unavailable", status=502, mimetype="text/plain")

    output_root = ET.Element("items")
    skipped = Counter()
    seen = set()
    total = 0
    published = 0
    for product in source_root.findall(".//product"):
        total += 1
        item = read_product(product)
        reason = invalid_reason(item)
        if reason:
            skipped[reason] += 1
            continue
        if item["id"] in seen:
            skipped["duplicate_id"] += 1
            continue
        seen.add(item["id"])
        output_item = ET.SubElement(output_root, "item")
        for tag, value in item.items():
            add(output_item, tag, value)
        published += 1

    if published == 0:
        app.logger.error("Klaviyo feed contains no valid products; source_count=%d skipped=%s", total, dict(skipped))
        return Response("No valid products in source XML", status=502, mimetype="text/plain")

    app.logger.info("Klaviyo feed generated: source=%d published=%d skipped=%s", total, published, dict(skipped))
    xml_bytes = ET.tostring(output_root, encoding="utf-8", xml_declaration=True)
    result = Response(xml_bytes, mimetype="application/xml")
    result.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    result.headers["X-Product-Count"] = str(published)
    result.headers["X-Skipped-Count"] = str(total - published)
    result.headers["X-Source-Fetched-At"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return result
