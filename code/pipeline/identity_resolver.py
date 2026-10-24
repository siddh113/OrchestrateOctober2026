from __future__ import annotations
import csv
from pathlib import Path
from typing import Optional

from pipeline import UserIdentity

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATASET = _REPO_ROOT / "dataset"


class IdentityResolver:
    def __init__(self) -> None:
        self._by_current_email: dict[str, dict] = {}
        self._by_user_id: dict[str, dict] = {}
        self._historical_emails: dict[str, list[str]] = {}  # user_id -> old emails
        self._historical_phones: dict[str, list[str]] = {}  # user_id -> old phones
        self._email_to_user_id: dict[str, str] = {}         # historical email -> user_id
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        # Load current identities
        with open(_DATASET / "user_identities.csv", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                email_lc = (row["email"] or "").strip().lower()
                uid = row["user_id"].strip()
                self._by_current_email[email_lc] = row
                self._by_user_id[uid] = row

        # Load audit log for historical identifiers
        with open(_DATASET / "user_audit_log.csv", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                uid = row["user_id"].strip()
                field = row["field_name"].strip()
                old_val = (row["old_value"] or "").strip()
                if not old_val:
                    continue
                if field == "email":
                    old_lc = old_val.lower()
                    self._historical_emails.setdefault(uid, []).append(old_lc)
                    self._email_to_user_id[old_lc] = uid
                elif field == "phone":
                    self._historical_phones.setdefault(uid, []).append(old_val)

        self._loaded = True

    def resolve(self, email: str) -> Optional[UserIdentity]:
        self._load()
        email_lc = email.strip().lower()

        # 1. Current email lookup
        row = self._by_current_email.get(email_lc)
        if row:
            return self._build(row)

        # 2. Historical email lookup
        uid = self._email_to_user_id.get(email_lc)
        if uid:
            row = self._by_user_id.get(uid)
            if row:
                return self._build(row)

        return None

    def _build(self, row: dict) -> UserIdentity:
        uid = row["user_id"].strip()
        current_email = (row["email"] or "").strip().lower()
        current_phone = (row["phone"] or "").strip()
        name = (row["name"] or "").strip()
        email_hash = (row["email_hash"] or "").strip()

        all_emails: set[str] = {current_email}
        for e in self._historical_emails.get(uid, []):
            all_emails.add(e)

        all_phones: set[str] = set()
        if current_phone:
            all_phones.add(current_phone)
        for p in self._historical_phones.get(uid, []):
            all_phones.add(p)

        return UserIdentity(
            user_id=uid,
            current_email=current_email,
            all_emails=all_emails,
            all_phones=all_phones,
            name=name,
            email_hash=email_hash,
        )

    def get_by_user_id(self, user_id: str) -> Optional[UserIdentity]:
        self._load()
        row = self._by_user_id.get(user_id.strip())
        if row:
            return self._build(row)
        return None
