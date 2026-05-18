#!/usr/bin/env python3
"""
name_call_type_sub_small_tiny_deterministic.py

Names SMALL/TINY call_type_sub clusters with deterministic rules only.
No Ollama. No LLM. No network calls.

Scope:
    - field_name = call_type_sub
    - non-anomaly clusters only
    - raw_label_count between --min-labels and --max-labels, default 2..5

Reads from:
    taxonomy_label_cluster_map

Writes to:
    taxonomy_cluster_names

Env priority for DB connection:
    CLUSTER_DB_* first, then LOCAL_PG_*
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
import csv
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv


FIELD_NAME = "outcome_sub"

# Phrase-aware lists. These are used only if weighted-mode and component matching do not resolve a name.
ENTITY_LIST = [
    "admin",
    "discovery",
    "prospecting",
    "cold call",
    "account management",
    "service",
    "negotiation",
    "dead lead",
    "unproductive connect",
    "dm",
    "ivr system",
    "customer",
    "renewal",
    "contract",
    "loa",
    "complaint",
    "risk",
    "partner",
    "supplier",
    "technical",
    "inbound",
    "gatekeeper",
    "voicemail",
    "lead",
    "billing",
    "setup",
    "legal",
    "compliance",
    "pitch",
    "closing",
    "internal",
    "personal",
]

ACTION_LIST = [
    "unavailable",
    "failed",
    "transfer failed",
    "chase",
    "request",
    "query",
    "review",
    "update",
    "verification",
    "confirmation",
    "callback",
    "handover",
    "setup",
    "blocked",
    "scheduled",
    "sent",
    "received",
    "connected",
    "no answer",
    "hang up",
    "time wasting",
    "information gathering",
    "follow up",
    "discussion",
    "dispute",
    "correction",
    "escalation",
    "routing",
    "support",
    "attempt",
]

# Logic-level synonyms. These help match concepts but do not overwrite DB raw labels.
SYNONYM_MAP = {
    "followup": "follow up",
    "follow up required": "follow up",
    "follow up": "chase",
    "return request": "chase",
    "return chase": "chase",
    "callback request": "callback",
    "call back": "callback",
    "loa follow up": "loa chase",
    "loa followup": "loa chase",
    "contract follow up": "contract chase",
    "contract followup": "contract chase",
    "noanswer": "no answer",
    "hangup": "hang up",
    "unintended time wasting": "time wasting",
    "accountmanagement": "account management",
    "deadlead": "dead lead",
    "managedoffice": "managed office",
    "outsourcedprocurement": "outsourced procurement",
    "wrongdepartment": "wrong department",
    "wrongquery": "wrong query",
    "sharedmetering": "shared metering",
    "whatsapp": "whatsapp",
    "whats app": "whatsapp",
}

ACRONYMS = {
    "loa": "LOA",
    "cot": "CoT",
    "dm": "DM",
    "mpan": "MPAN",
    "mprn": "MPRN",
    "vat": "VAT",
    "ccl": "CCL",
    "ngp": "NGP",
    "kva": "KVA",
    "edf": "EDF",
    "sse": "SSE",
    "eon": "E.ON",
    "ivr": "IVR",
    "dnc": "DNC",
    "gdpr": "GDPR",
    "crm": "CRM",
    "it": "IT",
    "hr": "HR",
    "rnr": "RNR",
    "ivr": "IVR",
    "dnc": "DNC",
    "loa": "LOA",
    "mpan": "MPAN",
    "mprn": "MPRN",
    "cot": "CoT",
    "ev": "EV",
    "kwh": "kWh",
    "kw": "kW",
    "vat": "VAT",
    "dd": "DD",
    "nda": "NDA",
    "tpi": "TPI",
    "hmrc": "HMRC",
    "bacs": "BACS",
    "rts": "RTS"
}

STOP_TOKENS_FOR_NGRAMS = {
    "required",
    "general",
}
OUTCOME_SUB_COMPONENT_PRIORITY = [
    "information sent",
    "info sent",
    "follow up scheduled",
    "followup scheduled",
    "callback scheduled",
    "callback requested",
    "email sent",
    "email confirmed",
    "bill requested",
    "loa sent",
    "loa received",
    "contract sent",
    "contract received",
    "proposal sent",
    "quote sent",
    "sale closed",
    "sale pending",
    "not interested",
    "wrong number",
    "wrong contact",
    "no answer",
    "voicemail",
    "customer unavailable",
    "internal admin",
    "research required",
    "awaiting customer",
    "awaiting supplier",
]

OUTCOME_SUB_COMPONENT_ALIASES = {
    "info sent": "Information Sent",
    "information sent": "Information Sent",

    "followup scheduled": "Follow Up Scheduled",
    "follow up scheduled": "Follow Up Scheduled",
    "followup required": "Follow Up Required",
    "follow up required": "Follow Up Required",

    "callback scheduled": "Callback Scheduled",
    "callback requested": "Callback Requested",
    "callback request": "Callback Requested",

    "email sent": "Email Sent",
    "email confirmed": "Email Confirmed",

    "bill requested": "Bill Requested",

    "loa sent": "LOA Sent",
    "loa received": "LOA Received",

    "contract sent": "Contract Sent",
    "contract received": "Contract Received",
    "contract signed": "Contract Signed",

    "proposal sent": "Proposal Sent",
    "quote sent": "Quote Sent",

    "sale closed": "Sale Closed",
    "sale pending": "Sale Pending",
    "sale closed pending": "Sale Pending",

    "notinterested": "Not Interested",
    "not interested": "Not Interested",

    "wrongnum": "Wrong Number",
    "wrongno": "Wrong Number",
    "wrong number": "Wrong Number",
    "wrongcontact": "Wrong Contact",
    "wrong contact": "Wrong Contact",

    "noanswer": "No Answer",
    "no answer": "No Answer",
    "voicemail": "Voicemail",

    "customer unavailable": "Customer Unavailable",
    "customer not available": "Customer Unavailable",

    "research required": "Research Required",
    "awaiting customer": "Awaiting Customer",
    "awaiting supplier": "Awaiting Supplier",

    "changeoftenancy": "Change Of Tenancy",
    "change of tenancy": "Change Of Tenancy",
    "changeofownership": "Change Of Ownership",
    "change of ownership": "Change Of Ownership",
}

OUTCOME_SUB_COMPACT_ALIASES = {
    "information sent": "Info Sent",
    "follow up scheduled": "Follow Up",
    "followup scheduled": "Follow Up",
    "follow up required": "Follow Up",
    "followup required": "Follow Up",

    "callback scheduled": "Callback",
    "callback requested": "Callback Request",

    "email sent": "Email",
    "email confirmed": "Email",

    "bill requested": "Bill",
    "loa sent": "LOA Sent",
    "loa received": "LOA Received",

    "contract sent": "Contract Sent",
    "contract received": "Contract Received",
    "contract signed": "Contract Signed",

    "proposal sent": "Proposal",
    "quote sent": "Quote",

    "sale closed": "Sale Closed",
    "sale pending": "Sale Pending",

    "not interested": "Not Interested",
    "wrong number": "Wrong Number",
    "wrong contact": "Wrong Contact",
    "no answer": "No Answer",
    "voicemail": "Voicemail",

    "customer unavailable": "Customer Unavailable",
    "research required": "Research",
    "awaiting customer": "Awaiting Customer",
    "awaiting supplier": "Awaiting Supplier",

    "change of tenancy": "CoT",
    "change of ownership": "Ownership Change",
}
MAX_DISPLAY_NAME_WORDS = 6
OUTCOME_SUB_SPECIFIC_COMPONENT_ALIASES = {
    "customer internal approval required": "Internal Approval Required",
    "customer seeks internal approval": "Internal Approval Required",

    "customer timing issue": "Timing Issue",
    "customer needs time": "Customer Needs Time",
    "customer business issue": "Business Issue",
    "customer supplier loyalty": "Supplier Loyalty",
    "customer said no": "Customer Said No",
    "customer hung up": "Customer Hung Up",
    "customer raised objection": "Raised Objection",
    "customer contract concern": "Contract Concern",
    "customer budget constraint": "Budget Constraint",
    "customer non committal": "Non Committal",
    "customer wants to negotiate": "Negotiation",
    "customer competitor shopping": "Competitor Shopping",
    "customer gatekeeper blocked": "Gatekeeper Blocked",
    "customer wrong contact": "Wrong Contact",

    "opportunity delayed": "Opportunity Delayed",
    "opp lost to competitor": "Lost To Competitor",
    "do not call": "Do Not Call",
    "not interested": "Not Interested",
    "busy": "Busy Customer",
    "customer busy": "Busy Customer",

    "follow up scheduled": "Follow Up Scheduled",
    "followup scheduled": "Follow Up Scheduled",
    "information sent": "Information Sent",
    "information gathered": "Information Gathered",
    "information requested": "Information Requested",
    "email confirmed": "Email Confirmed",
    "callback requested": "Callback Requested",
    "callback scheduled": "Callback Scheduled",

    "loa received": "LOA Received",
    "loa sent": "LOA Sent",
    "loa req by customer": "LOA Requested",

    "contract agreed": "Contract Agreed",
    "contract received": "Contract Received",
    "recv contract": "Contract Received",

    "lead generated": "Lead Generated",
    "research required": "Research Required",
    "positive buying signals": "Buying Signals",
    "customer closing intent": "Closing Intent",
    "customer agreed": "Customer Agreed",
    "customer agreed in principle": "Agreement In Principle",
    "sale closed": "Sale Closed",
    "successful renewal": "Successful Renewal",
    "successful pitch": "Successful Pitch",
    "risk identified": "Risk Identified",
    "missing information": "Missing Information",
}


OUTCOME_SUB_NAME_PRIORITY = [
    "Information Sent",
    "Information Gathered",
    "Information Requested",
    "Follow Up Scheduled",
    "Callback Requested",
    "Callback Scheduled",
    "Email Confirmed",
    "LOA Requested",
    "LOA Sent",
    "LOA Received",
    "Contract Received",
    "Contract Agreed",
    "Customer Said No",
    "Customer Hung Up",
    "Customer Needs Time",
    "Timing Issue",
    "Internal Approval Required",
    "Agreement In Principle",
    "Negotiation",
    "Competitor Shopping",
    "Supplier Loyalty",
    "Business Issue",
    "Contract Concern",
    "Raised Objection",
    "Budget Constraint",
    "Non Committal",
    "Gatekeeper Blocked",
    "Wrong Contact",
    "Do Not Call",
    "Not Interested",
    "Busy Customer",
    "Opportunity Delayed",
    "Lost To Competitor",
    "Lead Generated",
    "Research Required",
    "Buying Signals",
    "Closing Intent",
    "Customer Agreed",
    "Sale Closed",
    "Successful Renewal",
    "Successful Pitch",
    "Risk Identified",
    "Missing Information",
]


def clean_outcome_component_for_specific_name(component: str) -> str:
    norm = normalize_for_name(component)

    if norm in OUTCOME_SUB_SPECIFIC_COMPONENT_ALIASES:
        return OUTCOME_SUB_SPECIFIC_COMPONENT_ALIASES[norm]

    cleaned = clean_outcome_sub_component(norm)
    cleaned_norm = normalize_for_name(cleaned)

    if cleaned_norm in OUTCOME_SUB_SPECIFIC_COMPONENT_ALIASES:
        return OUTCOME_SUB_SPECIFIC_COMPONENT_ALIASES[cleaned_norm]

    return cleaned


def outcome_component_priority(name: str) -> tuple[int, str]:
    try:
        return (OUTCOME_SUB_NAME_PRIORITY.index(name), name)
    except ValueError:
        return (9999, name)


def extract_specific_component_weights(labels: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()

    for row in labels:
        count = label_count(row)
        raw = str(row.get("raw_label") or "")
        inner = raw[1:-1] if raw.startswith("{") and raw.endswith("}") else raw
        parts = [p.strip() for p in inner.split(",") if p.strip()]

        seen_for_label: set[str] = set()

        for part in parts:
            component = clean_outcome_component_for_specific_name(part)
            norm = normalize_for_name(component)

            if not norm or norm in seen_for_label:
                continue

            seen_for_label.add(norm)
            counts[component] += count

    return counts


def build_specific_outcome_name(labels: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    total = sum(label_count(row) for row in labels) or 1
    counts = extract_specific_component_weights(labels)

    if not counts:
        return None, None

    selected: list[str] = []

    # Keep strong components.
    for component, weight in counts.items():
        if weight / total >= 0.25:
            selected.append(component)

    # Always keep the strongest 2-3 components, otherwise tiny clusters lose meaning.
    strongest = [
        component
        for component, weight in sorted(
            counts.items(),
            key=lambda kv: (-kv[1], outcome_component_priority(kv[0])),
        )[:3]
    ]

    for component in strongest:
        if component not in selected:
            selected.append(component)

    selected = sorted(set(selected), key=outcome_component_priority)

    # Avoid too many generic customer prefixes.
    selected = [
        component
        for component in selected
        if component not in {"Customer", "Internal", "Agreement"}
    ]

    if not selected:
        return None, None

    full_name = " ".join(selected).strip()

    if is_acceptable_display_name(full_name):
        return (
            full_name,
            "Specific outcome_sub components selected from weighted cluster labels.",
        )

    # If too long, keep workflow + strongest differentiators.
    workflow = [
        component
        for component in selected
        if component in {
            "Information Sent",
            "Information Gathered",
            "Information Requested",
            "Follow Up Scheduled",
            "Callback Requested",
            "Callback Scheduled",
            "Email Confirmed",
        }
    ]

    differentiators = [
        component
        for component in selected
        if component not in workflow
    ]

    compact = workflow[:2] + differentiators[:2]

    compact_name = " ".join(compact).strip()

    if is_acceptable_display_name(compact_name):
        return (
            compact_name,
            "Specific outcome_sub compact name selected using workflow plus differentiator components.",
        )

    return (
        shorten_display_name(compact_name),
        "Specific outcome_sub name shortened to max display-name length.",
    )
# ---------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------

def qident(schema: str, table: str) -> str:
    return f'"{schema}"."{table}"'


def getenv_first(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def connect_db(env_file: str | None):
    if env_file:
        load_dotenv(env_file)
    else:
        load_dotenv()

    host = getenv_first("CLUSTER_DB_HOST", "LOCAL_PG_HOST")
    port = getenv_first("CLUSTER_DB_PORT", "LOCAL_PG_PORT", default="5432")
    db = getenv_first("CLUSTER_DB_NAME", "CLUSTER_DB_DB", "LOCAL_PG_DB")
    user = getenv_first("CLUSTER_DB_USER", "LOCAL_PG_USER")
    password = getenv_first("CLUSTER_DB_PASSWORD", "CLUSTER_DB_PASS", "LOCAL_PG_PASSWORD")

    missing = [
        name
        for name, value in {
            "host": host,
            "port": port,
            "database": db,
            "user": user,
            "password": password,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing DB connection values. Expected CLUSTER_DB_* or LOCAL_PG_* in .env. "
            f"Missing: {missing}"
        )

    return psycopg2.connect(
        host=host,
        port=int(port),
        dbname=db,
        user=user,
        password=password,
    )


def ensure_names_table(conn, schema: str) -> None:
    table = qident(schema, "taxonomy_cluster_names")
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id BIGSERIAL PRIMARY KEY,
                field_name TEXT NOT NULL,
                run_id TEXT NOT NULL,
                cluster_version TEXT NOT NULL,
                cluster_id TEXT NOT NULL,
                is_anomaly BOOLEAN DEFAULT FALSE,
                display_name TEXT,
                naming_method TEXT,
                naming_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_taxonomy_cluster_names_unique
            ON {table} (field_name, run_id, cluster_version, cluster_id);
            """
        )
    conn.commit()


