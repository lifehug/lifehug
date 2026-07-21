#!/usr/bin/env python3
"""Gmail connector: calibrated external-evidence ingestion (issue #44).

Privacy guardrails (hard rules):
- gmail.readonly scope ONLY — Lifehug can never send, delete, or modify mail.
- The OAuth token lives at state/connectors/gmail_token.json (gitignored).
- Ledger build fetches METADATA only (ids, dates, headers) — no bodies.
  Bodies are fetched lazily, only for threads being promoted or sampled
  during calibration, and are stored permanently only inside promoted
  sources (owner-only, immutable).

The google-auth / google-api-python-client imports are LAZY (inside
functions) so the CLI and tests work without those packages installed, and
tests never touch the network: the API client is injectable (any object
implementing GmailClient's methods).
"""

from __future__ import annotations

import base64
import time
from datetime import datetime, timezone
from email.utils import getaddresses, parseaddr
from pathlib import Path

from lifehug_core import now_utc, slugify, write_text
from connectors.base import BaseConnector, _thread_subject, append_ledger, load_cursor, save_cursor
from connectors.scoring import (
    INSTITUTIONAL_DOMAIN_KEYWORDS,
    address_tokens,
    build_context,
    date_anchor_score,
    is_noreply,
    load_scoring_config,
    text_tokens,
    tokens_known,
)

SCOPES = ("https://www.googleapis.com/auth/gmail.readonly",)

_METADATA_HEADERS = ("From", "To", "Cc", "Subject", "List-Id", "List-Unsubscribe")

# Discovery mining bars: a correspondent needs this much volume before we
# ask "who was this?", an institution this much recurring mail before we ask
# about the era. Deliberately high — the miner surfaces significance, not noise.
MIN_DISCOVERY_MESSAGES = 10
MIN_DISCOVERY_INSTITUTION_MESSAGES = 5
MAX_BODY_CHARS = 4000

# Date-evidence kinds, first match wins on the subject line.
DATE_EVIDENCE_KINDS = (
    ("enrollment", ("enrollment", "enrolled", "registration", "registrar",
                    "transcript", "diploma", "admission", "acceptance", "admitted")),
    ("travel", ("itinerary", "booking", "reservation", "flight", "boarding",
                "ticket", "hotel")),
    ("billing", ("invoice", "receipt", "payment", "bill", "statement", "order")),
    ("appointment", ("appointment", "reminder", "schedule", "confirmation", "confirm")),
)


def normalize_message(message: dict, owner_email: str = "") -> dict:
    """Normalize a Gmail API message resource (format=metadata) into one
    compact ledger entry. Headers only — never the body."""
    headers = {
        str(header.get("name", "")).lower(): str(header.get("value", ""))
        for header in message.get("payload", {}).get("headers", [])
    }
    from_name, from_email = parseaddr(headers.get("from", ""))
    timestamp = int(message.get("internalDate") or 0) // 1000
    to = sorted({addr.lower() for _name, addr in getaddresses([headers.get("to", "")]) if addr})
    cc = sorted({addr.lower() for _name, addr in getaddresses([headers.get("cc", "")]) if addr})
    from_email = from_email.lower()
    return {
        "message_id": str(message.get("id") or ""),
        "thread_id": str(message.get("threadId") or ""),
        "timestamp": timestamp,
        "date": datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
                if timestamp else "",
        "from_email": from_email,
        "from_name": from_name,
        "to": to,
        "cc": cc,
        "subject": headers.get("subject", ""),
        "labels": list(message.get("labelIds") or []),
        "list_id": headers.get("list-id") or None,
        "has_unsubscribe": "list-unsubscribe" in headers,
        "noreply": is_noreply(from_email),
        "sent_by_owner": bool(owner_email) and from_email == owner_email.lower(),
    }


def _extract_plain_text(payload: dict) -> str:
    """First text/plain part of a message payload, base64url-decoded."""
    mime = str(payload.get("mimeType") or "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data")
        if data:
            try:
                return base64.urlsafe_b64decode(data.encode("ascii")).decode("utf-8", errors="replace")
            except (ValueError, UnicodeError):
                return ""
    for part in payload.get("parts") or []:
        text = _extract_plain_text(part)
        if text:
            return text
    return ""


