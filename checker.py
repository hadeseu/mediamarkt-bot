"""Prüft, ob ein Produkt in einem Online-Shop bestellbar ist.

Unterstützt:
  * MediaMarkt / Saturn (eigene Erkennung, unterscheidet Marktplatz-Händler)
  * Shopify-Shops (viele kleine TCG-Shops) über deren Produkt-JSON
  * jeden anderen Shop, der die Standard-Produktdaten (schema.org) in die Seite schreibt
    – das machen die meisten großen Shops wegen Google.
"""

import ipaddress
import json
import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import aiohttp

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "de-AT,de;q=0.9",
}

SHOP_NAMES = {
    "mediamarkt.at": "MediaMarkt AT", "mediamarkt.de": "MediaMarkt DE",
    "saturn.de": "Saturn DE", "saturn.at": "Saturn AT",
    "thalia.at": "Thalia AT", "thalia.de": "Thalia DE",
    "hartlauer.at": "Hartlauer", "otto.at": "OTTO AT", "otto.de": "OTTO DE",
    "universal.at": "Universal", "conrad.at": "Conrad AT", "cyberport.at": "Cyberport AT",
    "alza.at": "Alza AT", "boozt.com": "Boozt", "e-tec.at": "e-tec", "games-island.eu": "Games Island",
    "gamestop.de": "GameStop DE", "lidl.at": "Lidl AT",
}

# Schema.org-Verfügbarkeit → (Text, bestellbar?)
SCHEMA_STATUS = {
    "InStock": ("Auf Lager", True),
    "OnlineOnly": ("Online bestellbar", True),
    "LimitedAvailability": ("Wenige verfügbar", True),
    "PreOrder": ("Vorbestellbar", True),
    "PreSale": ("Vorbestellbar", True),
    "BackOrder": ("Nachbestellbar (Lieferung später)", True),
    "OutOfStock": ("Ausverkauft", False),
    "SoldOut": ("Ausverkauft", False),
    "Discontinued": ("Nicht mehr erhältlich", False),
    "InStoreOnly": ("Nur im Geschäft", False),
    "MadeToOrder": ("Auf Bestellung", True),
}

MM_STATUS_TEXT = {
    "AVAILABLE": "Online bestellbar",
    "NO_DELIVERY": "Nicht lieferbar (höchstens Wolt-Sofort-Lieferung oder Abholung)",
    "MP_OFFER": "Nur über Marktplatz-Händler",
    "STORE_ONLY": "Nur im Markt erhältlich",
    "NOT_AVAILABLE": "Nicht verfügbar",
    "TEMPORARILY_NOT_AVAILABLE": "Zurzeit nicht verfügbar",
    "PERMANENTLY_NOT_AVAILABLE": "Dauerhaft nicht verfügbar",
    "COMING_SOON": "Bald erhältlich",
    "PRE_ORDER": "Vorbestellbar",
    "NO_VALID_MP_OFFER_PRICE": "Nicht verfügbar",
}

# Typische Bot-Schutz-Seiten (Cloudflare, Incapsula, Akamai, DataDome …)
BOT_WALL = re.compile(
    r"Just a moment\.\.\.|_Incapsula_Resource|cf-challenge|captcha-delivery|"
    r"Access Denied</title>|Attention Required! \| Cloudflare",
    re.I,
)


class BlockedError(Exception):
    """Der Shop hat die Anfrage abgelehnt (Bot-Schutz oder zu viele Anfragen)."""

    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


@dataclass
class Result:
    url: str
    shop: str
    name: str
    price: float | None
    status_text: str
    buyable: bool                # beim Shop selbst bestellbar
    marketplace: bool = False    # nur bei Marktplatz-Händler (MediaMarkt) bestellbar
    seller: str | None = None
    status: str = ""             # Rohstatus


# ---------- Hilfsfunktionen ----------

def host_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def shop_name(url: str) -> str:
    host = host_of(url)
    return SHOP_NAMES.get(host, host)