def load_small_tiny_clusters(
    conn,
    schema: str,
    run_id: str | None,
    min_labels: int,
    max_labels: int,
) -> dict[tuple[str, str, str, str], list[dict[str, Any]]]:
    label_map = qident(schema, "taxonomy_label_cluster_map")
    params: list[Any] = [FIELD_NAME, min_labels, max_labels]
    run_filter = ""
    if run_id:
        run_filter = "AND m.run_id = %s"
        params.append(run_id)

    sql = f"""
        WITH cluster_sizes AS (
            SELECT
                field_name,
                run_id,
                cluster_version,
                final_cluster_id,
                COUNT(DISTINCT raw_label) AS raw_label_count,
                SUM(value_count) AS total_occurrences,
                BOOL_OR(COALESCE(final_is_true_anomaly, false)) AS is_anomaly
            FROM {label_map}
            WHERE field_name = %s
              AND raw_label IS NOT NULL
              AND TRIM(raw_label) <> ''
              AND LOWER(TRIM(raw_label)) NOT IN ('nan', 'none', 'null')
            GROUP BY field_name, run_id, cluster_version, final_cluster_id
        )
        SELECT
            m.field_name,
            m.run_id,
            m.cluster_version,
            m.final_cluster_id,
            s.raw_label_count,
            s.total_occurrences,
            m.raw_label,
            m.normalized_label,
            COALESCE(m.value_count, 1) AS value_count
        FROM {label_map} m
        INNER JOIN cluster_sizes s
            ON s.field_name = m.field_name
           AND s.run_id = m.run_id
           AND s.cluster_version = m.cluster_version
           AND s.final_cluster_id = m.final_cluster_id
        WHERE s.is_anomaly = false
          AND s.raw_label_count BETWEEN %s AND %s
          {run_filter}
        ORDER BY s.total_occurrences DESC, m.final_cluster_id, m.value_count DESC;
    """

    clusters: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        for row in cur.fetchall():
            key = (
                row["field_name"],
                row["run_id"],
                row["cluster_version"],
                str(row["final_cluster_id"]),
            )
            clusters[key].append(dict(row))
    return clusters