def normalize_thread_message(message: dict) -> dict:
    """One message of a thread resource (format=full) for a promoted source."""
    headers = {
        str(header.get("name", "")).lower(): str(header.get("value", ""))
        for header in message.get("payload", {}).get("headers", [])
    }
    from_name, from_email = parseaddr(headers.get("from", ""))
    timestamp = int(message.get("internalDate") or 0) // 1000
    body = _extract_plain_text(message.get("payload", {})) or str(message.get("snippet") or "")
    return {
        "message_id": str(message.get("id") or ""),
        "date": datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
                if timestamp else "",
        "from_name": from_name,
        "from_email": from_email.lower(),
        "subject": headers.get("subject", ""),
        "body": body.strip()[:MAX_BODY_CHARS],
    }


# ---------------------------------------------------------------------------
# Real API client (lazy google imports; tests inject a fake instead)
# ---------------------------------------------------------------------------

class GmailClient:
    """Thin wrapper over the Gmail API surface the connector uses. Tests
    inject any object with the same methods — the real API is never called
    in tests."""

    def __init__(self, service):
        self.service = service
        self._profile: dict | None = None

    def profile(self) -> dict:
        if self._profile is None:
            self._profile = self.service.users().getProfile(userId="me").execute()
        return self._profile

    def profile_email(self) -> str:
        return str(self.profile().get("emailAddress") or "").lower()

    def history_id(self) -> str:
        return str(self.profile().get("historyId") or "")

    def list_message_ids(self, query: str | None = None):
        page_token = None
        while True:
            request = self.service.users().messages().list(
                userId="me", q=query or "", pageToken=page_token, maxResults=500)
            response = request.execute()
            for item in response.get("messages") or []:
                yield str(item["id"])
            page_token = response.get("nextPageToken")
            if not page_token:
                return

    def fetch_metadata(self, message_ids: list[str]) -> list[dict]:
        owner = self.profile_email()
        collected: dict[str, dict] = {}

        def _callback(_request_id, response, _error):
            if response:
                collected[str(response.get("id"))] = normalize_message(response, owner)

        service = self.service
        for start in range(0, len(message_ids), 100):
            chunk = message_ids[start:start + 100]
            try:
                batch = service.new_batch_http_request()
                for message_id in chunk:
                    batch.add(
                        service.users().messages().get(
                            userId="me", id=message_id, format="metadata",
                            metadataHeaders=list(_METADATA_HEADERS)),
                        callback=_callback)
                batch.execute()
            except Exception:  # noqa: BLE001 — fall back to serial gets
                for message_id in chunk:
                    response = service.users().messages().get(
                        userId="me", id=message_id, format="metadata",
                        metadataHeaders=list(_METADATA_HEADERS)).execute()
                    collected[str(response.get("id"))] = normalize_message(response, owner)
        return [collected[mid] for mid in message_ids if mid in collected]

    def fetch_thread(self, thread_id: str) -> list[dict]:
        response = self.service.users().threads().get(
            userId="me", id=thread_id, format="full").execute()
        return [normalize_thread_message(message) for message in response.get("messages") or []]


# ---------------------------------------------------------------------------
# The connector
# ---------------------------------------------------------------------------

