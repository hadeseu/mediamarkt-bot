"""Prüft, ob ein Produkt im MediaMarkt.at Online-Shop bestellbar ist."""

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "de-AT,de;q=0.9",
}

STATUS_TEXT = {
    "AVAILABLE": "Online bestellbar",
    "MP_OFFER": "Nur über Marktplatz-Händler",
    "STORE_ONLY": "Nur im Markt erhältlich",
    "NOT_AVAILABLE": "Nicht verfügbar",
    "TEMPORARILY_NOT_AVAILABLE": "Zurzeit nicht verfügbar",
    "PERMANENTLY_NOT_AVAILABLE": "Dauerhaft nicht verfügbar",
    "COMING_SOON": "Bald erhältlich",
    "PRE_ORDER": "Vorbestellbar",
    "NO_VALID_MP_OFFER_PRICE": "Nicht verfügbar",
}


class BlockedError(Exception):
    """MediaMarkt hat die Anfrage abgelehnt (zu viele Anfragen o. Ä.)."""

    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


@dataclass
class Result:
    url: str
    name: str
    price: float | None
    status: str          # Rohstatus von MediaMarkt, z. B. AVAILABLE
    buyable: bool        # bei MediaMarkt selbst bestellbar
    marketplace: bool    # nur bei einem Marktplatz-Händler bestellbar
    seller: str | None   # Name des Marktplatz-Händlers

    @property
    def status_text(self) -> str:
        if self.buyable:
            return STATUS_TEXT["AVAILABLE"]
        return STATUS_TEXT.get(self.status, self.status.replace("_", " ").capitalize())


def normalize_url(url: str) -> str | None:
    """Gibt eine saubere Produkt-URL zurück, oder None, wenn es keine MediaMarkt.at-Produktseite ist."""
    url = url.strip().strip("<>")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.hostname not in ("www.mediamarkt.at", "mediamarkt.at"):
        return None
    if not re.search(r"/product/.+-\d+\.html$", parsed.path):
        return None
    return f"https://www.mediamarkt.at{parsed.path}"


def product_id(url: str) -> str:
    return re.search(r"-(\d+)\.html$", url).group(1)


def parse(url: str, html: str) -> Result:
    pid = product_id(url)

    # Verfügbarkeit: MediaMarkt selbst = ohne [..], Marktplatz-Angebote = mit [AngebotsID]
    own, market = [], []
    pattern = (
        r'"CofrOnlineStatusFeature:Media:de:' + pid + r'(\[\d+\])?":(\{[^{}]*\})'
    )
    for m in re.finditer(pattern, html):
        try:
            data = json.loads(m.group(2))
        except json.JSONDecodeError:
            continue
        (market if m.group(1) else own).append(data)

    if not own and not market:
        raise ValueError("Keine Verfügbarkeitsdaten gefunden (Seite geändert?)")

    buyable = any(d.get("isAvailableAndBuyable") and d.get("onlineStatus") != "MP_OFFER" for d in own)
    mp_buyable = any(d.get("isAvailableAndBuyable") for d in market) or any(
        d.get("isAvailableAndBuyable") and d.get("onlineStatus") == "MP_OFFER" for d in own
    )
    status = (own or market)[0].get("onlineStatus") or "UNKNOWN"
    if buyable:
        status = "AVAILABLE"

    # Name
    name = "Unbekanntes Produkt"
    m = re.search(r'property="og:title" content="([^"]+)"', html)
    if m:
        name = re.sub(r"\s*\|\s*MediaMarkt\s*$", "", m.group(1)).replace("&amp;", "&")

    # Preis
    price = None
    m = re.search(r'"offers":\{"@type":"Offer","priceCurrency":"EUR","price":([\d.]+)', html)
    if not m:  # Marktplatz-Angebote haben den Preis woanders
        m = re.search(r'"CofrPriceFeaturePrice","amount":([\d.]+)', html)
    if m:
        price = float(m.group(1))

    seller = None
    m = re.search(r'"sellerName":"([^"]+)"', html)
    if m:
        seller = m.group(1)

    return Result(
        url=url,
        name=name,
        price=price,
        status=status,
        buyable=buyable,
        marketplace=mp_buyable and not buyable,
        seller=seller,
    )


async def check(session: aiohttp.ClientSession, url: str) -> Result:
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
        html = await resp.text()
    return parse(url, html)
