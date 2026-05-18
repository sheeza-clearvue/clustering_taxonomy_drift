#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

FIELD_NAME = "descriptive_keywords"
MAX_DISPLAY_NAME_WORDS = 6

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
    "bacs": "BACS",
    "rts": "RTS",
    "dd": "DD",
    "nda": "NDA",
    "tpi": "TPI",
    "hmrc": "HMRC",
    "ev": "EV",
    "kw": "kW",
    "kwh": "kWh",
    "cop": "COP",
    "mop": "MOP",
    "dc": "DC",
    "coc": "COC",
    "coo": "COO",
    "bic": "BIC",
    "bics": "BICS",
    "tcr": "TCR",
}

DISPLAY_ALIASES = {
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
    "changeoftenancy": "change of tenancy",
    "changeofownership": "change of ownership",
    "followup": "follow up",
    "callbackreq": "callback requested",
    "callbackrequest": "callback requested",
}

MAIN_REASON_SUB_COMPONENT_PRIORITY = [
    "prospecting",
    "cold call",
    "warm",
    "inbound",
    "admin",
    "service",
    "technical",
    "discovery",
    "negotiation",
    "account management",
    "contract",
    "contract review",
    "contract delay",
    "contract end date",
    "supplier",
    "supplier delay",
    "customer",
    "customer unreachable",
    "bill",
    "bill query",
    "bill request",
    "rates",
    "rates discussion",
    "loa",
    "loa request",
    "loa sent",
    "loa received",
    "cot",
    "change of tenancy",
    "change of ownership",
    "meter",
    "meter query",
    "meter reading",
    "mpan",
    "mprn",
    "callback",
    "callback scheduled",
    "follow up",
    "chase",
    "review",
    "query",
    "request",
    "update",
    "delay",
    "issue",
    "discussion",
    "renewal",
    "quote",
    "proposal",
    "sale",
    "closed",
    "not interested",
    "wrong number",
    "wrong contact",
    "voicemail",
    "no answer",
    "transfer",
    "failed",
]

MAIN_REASON_SUB_COMPONENT_ALIASES = {
    "cot": "CoT",
    "co t": "CoT",
    "change of tenancy": "CoT Tenancy",
    "change tenancy": "CoT Tenancy",
    "tenancy change": "CoT Tenancy",
    "change of ownership": "CoT Ownership",
    "ownership change": "CoT Ownership",
    "new ownership": "CoT Ownership",

    "followup": "Follow Up",
    "follow up": "Follow Up",
    "followup scheduled": "Follow Up Scheduled",
    "follow up scheduled": "Follow Up Scheduled",

    "callback": "Callback",
    "callback scheduled": "Callback Scheduled",
    "callback requested": "Callback Requested",

    "bill": "Bill",
    "billing": "Billing",
    "bill query": "Bill Query",
    "bill request": "Bill Request",
    "bill requested": "Bill Requested",

    "rates": "Rates",
    "rate": "Rates",
    "rates discussion": "Rates Discussion",
    "rate discussion": "Rates Discussion",

    "contract": "Contract",
    "contract review": "Contract Review",
    "contract delay": "Contract Delay",
    "contract end date": "Contract End Date",
    "contract end": "Contract End Date",
    "end date": "End Date",

    "supplier": "Supplier",
    "supplier delay": "Supplier Delay",
    "supplier issue": "Supplier Issue",
    "supplier query": "Supplier Query",

    "customer": "Customer",
    "customer unreachable": "Customer Unreachable",
    "customer unavailable": "Customer Unavailable",

    "loa": "LOA",
    "loa request": "LOA Request",
    "loa sent": "LOA Sent",
    "loa received": "LOA Received",
    "loa chase": "LOA Chase",

    "mpan": "MPAN",
    "mprn": "MPRN",
    "mpas": "MPAS",

    "meter": "Meter",
    "metering": "Metering",
    "meter query": "Meter Query",
    "meter reading": "Meter Reading",

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
    "voice mail": "Voicemail",

    "cold call": "Cold Call",
    "coldcall": "Cold Call",
    "warm market": "Warm Market",
    "market update": "Market Update",
    "market insight": "Market Insight",

    "discovery energy certificate": "Discovery Energy Certificate",
    "energy certificate": "Energy Certificate",
    "energy audit": "Energy Audit",

    "inbound transfer failed": "Inbound Transfer Failure",
    "inbound transfer failure": "Inbound Transfer Failure",
    "transfer failed": "Transfer Failure",
    "transfer failure": "Transfer Failure",
}

