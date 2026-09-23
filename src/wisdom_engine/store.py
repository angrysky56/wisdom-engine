"""Transactional SQLite event store with exact revision dependencies and replay."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterator
from uuid import uuid4

from .contracts import (Assessment, CaseInput, CaseSnapshot, Check, Claim, Observation,
                        PAYLOAD, Prediction, Record, RecordPayload, Resolution, dependencies)

MAX_RECORDS = 500
MAX_EVENTS = 5000


class InquiryError(ValueError):
    """An actionable domain failure safe to expose through MCP."""


def canonical(value: object) -> str:
    """Stable serialization for fingerprints and persisted events."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def invalid_reasons(records: dict[str, Record]) -> dict[str, list[str]]:
    """Invalidate transitively; alternative assessments remain independent records."""
    memo: dict[str, list[str]] = {}
    visiting: set[str] = set()

    def visit(key: str) -> list[str]:
        if key in visiting:
            raise InquiryError('Dependency cycle')
        if key in memo:
            return memo[key]
        visiting.add(key)
        record = records[key]
        reasons = [] if record.lifecycle == 'active' else ['withdrawn']
        for ref in dependencies(record.payload):
            target = records.get(ref.record_id)
            if target is None or target.revision != ref.revision:
                reasons.append(f'superseded_or_missing:{ref.record_id}@{ref.revision}')
            elif visit(ref.record_id):
                reasons.append(f'inactive_dependency:{ref.record_id}@{ref.revision}')
        visiting.remove(key)
        memo[key] = reasons
        return reasons

    for key in records:
        visit(key)
    return memo


def validate_event(records: dict[str, Record], record: Record) -> None:
    """Check a proposed revision before replacing its projection, including imports."""
    previous = records.get(record.id)
    if record.revision != (previous.revision + 1 if previous else 1):
        raise InquiryError('Nonconsecutive record revision')
    if previous and previous.payload.kind != record.payload.kind:
        raise InquiryError('Record kind cannot change')
    if previous is None and len(records) >= MAX_RECORDS:
        raise InquiryError(f'Case record limit is {MAX_RECORDS}')
    if not previous and record.lifecycle != 'active':
        raise InquiryError('A new record must be active')
    if record.lifecycle == 'withdrawn' and previous and record.payload != previous.payload:
        raise InquiryError('Withdrawal cannot also change content')
    if record.lifecycle == 'active':
        invalid = invalid_reasons(records)
        for ref in dependencies(record.payload):
            target = records.get(ref.record_id)
            if target is None or target.revision != ref.revision or invalid[ref.record_id]:
                raise InquiryError(f'Dependency not current and active: {ref.record_id}@{ref.revision}')
        payload = record.payload
        if isinstance(payload, (Prediction, Assessment)):
            if not isinstance(records[payload.claim.record_id].payload, Claim):
                raise InquiryError('claim must reference a claim')
        if isinstance(payload, Prediction) and payload.scope != records[payload.claim.record_id].payload.scope:
            raise InquiryError('Prediction scope must match the claim scope')
        if isinstance(payload, Check) and any(not isinstance(records[r.record_id].payload, Claim) for r in payload.scenarios):
            raise InquiryError('Check scenarios must reference claims')
        if isinstance(payload, Resolution) and any(not isinstance(records[r.record_id].payload, (Observation, Assessment))
                                                  for r in payload.evidence):
            raise InquiryError('Resolution evidence must reference observations or assessments')
        if isinstance(payload, Assessment):
            observed = records[payload.observation.record_id].payload
            if not isinstance(observed, Observation):
                raise InquiryError('observation must reference an observation')
            if payload.prediction:
                predicted = records[payload.prediction.record_id].payload
                if not isinstance(predicted, Prediction) or predicted.claim != payload.claim:
                    raise InquiryError('Prediction must belong to this claim revision')
                if payload.review and (not predicted.necessary or predicted.scope != observed.scope):
                    raise InquiryError('Refutation requires a necessary prediction with matching observation scope')
                if payload.review and not predicted.retrospective:
                    prediction_time = datetime.fromisoformat(records[payload.prediction.record_id].created_at)
                    observed_recorded = datetime.fromisoformat(records[payload.observation.record_id].created_at)
                    if min(datetime.fromisoformat(observed.observed_at), observed_recorded) < prediction_time:
                        raise InquiryError('Prediction postdates the outcome; mark it retrospective')
    for ref in dependencies(record.payload):
        if ref.record_id == record.id:
            raise InquiryError('A record cannot depend on itself')
    proposed = records | {record.id: record}
    visiting: set[str] = set()
    visited: set[str] = set()

    def check_cycle(key: str) -> None:
        if key in visiting:
            raise InquiryError('Dependency cycle')
        if key in visited:
            return
        visiting.add(key)
        for ref in dependencies(proposed[key].payload):
            if ref.record_id in proposed:
                check_cycle(ref.record_id)
        visiting.remove(key)
        visited.add(key)

    for key in proposed:
        check_cycle(key)
    invalid_reasons(proposed)  # Also rejects cycles introduced by a revision.


