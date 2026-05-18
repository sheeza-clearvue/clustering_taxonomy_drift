# review_large_clusters_with_gpt.py
#
# GPT-assisted naming for unnamed LARGE / VERY_LARGE taxonomy clusters.
#
# What this script does:
# 1. Pulls unnamed clusters from taxonomy_clusters.
# 2. Sends batches to GPT for proposed display names.
# 3. Checks for:
#    - existing name conflicts
#    - duplicate names inside the batch
#    - duplicate names against prior proposed names
#    - blank names
#    - repeated adjacent words
#    - max word count
# 4. If a name conflicts, it retries ONLY the conflicted cluster until a unique name is found.
# 5. Writes a CSV review file.
# 6. Optionally applies only clean rows from a CSV via --apply-csv.
#
# It does NOT auto-apply during review mode.

import os
import re
import csv
import json
import time
import argparse
from collections import Counter, defaultdict
from datetime import datetime

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

SIZE_RANGES = {
    "small": (3, 6),
    "large": (21, 100),
    "very_large": (101, None),
}

RETRYABLE_VALIDATION_NOTES = {
    "existing_name_conflict",
    "duplicate_against_prior_proposed",
    "duplicate_inside_batch",
    "adjacent_repeated_words",
    "blank_name",
}


def env_first(*names, default=None):
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
    value = value.replace("_", " ")
    value = value.replace("-", " ")
    value = value.replace("/", " ")
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


def extract_json(text: str):
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON found in GPT response: {text[:500]}")

    return json.loads(text[start:end + 1])


def top_labels_preview(label_rows, limit=12):
    return " | ".join(
        f"{row['normalized_label']} ({row['value_count']})"
        for row in label_rows[:limit]
    )


def fetch_unnamed_clusters(field_name, run_id, cluster_version, size_name, limit):
    min_size, max_size = SIZE_RANGES[size_name]

    conn = get_conn()
    conn.autocommit = True

    with conn.cursor() as cur:
        cur.execute("SELECT current_database(), current_schema(), current_user;")
        print("DB connection:", cur.fetchone())

        size_filter = "c.cluster_size >= %s"
        params = [field_name, run_id, cluster_version, min_size]

        if max_size is not None:
            size_filter += " AND c.cluster_size <= %s"
            params.append(max_size)

        params.append(limit)

        cur.execute(
            f"""
            WITH target_clusters AS (
                SELECT
                    c.cluster_id,
                    c.cluster_size,
                    c.total_occurrences,
                    c.medoid_label,
                    c.representative_labels
                FROM taxonomy_clusters c
                LEFT JOIN taxonomy_cluster_names n
                    ON n.field_name = c.field_name
                   AND n.run_id = c.run_id
                   AND n.cluster_version = c.cluster_version
                   AND n.cluster_id = c.cluster_id
                   AND COALESCE(n.is_anomaly, false) = false
                WHERE c.field_name = %s
                  AND c.run_id = %s
                  AND c.cluster_version = %s
                  AND c.active = true
                  AND COALESCE(c.is_true_anomaly_cluster, false) = false
                  AND n.cluster_id IS NULL
                  AND {size_filter}
                ORDER BY
                    c.total_occurrences DESC,
                    c.cluster_size DESC,
                    c.cluster_id
                LIMIT %s
            )
            SELECT
                cluster_id,
                cluster_size,
                total_occurrences,
                medoid_label,
                representative_labels
            FROM target_clusters;
            """,
            params,
        )
        cluster_rows = cur.fetchall()

        cluster_ids = [row[0] for row in cluster_rows]

        if not cluster_ids:
            conn.close()
            return [], {}, set()

        cur.execute(
            """
            SELECT
                lm.final_cluster_id,
                lm.normalized_label,
                lm.raw_label,
                lm.value_count
            FROM taxonomy_label_cluster_map lm
            WHERE lm.field_name = %s
              AND lm.run_id = %s
              AND lm.cluster_version = %s
              AND COALESCE(lm.final_is_true_anomaly, false) = false
              AND lm.final_cluster_id = ANY(%s)
            ORDER BY
                lm.final_cluster_id,
                lm.value_count DESC,
                lm.normalized_label;
            """,
            (field_name, run_id, cluster_version, cluster_ids),
        )
        label_rows = cur.fetchall()

        cur.execute(
            """
            SELECT
                LOWER(TRIM(display_name)) AS display_name_key
            FROM taxonomy_cluster_names
            WHERE field_name = %s
              AND run_id = %s
              AND cluster_version = %s
              AND COALESCE(is_anomaly, false) = false
              AND NULLIF(TRIM(display_name), '') IS NOT NULL;
            """,
            (field_name, run_id, cluster_version),
        )
        existing_names = {normalize_key(row[0]) for row in cur.fetchall()}

    conn.close()

    labels_by_cluster = defaultdict(list)
    for cluster_id, normalized_label, raw_label, value_count in label_rows:
        labels_by_cluster[cluster_id].append({
            "normalized_label": normalized_label,
            "raw_label": raw_label,
            "value_count": int(value_count or 0),
        })

    clusters = []
    for cluster_id, cluster_size, total_occurrences, medoid_label, representative_labels in cluster_rows:
        clusters.append({
            "cluster_id": cluster_id,
            "cluster_size": int(cluster_size or 0),
            "total_occurrences": int(total_occurrences or 0),
            "medoid_label": medoid_label,
            "representative_labels": representative_labels,
            "top_labels": labels_by_cluster.get(cluster_id, [])[:15],
        })

    return clusters, labels_by_cluster, existing_names