MAIN_REASON_SUB_COMPACT_ALIASES = {
    "contract review": "Contract Review",
    "supplier review": "Supplier Review",
    "rates discussion": "Rates",
    "bill query": "Bill Query",
    "bill request": "Bill Request",
    "contract end date": "Contract End Date",
    "customer unreachable": "Customer Unreachable",
    "supplier delay": "Supplier Delay",
    "contract delay": "Contract Delay",
    "change of tenancy": "CoT Tenancy",
    "change of ownership": "CoT Ownership",
    "follow up scheduled": "Follow Up",
    "callback scheduled": "Callback",
    "callback requested": "Callback Request",
    "information sent": "Info Sent",
    "not interested": "Not Interested",
    "wrong number": "Wrong Number",
    "wrong contact": "Wrong Contact",
}

STOP_TOKENS_FOR_NGRAMS = {
    "required",
    "general",
}


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
        name for name, value in {
            "host": host,
            "port": port,
            "database": db,
            "user": user,
            "password": password,
        }.items()
        if not value
    ]

    if missing:
        raise RuntimeError(f"Missing DB connection values: {missing}")

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


def split_camel(text: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(text or ""))


def normalize_for_name(text: str) -> str:
    text = split_camel(str(text or ""))
    text = text.lower()
    text = re.sub(r"[{}\[\]_\n\t\-\./,;:|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def proper_case_name(name: str) -> str:
    words = normalize_for_name(name).split()
    fixed: list[str] = []

    for word in words:
        fixed.append(ACRONYMS.get(word, word.capitalize()))

    return " ".join(fixed)


def clean_display_label(raw_label: str) -> str:
    text = normalize_for_name(raw_label)

    for src, dst in sorted(DISPLAY_ALIASES.items(), key=lambda kv: len(kv[0]), reverse=True):
        text = re.sub(rf"\b{re.escape(src)}\b", dst, text)

    return proper_case_name(text)


def clean_main_reason_sub_component(raw_component: str) -> str:
    text = clean_display_label(raw_component)
    norm = normalize_for_name(text)

    if norm in MAIN_REASON_SUB_COMPONENT_ALIASES:
        return MAIN_REASON_SUB_COMPONENT_ALIASES[norm]

    return text


def canonical_main_reason_sub_sequence(seq: list[str]) -> list[str]:
    priority_index = {
        normalize_for_name(term): idx
        for idx, term in enumerate(MAIN_REASON_SUB_COMPONENT_PRIORITY)
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


def main_reason_sub_sequence_display_name(seq: list[str]) -> str:
    ordered = canonical_main_reason_sub_sequence(seq)
    full_name = " ".join(ordered).strip()

    if is_acceptable_display_name(full_name):
        return full_name

    compact_parts = []

    for item in ordered:
        norm = normalize_for_name(item)
        compact_parts.append(MAIN_REASON_SUB_COMPACT_ALIASES.get(norm, item))

    compact_name = " ".join(compact_parts).strip()

    if is_acceptable_display_name(compact_name):
        return compact_name

    return shorten_display_name(compact_name, MAX_DISPLAY_NAME_WORDS)


def label_count(row: dict[str, Any]) -> int:
    try:
        return int(row.get("value_count") or 1)
    except Exception:
        return 1


def sorted_labels(labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(labels, key=label_count, reverse=True)


def extract_component_display_sequence(raw_label: str) -> list[str]:
    raw = str(raw_label or "").strip()
    inner = raw[1:-1] if raw.startswith("{") and raw.endswith("}") else raw

    if "," in inner:
        parts = [p.strip() for p in inner.split(",") if p.strip()]
    else:
        parts = [inner]

    displays = [clean_main_reason_sub_component(part) for part in parts]
    displays = [d for d in displays if d]

    return canonical_main_reason_sub_sequence(displays)


def component_signature(seq: list[str]) -> tuple[str, ...]:
    return tuple(sorted(normalize_for_name(x) for x in seq if x))


def weighted_display_name_counts(labels: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()

    for row in labels:
        display = clean_display_label(str(row.get("raw_label") or ""))

        if display:
            counts[display] += label_count(row)

    return counts


def best_component_signature_name(
    labels: list[dict[str, Any]],
    threshold: float,
) -> tuple[str | None, str | None]:
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

        if sig not in sig_best_order or count > sig_best_order[sig][0]:
            sig_best_order[sig] = (count, seq)

    if not sig_counts:
        return None, None

    sig, weight = sig_counts.most_common(1)[0]

    if weight / total < threshold:
        return None, None

    best_seq = sig_best_order[sig][1]
    display_name = main_reason_sub_sequence_display_name(best_seq)

    return (
        display_name,
        f"Component signature covered {weight:,}/{total:,} occurrences. Highest-count component order was used.",
    )


def best_component_coverage_name(
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

    display_name = main_reason_sub_sequence_display_name(selected)

    if not display_name or not is_acceptable_display_name(display_name):
        return None, None

    coverage_text = [
        f"{component}={component_counts[component]:,}/{total:,}"
        for component in canonical_main_reason_sub_sequence(selected)
    ]

    return (
        display_name,
        "Component coverage selected; " + "; ".join(coverage_text) + ".",
    )


def ngram_name(labels: list[dict[str, Any]], threshold: float) -> tuple[str | None, str | None]:
    total = sum(label_count(row) for row in labels) or 1
    ngram_counts: Counter[str] = Counter()

    for row in labels:
        count = label_count(row)
        text = normalize_for_name(str(row.get("raw_label") or ""))
        tokens = [t for t in text.split() if t and t not in STOP_TOKENS_FOR_NGRAMS]

        seen_for_label: set[str] = set()

        for n in (6, 5, 4, 3, 2):
            if len(tokens) < n:
                continue

            for i in range(len(tokens) - n + 1):
                phrase = " ".join(tokens[i : i + n])
                seen_for_label.add(phrase)

        for phrase in seen_for_label:
            ngram_counts[phrase] += count

    if not ngram_counts:
        return None, None

    phrase, weight = sorted(
        ngram_counts.items(),
        key=lambda kv: (-kv[1], -len(kv[0].split()), kv[0]),
    )[0]

    if weight / total < threshold:
        return None, None

    display = proper_case_name(phrase)

    if not is_acceptable_display_name(display):
        display = shorten_display_name(display)

    return display, f"Most frequent phrase covered {weight:,}/{total:,} occurrences."


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

    sig_name, sig_reason = best_component_signature_name(labels_sorted, threshold=0.50)

    if sig_name and is_acceptable_display_name(sig_name):
        return (
            sig_name,
            "deterministic_component_signature",
            sig_reason or "Component signature selected.",
        )

    coverage_name, coverage_reason = best_component_coverage_name(labels_sorted, threshold=0.35)

    if coverage_name and is_acceptable_display_name(coverage_name):
        return (
            coverage_name,
            "deterministic_component_coverage",
            coverage_reason or "Component coverage selected.",
        )

    display_counts = weighted_display_name_counts(labels_sorted)
    top_display = None
    top_weight = 0

    if display_counts:
        top_display, top_weight = display_counts.most_common(1)[0]

        if top_weight / total >= 0.75 and is_acceptable_display_name(top_display):
            return (
                top_display,
                "deterministic_weighted_mode",
                f"Highest-count cleaned label covered {top_weight:,}/{total:,} occurrences.",
            )

    phrase_name, phrase_reason = ngram_name(labels_sorted, threshold=0.50)

    if phrase_name and is_acceptable_display_name(phrase_name):
        return (
            phrase_name,
            "deterministic_ngram",
            phrase_reason or "Frequent phrase selected.",
        )

    if top_display and top_weight / total >= 0.60:
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
        "No strong component or phrase pattern found. Highest-count raw label was used.",
    )


def write_naming_output_file(
    output_path: str | Path,
    rows: list[tuple[tuple[str, str, str, str], str, str, str]],
    clusters: dict[tuple[str, str, str, str], list[dict[str, Any]]],
) -> None:
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


def existing_named_clusters(
    conn,
    schema: str,
    keys: list[tuple[str, str, str, str]],
) -> set[tuple[str, str, str, str]]:
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--schema", default="public")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--min-labels", type=int, default=2)
    parser.add_argument("--max-labels", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--commit-batch-size", type=int, default=500)

    args = parser.parse_args()

    conn = connect_db(args.env_file)

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_schema(), current_user;")
            print("Connected to:", cur.fetchone())

        ensure_names_table(conn, args.schema)

        clusters = load_small_tiny_clusters(
            conn,
            args.schema,
            args.run_id,
            args.min_labels,
            args.max_labels,
        )

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
            output_path=f"taxonomy_cluster_output/main_reason_sub_small_tiny_names_{output_run_id}_{output_mode}.csv",
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