def normalize_url(url: str) -> str | None:
    """Prüft, ob es ein brauchbarer Shop-Link ist, und entfernt Tracking-Kram."""
    url = url.strip().strip("<>")
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    host = p.hostname.lower()
    # Keine internen Adressen (Router o. Ä.) abfragen lassen
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    if "." not in host or host.endswith((".local", ".lan", ".home", ".internal")) or host == "localhost":
        return None
    query = urlencode([
        (k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
        if not k.lower().startswith(("utm_", "gclid", "fbclid", "ref", "srsltid"))
    ])
    return urlunparse(("https", p.netloc.lower(), p.path, "", query, ""))


def _price(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _og_title(html: str) -> str | None:
    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if not m:
        m = re.search(r"<title[^>]*>([^<]+)", html, re.I)
    return unescape(m.group(1)).strip() if m else None


# ---------- MediaMarkt / Saturn ----------

def parse_mediamarkt(url: str, html: str) -> Result | None:
    m = re.search(r"-(\d+)\.html$", urlparse(url).path)
    if not m:
        return None
    pid = m.group(1)
    own, market = [], []
    pattern = r'"CofrOnlineStatusFeature:(?:Media|Saturn):[a-z]{2}:' + pid + r'(\[\d+\])?":(\{[^{}]*\})'
    for m in re.finditer(pattern, html):
        try:
            data = json.loads(m.group(2))
        except json.JSONDecodeError:
            continue
        (market if m.group(1) else own).append(data)
    if not own and not market:
        return None

    # Was auf der Seite bei "Lieferung" steht. Nur wenn dort normale Lieferung möglich ist,
    # kann man es wirklich bestellen (Wolt-Sofort-Lieferung oder Abholung zählen nicht).
    delivery: dict[str, str | None] = {}
    dpat = (r'"CofrDeliveryFeature:(?:Media|Saturn):[a-z]{2}:' + pid
            + r'(\[\d+\])?":\{[^{}]*"delivery":(?:null|\{[^{}]*?"displayStatus":"([A-Z_]+)")')
    for dm in re.finditer(dpat, html):
        delivery[dm.group(1) or ""] = dm.group(2)
    own_ships = delivery.get("") == "AVAILABLE"
    mp_ships = own_ships or any(v == "AVAILABLE" for k, v in delivery.items() if k)

    buyable_flag = any(d.get("isAvailableAndBuyable") and d.get("onlineStatus") != "MP_OFFER" for d in own)
    mp_flag = any(d.get("isAvailableAndBuyable") for d in market) or any(
        d.get("isAvailableAndBuyable") and d.get("onlineStatus") == "MP_OFFER" for d in own
    )
    buyable = buyable_flag and own_ships
    mp_buyable = mp_flag and mp_ships
    if buyable:
        status = "AVAILABLE"
    elif buyable_flag:
        status = "NO_DELIVERY"
    else:
        status = (own or market)[0].get("onlineStatus") or "UNKNOWN"

    name = _og_title(html) or "Unbekanntes Produkt"
    name = re.sub(r"\s*\|\s*(MediaMarkt|Saturn)\s*$", "", name)

    price = None
    pm = re.search(r'"offers":\{"@type":"Offer","priceCurrency":"EUR","price":([\d.]+)', html)
    if not pm:
        pm = re.search(r'"CofrPriceFeaturePrice","amount":([\d.]+)', html)
    if pm:
        price = float(pm.group(1))
    sm = re.search(r'"sellerName":"([^"]+)"', html)

    return Result(
        url=url, shop=shop_name(url), name=name, price=price,
        status_text=MM_STATUS_TEXT.get(status, status.replace("_", " ").capitalize()),
        buyable=buyable, marketplace=mp_buyable and not buyable,
        seller=sm.group(1) if sm else None, status=status,
    )


# ---------- Shopify ----------

async def check_shopify(session: aiohttp.ClientSession, url: str) -> Result | None:
    p = urlparse(url)
    m = re.search(r"(/products/[^/?#]+)", p.path)
    if not m:
        return None
    js_url = f"https://{p.netloc}{m.group(1)}.js"
    try:
        async with session.get(js_url, headers={**HEADERS, "Accept": "application/json"},
                               timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200 or "json" not in resp.headers.get("Content-Type", ""):
                return None
            data = await resp.json(content_type=None)
    except (aiohttp.ClientError, json.JSONDecodeError, TimeoutError):
        return None
    if not isinstance(data, dict) or "variants" not in data:
        return None

    variants = data.get("variants") or []
    wanted = dict(parse_qsl(p.query)).get("variant")
    if wanted:
        variants = [v for v in variants if str(v.get("id")) == wanted] or variants
    available = any(v.get("available") for v in variants) if variants else bool(data.get("available"))
    prices = [v.get("price") for v in variants if v.get("price") is not None] or [data.get("price")]
    price = min(prices) / 100 if prices and prices[0] is not None else None
    return Result(
        url=url, shop=shop_name(url), name=data.get("title") or "Unbekanntes Produkt",
        price=price, status_text="Auf Lager" if available else "Ausverkauft",
        buyable=available, status="SHOPIFY",
    )


# ---------- Allgemein: schema.org-Daten ----------

def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _is_type(d: dict, name: str) -> bool:
    t = d.get("@type")
    return name in t if isinstance(t, list) else t == name


def parse_jsonld(url: str, html: str) -> Result | None:
    products = []
    for block in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I
    ):
        try:
            data = json.loads(block.strip(), strict=False)
        except json.JSONDecodeError:
            continue
        products += [d for d in _walk(data) if _is_type(d, "Product") or _is_type(d, "ProductGroup")]

    # Seiten listen oft auch "ähnliche Produkte" – das zur URL passende zuerst nehmen
    path = urlparse(url).path.rstrip("/")
    products.sort(key=lambda d: 0 if path and path in str(d.get("url", "")) else 1)

    for prod in products:
        source = prod.get("offers") or prod.get("hasVariant") or []
        offers = [o for o in _walk(source) if "availability" in o or "price" in o]
        avail = [str(o.get("availability", "")).rstrip("/").split("/")[-1] for o in offers]
        avail = [a for a in avail if a]
        if not avail:
            continue
        buyable_states = [a for a in avail if SCHEMA_STATUS.get(a, ("", False))[1]]
        state = buyable_states[0] if buyable_states else avail[0]
        text, buyable = SCHEMA_STATUS.get(state, (state, False))
        price = None
        for o in offers:
            price = _price(o.get("price") or o.get("lowPrice"))
            if price is not None:
                break
        name = unescape(str(prod.get("name") or _og_title(html) or "Unbekanntes Produkt"))
        return Result(url=url, shop=shop_name(url), name=name, price=price,
                      status_text=text, buyable=buyable, status=state)

    # Manche Shops nutzen Mikrodaten statt JSON-LD
    m = re.search(r'itemprop=["\']availability["\'][^>]*(?:href|content)=["\'][^"\']*?(\w+)["\']', html, re.I)
    if m and m.group(1) in SCHEMA_STATUS:
        text, buyable = SCHEMA_STATUS[m.group(1)]
        pm = re.search(r'itemprop=["\']price["\'][^>]*content=["\']([\d.,]+)', html, re.I)
        return Result(url=url, shop=shop_name(url), name=_og_title(html) or "Unbekanntes Produkt",
                      price=_price(pm.group(1)) if pm else None,
                      status_text=text, buyable=buyable, status=m.group(1))
    return None


# ---------- Einstieg ----------

async def check(session: aiohttp.ClientSession, url: str) -> Result:
    if "/products/" in url:
        r = await check_shopify(session, url)
        if r:
            return r

    timeout = aiohttp.ClientTimeout(total=30)
    async with session.get(url, headers=HEADERS, timeout=timeout) as resp:
        if resp.status in (403, 429, 503):
            retry_after = resp.headers.get("Retry-After", "")
            raise BlockedError(
                f"HTTP {resp.status}",
                float(retry_after) if retry_after.isdigit() else None,
            )
        if resp.status == 404:
            raise ValueError("Produkt nicht gefunden (404)")
        resp.raise_for_status()
        html = await resp.text(errors="replace")

    if BOT_WALL.search(html[:20000]):
        raise BlockedError("Bot-Schutz-Seite")

    host = host_of(url)
    if host.startswith(("mediamarkt.", "saturn.")):
        r = parse_mediamarkt(url, html)
        if r:
            return r
    r = parse_jsonld(url, html)
    if r:
        return r
    raise ValueError("Konnte auf dieser Seite nicht erkennen, ob das Produkt verfügbar ist")