def build_prompt(field_name, size_name, clusters, forbidden_names=None, rejected_names_by_cluster=None):
    forbidden_names = sorted(forbidden_names or [])
    rejected_names_by_cluster = rejected_names_by_cluster or {}

    compact_clusters = []
    for cluster in clusters:
        compact_clusters.append({
            "cluster_id": cluster["cluster_id"],
            "cluster_size": cluster["cluster_size"],
            "total_occurrences": cluster["total_occurrences"],
            "medoid_label": cluster["medoid_label"],
            "top_normalized_labels": [
                {
                    "label": label["normalized_label"],
                    "count": label["value_count"],
                }
                for label in cluster["top_labels"][:12]
            ],
            "rejected_names_for_this_cluster": rejected_names_by_cluster.get(cluster["cluster_id"], []),
        })

    forbidden_block = ""
    if forbidden_names:
        # Keep prompt bounded. Validation still checks full forbidden set in Python.
        forbidden_block = f"""
Forbidden names. Do not use these exact names:
{json.dumps(forbidden_names[:350], ensure_ascii=False, indent=2)}
""".strip()

    return f"""
You are naming taxonomy clusters for call classification.

Field:
{field_name}

Cluster size bucket:
{size_name.upper()}

Task:
For each cluster, propose one concise display name.

Rules:
- Return JSON only.
- Use max {MAX_NAME_WORDS} words per display name.
- Use Title Case.
- Preserve acronyms exactly: DM, LOA, IVR, TPS, CRM, VAT, MOP, KVA, MPAN, MHHS, CCL, DNC, CoT, 3CX.
- Do not hallucinate information not supported by labels.
- Do not include counts, IDs, punctuation, slashes, parentheses, or underscores in names.
- Avoid generic names such as Admin, Discovery, Account Management, Customer Query, Technical Support unless labels are truly that broad.
- Prefer the dominant weighted intent.
- If labels show multiple repeated components, choose the clearest combined category.
- Avoid duplicate names across clusters.
- Avoid names listed as forbidden.
- Avoid names listed as rejected for the same cluster.
- Avoid awkward repetition such as Admin Admin, Customer Customer, Risk Risk, Service Service.
- Do not add "Review" just to make names unique.
- If the cluster cannot be named safely, set action to manual_review.

Allowed action values:
name
manual_review

Required JSON shape:
{{
  "items": [
    {{
      "cluster_id": "base_123",
      "action": "name",
      "proposed_display_name": "Name Here",
      "reason": "Brief reason based only on labels"
    }}
  ]
}}

{forbidden_block}

Clusters:
{json.dumps(compact_clusters, ensure_ascii=False, indent=2)}
""".strip()


def build_single_retry_prompt(field_name, size_name, cluster, forbidden_names, rejected_names, validation_notes):
    return build_prompt(
        field_name=field_name,
        size_name=size_name,
        clusters=[cluster],
        forbidden_names=forbidden_names,
        rejected_names_by_cluster={cluster["cluster_id"]: rejected_names + validation_notes},
    )