class GmailConnector(BaseConnector):
    name = "gmail"

    @property
    def token_path(self) -> Path:
        return self.state_dir / "gmail_token.json"

    @property
    def client_secrets_path(self) -> Path:
        return self.state_dir / "gmail_client_secrets.json"

    def thread_url(self, thread_id: str) -> str:
        return f"https://mail.google.com/mail/u/0/#all/{thread_id}"

    # --- auth (live only; never exercised in tests) --------------------------

    def run_auth_flow(self) -> int:
        """One-time desktop OAuth consent. google-auth imports are lazy so
        the rest of the CLI works without the google packages installed."""
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError:
            print("Error: google-auth and google-api-python-client are required "
                  "for connector-auth (pip install google-auth google-auth-oauthlib "
                  "google-api-python-client)")
            return 1
        credentials = None
        if self.token_path.exists():
            credentials = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        if not credentials or not credentials.valid:
            if not self.client_secrets_path.exists():
                print(f"Error: OAuth client secrets not found at {self.client_secrets_path}")
                print("Download a desktop-app client config from Google Cloud Console "
                      "(Gmail API enabled, scope gmail.readonly) and save it there.")
                return 1
            flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secrets_path), SCOPES)
            credentials = flow.run_local_server(port=0)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(credentials.to_json(), encoding="utf-8")
        print(f"✓ gmail authorized (scope gmail.readonly only) — token at {self.token_path}")
        return 0

    def build_client(self) -> GmailClient:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        if not self.token_path.exists():
            raise SystemExit(f"gmail token missing — run: python3 system/lifehug.py connector-auth gmail")
        credentials = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self.token_path.write_text(credentials.to_json(), encoding="utf-8")
        service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        return GmailClient(service)

    # --- fetch (Tier 0 ledger build: metadata only) --------------------------

    def fetch(self, *, client=None, query: str | None = None, limit: int | None = None) -> dict:
        """Append NEW message metadata to the permanent ledger. Cursor-based:
        after the first full pull, later fetches only list mail newer than
        the last run (dedupe by message id makes overlaps harmless)."""
        client = client or self.build_client()
        owner = client.profile_email()
        cursor = load_cursor(self.cursor_path)
        effective_query = query
        if effective_query is None and cursor.get("last_fetch_epoch"):
            # overlap one day; the ledger's message-id dedupe absorbs it
            effective_query = f"after:{int(cursor['last_fetch_epoch']) - 86400}"
        message_ids = []
        for message_id in client.list_message_ids(query=effective_query):
            message_ids.append(message_id)
            if limit and len(message_ids) >= limit:
                break
        entries = client.fetch_metadata(message_ids)
        for entry in entries:
            entry["sent_by_owner"] = bool(owner) and entry.get("from_email") == owner.lower()
        added, total = append_ledger(self.ledger_path, entries)
        cursor.update({
            "version": 1,
            "owner": owner,
            "last_fetch_at": now_utc(),
            "last_fetch_epoch": time.time(),
            "history_id": client.history_id() or cursor.get("history_id"),
            "total_messages": total,
        })
        save_cursor(self.cursor_path, cursor)
        print(f"✓ gmail fetch: {added} new message(s) appended; ledger holds {total}")
        if added:
            print(f"  next: python3 system/lifehug.py connector-excavate gmail --dry-run")
        return {"added": added, "total": total}

    # --- Phase 0: stratified probe -------------------------------------------

    DEFAULT_PROBE_WINDOWS = (
        ("before 2010", "", "2010/1/1"),
        ("2010-2014", "2010/1/1", "2015/1/1"),
        ("2015-2019", "2015/1/1", "2020/1/1"),
        ("2020+", "2020/1/1", ""),
    )

    def probe(self, *, client=None, windows=None, per_window: int = 50) -> Path:
        """Phase 0 'what's actually in there?': a stratified metadata sample
        (one window per era), a report, and NOTHING else — no ledger, no
        sources, no bodies stored."""
        client = client or self.build_client()
        owner = client.profile_email()
        windows = windows or self.DEFAULT_PROBE_WINDOWS
        sampled: list[dict] = []
        window_counts: list[tuple[str, int]] = []
        for label, after, before in windows:
            query = " ".join(part for part in (
                f"after:{after}" if after else "",
                f"before:{before}" if before else "") if part)
            ids = []
            for message_id in client.list_message_ids(query=query or None):
                ids.append(message_id)
                if len(ids) >= per_window:
                    break
            window_counts.append((label, len(ids)))
            sampled.extend(client.fetch_metadata(ids))

        config = load_scoring_config(self.weights_path)
        context = build_context(self.repo_dir, sampled, config, owner_email=owner)
        automated = sum(1 for e in sampled
                        if e.get("noreply") or e.get("list_id") or e.get("has_unsubscribe"))
        known_hits = sum(
            1 for e in sampled
            if tokens_known(address_tokens(e.get("from_name", ""), e.get("from_email", "")),
                            context.known_any_token_sets))
        anchor_scores: dict[str, float] = {}
        for entry in sampled:
            score, _why = date_anchor_score([entry])
            if score > 0:
                domain = str(entry.get("from_email", "")).split("@")[-1]
                anchor_scores[domain] = max(anchor_scores.get(domain, 0.0), score)

        stats = context.correspondent_stats
        top = sorted(stats.items(), key=lambda item: (-item[1]["messages"], item[0]))[:20]
        lines = [
            f"# gmail probe — {now_utc()}",
            "",
            f"Stratified metadata sample: {len(sampled)} message(s). "
            "No ledger written, no bodies fetched.",
            "",
            "## Windows",
        ]
        lines += [f"- {label}: {count} sampled" for label, count in window_counts]
        lines += [
            "",
            "## Automated vs personal",
            f"- automated (noreply/list/unsubscribe): {automated}/{len(sampled)}",
            f"- known-entity hit rate (vs current rosters/wiki): {known_hits}/{len(sampled)}",
            "",
            "## Top date_anchor senders",
        ]
        lines += [f"- {domain}: {score:.2f}"
                  for domain, score in sorted(anchor_scores.items(), key=lambda kv: -kv[1])[:10]] or ["- (none)"]
        lines += ["", "## Top correspondents by volume (known/unknown vs rosters)"]
        for email, info in top:
            known = tokens_known(address_tokens(info.get("name", ""), email),
                                 context.known_any_token_sets)
            lines.append(f"- {info.get('name') or email} <{email}> — {info['messages']} msg — "
                         f"{'known' if known else 'UNKNOWN'}")
        path = self.reports_dir / "gmail_probe.md"
        write_text(path, "\n".join(lines) + "\n")
        print(f"✓ probe report: {path}")
        return path

    # --- promotion hook: bodies for ONE thread only --------------------------

    def fetch_thread(self, client, thread_id: str, entries: list[dict]) -> list[dict]:
        client = client or self.build_client()
        return client.fetch_thread(thread_id)

    # --- date evidence --------------------------------------------------------

    def extract_date_evidence(self, entries: list[dict], thresholds: dict) -> list[dict]:
        """{date, entity, kind, message_id} assertions from institutional
        mail, refreshed every excavation. The utility-bill rule: the content
        is ignored; the date + institution is the proof."""
        bar = thresholds.get("date_evidence", 0.4)
        evidence: list[dict] = []
        for entry in entries:
            score, _why = date_anchor_score([entry])
            if score < bar or not entry.get("date"):
                continue
            domain = str(entry.get("from_email") or "").split("@")[-1].lower()
            parts = domain.split(".")
            entity = parts[-2] if len(parts) >= 2 else domain
            subject = str(entry.get("subject") or "").lower()
            kind = "institutional"
            for candidate_kind, keywords in DATE_EVIDENCE_KINDS:
                if any(keyword in subject for keyword in keywords):
                    kind = candidate_kind
                    break
            evidence.append({
                "date": str(entry["date"]),
                "entity": entity,
                "kind": kind,
                "message_id": str(entry.get("message_id") or ""),
            })
        evidence.sort(key=lambda item: (item["date"], item["entity"], item["message_id"]))
        return evidence

    # --- discovery mining -----------------------------------------------------

    def mine_discovery(self, entries, threads, scored, context) -> list[dict]:
        """Mine the ledger for what the wiki DOESN'T know — unknown
        high-volume correspondents, untold narrative threads, unknown
        institutions — as proposals in the existing candidate schema,
        marked provenance=connector-mined."""
        now = now_utc()
        ledger_ref = f"state/connectors/{self.name}_ledger.jsonl"
        candidates: list[dict] = []

        # 1. Unknown significant people — ranked by volume/reciprocity/span.
        unknown_people = []
        for email, stats in context.correspondent_stats.items():
            if email in context.vip_correspondents:
                continue  # declared known — see the VIP-page candidates below
            if email in context.known_emails:
                continue  # roster entity carries this address as an alias
            if int(stats.get("messages") or 0) < MIN_DISCOVERY_MESSAGES:
                continue
            if tokens_known(address_tokens(stats.get("name", ""), email), context.known_any_token_sets):
                continue
            unknown_people.append((email, stats))
        unknown_people.sort(key=lambda item: (-item[1]["messages"], item[0]))
        for email, stats in unknown_people[:10]:
            display = stats.get("name") or email
            slug = slugify(display) or slugify(email.split("@")[0])
            first_year = str(stats.get("first_date") or "")[:4]
            last_year = str(stats.get("last_date") or "")[:4]
            span = f"{first_year}–{last_year}" if first_year and first_year != last_year else first_year
            candidates.append({
                "id": f"cand-gmail-person-{slug}",
                "text": (f"You exchanged {stats['messages']} emails with {display} "
                         f"({span}), but they have no page in your wiki — who were they, "
                         "and what did they mean to you?"),
                "source_path": ledger_ref,
                "target_page": None,
                "kind": "discovery_person",
                "priority": 0.65,
                "reason": (f"Connector-mined: unknown correspondent with {stats['messages']} "
                           f"messages over {stats.get('span_days', 0)} days, "
                           f"owner replied {stats.get('owner_replies', 0)} time(s), "
                           "absent from all rosters and wiki."),
                "status": "candidate",
                "provenance": "connector-mined",
                "connector": self.name,
                "created_at": now,
            })

        # 1b. Declared VIPs with no wiki page — the owner said these people
        # matter; if the graph hasn't caught up, propose the page.
        for email, label in sorted(context.vip_correspondents.items()):
            stats = context.correspondent_stats.get(email) or {}
            if not stats:
                continue  # declared but never seen in this ledger
            if tokens_known(text_tokens(label), context.known_any_token_sets):
                continue  # page already exists
            first_year = str(stats.get("first_date") or "")[:4]
            last_year = str(stats.get("last_date") or "")[:4]
            span = f"{first_year}–{last_year}" if first_year and first_year != last_year else first_year
            candidates.append({
                "id": f"cand-gmail-vip-{slugify(label)}",
                "text": (f"You declared {label} ({email}) as important — "
                         f"{stats.get('messages', 0)} emails ({span}), but no wiki page yet. "
                         "Who are they in your story?"),
                "source_path": ledger_ref,
                "target_page": None,
                "kind": "discovery_vip",
                "priority": 0.8,
                "reason": ("Owner-declared VIP correspondent absent from rosters and wiki; "
                           "declaration is first-person knowledge the heuristics can't have."),
                "status": "candidate",
                "provenance": "connector-mined",
                "connector": self.name,
                "created_at": now,
            })

        # 2. Untold narrative threads — high density + high novelty that did
        # not themselves cross the promotion threshold.
        untold = sorted(
            ((tid, r) for tid, r in scored.items()
             if r["band"] != "promote"
             and r["scores"]["narrative_density"] >= 0.6
             and r["scores"]["novelty"] >= 0.7),
            key=lambda item: -item[1]["total"])[:10]
        for tid, result in untold:
            subject = _thread_subject(threads[tid])
            year = min((str(e.get("date") or "")[:4] for e in threads[tid] if e.get("date")), default="")
            candidates.append({
                "id": f"cand-gmail-thread-{tid}",
                "text": (f"A {len(threads[tid])}-message email thread \"{subject}\" ({year}) "
                         "reads like a story you've never told — what actually happened?"),
                "source_path": ledger_ref,
                "target_page": None,
                "kind": "discovery_thread",
                "priority": 0.55,
                "reason": (f"Connector-mined: narrative_density "
                           f"{result['scores']['narrative_density']:.2f}, novelty "
                           f"{result['scores']['novelty']:.2f}, total {result['total']} "
                           "(below promote threshold)."),
                "status": "candidate",
                "provenance": "connector-mined",
                "connector": self.name,
                "created_at": now,
            })

        # 3. Unknown institutions — recurring organizational senders matching
        # no period/place page → era-signal candidates.
        domain_counts: dict[str, dict] = {}
        for entry in entries:
            domain = str(entry.get("from_email") or "").split("@")[-1].lower()
            if not domain or "@" not in str(entry.get("from_email") or ""):
                continue
            if not entry.get("noreply") and not any(
                    keyword in domain for keyword in INSTITUTIONAL_DOMAIN_KEYWORDS):
                continue
            parts = domain.split(".")
            entity = parts[-2] if len(parts) >= 2 else domain
            slot = domain_counts.setdefault(entity, {"messages": 0, "first": None, "last": None})
            slot["messages"] += 1
            day = str(entry.get("date") or "")
            if day:
                slot["first"] = day if slot["first"] is None else min(slot["first"], day)
                slot["last"] = day if slot["last"] is None else max(slot["last"], day)
        era_candidates = sorted(
            ((entity, slot) for entity, slot in domain_counts.items()
             if slot["messages"] >= MIN_DISCOVERY_INSTITUTION_MESSAGES
             and not tokens_known(text_tokens(entity), context.known_any_token_sets)),
            key=lambda item: -item[1]["messages"])[:5]
        for entity, slot in era_candidates:
            first_year = str(slot.get("first") or "")[:4]
            last_year = str(slot.get("last") or "")[:4]
            candidates.append({
                "id": f"cand-gmail-era-{slugify(entity)}",
                "text": (f"You received {slot['messages']} emails from {entity} between "
                         f"{first_year} and {last_year}, with no matching period or place "
                         "in your wiki — what was your connection to it?"),
                "source_path": ledger_ref,
                "target_page": None,
                "kind": "discovery_era",
                "priority": 0.5,
                "reason": (f"Connector-mined: {slot['messages']} institutional messages from "
                           f"{entity}, absent from rosters/wiki."),
                "status": "candidate",
                "provenance": "connector-mined",
                "connector": self.name,
                "created_at": now,
            })
        return candidates
