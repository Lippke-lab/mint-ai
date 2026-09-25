"""MintCards-Daten: Bestand und Einkaufsliste als lokale JSON-Dateien."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

ZUSTAENDE = ("MT", "NM", "EX", "GD", "LP", "PL", "PO", "Sealed")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _money(value, field: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        amount = round(float(str(value).replace(",", ".")), 2)
    except ValueError as exc:
        raise ValueError(f"{field} muss eine Zahl sein.") from exc
    if amount < 0:
        raise ValueError(f"{field} darf nicht negativ sein.")
    return amount


class _JsonList:
    """Eine Liste von Einträgen in einer JSON-Datei, threadsicher und atomar gespeichert."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._items: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("keine Liste")
            return [d for d in data if isinstance(d, dict) and "id" in d]
        except (OSError, ValueError) as exc:
            backup = self.path.with_suffix(".defekt.json")
            log.warning("%s unlesbar (%s), gesichert als %s.", self.path.name, exc, backup.name)
            try:
                self.path.replace(backup)
            except OSError:
                pass
            return []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._items, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def all(self) -> list[dict]:
        with self._lock:
            return [dict(i) for i in self._items]

    def add(self, item: dict) -> dict:
        item = {"id": uuid.uuid4().hex[:10], **item}
        with self._lock:
            self._items.append(item)
            self._save()
        return dict(item)

    def update(self, item_id: str, **changes) -> dict:
        with self._lock:
            for item in self._items:
                if item["id"] == item_id:
                    item.update(changes)
                    self._save()
                    return dict(item)
        raise KeyError(item_id)

    def remove(self, item_id: str) -> None:
        with self._lock:
            before = len(self._items)
            self._items = [i for i in self._items if i["id"] != item_id]
            if len(self._items) == before:
                raise KeyError(item_id)
            self._save()


class MintCardsData:
    def __init__(self, data_dir: Path):
        self.bestand = _JsonList(data_dir / "bestand.json")
        self.einkaufsliste = _JsonList(data_dir / "einkaufsliste.json")

    # --- Einkaufsliste ---
    def add_einkauf(self, text: str, maxpreis=None) -> dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("Bitte beschreiben, was gekauft werden soll.")
        return self.einkaufsliste.add({
            "text": text[:200],
            "maxpreis": _money(maxpreis, "Maximalpreis"),
            "erledigt": False,
            "erstellt": _now(),
        })

    def toggle_einkauf(self, item_id: str) -> dict:
        current = next((i for i in self.einkaufsliste.all() if i["id"] == item_id), None)
        if current is None:
            raise KeyError(item_id)
        return self.einkaufsliste.update(item_id, erledigt=not current.get("erledigt"))

    # --- Bestand ---
    def add_karte(self, data: dict) -> dict:
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("Bitte den Namen der Karte angeben.")
        zustand = (data.get("zustand") or "NM").strip()
        if zustand not in ZUSTAENDE:
            raise ValueError(f"Zustand muss einer von {', '.join(ZUSTAENDE)} sein.")
        try:
            menge = int(data.get("menge") or 1)
        except ValueError as exc:
            raise ValueError("Menge muss eine ganze Zahl sein.") from exc
        if menge < 1:
            raise ValueError("Menge muss mindestens 1 sein.")
        return self.bestand.add({
            "name": name[:120],
            "set": (data.get("set") or "").strip()[:80],
            "nummer": (data.get("nummer") or "").strip()[:20],
            "zustand": zustand,
            "menge": menge,
            "einkauf": _money(data.get("einkauf"), "Einkaufspreis"),
            "marktwert": _money(data.get("marktwert"), "Marktwert"),
            "hinzugefuegt": _now(),
        })

    def snapshot(self) -> dict:
        return {"bestand": self.bestand.all(), "einkaufsliste": self.einkaufsliste.all()}
