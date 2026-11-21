"""Selbst-Update: schaut jede Minute auf GitHub nach einer neuen Version,
lädt sie herunter und startet den Bot neu. Funktioniert bei jedem Hoster,
weil nur Python gebraucht wird (kein git, kein Server-Zugang)."""

import asyncio
import io
import logging
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import aiohttp

log = logging.getLogger("mmbot.update")

BASE = Path(__file__).parent
VERSION_FILE = BASE / "data" / "version.txt"
JUST_UPDATED = BASE / "data" / "just_updated.txt"
BRANCH = "main"
KEEP = {".env"}            # wird nie überschrieben
KEEP_DIRS = {"data", ".local", ".venv"}


def current_version() -> str | None:
    return VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else None


async def latest_version(session: aiohttp.ClientSession, repo: str) -> str:
    # Gleiche Abfrage wie "git ls-remote" – zählt nicht zum GitHub-API-Limit
    url = f"https://github.com/{repo}.git/info/refs?service=git-upload-pack"
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
        resp.raise_for_status()
        body = await resp.read()
    m = re.search(rb"([0-9a-f]{40}) refs/heads/" + BRANCH.encode() + rb"\n", body)
    if not m:
        raise RuntimeError(f"Branch '{BRANCH}' nicht gefunden in {repo}")
    return m.group(1).decode()


async def apply(session: aiohttp.ClientSession, repo: str, sha: str) -> None:
    url = f"https://codeload.github.com/{repo}/zip/{sha}"
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
        resp.raise_for_status()
        data = await resp.read()

    old_req = (BASE / "requirements.txt").read_bytes() if (BASE / "requirements.txt").exists() else b""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            parts = Path(info.filename).parts[1:]  # obersten Ordner "repo-sha/" weglassen
            if not parts or info.is_dir():
                continue
            if parts[0] in KEEP_DIRS or (len(parts) == 1 and parts[0] in KEEP) or ".." in parts:
                continue
            target = BASE.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))

    if (BASE / "requirements.txt").read_bytes() != old_req:
        log.info("requirements.txt geändert – installiere Pakete")
        await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "pip", "install", "-q", "-U", "--prefix", ".local",
             "-r", "requirements.txt"],
            cwd=BASE, check=False,
        )

    VERSION_FILE.parent.mkdir(exist_ok=True)
    VERSION_FILE.write_text(sha)
    JUST_UPDATED.write_text(sha)


def restart() -> None:
    log.info("Starte neu …")
    sys.stdout.flush()
    os.execv(sys.executable, [sys.executable, *sys.argv])


async def run(session: aiohttp.ClientSession, repo: str, every: float = 60) -> None:
    while True:
        try:
            sha = await latest_version(session, repo)
            if sha != current_version():
                log.info("Neue Version %s gefunden – aktualisiere", sha[:7])
                await apply(session, repo, sha)
                restart()
        except Exception as err:  # noqa: BLE001
            log.warning("Update-Prüfung fehlgeschlagen: %s", err)
        await asyncio.sleep(every)