def call_gpt(client, model, prompt, retries=3):
    for attempt in range(1, retries + 1):
        try:
            response = client.responses.create(
                model=model,
                input=prompt,
            )
            return extract_json(response.output_text)

        except Exception as exc:
            if attempt == retries:
                raise
            wait_seconds = attempt * 3
            print(f"GPT call failed attempt {attempt}: {exc}")
            print(f"Retrying in {wait_seconds}s...")
            time.sleep(wait_seconds)


def get_validation_notes(proposed, action, existing_names, proposed_names, seen_this_batch):
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


def validate_items(clusters, gpt_items, existing_names, proposed_names):
    cluster_by_id = {cluster["cluster_id"]: cluster for cluster in clusters}
    output = []
    seen_this_batch = set()

    for item in gpt_items:
        cluster_id = item.get("cluster_id")
        if cluster_id not in cluster_by_id:
            continue

        cluster = cluster_by_id[cluster_id]
        action = normalize_key(item.get("action", "manual_review"))

        if action not in {"name", "manual_review"}:
            action = "manual_review"

        proposed = clean_display_name(item.get("proposed_display_name", ""))
        reason = item.get("reason", "")

        notes = get_validation_notes(
            proposed=proposed,
            action=action,
            existing_names=existing_names,
            proposed_names=proposed_names,
            seen_this_batch=seen_this_batch,
        )

        proposed_key = normalize_key(proposed)
        is_clean = action == "name" and not notes

        if proposed_key:
            seen_this_batch.add(proposed_key)

        if is_clean:
            proposed_names.add(proposed_key)

        output.append({
            "cluster_id": cluster_id,
            "cluster_size": cluster["cluster_size"],
            "total_occurrences": cluster["total_occurrences"],
            "medoid_label": cluster["medoid_label"],
            "proposed_display_name": proposed,
            "action": "name" if is_clean else "manual_review",
            "confidence": "high" if is_clean else "manual_review",
            "validation_notes": ";".join(notes),
            "reason": reason,
            "top_normalized_labels": top_labels_preview(cluster["top_labels"]),
            "retry_count": 0,
        })

    returned_ids = {row["cluster_id"] for row in output}
    missing_ids = set(cluster_by_id) - returned_ids

    for cluster_id in sorted(missing_ids):
        cluster = cluster_by_id[cluster_id]
        output.append({
            "cluster_id": cluster_id,
            "cluster_size": cluster["cluster_size"],
            "total_occurrences": cluster["total_occurrences"],
            "medoid_label": cluster["medoid_label"],
            "proposed_display_name": "",
            "action": "manual_review",
            "confidence": "manual_review",
            "validation_notes": "missing_from_gpt_response",
            "reason": "GPT did not return this cluster.",
            "top_normalized_labels": top_labels_preview(cluster["top_labels"]),
            "retry_count": 0,
        })

    return output


def should_retry_row(row):
    if row["action"] != "manual_review":
        return False

    notes = {
        note.split(":")[0]
        for note in row.get("validation_notes", "").split(";")
        if note
    }

    if "missing_from_gpt_response" in notes:
        return False

    return bool(notes.intersection(RETRYABLE_VALIDATION_NOTES))


