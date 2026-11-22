"""Discord-Bot: meldet, wenn Produkte im MediaMarkt.at Online-Shop bestellbar werden."""

import asyncio
import json
import logging
import os
from pathlib import Path

import aiohttp
import discord
from discord import app_commands

import checker
import updater

BASE = Path(__file__).parent
DATA_FILE = BASE / "data" / "products.json"


def load_env(path: Path) -> None:
    """Liest eine einfache .env-Datei (KEY=wert) ein, falls vorhanden."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


load_env(BASE / ".env")

TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["CHANNEL_ID"])
# Eine oder mehrere User-IDs, mit Komma getrennt: 111,222
PING_USER_IDS = [
    p.strip() for p in os.environ.get("PING_USER_ID", "").replace(";", ",").split(",")
    if p.strip().isdigit()
]
# Ziel: jedes Produkt alle CHECK_SECONDS prüfen ...
CHECK_SECONDS = max(10.0, float(os.environ.get("CHECK_SECONDS", "10")))
# ... aber nie mehr als eine Anfrage pro MIN_GAP Sekunden an MediaMarkt
MIN_GAP = max(2.0, float(os.environ.get("MIN_GAP_SECONDS", "3")))
ALLOW_MARKETPLACE = os.environ.get("ALLOW_MARKETPLACE", "false").lower() == "true"
# GitHub-Repo für automatische Updates, z. B. "deinname/mediamarkt-bot" (leer = aus)
UPDATE_REPO = os.environ.get("UPDATE_REPO", "").strip()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mmbot")

GREEN, RED, ORANGE = 0x2ECC71, 0xE74C3C, 0xF39C12


# ---------- Speicher ----------

def load_products() -> dict:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {}


def save_products(products: dict) -> None:
    DATA_FILE.parent.mkdir(exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(products, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(DATA_FILE)


def is_hit(r: checker.Result) -> bool:
    return r.buyable or (ALLOW_MARKETPLACE and r.marketplace)


def make_embed(r: checker.Result, title: str | None = None) -> discord.Embed:
    color = GREEN if is_hit(r) else (ORANGE if r.marketplace else RED)
    e = discord.Embed(title=title or r.name, url=r.url, color=color)
    if title:
        e.description = f"**{r.name}**"
    e.add_field(name="Status", value=r.status_text, inline=True)
    if r.price is not None:
        e.add_field(name="Preis", value=f"{r.price:.2f} €".replace(".", ","), inline=True)
    if r.marketplace and r.seller:
        e.add_field(name="Verkäufer", value=r.seller, inline=True)
    e.set_footer(text="MediaMarkt.at")
    return e


# ---------- Bot ----------

class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.products = load_products()
        self.http_session: aiohttp.ClientSession | None = None
        self.lock = asyncio.Lock()
        self.slow = 1.0        # Bremsfaktor: steigt bei Blockierung, sinkt langsam wieder
        self.ok_streak = 0     # erfolgreiche Anfragen seit der letzten Blockierung
        self.scheduler_task: asyncio.Task | None = None
        self.update_task: asyncio.Task | None = None

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession()
        self.scheduler_task = asyncio.create_task(self.scheduler())
        if UPDATE_REPO:
            self.update_task = asyncio.create_task(updater.run(self.http_session, UPDATE_REPO))
        else:
            log.info("UPDATE_REPO nicht gesetzt – automatische Updates sind aus")

    async def on_ready(self):
        if getattr(self, "_synced", False):  # on_ready kommt nach jedem Reconnect
            return
        self._synced = True
        channel = self.get_channel(CHANNEL_ID) or await self.fetch_channel(CHANNEL_ID)
        guild = channel.guild
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        log.info("Eingeloggt als %s, Server: %s, Channel: #%s", self.user, guild.name, channel.name)

        if updater.JUST_UPDATED.exists():
            sha = updater.JUST_UPDATED.read_text().strip()
            updater.JUST_UPDATED.unlink()
            await channel.send(f"🔄 Update installiert (Version `{sha[:7]}`) – läuft wieder.")

    async def close(self):
        for task in (self.scheduler_task, self.update_task):
            if task:
                task.cancel()
        if self.http_session:
            await self.http_session.close()
        await super().close()

    async def scheduler(self):
        """Prüft die Produkte reihum in gleichmäßigen Abständen.

        Abstand zwischen zwei Anfragen = CHECK_SECONDS / Anzahl Produkte, aber nie
        weniger als MIN_GAP. So bleibt die Last auf MediaMarkt gleich, egal wie viele
        Produkte überwacht werden. Bei einer Blockierung wird automatisch gebremst,
        danach langsam wieder beschleunigt.
        """
        await self.wait_until_ready()
        clock = asyncio.get_running_loop().time
        idx = 0
        while not self.is_closed():
            async with self.lock:
                urls = list(self.products)
            if not urls:
                await asyncio.sleep(5)
                continue
            idx %= len(urls)
            url = urls[idx]
            idx += 1
            gap = max(MIN_GAP, CHECK_SECONDS / len(urls)) * self.slow
            started = clock()
            try:
                await self.check_one(url)
                self.ok_streak += 1
                if self.slow > 1 and self.ok_streak >= 100:
                    self.slow = max(1.0, self.slow / 1.5)
                    self.ok_streak = 0
                    log.info("Läuft stabil – wieder schneller (Faktor %.1f)", self.slow)
            except checker.BlockedError as err:
                self.slow = min(self.slow * 2, 32)
                self.ok_streak = 0
                pause = max(err.retry_after or 0, 60)
                log.warning("Geblockt (%s) – %.0f s Pause, danach langsamer (Faktor %.0f)", err, pause, self.slow)
                await asyncio.sleep(pause)
                continue
            except Exception as err:  # noqa: BLE001
                log.warning("Fehler bei %s: %s", url, err)
            await asyncio.sleep(max(0.0, gap - (clock() - started)))

    async def check_one(self, url: str):
        r = await checker.check(self.http_session, url)
        async with self.lock:
            entry = self.products.get(url)
            if entry is None:  # inzwischen entfernt
                return
            was_hit = entry.get("hit", False)
            entry.update(name=r.name, hit=is_hit(r), status=r.status)
            save_products(self.products)

        channel = self.get_channel(CHANNEL_ID)
        if channel is None:
            return
        if is_hit(r) and not was_hit:
            mention = "".join(f"<@{uid}> " for uid in PING_USER_IDS)
            await channel.send(
                f"{mention}🚨 **Jetzt verfügbar!** {r.url}",
                embed=make_embed(r, "🟢 Jetzt bestellbar!"),
                allowed_mentions=discord.AllowedMentions(users=True),
            )
            log.info("VERFÜGBAR: %s", r.name)
        elif was_hit and not is_hit(r):
            await channel.send(embed=make_embed(r, "🔴 Wieder ausverkauft"))


bot = Bot()


def in_bot_channel(interaction: discord.Interaction) -> bool:
    return interaction.channel_id == CHANNEL_ID


async def wrong_channel(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"Bitte benutze mich in <#{CHANNEL_ID}>.", ephemeral=True
    )


@bot.tree.command(name="add", description="Produkt zur Überwachung hinzufügen")
@app_commands.describe(link="Link zur Produktseite auf mediamarkt.at")
async def add_cmd(interaction: discord.Interaction, link: str):
    if not in_bot_channel(interaction):
        return await wrong_channel(interaction)
    url = checker.normalize_url(link)
    if not url:
        return await interaction.response.send_message(
            "Das ist kein gültiger MediaMarkt.at-Produktlink.\n"
            "Beispiel: `https://www.mediamarkt.at/de/product/_....-12345678.html`",
            ephemeral=True,
        )
    if url in bot.products:
        return await interaction.response.send_message("Das Produkt wird schon überwacht.", ephemeral=True)

    await interaction.response.defer()
    try:
        r = await checker.check(bot.http_session, url)
    except Exception as err:  # noqa: BLE001
        return await interaction.followup.send(f"Konnte die Seite nicht prüfen: {err}")

    async with bot.lock:
        bot.products[url] = {"name": r.name, "hit": is_hit(r), "status": r.status}
        save_products(bot.products)

    note = (
        "Ist **gerade verfügbar** – schnell sein! 🛒"
        if is_hit(r)
        else "Ich pinge dich, sobald es bestellbar ist (Prüfung alle "
        f"{max(CHECK_SECONDS, MIN_GAP * len(bot.products)):g} Sek.)."
    )
    await interaction.followup.send(f"✅ Hinzugefügt. {note}", embed=make_embed(r))


@bot.tree.command(name="check", description="Sofort prüfen, ob ein Produkt verfügbar ist")
@app_commands.describe(link="Link zur Produktseite auf mediamarkt.at")
async def check_cmd(interaction: discord.Interaction, link: str):
    if not in_bot_channel(interaction):
        return await wrong_channel(interaction)
    url = checker.normalize_url(link)
    if not url:
        return await interaction.response.send_message("Das ist kein gültiger MediaMarkt.at-Produktlink.", ephemeral=True)
    await interaction.response.defer()
    try:
        r = await checker.check(bot.http_session, url)
    except Exception as err:  # noqa: BLE001
        return await interaction.followup.send(f"Konnte die Seite nicht prüfen: {err}")
    await interaction.followup.send(embed=make_embed(r))


@bot.tree.command(name="list", description="Alle überwachten Produkte anzeigen")
async def list_cmd(interaction: discord.Interaction):
    if not in_bot_channel(interaction):
        return await wrong_channel(interaction)
    if not bot.products:
        return await interaction.response.send_message("Noch keine Produkte. Füge eins mit `/add` hinzu.")
    lines = []
    for i, (url, p) in enumerate(bot.products.items(), 1):
        icon = "🟢" if p.get("hit") else "🔴"
        lines.append(f"`{i}.` {icon} [{p.get('name', url)[:80]}]({url})")
    e = discord.Embed(title="Überwachte Produkte", description="\n".join(lines)[:4000])
    e.set_footer(text="Entfernen mit /remove <Nummer>")
    await interaction.response.send_message(embed=e)


@bot.tree.command(name="remove", description="Produkt aus der Überwachung entfernen")
@app_commands.describe(nummer="Nummer aus /list")
async def remove_cmd(interaction: discord.Interaction, nummer: int):
    if not in_bot_channel(interaction):
        return await wrong_channel(interaction)
    async with bot.lock:
        urls = list(bot.products)
        if not 1 <= nummer <= len(urls):
            return await interaction.response.send_message("Diese Nummer gibt es nicht. Schau mit `/list` nach.", ephemeral=True)
        p = bot.products.pop(urls[nummer - 1])
        save_products(bot.products)
    await interaction.response.send_message(f"🗑️ Entfernt: {p.get('name')}")


if __name__ == "__main__":
    bot.run(TOKEN, log_handler=None)