class Store:
    """Each operation owns a connection; transactions cover validation and append."""

    def __init__(self, path: Path | str | None = None):
        directory = Path(os.environ.get('WISDOM_DATA_DIR', '~/.local/share/wisdom-engine')).expanduser()
        self.path = Path(path) if path is not None else directory / 'inquiry.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise InquiryError(f'Unsupported database schema {version}; expected 1')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY, data TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    case_id TEXT NOT NULL REFERENCES cases(id), sequence INTEGER NOT NULL,
                    data TEXT NOT NULL, PRIMARY KEY(case_id, sequence));
                CREATE TABLE IF NOT EXISTS requests (
                    case_id TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    response TEXT NOT NULL, PRIMARY KEY(case_id, request_id));
                PRAGMA user_version=1;
            ''')

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=3, isolation_level=None)
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _lookup(db: sqlite3.Connection, case_id: str, request_id: str, intent: object) -> dict | None:
        row = db.execute('SELECT fingerprint, response FROM requests WHERE case_id=? AND request_id=?',
                         (case_id, request_id)).fetchone()
        if row:
            if row[0] != fingerprint(intent):
                raise InquiryError('Idempotency key already used with different input')
            return json.loads(row[1])
        return None

    def lookup(self, case_id: str, request_id: str, intent: object) -> dict | None:
        with self.connect() as db:
            return self._lookup(db, case_id, request_id, intent)

    @staticmethod
    def _remember(db: sqlite3.Connection, case_id: str, request_id: str, intent: object, response: dict) -> dict:
        db.execute('INSERT INTO requests VALUES (?, ?, ?, ?)',
                   (case_id, request_id, fingerprint(intent), canonical(response)))
        return response

    def open_case(self, case: CaseInput, request_id: str) -> dict:
        intent = case.model_dump()
        with self.transaction() as db:
            if old := self._lookup(db, '__open__', request_id, intent):
                return old
            case_id = uuid4().hex
            db.execute('INSERT INTO cases VALUES (?, ?, ?)', (case_id, canonical(intent), now()))
            return self._remember(db, '__open__', request_id, intent,
                                  {'case_id': case_id, 'sequence': 0, 'schema_version': 1})

    @staticmethod
    def _snapshot(db: sqlite3.Connection, case_id: str) -> CaseSnapshot:
        row = db.execute('SELECT data FROM cases WHERE id=?', (case_id,)).fetchone()
        if row is None:
            raise InquiryError('Case not found')
        events = db.execute('SELECT data FROM events WHERE case_id=? ORDER BY sequence', (case_id,)).fetchall()
        records: dict[str, Record] = {}
        for event in events:
            record = Record.model_validate_json(event[0])
            records[record.id] = record
        return CaseSnapshot(case_id=case_id, case=CaseInput.model_validate_json(row[0]),
                            sequence=len(events), records=list(records.values()))

    def snapshot(self, case_id: str) -> CaseSnapshot:
        with self.connect() as db:
            db.execute('BEGIN')  # A consistent read snapshot across all SELECTs.
            return self._snapshot(db, case_id)

    def list_cases(self, offset: int = 0, limit: int = 50) -> dict:
        """Discover saved inquiries after a restart without exposing full evidence."""
        with self.connect() as db:
            db.execute('BEGIN')
            rows = db.execute('SELECT id, data, created_at FROM cases ORDER BY created_at, id LIMIT ? OFFSET ?',
                              (limit + 1, offset)).fetchall()
            return {'schema_version': 1,
                    'cases': [{'case_id': key, 'question': json.loads(data)['question'], 'created_at': created}
                              for key, data, created in rows[:limit]],
                    'next_offset': offset + limit if len(rows) > limit else None}

    def append(self, case_id: str, payloads: list[RecordPayload], expected_sequence: int,
               request_id: str, *, intent: object | None = None, metadata: dict | None = None) -> dict:
        """Append a whole batch or nothing. Repeated request IDs replay the result."""
        if not 1 <= len(payloads) <= 20:
            raise InquiryError('Batch must contain 1–20 records')
        payloads = [PAYLOAD.validate_python(p.model_dump()) for p in payloads]
        if intent is None:
            intent = {'operation': 'append', 'payloads': [p.model_dump() for p in payloads],
                      'expected_sequence': expected_sequence}
        with self.transaction() as db:
            if old := self._lookup(db, case_id, request_id, intent):
                return old
            snap = self._snapshot(db, case_id)
            if snap.sequence != expected_sequence:
                raise InquiryError('Stale case sequence; refresh get_case before retrying with a new request_id')
            records = {r.id: r for r in snap.records}
            added = []
            for payload in payloads:
                record = Record(id=uuid4().hex, revision=1, created_at=now(), change_reason='created', payload=payload)
                validate_event(records, record)
                records[record.id] = record
                added.append(record)
            return self._write(db, snap, added, request_id, intent, metadata)

    def revise(self, case_id: str, record_id: str, expected_revision: int, expected_sequence: int,
               request_id: str, reason: str, replacement: RecordPayload | None = None,
               withdraw: bool = False) -> dict:
        intent = {'operation': 'revise', 'record_id': record_id, 'expected_revision': expected_revision,
                  'expected_sequence': expected_sequence, 'reason': reason, 'withdraw': withdraw,
                  'replacement': replacement.model_dump() if replacement else None}
        if withdraw == (replacement is not None):
            raise InquiryError('Specify either withdrawal or a replacement')
        with self.transaction() as db:
            if old := self._lookup(db, case_id, request_id, intent):
                return old
            snap = self._snapshot(db, case_id)
            records = {r.id: r for r in snap.records}
            previous = records.get(record_id)
            if snap.sequence != expected_sequence or previous is None or previous.revision != expected_revision:
                raise InquiryError('Stale or missing record; refresh get_case')
            record = Record(id=record_id, revision=previous.revision + 1, created_at=now(),
                            lifecycle='withdrawn' if withdraw else 'active', change_reason=reason,
                            payload=replacement or previous.payload)
            validate_event(records, record)
            return self._write(db, snap, [record], request_id, intent)

    def _write(self, db: sqlite3.Connection, snap: CaseSnapshot, added: list[Record], request_id: str,
               intent: object, metadata: dict | None = None) -> dict:
        if snap.sequence + len(added) > MAX_EVENTS:
            raise InquiryError(f'Case event limit is {MAX_EVENTS}')
        for index, record in enumerate(added, snap.sequence + 1):
            db.execute('INSERT INTO events VALUES (?, ?, ?)', (snap.case_id, index, record.model_dump_json()))
        return self._remember(db, snap.case_id, request_id, intent,
                              {**(metadata or {}), 'case_id': snap.case_id, 'sequence': snap.sequence + len(added),
                               'records': [r.model_dump() for r in added], 'schema_version': 1})

    def export_case(self, case_id: str) -> dict:
        with self.connect() as db:
            db.execute('BEGIN')
            snap = self._snapshot(db, case_id)
            rows = db.execute('SELECT sequence, data FROM events WHERE case_id=? ORDER BY sequence', (case_id,)).fetchall()
            created = db.execute('SELECT created_at FROM cases WHERE id=?', (case_id,)).fetchone()[0]
            return {'schema_version': 1, 'case_id': case_id, 'case': snap.case.model_dump(),
                    'created_at': created, 'events': [{'sequence': n, 'record': json.loads(s)} for n, s in rows]}

    def import_case(self, bundle: dict, request_id: str) -> dict:
        """Validate/replay before atomic import; never overwrite an existing case."""
        from .transfer import Bundle
        parsed = Bundle.model_validate(bundle)
        records: dict[str, Record] = {}
        for seq, event in enumerate(parsed.events, 1):
            if event.sequence != seq:
                raise InquiryError('Nonconsecutive event sequence')
            validate_event(records, event.record)
            records[event.record.id] = event.record
        with self.transaction() as db:
            if old := self._lookup(db, '__import__', request_id, bundle):
                return old
            if db.execute('SELECT 1 FROM cases WHERE id=?', (parsed.case_id,)).fetchone():
                raise InquiryError('Case already exists; imports never overwrite')
            db.execute('INSERT INTO cases VALUES (?, ?, ?)',
                       (parsed.case_id, parsed.case.model_dump_json(), parsed.created_at))
            for event in parsed.events:
                db.execute('INSERT INTO events VALUES (?, ?, ?)',
                           (parsed.case_id, event.sequence, event.record.model_dump_json()))
            return self._remember(db, '__import__', request_id, bundle,
                                  {'case_id': parsed.case_id, 'sequence': len(parsed.events), 'schema_version': 1})