def repair_rows_until_unique(
    client,
    model,
    field_name,
    size_name,
    rows,
    clusters_by_id,
    existing_names,
    proposed_names,
    max_name_retries,
):
    final_rows = []
    repaired_count = 0
    unrepaired_count = 0

    for row in rows:
        if not should_retry_row(row):
            final_rows.append(row)
            continue

        cluster = clusters_by_id[row["cluster_id"]]
        rejected_names = []
        current_row = row

        for retry_index in range(1, max_name_retries + 1):
            old_name = current_row.get("proposed_display_name", "")
            if old_name:
                rejected_names.append(old_name)

            forbidden_names = set(existing_names) | set(proposed_names) | {normalize_key(x) for x in rejected_names}

            prompt = build_single_retry_prompt(
                field_name=field_name,
                size_name=size_name,
                cluster=cluster,
                forbidden_names=forbidden_names,
                rejected_names=rejected_names,
                validation_notes=current_row.get("validation_notes", "").split(";"),
            )

            print(
                f"  Repair retry {retry_index}/{max_name_retries} for {cluster['cluster_id']} "
                f"(previous='{old_name}', notes='{current_row.get('validation_notes', '')}')"
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

            item = retry_items[0]
            action = normalize_key(item.get("action", "manual_review"))
            if action not in {"name", "manual_review"}:
                action = "manual_review"

            proposed = clean_display_name(item.get("proposed_display_name", ""))
            notes = get_validation_notes(
                proposed=proposed,
                action=action,
                existing_names=existing_names,
                proposed_names=proposed_names,
                seen_this_batch=set(),
            )

            is_clean = action == "name" and not notes

            current_row = {
                "cluster_id": cluster["cluster_id"],
                "cluster_size": cluster["cluster_size"],
                "total_occurrences": cluster["total_occurrences"],
                "medoid_label": cluster["medoid_label"],
                "proposed_display_name": proposed,
                "action": "name" if is_clean else "manual_review",
                "confidence": "high" if is_clean else "manual_review",
                "validation_notes": ";".join(notes),
                "reason": item.get("reason", ""),
                "top_normalized_labels": top_labels_preview(cluster["top_labels"]),
                "retry_count": retry_index,
            }

            if is_clean:
                proposed_names.add(normalize_key(proposed))
                repaired_count += 1
                break

        if current_row["action"] != "name":
            unrepaired_count += 1

        final_rows.append(current_row)

    if repaired_count or unrepaired_count:
        print(f"Conflict repair summary: repaired={repaired_count}, still_manual={unrepaired_count}")

    return final_rows


def review_mode(args):
    model = os.getenv("OPENAI_MODEL")
    if not model:
        raise RuntimeError("OPENAI_MODEL missing from .env")

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY missing from .env")

    if args.size not in SIZE_RANGES:
        raise RuntimeError(f"Unsupported size: {args.size}. Use one of: {sorted(SIZE_RANGES)}")

    os.makedirs(args.output_dir, exist_ok=True)

    clusters, _, existing_names = fetch_unnamed_clusters(
        field_name=args.field,
        run_id=args.run_id,
        cluster_version=args.cluster_version,
        size_name=args.size,
        limit=args.limit,
    )

    print(f"Unnamed {args.size.upper()} clusters fetched: {len(clusters)}")

    if not clusters:
        print("Nothing to name.")
        return

    output_file = os.path.join(
        args.output_dir,
        f"{args.field}_{args.size}_gpt_name_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    )

    client = OpenAI()
    proposed_names = set()
    all_rows = []

    for batch_index, start in enumerate(range(0, len(clusters), args.batch_size), start=1):
        batch = clusters[start:start + args.batch_size]
        print(f"GPT naming batch {batch_index}: {len(batch)} clusters")

        prompt = build_prompt(
            field_name=args.field,
            size_name=args.size,
            clusters=batch,
            forbidden_names=existing_names | proposed_names,
        )

        result = call_gpt(client, model, prompt)
        items = result.get("items", [])

        batch_rows = validate_items(
            clusters=batch,
            gpt_items=items,
            existing_names=existing_names,
            proposed_names=proposed_names,
        )

        clusters_by_id = {cluster["cluster_id"]: cluster for cluster in batch}

        batch_rows = repair_rows_until_unique(
            client=client,
            model=model,
            field_name=args.field,
            size_name=args.size,
            rows=batch_rows,
            clusters_by_id=clusters_by_id,
            existing_names=existing_names,
            proposed_names=proposed_names,
            max_name_retries=args.max_name_retries,
        )

        for row in batch_rows:
            row["field_name"] = args.field
            row["run_id"] = args.run_id
            row["cluster_version"] = args.cluster_version
            row["size_bucket"] = args.size.upper()
            row["batch_index"] = batch_index

        all_rows.extend(batch_rows)

    fieldnames = [
        "field_name",
        "run_id",
        "cluster_version",
        "size_bucket",
        "batch_index",
        "cluster_id",
        "cluster_size",
        "total_occurrences",
        "medoid_label",
        "proposed_display_name",
        "action",
        "confidence",
        "validation_notes",
        "retry_count",
        "reason",
        "top_normalized_labels",
    ]

    with open(output_file, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nOutput written: {output_file}")
    print(f"Rows written: {len(all_rows)}")

    print("Action summary:")
    for key, value in Counter(row["action"] for row in all_rows).items():
        print(f"  {key}: {value}")

    print("Confidence summary:")
    for key, value in Counter(row["confidence"] for row in all_rows).items():
        print(f"  {key}: {value}")

    print("Retry summary:")
    retry_counter = Counter(int(row.get("retry_count", 0) or 0) for row in all_rows)
    for key, value in sorted(retry_counter.items()):
        print(f"  retry_count_{key}: {value}")

    print("Validation notes summary:")
    notes = Counter()
    for row in all_rows:
        for note in row["validation_notes"].split(";"):
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
    with open(csv_path, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row["action"] == "name" and row["confidence"] == "high" and not row["validation_notes"].strip():
                rows.append(row)

    print(f"CSV: {csv_path}")
    print(f"Safe rows to apply: {len(rows)}")

    if not rows:
        print("Nothing to apply.")
        return

    proposed_keys = [normalize_key(row["proposed_display_name"]) for row in rows]
    dupes = [name for name, count in Counter(proposed_keys).items() if count > 1]
    if dupes:
        raise RuntimeError(f"CSV contains duplicate proposed names: {dupes[:20]}")

    field_name = rows[0]["field_name"]
    run_id = rows[0]["run_id"]
    cluster_version = rows[0]["cluster_version"]

    conn = get_conn()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database(), current_schema(), current_user;")
                print("DB connection:", cur.fetchone())

                cur.execute(
                    """
                    SELECT LOWER(TRIM(display_name))
                    FROM taxonomy_cluster_names
                    WHERE field_name = %s
                      AND run_id = %s
                      AND cluster_version = %s
                      AND COALESCE(is_anomaly, false) = false
                      AND NULLIF(TRIM(display_name), '') IS NOT NULL;
                    """,
                    (field_name, run_id, cluster_version),
                )
                existing_names = {normalize_key(row[0]) for row in cur.fetchall()}

                conflicts = [
                    row["proposed_display_name"]
                    for row in rows
                    if normalize_key(row["proposed_display_name"]) in existing_names
                ]

                if conflicts:
                    raise RuntimeError(f"Existing-name conflicts found before apply: {conflicts[:20]}")

                inserted = 0

                for row in rows:
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
                        SELECT
                            %s,
                            %s,
                            %s,
                            %s,
                            false,
                            %s,
                            'gpt_large_cluster_naming',
                            %s,
                            CURRENT_TIMESTAMP,
                            CURRENT_TIMESTAMP
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM taxonomy_cluster_names n
                            WHERE n.field_name = %s
                              AND n.run_id = %s
                              AND n.cluster_version = %s
                              AND n.cluster_id = %s
                              AND COALESCE(n.is_anomaly, false) = false
                        );
                        """,
                        (
                            field_name,
                            run_id,
                            cluster_version,
                            row["cluster_id"],
                            row["proposed_display_name"],
                            "GPT-assisted LARGE cluster naming based on top normalized labels. Applied only high-confidence rows with no duplicate or existing-name conflicts.",
                            field_name,
                            run_id,
                            cluster_version,
                            row["cluster_id"],
                        ),
                    )

                    if cur.rowcount != 1:
                        raise RuntimeError(
                            f"Expected insert 1 row but inserted {cur.rowcount}: "
                            f"{row['cluster_id']} -> {row['proposed_display_name']}"
                        )

                    inserted += 1

        print(f"Committed successfully. Inserted rows: {inserted}")

    except Exception:
        conn.rollback()
        print("Rolled back due to error.")
        raise

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--field", help="Field name, e.g. additional_tags")
    parser.add_argument("--run-id", help="Run ID")
    parser.add_argument("--cluster-version", help="Cluster version")
    parser.add_argument("--size", default="large", choices=sorted(SIZE_RANGES.keys()))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--max-name-retries", type=int, default=5)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)

    parser.add_argument("--apply-csv", help="Apply safe rows from a GPT review CSV")

    args = parser.parse_args()

    if args.apply_csv:
        apply_mode(args)
        return

    missing = [
        name for name, value in {
            "--field": args.field,
            "--run-id": args.run_id,
            "--cluster-version": args.cluster_version,
        }.items()
        if not value
    ]

    if missing:
        raise RuntimeError(f"Missing required args for review mode: {', '.join(missing)}")

    review_mode(args)


if __name__ == "__main__":
    main()
