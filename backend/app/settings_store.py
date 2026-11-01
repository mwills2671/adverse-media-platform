"""Configurable taxonomy / policy. Defaults live in data/*.json; admin overrides are stored in app_config."""
import copy
import json
from functools import lru_cache

from sqlalchemy.orm import Session

from .config import DATA_DIR
from .models import AppConfig, now


@lru_cache
def _defaults(name: str) -> dict:
    return json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


def default(name: str) -> dict:
    return copy.deepcopy(_defaults(name))


def get_policy(db: Session | None) -> dict:
    p = default("policy")
    if db is not None:
        row = db.get(AppConfig, "policy")
        if row:
            _deep_update(p, row.value)
    return p


def get_taxonomy(db: Session | None) -> dict:
    t = default("taxonomy")
    if db is not None:
        row = db.get(AppConfig, "taxonomy_overrides")
        if row:
            for cat in t["categories"]:
                o = row.value.get(cat["id"])
                if o:
                    for k in ("enabled", "weight", "severity"):
                        if k in o:
                            cat[k] = o[k]
    return t


def save(db: Session, key: str, value: dict, user: str) -> None:
    row = db.get(AppConfig, key)
    if row:
        row.value = value
        row.updated_by = user
        row.updated_at = now()
    else:
        db.add(AppConfig(key=key, value=value, updated_by=user))
    db.commit()


def _deep_update(base: dict, upd: dict) -> None:
    for k, v in upd.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