# ---------------------------------------------------------------------
# Deterministic naming helpers
# ---------------------------------------------------------------------

def split_camel(text: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(text or ""))


def normalize_for_name(text: str) -> str:
    text = split_camel(str(text or ""))
    text = text.lower()
    text = re.sub(r"[{}\[\]_\n\t\-\./,;:|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def apply_logic_synonyms(text: str) -> str:
    out = normalize_for_name(text)
    for src in sorted(SYNONYM_MAP, key=len, reverse=True):
        src_norm = normalize_for_name(src)
        dst_norm = normalize_for_name(SYNONYM_MAP[src])
        out = re.sub(rf"\b{re.escape(src_norm)}\b", dst_norm, out)
    return re.sub(r"\s+", " ", out).strip()


def proper_case_name(name: str) -> str:
    words = normalize_for_name(name).split()
    fixed: list[str] = []
    for word in words:
        fixed.append(ACRONYMS.get(word, word.capitalize()))
    return " ".join(fixed)


def clean_display_label(raw_label: str) -> str:
    # Display cleaning intentionally does NOT convert follow-up into chase.
    text = normalize_for_name(raw_label)
    display_aliases = {
    "deadlead": "dead lead",
    "managedoffice": "managed office",
    "noanswer": "no answer",
    "whats app": "whatsapp",
    "what s app": "whatsapp",

    "wrongnum": "wrong number",
    "wrongno": "wrong number",
    "wrongcontact": "wrong contact",
    "nocontact": "no contact",
    "noreply": "no reply",
    "notinterested": "not interested",

    "callbackreq": "callback requested",
    "callbackrequest": "callback requested",

    "changeoftenancy": "change of tenancy",
    "changeofownership": "change of ownership",
}
    for src, dst in sorted(display_aliases.items(), key=lambda kv: len(kv[0]), reverse=True):
        text = re.sub(rf"\b{re.escape(src)}\b", dst, text)
    return proper_case_name(text)

def clean_outcome_sub_component(raw_component: str) -> str:
    text = clean_display_label(raw_component)
    norm = normalize_for_name(text)

    if norm in OUTCOME_SUB_COMPONENT_ALIASES:
        return OUTCOME_SUB_COMPONENT_ALIASES[norm]

    return text


def canonical_outcome_sub_sequence(seq: list[str]) -> list[str]:
    priority_index = {
        normalize_for_name(term): idx
        for idx, term in enumerate(OUTCOME_SUB_COMPONENT_PRIORITY)
    }

    seen: set[str] = set()
    unique: list[str] = []

    for item in seq:
        norm = normalize_for_name(item)

        if not norm or norm in seen:
            continue

        seen.add(norm)
        unique.append(item)

    return sorted(
        unique,
        key=lambda item: (
            priority_index.get(normalize_for_name(item), 9999),
            normalize_for_name(item),
        ),
    )


def outcome_sub_sequence_display_name(seq: list[str]) -> str:
    ordered = canonical_outcome_sub_sequence(seq)

    full_name = " ".join(ordered).strip()

    if is_acceptable_display_name(full_name):
        return full_name

    compact_parts = []

    for item in ordered:
        norm = normalize_for_name(item)
        compact_parts.append(OUTCOME_SUB_COMPACT_ALIASES.get(norm, item))

    compact_name = " ".join(compact_parts).strip()

    if is_acceptable_display_name(compact_name):
        return compact_name

    return shorten_display_name(compact_name, MAX_DISPLAY_NAME_WORDS)


def best_outcome_sub_component_coverage_name(
    labels: list[dict[str, Any]],
    threshold: float = 0.35,
) -> tuple[str | None, str | None]:
    total = sum(label_count(row) for row in labels) or 1
    component_counts: Counter[str] = Counter()

    for row in labels:
        count = label_count(row)
        seq = extract_component_display_sequence(str(row.get("raw_label") or ""))

        seen_for_label: set[str] = set()

        for component in seq:
            norm = normalize_for_name(component)

            if not norm or norm in seen_for_label:
                continue

            seen_for_label.add(norm)
            component_counts[component] += count

    if not component_counts:
        return None, None

    selected = []

    for component, weight in component_counts.items():
        if weight / total >= threshold:
            selected.append(component)

    if not selected:
        return None, None

    display_name = outcome_sub_sequence_display_name(selected)

    if not display_name or not is_acceptable_display_name(display_name):
        return None, None

    selected_with_coverage = [
        f"{component}={component_counts[component]:,}/{total:,}"
        for component in canonical_outcome_sub_sequence(selected)
    ]

    return (
        display_name,
        "Component coverage selected; "
        + "; ".join(selected_with_coverage)
        + ".",
    )
def label_count(row: dict[str, Any]) -> int:
    try:
        return int(row.get("value_count") or 1)
    except Exception:
        return 1


def sorted_labels(labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(labels, key=label_count, reverse=True)


def weighted_display_name_counts(labels: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in labels:
        display = clean_display_label(str(row.get("raw_label") or ""))
        if display:
            counts[display] += label_count(row)
    return counts


def extract_component_display_sequence(raw_label: str) -> list[str]:
    raw = str(raw_label or "").strip()
    inner = raw[1:-1] if raw.startswith("{") and raw.endswith("}") else raw

    if "," in inner:
        parts = [p.strip() for p in inner.split(",") if p.strip()]
    else:
        parts = [inner]

    if FIELD_NAME == "outcome_sub":
        displays = [clean_outcome_sub_component(part) for part in parts]
        displays = [d for d in displays if d]
        return canonical_outcome_sub_sequence(displays)

    displays = [clean_display_label(part) for part in parts]
    return [d for d in displays if d]


def component_signature(seq: list[str]) -> tuple[str, ...]:
    return tuple(sorted(normalize_for_name(x) for x in seq if x))


def best_component_signature_name(labels: list[dict[str, Any]], threshold: float) -> tuple[str | None, str | None]:
    total = sum(label_count(row) for row in labels) or 1
    sig_counts: Counter[tuple[str, ...]] = Counter()
    sig_best_order: dict[tuple[str, ...], tuple[int, list[str]]] = {}

    for row in labels:
        count = label_count(row)
        seq = extract_component_display_sequence(str(row.get("raw_label") or ""))
        if not seq:
            continue
        sig = component_signature(seq)
        if not sig:
            continue
        sig_counts[sig] += count
        display = " ".join(seq)
        if sig not in sig_best_order or count > sig_best_order[sig][0]:
            sig_best_order[sig] = (count, seq)

    if not sig_counts:
        return None, None

    sig, weight = sig_counts.most_common(1)[0]
    if weight / total < threshold:
        return None, None

    best_seq = sig_best_order[sig][1]

    if FIELD_NAME == "outcome_sub":
        display_name = outcome_sub_sequence_display_name(best_seq)
    else:
        display_name = " ".join(best_seq)

    return display_name, f"Component signature covered {weight:,}/{total:,} occurrences. Highest-count component order was used."


def match_phrase_terms(text: str, terms: list[str]) -> set[str]:
    found: set[str] = set()
    norm_text = f" {apply_logic_synonyms(text)} "
    # Match longer phrases first; overlapping does not matter for small clusters because this is only a fallback route.
    for term in sorted(terms, key=lambda x: (-len(normalize_for_name(x).split()), terms.index(x))):
        term_norm = normalize_for_name(term)
        if not term_norm:
            continue
        if re.search(rf"\b{re.escape(term_norm)}\b", norm_text):
            found.add(term_norm)
    return found


def ranked_best_term(counts: Counter[str], priority: list[str]) -> tuple[str | None, int]:
    if not counts:
        return None, 0
    priority_norm = [normalize_for_name(x) for x in priority]
    priority_index = {term: i for i, term in enumerate(priority_norm)}
    best = sorted(
        counts.items(),
        key=lambda kv: (-kv[1], priority_index.get(kv[0], 9999), kv[0]),
    )[0]
    return best[0], int(best[1])


def entity_action_name(labels: list[dict[str, Any]], threshold: float) -> tuple[str | None, str | None]:
    total = sum(label_count(row) for row in labels) or 1
    entity_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()

    for row in labels:
        raw = str(row.get("raw_label") or "")
        count = label_count(row)
        for term in match_phrase_terms(raw, ENTITY_LIST):
            entity_counts[term] += count
        for term in match_phrase_terms(raw, ACTION_LIST):
            action_counts[term] += count

    entity, entity_weight = ranked_best_term(entity_counts, ENTITY_LIST)
    action, action_weight = ranked_best_term(action_counts, ACTION_LIST)

    if not entity or not action:
        return None, None

    if entity_weight / total < threshold or action_weight / total < threshold:
        return None, None

    # Avoid duplicated wording such as "Setup Setup".
    if normalize_for_name(entity) == normalize_for_name(action):
        return proper_case_name(entity), f"Entity/action both resolved to '{entity}' with strong weighted coverage."

    display_name = proper_case_name(f"{entity} {action}")
    reason = (
        f"Entity '{proper_case_name(entity)}' covered {entity_weight:,}/{total:,} occurrences and "
        f"action '{proper_case_name(action)}' covered {action_weight:,}/{total:,} occurrences."
    )
    return display_name, reason


def ngram_name(labels: list[dict[str, Any]], threshold: float) -> tuple[str | None, str | None]:
    total = sum(label_count(row) for row in labels) or 1
    ngram_counts: Counter[str] = Counter()

    for row in labels:
        count = label_count(row)
        text = apply_logic_synonyms(str(row.get("raw_label") or ""))
        tokens = [t for t in text.split() if t and t not in STOP_TOKENS_FOR_NGRAMS]
        seen_for_label: set[str] = set()
        for n in (4, 3, 2):
            if len(tokens) < n:
                continue
            for i in range(len(tokens) - n + 1):
                phrase = " ".join(tokens[i : i + n])
                seen_for_label.add(phrase)
        for phrase in seen_for_label:
            ngram_counts[phrase] += count

    if not ngram_counts:
        return None, None

    # Prefer higher share, then longer phrase, then lexical order.
    phrase, weight = sorted(
        ngram_counts.items(),
        key=lambda kv: (-kv[1], -len(kv[0].split()), kv[0]),
    )[0]

    if weight / total < threshold:
        return None, None

    return proper_case_name(phrase), f"Most frequent phrase covered {weight:,}/{total:,} occurrences."

def display_word_count(name: str) -> int:
    return len(normalize_for_name(name).split())


def is_acceptable_display_name(name: str) -> bool:
    if not name or not str(name).strip():
        return False
    return display_word_count(name) <= MAX_DISPLAY_NAME_WORDS


def shorten_display_name(name: str, max_words: int = MAX_DISPLAY_NAME_WORDS) -> str:
    words = proper_case_name(name).split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words])
def deterministic_name(labels: list[dict[str, Any]]) -> tuple[str, str, str]:
    if not labels:
        return "Unknown", "deterministic_empty_cluster", "No labels were available."

    labels_sorted = sorted_labels(labels)
    total = sum(label_count(row) for row in labels_sorted) or 1

    if FIELD_NAME == "outcome_sub":
        specific_name, specific_reason = build_specific_outcome_name(labels_sorted)
        if specific_name and is_acceptable_display_name(specific_name):
            return (
                specific_name,
                "deterministic_specific_components",
                specific_reason or "Specific outcome_sub components selected.",
            )

    display_counts = weighted_display_name_counts(labels_sorted)

    top_display = None
    top_weight = 0

    if display_counts:
        top_display, top_weight = display_counts.most_common(1)[0]

        if top_weight / total >= 0.65 and is_acceptable_display_name(top_display):
            return (
                top_display,
                "deterministic_weighted_mode",
                f"Highest-count cleaned label covered {top_weight:,}/{total:,} occurrences.",
            )

    sig_name, sig_reason = best_component_signature_name(labels_sorted, threshold=0.50)
    if sig_name and is_acceptable_display_name(sig_name):
        return (
            sig_name,
            "deterministic_component_signature",
            sig_reason or "Component signature selected.",
        )

    if FIELD_NAME == "outcome_sub":
        coverage_name, coverage_reason = best_outcome_sub_component_coverage_name(
            labels_sorted,
            threshold=0.35,
        )
        if coverage_name and is_acceptable_display_name(coverage_name):
            return (
                coverage_name,
                "deterministic_component_coverage",
                coverage_reason or "Component coverage selected.",
            )

    phrase_name, phrase_reason = ngram_name(labels_sorted, threshold=0.50)
    if phrase_name and is_acceptable_display_name(phrase_name):
        return (
            phrase_name,
            "deterministic_ngram",
            phrase_reason or "Frequent phrase selected.",
        )

    ea_name, ea_reason = entity_action_name(labels_sorted, threshold=0.50)
    if ea_name and is_acceptable_display_name(ea_name):
        return (
            ea_name,
            "deterministic_entity_action",
            ea_reason or "Entity/action selected.",
        )

    if top_display and top_weight / total >= 0.65:
        shortened = shorten_display_name(top_display)

        return (
            shortened,
            "deterministic_weighted_mode_shortened",
            (
                f"Highest-count cleaned label covered {top_weight:,}/{total:,} occurrences, "
                f"but the full name was longer than {MAX_DISPLAY_NAME_WORDS} words, so it was shortened."
            ),
        )

    best = labels_sorted[0]
    fallback = clean_display_label(str(best.get("raw_label") or ""))

    if not is_acceptable_display_name(fallback):
        fallback = shorten_display_name(fallback)

    return (
        fallback,
        "deterministic_top_label_fallback",
        "No dominant mode/component/entity-action/ngram pattern found. Highest-count raw label was used.",
    )

# ---------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------
def cluster_total_occurrences(labels: list[dict[str, Any]]) -> int:
    return sum(label_count(row) for row in labels)


def refine_duplicate_names(
    rows: list[tuple[tuple[str, str, str, str], str, str, str]],
    clusters: dict[tuple[str, str, str, str], list[dict[str, Any]]],
) -> list[tuple[tuple[str, str, str, str], str, str, str]]:
    grouped: dict[str, list[tuple[tuple[str, str, str, str], str, str, str]]] = defaultdict(list)

    for row in rows:
        key, display_name, method, reason = row
        grouped[display_name].append(row)

    refined_rows: list[tuple[tuple[str, str, str, str], str, str, str]] = []

    for display_name, group_rows in grouped.items():
        if len(group_rows) == 1:
            refined_rows.extend(group_rows)
            continue

        used_names: Counter[str] = Counter()

        # Sort largest first. The largest cluster keeps the clean parent name if appropriate.
        group_rows_sorted = sorted(
            group_rows,
            key=lambda row: cluster_total_occurrences(clusters.get(row[0], [])),
            reverse=True,
        )

        for idx, row in enumerate(group_rows_sorted):
            key, old_name, method, reason = row
            labels = clusters.get(key, [])

            specific_name, specific_reason = build_specific_outcome_name(labels)

            if specific_name and is_acceptable_display_name(specific_name):
                new_name = specific_name
            else:
                new_name = old_name

            # If duplicate still remains, add the strongest differentiator not already in the name.
            if used_names[new_name] > 0:
                counts = extract_specific_component_weights(labels)
                differentiators = [
                    component
                    for component, weight in sorted(
                        counts.items(),
                        key=lambda kv: (-kv[1], outcome_component_priority(kv[0])),
                    )
                    if normalize_for_name(component) not in normalize_for_name(new_name)
                ]

                for diff in differentiators:
                    candidate = f"{new_name} {diff}".strip()
                    if is_acceptable_display_name(candidate):
                        new_name = candidate
                        break

            # Final safety: if still duplicate, add cluster id only as last resort.
            if used_names[new_name] > 0:
                cluster_id = key[3]
                candidate = f"{new_name} {cluster_id.replace('_', ' ').title()}"

                if is_acceptable_display_name(candidate):
                    new_name = candidate
                else:
                    new_name = f"{shorten_display_name(new_name, 5)} {cluster_id}"

            used_names[new_name] += 1

            if new_name != old_name:
                refined_rows.append(
                    (
                        key,
                        new_name,
                        "deterministic_duplicate_refined",
                        (
                            "Duplicate display_name refined using cluster-specific weighted components. "
                            + (specific_reason or "")
                        ).strip(),
                    )
                )
            else:
                refined_rows.append(row)

    return refined_rows
def write_naming_output_file(
    output_path: str | Path,
    rows: list[tuple[tuple[str, str, str, str], str, str, str]],
    clusters: dict[tuple[str, str, str, str], list[dict[str, Any]]],
) -> None:
    """
    Writes generated cluster names to a CSV file.

    rows format:
        [
            (
                (field_name, run_id, cluster_version, cluster_id),
                display_name,
                naming_method,
                naming_reason
            )
        ]
    """

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "field_name",
        "run_id",
        "cluster_version",
        "cluster_id",
        "display_name",
        "naming_method",
        "naming_reason",
        "raw_label_count",
        "total_occurrences",
        "labels_json",
    ]

    with output_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for key, display_name, naming_method, naming_reason in rows:
            field_name, run_id, cluster_version, cluster_id = key
            labels = clusters.get(key, [])

            labels_sorted = sorted(
                labels,
                key=lambda r: int(r.get("value_count") or 1),
                reverse=True,
            )

            labels_payload = [
                {
                    "raw_label": str(row.get("raw_label") or ""),
                    "normalized_label": str(row.get("normalized_label") or ""),
                    "value_count": int(row.get("value_count") or 1),
                }
                for row in labels_sorted
            ]

            raw_label_count = len({
                str(row.get("raw_label") or "").strip()
                for row in labels
                if str(row.get("raw_label") or "").strip()
            })

            total_occurrences = sum(
                int(row.get("value_count") or 1)
                for row in labels
            )

            writer.writerow({
                "field_name": field_name,
                "run_id": run_id,
                "cluster_version": cluster_version,
                "cluster_id": cluster_id,
                "display_name": display_name,
                "naming_method": naming_method,
                "naming_reason": naming_reason,
                "raw_label_count": raw_label_count,
                "total_occurrences": total_occurrences,
                "labels_json": json.dumps(labels_payload, ensure_ascii=False),
            })

    print(f"Saved naming output file: {output_path}")
