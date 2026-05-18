#!/usr/bin/env python3
"""
name_call_type_small_tiny_deterministic.py

Names SMALL/TINY call_type clusters with deterministic rules only.
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


FIELD_NAME = "additional_tags"

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
    "mop": "MOP",
    "dc": "DC",
    "da": "DA",
    "dcda": "DCDA",
    "coo": "COO",
    "coc": "COC",
    "dd": "DD",
    "tcr": "TCR",
    "bics": "BICS",
    "nda": "NDA",
    "tpi": "TPI",
    "tps": "TPS",
    "hmrc": "HMRC",
    "mpas": "MPAS",
    "docusign": "DocuSign",
}

STOP_TOKENS_FOR_NGRAMS = {
    "required",
    "general",
}

MAX_DISPLAY_NAME_WORDS = 4
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
        ORDER BY s.raw_label_count ASC, s.total_occurrences DESC, m.final_cluster_id, m.value_count DESC;
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
    }
    for src, dst in sorted(display_aliases.items(), key=lambda kv: len(kv[0]), reverse=True):
        text = re.sub(rf"\b{re.escape(src)}\b", dst, text)
    return proper_case_name(text)


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

    displays = [clean_display_label(part) for part in parts]
    return [d for d in displays if d]


def component_signature(seq: list[str]) -> tuple[str, ...]:
    return tuple(sorted(normalize_for_name(x) for x in seq if x))


def best_component_signature_name(labels: list[dict[str, Any]], threshold: float) -> tuple[str | None, str | None]:
    total = sum(label_count(row) for row in labels) or 1
    sig_counts: Counter[tuple[str, ...]] = Counter()
    sig_best_order: dict[tuple[str, ...], tuple[int, str]] = {}

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
            sig_best_order[sig] = (count, display)

    if not sig_counts:
        return None, None

    sig, weight = sig_counts.most_common(1)[0]
    if weight / total < threshold:
        return None, None

    display_name = sig_best_order[sig][1]
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

    display_counts = weighted_display_name_counts(labels_sorted)

    top_display = None
    top_weight = 0

    if display_counts:
        top_display, top_weight = display_counts.most_common(1)[0]

        # Safe dominant-label route.
        # Only use this when one cleaned label clearly dominates.
        if top_weight / total >= 0.65 and is_acceptable_display_name(top_display):
            return (
                top_display,
                "deterministic_weighted_mode",
                f"Highest-count cleaned label covered {top_weight:,}/{total:,} occurrences.",
            )

    # Handles reversed compounds such as {A,B} and {B,A}.
    # This must run BEFORE ngram, otherwise ngram may drop useful secondary components.
    sig_name, sig_reason = best_component_signature_name(labels_sorted, threshold=0.50)
    if sig_name and is_acceptable_display_name(sig_name):
        return (
            sig_name,
            "deterministic_component_signature",
            sig_reason or "Component signature selected.",
        )

    # Phrase fallback after component signature.
    phrase_name, phrase_reason = ngram_name(labels_sorted, threshold=0.50)
    if phrase_name and is_acceptable_display_name(phrase_name):
        return (
            phrase_name,
            "deterministic_ngram",
            phrase_reason or "Frequent phrase selected.",
        )

    # Structured entity/action fallback.
    ea_name, ea_reason = entity_action_name(labels_sorted, threshold=0.50)
    if ea_name and is_acceptable_display_name(ea_name):
        return (
            ea_name,
            "deterministic_entity_action",
            ea_reason or "Entity/action selected.",
        )

    # If the highest-count label dominated but was too long, shorten it safely.
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
            method_counts[method] += 1
            row_out = (key, display_name, method, reason)
            pending_rows.append(row_out)
            all_output_rows.append(row_out)

            if args.dry_run:
                print_dry_run_detail(
                    processed,
                    len(keys),
                    key,
                    clusters[key],
                    display_name,
                    method,
                    reason,
                )
            elif processed == 1 or processed % 100 == 0 or processed == len(keys):
                print(f"{processed:,}/{len(keys):,} {key[3]} -> {display_name}", flush=True)

            if not args.dry_run and len(pending_rows) >= args.commit_batch_size:
                bulk_upsert_names(conn, args.schema, pending_rows, args.overwrite)
                pending_rows.clear()

        if not args.dry_run and pending_rows:
            bulk_upsert_names(conn, args.schema, pending_rows, args.overwrite)
            pending_rows.clear()
        output_run_id = args.run_id or "all"
        output_mode = "dry_run" if args.dry_run else "inserted"

        write_naming_output_file(
            output_path=f"taxonomy_cluster_output/additional_tags_medium_names_{output_run_id}_{output_mode}.csv",
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
