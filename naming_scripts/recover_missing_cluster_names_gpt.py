#!/usr/bin/env python3
"""
recover_missing_cluster_names_gpt.py

CSV-driven GPT naming recovery for active taxonomy clusters that are missing rows in
`taxonomy_cluster_names`, using the exported label-map recovery CSV.

Typical flow:

1) Review/generate names only:
   python recover_missing_cluster_names_gpt.py \
     --input-csv outputs/missing_active_clusters_recovery.csv \
     --output-dir outputs \
     --batch-size 20 \
     --max-name-retries 5

2) Inspect the generated CSV.

3) Apply only safe rows:
   python recover_missing_cluster_names_gpt.py \
     --apply-csv outputs/missing_cluster_names_gpt_review_YYYYMMDD_HHMMSS.csv

Required env vars:
- OPENAI_API_KEY
- OPENAI_MODEL
- LOCAL_DATABASE_URL or DATABASE_URL, or LOCAL_PG_* / PG* connection vars
"""

import argparse
import csv
import json
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Set, Tuple

import psycopg2
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DEFAULT_OUTPUT_DIR = "outputs"
MAX_NAME_WORDS = 6

ACRONYMS = {
    "dm": "DM",
    "loa": "LOA",
    "ivr": "IVR",
    "iv": "IV",
    "vat": "VAT",
    "tps": "TPS",
    "crm": "CRM",
    "kva": "KVA",
    "mop": "MOP",
    "mpan": "MPAN",
    "mhhs": "MHHS",
    "ccl": "CCL",
    "ems": "EMS",
    "dnc": "DNC",
    "ngp": "NGP",
    "cot": "CoT",
    "co t": "CoT",
    "3cx": "3CX",
}

RETRYABLE_VALIDATION_NOTES = {
    "existing_name_conflict",
    "duplicate_against_prior_proposed",
    "duplicate_inside_batch",
    "adjacent_repeated_words",
    "blank_name",
}

REQUIRED_INPUT_COLUMNS = {
    "field_name",
    "run_id",
    "cluster_version",
    "cluster_id",
    "cluster_source",
    "cluster_size",
    "total_occurrences",
    "raw_labels",
    "normalized_labels",
    "mapped_occurrences",
}

REVIEW_FIELDNAMES = [
    "field_name",
    "run_id",
    "cluster_version",
    "cluster_id",
    "cluster_source",
    "cluster_size",
    "total_occurrences",
    "mapped_occurrences",
    "proposed_display_name",
    "action",
    "confidence",
    "validation_notes",
    "retry_count",
    "reason",
    "top_normalized_labels",
    "raw_labels",
    "normalized_labels",
]


def env_first(*names: str, default: Optional[str] = None) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return default