def existing_named_clusters(conn, schema: str, keys: list[tuple[str, str, str, str]]) -> set[tuple[str, str, str, str]]:
    if not keys:
        return set()
    table = qident(schema, "taxonomy_cluster_names")
    existing: set[tuple[str, str, str, str]] = set()
    with conn.cursor() as cur:
        for field_name, run_id, cluster_version, cluster_id in keys:
            cur.execute(
                f"""
                SELECT 1
                FROM {table}
                WHERE field_name = %s
                  AND run_id = %s
                  AND cluster_version = %s
                  AND cluster_id = %s
                LIMIT 1;
                """,
                (field_name, run_id, cluster_version, cluster_id),
            )
            if cur.fetchone():
                existing.add((field_name, run_id, cluster_version, cluster_id))
    return existing


def bulk_upsert_names(
    conn,
    schema: str,
    rows: list[tuple[tuple[str, str, str, str], str, str, str]],
    overwrite: bool,
) -> int:
    if not rows:
        return 0

    table = qident(schema, "taxonomy_cluster_names")

    values = []
    for key, display_name, method, reason in rows:
        field_name, run_id, cluster_version, cluster_id = key
        values.append((field_name, run_id, cluster_version, cluster_id, False, display_name, method, reason))

    if overwrite:
        sql = f"""
            INSERT INTO {table} (
                field_name,
                run_id,
                cluster_version,
                cluster_id,
                is_anomaly,
                display_name,
                naming_method,
                naming_reason,
                created_at,
                updated_at
            ) VALUES %s
            ON CONFLICT (field_name, run_id, cluster_version, cluster_id)
            DO UPDATE SET
                is_anomaly = EXCLUDED.is_anomaly,
                display_name = EXCLUDED.display_name,
                naming_method = EXCLUDED.naming_method,
                naming_reason = EXCLUDED.naming_reason,
                updated_at = CURRENT_TIMESTAMP;
        """
    else:
        sql = f"""
            INSERT INTO {table} (
                field_name,
                run_id,
                cluster_version,
                cluster_id,
                is_anomaly,
                display_name,
                naming_method,
                naming_reason,
                created_at,
                updated_at
            ) VALUES %s
            ON CONFLICT (field_name, run_id, cluster_version, cluster_id)
            DO NOTHING;
        """

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            sql,
            values,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            page_size=500,
        )

    conn.commit()
    return len(rows)


