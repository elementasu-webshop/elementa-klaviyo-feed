# Elementa → Klaviyo XML feed

Izvor:
https://www.elementa.rs/index/eponuda-xml

Javni endpoint:
`/klaviyo.xml`

Mapping:
- `product_mpn` → `$id`
- `product_name` → `$title`
- `product_description` → `$description`
- `product_url` → `$link`
- `product_image_url` → `$image_link`
- `product_price` → `$price`
- `product_stock` → `$inventory_quantity`
- `product_category` → `$categories`