def get_conn():
    database_url = env_first("LOCAL_DATABASE_URL", "DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)

    return psycopg2.connect(
        host=env_first("LOCAL_PG_HOST", default="localhost"),
        port=env_first("LOCAL_PG_PORT", default="5432"),
        dbname=env_first("LOCAL_PG_DB", "LOCAL_PG_DATABASE", "PGDATABASE"),
        user=env_first("LOCAL_PG_USER", "PGUSER"),
        password=env_first("LOCAL_PG_PASSWORD", "PGPASSWORD"),
    )


def normalize_key(value: str) -> str:
    value = value or ""
    value = value.lower().strip()
    value = value.replace("_", " ").replace("-", " ").replace("/", " ")
    value = re.sub(r"[^a-z0-9\s]", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def clean_display_name(name: str) -> str:
    name = name or ""
    name = name.replace("_", " ").replace("-", " ").replace("/", " ")
    name = re.sub(r"[^A-Za-z0-9\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()

    words = []
    for word in name.split():
        key = normalize_key(word)
        if key in ACRONYMS:
            words.append(ACRONYMS[key])
        else:
            words.append(word.capitalize())

    cleaned = " ".join(words)

    for key, value in ACRONYMS.items():
        if " " in key:
            pattern = re.compile(r"\b" + re.escape(key.title()) + r"\b", re.IGNORECASE)
            cleaned = pattern.sub(value, cleaned)

    cleaned_words = cleaned.split()
    if len(cleaned_words) > MAX_NAME_WORDS:
        cleaned = " ".join(cleaned_words[:MAX_NAME_WORDS])

    return cleaned.strip()


def extract_json(text: str) -> dict:
    text = (text or "").strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON found in GPT response: {text[:500]}")

    return json.loads(text[start : end + 1])


def parse_pg_text_array(value: str) -> List[str]:
    """Parse the specific Postgres ARRAY_AGG text format from the recovery CSV.

    Example: '{{a,b},{c}}' -> ['a,b', 'c']
    The labels themselves were stored like '{A,B}', so ARRAY_AGG produces nested braces.
    """
    value = (value or "").strip()
    if not value or value.lower() == "null":
        return []

    matches = re.findall(r"\{([^{}]*)\}", value)
    if matches:
        return [m.strip().strip('"') for m in matches if m.strip().strip('"')]

    # Fallback for a simple comma-separated value.
    value = value.strip("{}")
    return [part.strip().strip('"') for part in value.split(",") if part.strip().strip('"')]


def top_labels_preview(labels: List[str], limit: int = 12) -> str:
    return " | ".join(labels[:limit])


def read_input_csv(path: str) -> List[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        columns = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_INPUT_COLUMNS - columns)
        if missing:
            raise RuntimeError(f"Input CSV missing required columns: {missing}")

        for row in reader:
            normalized_labels = parse_pg_text_array(row.get("normalized_labels", ""))
            raw_labels = parse_pg_text_array(row.get("raw_labels", ""))
            if not normalized_labels and not raw_labels:
                raise RuntimeError(f"No labels available for cluster {row.get('cluster_id')}")

            rows.append(
                {
                    "field_name": row["field_name"],
                    "run_id": row["run_id"],
                    "cluster_version": row["cluster_version"],
                    "cluster_id": row["cluster_id"],
                    "cluster_source": row.get("cluster_source", ""),
                    "cluster_size": int(row.get("cluster_size") or 0),
                    "total_occurrences": int(float(row.get("total_occurrences") or 0)),
                    "mapped_occurrences": int(float(row.get("mapped_occurrences") or 0)),
                    "raw_labels": raw_labels,
                    "normalized_labels": normalized_labels,
                }
            )

    return rows


def load_existing_names(rows: List[dict]) -> Dict[Tuple[str, str, str], Set[str]]:
    keys = sorted({(r["field_name"], r["run_id"], r["cluster_version"]) for r in rows})
    existing: Dict[Tuple[str, str, str], Set[str]] = defaultdict(set)

    conn = get_conn()
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_schema(), current_user;")
            print("DB connection:", cur.fetchone())

            for field_name, run_id, cluster_version in keys:
                cur.execute(
                    """
                    SELECT display_name
                    FROM taxonomy_cluster_names
                    WHERE field_name = %s
                      AND run_id = %s
                      AND cluster_version = %s
                      AND COALESCE(is_anomaly, false) = false
                      AND NULLIF(TRIM(display_name), '') IS NOT NULL;
                    """,
                    (field_name, run_id, cluster_version),
                )
                existing[(field_name, run_id, cluster_version)] = {
                    normalize_key(row[0]) for row in cur.fetchall() if row[0]
                }
    finally:
        conn.close()

    return existing


def build_prompt(rows: List[dict], forbidden_names_by_key: Dict[Tuple[str, str, str], Set[str]], rejected_names_by_cluster=None) -> str:
    rejected_names_by_cluster = rejected_names_by_cluster or {}

    compact_clusters = []
    for row in rows:
        key = (row["field_name"], row["run_id"], row["cluster_version"])
        compact_clusters.append(
            {
                "field_name": row["field_name"],
                "cluster_id": row["cluster_id"],
                "cluster_size": row["cluster_size"],
                "total_occurrences": row["total_occurrences"],
                "mapped_occurrences": row["mapped_occurrences"],
                "top_normalized_labels": row["normalized_labels"][:12],
                "forbidden_names_for_this_field": sorted(forbidden_names_by_key.get(key, set()))[:250],
                "rejected_names_for_this_cluster": rejected_names_by_cluster.get(row["cluster_id"], []),
            }
        )

    return f"""
You are naming taxonomy clusters for call-classification data.

Task:
For each cluster, propose one concise display name using only the provided labels.

Rules:
- Return JSON only.
- Use max {MAX_NAME_WORDS} words per display name.
- Use Title Case.
- Preserve acronyms exactly: DM, LOA, IVR, IV, TPS, CRM, VAT, MOP, KVA, MPAN, MHHS, CCL, DNC, CoT, 3CX.
- Do not hallucinate information not supported by labels.
- Do not include counts, IDs, punctuation, slashes, parentheses, underscores, or braces in names.
- Avoid generic names such as Admin, Discovery, Account Management, Customer Query, Technical Support unless the labels are truly that broad.
- Prefer the dominant repeated intent across labels.
- If labels show the same components in different orders, choose the clearest combined category.
- Avoid duplicate names within the same field.
- Avoid names listed as forbidden for that field.
- Avoid names listed as rejected for the same cluster.
- Avoid awkward repetition such as Admin Admin, Customer Customer, Risk Risk, Service Service.
- Do not add filler words such as Review, Other, General, Misc, or Category just to make names unique.
- If the cluster cannot be named safely, set action to manual_review.

Allowed action values:
name
manual_review

Required JSON shape:
{{
  "items": [
    {{
      "field_name": "call_type_sub",
      "cluster_id": "base_123",
      "action": "name",
      "proposed_display_name": "Name Here",
      "reason": "Brief reason based only on labels"
    }}
  ]
}}

Clusters:
{json.dumps(compact_clusters, ensure_ascii=False, indent=2)}
""".strip()


def call_gpt(client: OpenAI, model: str, prompt: str, retries: int = 3) -> dict:
    for attempt in range(1, retries + 1):
        try:
            response = client.responses.create(model=model, input=prompt)
            return extract_json(response.output_text)
        except Exception as exc:
            if attempt == retries:
                raise
            wait_seconds = attempt * 3
            print(f"GPT call failed attempt {attempt}: {exc}")
            print(f"Retrying in {wait_seconds}s...")
            time.sleep(wait_seconds)

    raise RuntimeError("Unreachable GPT retry state")


def get_validation_notes(
    proposed: str,
    action: str,
    existing_names: Set[str],
    proposed_names: Set[str],
    seen_this_batch: Set[str],
) -> List[str]:
    notes = []

    if not proposed:
        notes.append("blank_name")
        return notes

    proposed_key = normalize_key(proposed)

    if len(proposed.split()) > MAX_NAME_WORDS:
        notes.append("too_many_words")

    if proposed_key in existing_names:
        notes.append("existing_name_conflict")

    if proposed_key in proposed_names:
        notes.append("duplicate_against_prior_proposed")

    if proposed_key in seen_this_batch:
        notes.append("duplicate_inside_batch")

    words = proposed.split()
    for i in range(1, len(words)):
        if words[i].lower() == words[i - 1].lower():
            notes.append("adjacent_repeated_words")
            break

    if action == "manual_review":
        notes.append("gpt_marked_manual_review")

    return notes


def validate_items(
    clusters: List[dict],
    gpt_items: List[dict],
    existing_names_by_key: Dict[Tuple[str, str, str], Set[str]],
    proposed_names_by_key: Dict[Tuple[str, str, str], Set[str]],
) -> List[dict]:
    cluster_by_pair = {(row["field_name"], row["cluster_id"]): row for row in clusters}
    output = []
    seen_this_batch_by_key: Dict[Tuple[str, str, str], Set[str]] = defaultdict(set)

    for item in gpt_items:
        pair = (item.get("field_name"), item.get("cluster_id"))
        if pair not in cluster_by_pair:
            continue

        cluster = cluster_by_pair[pair]
        key = (cluster["field_name"], cluster["run_id"], cluster["cluster_version"])
        action = normalize_key(item.get("action", "manual_review"))
        if action not in {"name", "manual_review"}:
            action = "manual_review"

        proposed = clean_display_name(item.get("proposed_display_name", ""))
        notes = get_validation_notes(
            proposed=proposed,
            action=action,
            existing_names=existing_names_by_key.get(key, set()),
            proposed_names=proposed_names_by_key.get(key, set()),
            seen_this_batch=seen_this_batch_by_key[key],
        )

        proposed_key = normalize_key(proposed)
        is_clean = action == "name" and not notes

        if proposed_key:
            seen_this_batch_by_key[key].add(proposed_key)

        if is_clean:
            proposed_names_by_key[key].add(proposed_key)

        output.append(
            {
                **cluster,
                "proposed_display_name": proposed,
                "action": "name" if is_clean else "manual_review",
                "confidence": "high" if is_clean else "manual_review",
                "validation_notes": ";".join(notes),
                "retry_count": 0,
                "reason": item.get("reason", ""),
                "top_normalized_labels": top_labels_preview(cluster["normalized_labels"]),
            }
        )

    returned_pairs = {(row["field_name"], row["cluster_id"]) for row in output}
    for cluster in clusters:
        pair = (cluster["field_name"], cluster["cluster_id"])
        if pair in returned_pairs:
            continue
        output.append(
            {
                **cluster,
                "proposed_display_name": "",
                "action": "manual_review",
                "confidence": "manual_review",
                "validation_notes": "missing_from_gpt_response",
                "retry_count": 0,
                "reason": "GPT did not return this cluster.",
                "top_normalized_labels": top_labels_preview(cluster["normalized_labels"]),
            }
        )

    return output


def should_retry_row(row: dict) -> bool:
    if row["action"] != "manual_review":
        return False
    notes = {note.split(":")[0] for note in row.get("validation_notes", "").split(";") if note}
    if "missing_from_gpt_response" in notes:
        return False
    return bool(notes.intersection(RETRYABLE_VALIDATION_NOTES))


def repair_rows_until_unique(
    client: OpenAI,
    model: str,
    rows: List[dict],
    existing_names_by_key: Dict[Tuple[str, str, str], Set[str]],
    proposed_names_by_key: Dict[Tuple[str, str, str], Set[str]],
    max_name_retries: int,
) -> List[dict]:
    final_rows = []
    repaired_count = 0
    unrepaired_count = 0

    for row in rows:
        if not should_retry_row(row):
            final_rows.append(row)
            continue

        current_row = row
        rejected_names = []

        for retry_index in range(1, max_name_retries + 1):
            old_name = current_row.get("proposed_display_name", "")
            if old_name:
                rejected_names.append(old_name)

            key = (row["field_name"], row["run_id"], row["cluster_version"])
            forbidden = set(existing_names_by_key.get(key, set())) | set(proposed_names_by_key.get(key, set()))
            forbidden |= {normalize_key(name) for name in rejected_names}

            prompt = build_prompt(
                [row],
                forbidden_names_by_key={key: forbidden},
                rejected_names_by_cluster={row["cluster_id"]: rejected_names + current_row.get("validation_notes", "").split(";")},
            )

            print(
                f"  Repair retry {retry_index}/{max_name_retries} for "
                f"{row['field_name']} {row['cluster_id']} previous='{old_name}' "
                f"notes='{current_row.get('validation_notes', '')}'"
            )

            try:
                retry_json = call_gpt(client, model, prompt)
                retry_items = retry_json.get("items", [])
            except Exception as exc:
                current_row["validation_notes"] = f"{current_row.get('validation_notes', '')};retry_gpt_error:{exc}"
                break

            if not retry_items:
                current_row["validation_notes"] = f"{current_row.get('validation_notes', '')};retry_empty_response"
                break

            retry_rows = validate_items(
                clusters=[row],
                gpt_items=retry_items,
                existing_names_by_key=existing_names_by_key,
                proposed_names_by_key=proposed_names_by_key,
            )
            current_row = retry_rows[0]
            current_row["retry_count"] = retry_index

            if current_row["action"] == "name":
                repaired_count += 1
                break

        if current_row["action"] != "name":
            unrepaired_count += 1

        final_rows.append(current_row)

    if repaired_count or unrepaired_count:
        print(f"Conflict repair summary: repaired={repaired_count}, still_manual={unrepaired_count}")

    return final_rows


def serialize_review_row(row: dict) -> dict:
    out = {key: row.get(key, "") for key in REVIEW_FIELDNAMES}
    out["raw_labels"] = " | ".join(row.get("raw_labels") or [])
    out["normalized_labels"] = " | ".join(row.get("normalized_labels") or [])
    return out


def review_mode(args):
    model = os.getenv("OPENAI_MODEL")
    if not model:
        raise RuntimeError("OPENAI_MODEL missing from .env")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY missing from .env")

    os.makedirs(args.output_dir, exist_ok=True)

    clusters = read_input_csv(args.input_csv)
    if args.fields:
        wanted = {field.strip() for field in args.fields.split(",") if field.strip()}
        clusters = [row for row in clusters if row["field_name"] in wanted]

    clusters.sort(key=lambda r: (r["field_name"], -r["total_occurrences"], r["cluster_id"]))
    if args.limit:
        clusters = clusters[: args.limit]

    print(f"Clusters loaded for review: {len(clusters)}")
    if not clusters:
        print("Nothing to name.")
        return

    print("Field summary:")
    for field, count in Counter(row["field_name"] for row in clusters).items():
        print(f"  {field}: {count}")

    existing_names_by_key = load_existing_names(clusters)
    proposed_names_by_key: Dict[Tuple[str, str, str], Set[str]] = defaultdict(set)

    client = OpenAI()
    all_rows = []

    for batch_index, start in enumerate(range(0, len(clusters), args.batch_size), start=1):
        batch = clusters[start : start + args.batch_size]
        print(f"GPT naming batch {batch_index}: {len(batch)} clusters")

        prompt = build_prompt(
            batch,
            forbidden_names_by_key={
                key: existing_names_by_key.get(key, set()) | proposed_names_by_key.get(key, set())
                for key in existing_names_by_key.keys() | proposed_names_by_key.keys()
            },
        )

        result = call_gpt(client, model, prompt)
        items = result.get("items", [])

        batch_rows = validate_items(
            clusters=batch,
            gpt_items=items,
            existing_names_by_key=existing_names_by_key,
            proposed_names_by_key=proposed_names_by_key,
        )

        batch_rows = repair_rows_until_unique(
            client=client,
            model=model,
            rows=batch_rows,
            existing_names_by_key=existing_names_by_key,
            proposed_names_by_key=proposed_names_by_key,
            max_name_retries=args.max_name_retries,
        )

        for row in batch_rows:
            row["batch_index"] = batch_index

        all_rows.extend(batch_rows)

    output_file = os.path.join(
        args.output_dir,
        f"missing_cluster_names_gpt_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    )

    with open(output_file, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=REVIEW_FIELDNAMES)
        writer.writeheader()
        for row in all_rows:
            writer.writerow(serialize_review_row(row))

    print(f"\nOutput written: {output_file}")
    print(f"Rows written: {len(all_rows)}")

    print("Action summary:")
    for key, value in Counter(row["action"] for row in all_rows).items():
        print(f"  {key}: {value}")

    print("Validation notes summary:")
    notes = Counter()
    for row in all_rows:
        for note in row.get("validation_notes", "").split(";"):
            if note:
                notes[note.split(":")[0]] += 1
    if not notes:
        print("  none")
    else:
        for key, value in notes.items():
            print(f"  {key}: {value}")


def apply_mode(args):
    csv_path = args.apply_csv

    rows = []
    with open(csv_path, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for row in reader:
            if (
                row.get("action") == "name"
                and row.get("confidence") == "high"
                and not row.get("validation_notes", "").strip()
                and row.get("proposed_display_name", "").strip()
            ):
                rows.append(row)

    print(f"CSV: {csv_path}")
    print(f"Safe rows to apply: {len(rows)}")

    if not rows:
        print("Nothing to apply.")
        return

    keys_seen = set()
    name_keys_by_scope = defaultdict(list)
    for row in rows:
        row_key = (row["field_name"], row["run_id"], row["cluster_version"], row["cluster_id"])
        if row_key in keys_seen:
            raise RuntimeError(f"Duplicate cluster row in CSV: {row_key}")
        keys_seen.add(row_key)

        scope = (row["field_name"], row["run_id"], row["cluster_version"])
        name_keys_by_scope[scope].append(normalize_key(row["proposed_display_name"]))

    for scope, names in name_keys_by_scope.items():
        dupes = [name for name, count in Counter(names).items() if count > 1]
        if dupes:
            raise RuntimeError(f"CSV contains duplicate proposed names in {scope}: {dupes[:20]}")

    naming_method = args.naming_method
    naming_reason = args.naming_reason

    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database(), current_schema(), current_user;")
                print("DB connection:", cur.fetchone())

                for row in rows:
                    field_name = row["field_name"]
                    run_id = row["run_id"]
                    cluster_version = row["cluster_version"]
                    cluster_id = row["cluster_id"]
                    display_name = clean_display_name(row["proposed_display_name"])

                    cur.execute(
                        """
                        SELECT 1
                        FROM taxonomy_clusters c
                        WHERE c.field_name = %s
                          AND c.run_id = %s
                          AND c.cluster_version = %s
                          AND c.cluster_id = %s
                          AND COALESCE(c.active, true) = true
                          AND COALESCE(c.is_true_anomaly_cluster, false) = false;
                        """,
                        (field_name, run_id, cluster_version, cluster_id),
                    )
                    if cur.fetchone() is None:
                        raise RuntimeError(f"Active standard cluster not found: {field_name} {cluster_id}")

                    cur.execute(
                        """
                        SELECT 1
                        FROM taxonomy_cluster_names n
                        WHERE n.field_name = %s
                          AND n.run_id = %s
                          AND n.cluster_version = %s
                          AND n.cluster_id = %s
                          AND COALESCE(n.is_anomaly, false) = false;
                        """,
                        (field_name, run_id, cluster_version, cluster_id),
                    )
                    if cur.fetchone() is not None:
                        raise RuntimeError(f"Name row already exists for: {field_name} {cluster_id}")

                    cur.execute(
                        """
                        SELECT cluster_id, display_name
                        FROM taxonomy_cluster_names n
                        WHERE n.field_name = %s
                          AND n.run_id = %s
                          AND n.cluster_version = %s
                          AND COALESCE(n.is_anomaly, false) = false
                          AND NULLIF(TRIM(n.display_name), '') IS NOT NULL;
                        """,
                        (field_name, run_id, cluster_version),
                    )
                    existing_names = {normalize_key(r[1]): r[0] for r in cur.fetchall()}
                    display_key = normalize_key(display_name)
                    if display_key in existing_names:
                        raise RuntimeError(
                            f"Existing-name conflict in DB for {field_name} {cluster_id}: "
                            f"'{display_name}' already used by {existing_names[display_key]}"
                        )

                    cur.execute(
                        """
                        INSERT INTO taxonomy_cluster_names (
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
                        )
                        VALUES (%s, %s, %s, %s, false, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
                        """,
                        (
                            field_name,
                            run_id,
                            cluster_version,
                            cluster_id,
                            display_name,
                            naming_method,
                            naming_reason,
                        ),
                    )

        print(f"Committed successfully. Inserted rows: {len(rows)}")

    except Exception:
        conn.rollback()
        print("Rolled back due to error.")
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-csv", help="Recovery export CSV containing label-map rows for missing active clusters.")
    parser.add_argument("--fields", help="Optional comma-separated field filter, e.g. call_type_sub,outcome_sub")
    parser.add_argument("--limit", type=int, default=0, help="Optional max rows for testing. 0 means no limit.")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--max-name-retries", type=int, default=5)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)

    parser.add_argument("--apply-csv", help="Apply safe rows from a generated review CSV.")
    parser.add_argument("--naming-method", default="gpt_missing_active_cluster_recovery")
    parser.add_argument(
        "--naming-reason",
        default=(
            "GPT-assisted recovery naming for active clusters missing taxonomy_cluster_names rows, "
            "based on recovered taxonomy_label_cluster_map normalized labels."
        ),
    )

    args = parser.parse_args()

    if args.apply_csv:
        apply_mode(args)
        return

    if not args.input_csv:
        raise RuntimeError("Missing required arg: --input-csv")

    review_mode(args)


if __name__ == "__main__":
    main()