def format_cluster_labels_for_print(labels: list[dict[str, Any]]) -> str:
    lines = []
    for row in sorted_labels(labels):
        raw_label = str(row.get("raw_label") or "")
        normalized_label = str(row.get("normalized_label") or "")
        value_count = label_count(row)
        lines.append(f"    - raw={raw_label} | normalized={normalized_label} | count={value_count}")
    return "\n".join(lines)


def print_dry_run_detail(
    idx: int,
    total: int,
    key: tuple[str, str, str, str],
    labels: list[dict[str, Any]],
    display_name: str,
    method: str,
    reason: str,
) -> None:
    field_name, run_id, cluster_version, cluster_id = key
    print("\n" + "-" * 90)
    print(f"DRY RUN {idx:,}/{total:,}")
    print(f"field_name      : {field_name}")
    print(f"run_id          : {run_id}")
    print(f"cluster_version : {cluster_version}")
    print(f"cluster_id      : {cluster_id}")
    print("labels:")
    print(format_cluster_labels_for_print(labels))
    print(f"display_name    : {display_name}")
    print(f"naming_method   : {method}")
    print(f"naming_reason   : {reason}")
    print("-" * 90, flush=True)


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--schema", default="public")
    parser.add_argument("--run-id", default=None, help="Optional run_id filter. If omitted, all call_type_sub runs are processed.")
    parser.add_argument("--min-labels", type=int, default=2)
    parser.add_argument("--max-labels", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true", help="Overwrite names already present in taxonomy_cluster_names.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--commit-batch-size", type=int, default=500)

    # Compatibility args. They are ignored because this script is deterministic-only.
    parser.add_argument("--workers", type=int, default=1, help="Ignored. Kept for command compatibility.")
    parser.add_argument("--ollama-model", default=None, help="Ignored. No Ollama is used.")
    parser.add_argument("--ollama-url", default=None, help="Ignored. No Ollama is used.")
    parser.add_argument("--timeout", type=int, default=0, help="Ignored. No Ollama is used.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Ignored. No Ollama is used.")

    args = parser.parse_args()

    conn = connect_db(args.env_file)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_schema(), current_user;")
            print("Connected to:", cur.fetchone())

        ensure_names_table(conn, args.schema)
        clusters = load_small_tiny_clusters(conn, args.schema, args.run_id, args.min_labels, args.max_labels)
        keys = list(clusters.keys())

        if args.limit is not None:
            keys = keys[: args.limit]

        print(f"Loaded {len(keys):,} {FIELD_NAME} clusters for deterministic naming.")
        print(f"Label count range: {args.min_labels}..{args.max_labels}")
        print(f"Overwrite existing: {args.overwrite}")
        print(f"Dry run: {args.dry_run}")
        print("Ollama/LLM: disabled")

        if not args.overwrite:
            existing = existing_named_clusters(conn, args.schema, keys)
            keys = [key for key in keys if key not in existing]
            print(f"After skipping existing names: {len(keys):,} clusters remain.")

        processed = 0
        pending_rows: list[tuple[tuple[str, str, str, str], str, str, str]] = []
        all_output_rows: list[tuple[tuple[str, str, str, str], str, str, str]] = []
        method_counts: Counter[str] = Counter()

        for key in keys:
            display_name, method, reason = deterministic_name(clusters[key])
            processed += 1
            row_out = (key, display_name, method, reason)
            all_output_rows.append(row_out)

        all_output_rows = refine_duplicate_names(all_output_rows, clusters)

        method_counts = Counter(row[2] for row in all_output_rows)

        if args.dry_run:
            for idx, row_out in enumerate(all_output_rows, start=1):
                key, display_name, method, reason = row_out
                print_dry_run_detail(
                    idx,
                    len(all_output_rows),
                    key,
                    clusters[key],
                    display_name,
                    method,
                    reason,
                )
        else:
            for idx, row_out in enumerate(all_output_rows, start=1):
                pending_rows.append(row_out)

                if idx == 1 or idx % 100 == 0 or idx == len(all_output_rows):
                    key, display_name, method, reason = row_out
                    print(f"{idx:,}/{len(all_output_rows):,} {key[3]} -> {display_name}", flush=True)

                if len(pending_rows) >= args.commit_batch_size:
                    bulk_upsert_names(conn, args.schema, pending_rows, args.overwrite)
                    pending_rows.clear()

            if pending_rows:
                bulk_upsert_names(conn, args.schema, pending_rows, args.overwrite)
                pending_rows.clear()

        if not args.dry_run and pending_rows:
            bulk_upsert_names(conn, args.schema, pending_rows, args.overwrite)
            pending_rows.clear()
        output_run_id = args.run_id or "all"
        output_mode = "dry_run" if args.dry_run else "inserted"

        write_naming_output_file(
            output_path=f"taxonomy_cluster_output/outcome_sub_small_tiny_names_{output_run_id}_{output_mode}.csv",
            rows=all_output_rows,
            clusters=clusters,
)

        print("Done.")
        print(f"Processed: {processed:,}")
        print("Method counts:")
        for method, count in method_counts.most_common():
            print(f"  {method}: {count:,}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
