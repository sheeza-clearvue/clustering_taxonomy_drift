#!/usr/bin/env python3
"""
rebuild_all_active_cluster_centroids.py

Rebuild centroid metadata for ALL active standard taxonomy clusters from the
current taxonomy_label_cluster_map and taxonomy_label_embeddings tables.

This does NOT recluster.
This does NOT change taxonomy_cluster_names.
This does NOT change taxonomy_label_cluster_map.

It updates only taxonomy_clusters:
- centroid_embedding
- medoid_label
- medoid_global_label_id
- medoid_similarity_to_centroid
- representative_labels
- updated_at

Why use this:
After manual merges, cleanup, workbook restores, stale-row deletion, or active cluster
changes, old centroid/medoid metadata may no longer represent the current final cluster
membership.

Default behavior:
- Targets every active non-anomaly cluster in taxonomy_clusters.
- Uses taxonomy_label_cluster_map rows where:
    lm.field_name = c.field_name
    lm.run_id = c.run_id
    lm.cluster_version = c.cluster_version
    lm.final_cluster_id = c.cluster_id
- Uses cached embeddings by:
    e.field_name = lm.field_name
    lower(trim(e.raw_label)) = lower(trim(lm.raw_label))
- Excludes null/blank/nan/null/none raw labels.
- Computes weighted centroid using value_count.
- Selects medoid as label whose embedding is closest to the weighted centroid.
- Stores representative_labels as top weighted raw labels JSON array.

Usage:

Dry run all fields:
    python rebuild_all_active_cluster_centroids.py --dry-run

Apply all fields:
    python rebuild_all_active_cluster_centroids.py --apply

Dry run one field:
    python rebuild_all_active_cluster_centroids.py --field additional_tags --dry-run

Apply one field:
    python rebuild_all_active_cluster_centroids.py --field additional_tags --apply

Optional filters:
    --run-id 20260513_093749
    --cluster-version 20260513_093749

Required env:
    LOCAL_DATABASE_URL or DATABASE_URL
    or LOCAL_PG_HOST / LOCAL_PG_PORT / LOCAL_PG_DB / LOCAL_PG_USER / LOCAL_PG_PASSWORD
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv


load_dotenv()

DEFAULT_OUTPUT_DIR = "outputs"
DEFAULT_REPRESENTATIVE_LIMIT = 12
INVALID_RAW_LABELS = {"", "nan", "none", "null"}


def env_first(*names: str, default: Optional[str] = None) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return default


def get_conn():
    database_url = env_first("LOCAL_DATABASE_URL", "DATABASE_URL", "LOCAL_PG_CONN_STR", "PG_CONN_STR")
    if database_url:
        return psycopg2.connect(database_url)

    return psycopg2.connect(
        host=env_first("LOCAL_PG_HOST", "CLUSTER_DB_HOST", default="localhost"),
        port=env_first("LOCAL_PG_PORT", "CLUSTER_DB_PORT", default="5432"),
        dbname=env_first("LOCAL_PG_DB", "LOCAL_PG_DATABASE", "CLUSTER_DB_NAME", "PGDATABASE", default="taxonomy_drift_local"),
        user=env_first("LOCAL_PG_USER", "CLUSTER_DB_USER", "PGUSER", default="postgres"),
        password=env_first("LOCAL_PG_PASSWORD", "CLUSTER_DB_PASS", "PGPASSWORD", default="postgres"),
    )


def parse_embedding(value: Any) -> Optional[np.ndarray]:
    """Parse embedding from PostgreSQL float[]/list/json-ish values."""
    if value is None:
        return None

    if isinstance(value, np.ndarray):
        arr = value.astype(np.float32)
    elif isinstance(value, list):
        arr = np.asarray(value, dtype=np.float32)
    elif isinstance(value, tuple):
        arr = np.asarray(list(value), dtype=np.float32)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            if text.startswith("["):
                arr = np.asarray(json.loads(text), dtype=np.float32)
            else:
                # PostgreSQL array string: {0.1,0.2,...}
                text = text.strip("{}")
                arr = np.asarray([float(x) for x in text.split(",") if x.strip()], dtype=np.float32)
        except Exception:
            return None
    else:
        try:
            arr = np.asarray(value, dtype=np.float32)
        except Exception:
            return None

    if arr.ndim != 1 or arr.size == 0:
        return None

    if not np.all(np.isfinite(arr)):
        return None

    return arr.astype(np.float32)


def normalize_vector(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    if norm <= 0.0 or not math.isfinite(norm):
        return vec.astype(np.float32)
    return (vec / norm).astype(np.float32)


def weighted_centroid(embeddings: np.ndarray, weights: np.ndarray) -> np.ndarray:
    weights = weights.astype(np.float32)
    weights = np.where(np.isfinite(weights) & (weights > 0), weights, 1.0).astype(np.float32)
    centroid = np.average(embeddings, axis=0, weights=weights)
    return normalize_vector(centroid.astype(np.float32))


def cosine_similarity_matrix_to_vector(embeddings: np.ndarray, vector: np.ndarray) -> np.ndarray:
    # Embeddings are expected to be normalized from cache, but normalize defensively.
    emb_norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    emb_norms = np.where(emb_norms == 0, 1.0, emb_norms)
    norm_embeddings = embeddings / emb_norms

    vector = normalize_vector(vector)
    return np.dot(norm_embeddings, vector)


def valid_raw_label(raw_label: Any) -> bool:
    if raw_label is None:
        return False
    text = str(raw_label).strip()
    return text.lower() not in INVALID_RAW_LABELS


def fetch_targets(conn, field: Optional[str], run_id: Optional[str], cluster_version: Optional[str]) -> List[dict]:
    where = [
        "COALESCE(c.active, true) = true",
        "COALESCE(c.is_true_anomaly_cluster, false) = false",
    ]
    params: List[Any] = []

    if field:
        where.append("c.field_name = %s")
        params.append(field)
    if run_id:
        where.append("c.run_id = %s")
        params.append(run_id)
    if cluster_version:
        where.append("c.cluster_version = %s")
        params.append(cluster_version)

    sql = f"""
        SELECT
            c.field_name,
            c.run_id,
            c.cluster_version,
            c.cluster_id,
            c.cluster_size,
            c.total_occurrences,
            c.cluster_source
        FROM taxonomy_clusters c
        WHERE {' AND '.join(where)}
        ORDER BY c.field_name, c.run_id, c.cluster_version, c.cluster_id;
    """

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def fetch_label_embedding_rows(conn, targets: List[dict]) -> Dict[Tuple[str, str, str, str], List[dict]]:
    """
    Fetch all label-map rows plus cached embeddings for the target clusters.

    Uses a temp table for target keys to avoid giant IN clauses.
    """
    grouped: Dict[Tuple[str, str, str, str], List[dict]] = defaultdict(list)

    if not targets:
        return grouped

    target_rows = [
        (
            t["field_name"],
            t["run_id"],
            t["cluster_version"],
            t["cluster_id"],
        )
        for t in targets
    ]

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            CREATE TEMP TABLE tmp_centroid_targets (
                field_name TEXT NOT NULL,
                run_id TEXT NOT NULL,
                cluster_version TEXT NOT NULL,
                cluster_id TEXT NOT NULL
            ) ON COMMIT DROP;
            """
        )

        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO tmp_centroid_targets (
                field_name,
                run_id,
                cluster_version,
                cluster_id
            ) VALUES %s;
            """,
            target_rows,
            page_size=5000,
        )

        cur.execute(
            """
            SELECT
                lm.field_name,
                lm.run_id,
                lm.cluster_version,
                lm.final_cluster_id AS cluster_id,
                lm.id AS label_map_id,
                lm.raw_label,
                lm.normalized_label,
                COALESCE(lm.value_count, 1) AS value_count,
                e.id AS embedding_id,
                e.embedding
            FROM tmp_centroid_targets t
            JOIN taxonomy_label_cluster_map lm
              ON lm.field_name = t.field_name
             AND lm.run_id = t.run_id
             AND lm.cluster_version = t.cluster_version
             AND lm.final_cluster_id = t.cluster_id
            LEFT JOIN taxonomy_label_embeddings e
              ON e.field_name = lm.field_name
             AND LOWER(TRIM(e.raw_label)) = LOWER(TRIM(lm.raw_label))
            WHERE lm.final_cluster_id IS NOT NULL
              AND lm.raw_label IS NOT NULL
              AND LOWER(TRIM(lm.raw_label)) NOT IN ('', 'nan', 'none', 'null')
              AND COALESCE(lm.final_is_true_anomaly, false) = false
            ORDER BY
                lm.field_name,
                lm.run_id,
                lm.cluster_version,
                lm.final_cluster_id,
                COALESCE(lm.value_count, 1) DESC,
                lm.raw_label;
            """
        )

        for row in cur.fetchall():
            key = (
                row["field_name"],
                row["run_id"],
                row["cluster_version"],
                row["cluster_id"],
            )
            grouped[key].append(dict(row))

    return grouped


def compute_update_for_cluster(
    target: dict,
    label_rows: List[dict],
    representative_limit: int,
) -> Tuple[Optional[dict], Optional[dict]]:
    """
    Returns (update, issue). Exactly one may be non-null.
    """
    key = (
        target["field_name"],
        target["run_id"],
        target["cluster_version"],
        target["cluster_id"],
    )

    usable = []
    missing_embedding_rows = 0
    embedding_dim_counts = defaultdict(int)

    for row in label_rows:
        if not valid_raw_label(row.get("raw_label")):
            continue

        emb = parse_embedding(row.get("embedding"))
        if emb is None:
            missing_embedding_rows += 1
            continue

        embedding_dim_counts[int(emb.size)] += 1

        try:
            weight = int(row.get("value_count") or 1)
        except Exception:
            weight = 1

        usable.append(
            {
                "raw_label": str(row["raw_label"]),
                "normalized_label": row.get("normalized_label"),
                "value_count": max(weight, 1),
                "label_map_id": row.get("label_map_id"),
                "embedding_id": row.get("embedding_id"),
                "embedding": emb,
            }
        )

    if not usable:
        return None, {
            "field_name": target["field_name"],
            "run_id": target["run_id"],
            "cluster_version": target["cluster_version"],
            "cluster_id": target["cluster_id"],
            "issue": "no_usable_embeddings",
            "label_rows": len(label_rows),
            "missing_embedding_rows": missing_embedding_rows,
        }

    dims = CounterLike([int(u["embedding"].size) for u in usable])
    dominant_dim, dominant_dim_count = dims.most_common(1)[0]

    usable_same_dim = [u for u in usable if int(u["embedding"].size) == dominant_dim]
    dropped_wrong_dim = len(usable) - len(usable_same_dim)

    if not usable_same_dim:
        return None, {
            "field_name": target["field_name"],
            "run_id": target["run_id"],
            "cluster_version": target["cluster_version"],
            "cluster_id": target["cluster_id"],
            "issue": "no_consistent_embedding_dimension",
            "label_rows": len(label_rows),
            "missing_embedding_rows": missing_embedding_rows,
        }

    embeddings = np.vstack([u["embedding"] for u in usable_same_dim]).astype(np.float32)
    weights = np.asarray([u["value_count"] for u in usable_same_dim], dtype=np.float32)

    centroid = weighted_centroid(embeddings, weights)
    sims = cosine_similarity_matrix_to_vector(embeddings, centroid)
    medoid_idx = int(np.argmax(sims))
    medoid = usable_same_dim[medoid_idx]

    # Top representative labels by value_count, then by similarity to centroid.
    rep_candidates = []
    for u, sim in zip(usable_same_dim, sims):
        rep_candidates.append(
            {
                "raw_label": u["raw_label"],
                "normalized_label": u.get("normalized_label"),
                "value_count": int(u["value_count"]),
                "similarity_to_centroid": float(sim),
            }
        )

    rep_candidates.sort(
        key=lambda r: (
            -int(r["value_count"]),
            -float(r["similarity_to_centroid"]),
            str(r["raw_label"]),
        )
    )

    representative_labels = rep_candidates[:representative_limit]

    update = {
        "field_name": target["field_name"],
        "run_id": target["run_id"],
        "cluster_version": target["cluster_version"],
        "cluster_id": target["cluster_id"],
        "centroid_embedding": centroid.astype(float).tolist(),
        "medoid_label": medoid["raw_label"],
        "medoid_global_label_id": medoid.get("label_map_id"),
        "medoid_similarity_to_centroid": float(sims[medoid_idx]),
        "representative_labels": representative_labels,
        "label_rows": len(label_rows),
        "usable_embedding_rows": len(usable_same_dim),
        "missing_embedding_rows": missing_embedding_rows,
        "dropped_wrong_dim_rows": dropped_wrong_dim,
        "embedding_dim": int(dominant_dim),
        "cluster_size_before": target.get("cluster_size"),
        "total_occurrences_before": target.get("total_occurrences"),
        "computed_cluster_size": len({u["raw_label"] for u in usable_same_dim}),
        "computed_total_occurrences": int(sum(int(u["value_count"]) for u in usable_same_dim)),
        "medoid_value_count": int(medoid["value_count"]),
    }

    return update, None


class CounterLike:
    """Tiny local replacement to keep typing simple."""
    def __init__(self, values: Iterable[int]):
        self.counts = defaultdict(int)
        for value in values:
            self.counts[value] += 1

    def most_common(self, n: int):
        return sorted(self.counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def write_review_csv(output_dir: Path, updates: List[dict], issues: List[dict]) -> Tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    review_path = output_dir / f"all_active_centroid_rebuild_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    issues_path = output_dir / f"all_active_centroid_rebuild_issues_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    review_fields = [
        "field_name",
        "run_id",
        "cluster_version",
        "cluster_id",
        "label_rows",
        "usable_embedding_rows",
        "missing_embedding_rows",
        "dropped_wrong_dim_rows",
        "embedding_dim",
        "cluster_size_before",
        "computed_cluster_size",
        "total_occurrences_before",
        "computed_total_occurrences",
        "medoid_label",
        "medoid_value_count",
        "medoid_global_label_id",
        "medoid_similarity_to_centroid",
        "top_representative_labels",
    ]

    with review_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=review_fields)
        writer.writeheader()
        for u in updates:
            reps = u.get("representative_labels") or []
            writer.writerow(
                {
                    **{k: u.get(k) for k in review_fields if k != "top_representative_labels"},
                    "top_representative_labels": " | ".join(
                        f"{r.get('raw_label')} ({r.get('value_count')}, sim={float(r.get('similarity_to_centroid', 0)):.4f})"
                        for r in reps[:8]
                    ),
                }
            )

    issue_fields = [
        "field_name",
        "run_id",
        "cluster_version",
        "cluster_id",
        "issue",
        "label_rows",
        "missing_embedding_rows",
    ]

    with issues_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=issue_fields)
        writer.writeheader()
        for issue in issues:
            writer.writerow({k: issue.get(k) for k in issue_fields})

    return review_path, issues_path


def apply_updates(conn, updates: List[dict], page_size: int = 500) -> int:
    """
    Apply updates in batches.

    Important:
    psycopg2 execute_values with page_size may leave cursor.rowcount equal to only
    the last batch, not the total. So this function returns len(updates) after the
    batched UPDATE succeeds. The caller should run post-apply health SQL for final
    verification.
    """
    if not updates:
        return 0

    rows = [
        (
            psycopg2.extras.Json(u["centroid_embedding"]),
            u["medoid_label"],
            u["medoid_global_label_id"],
            u["medoid_similarity_to_centroid"],
            psycopg2.extras.Json(u["representative_labels"]),
            u["field_name"],
            u["run_id"],
            u["cluster_version"],
            u["cluster_id"],
        )
        for u in updates
    ]

    sql = """
        UPDATE taxonomy_clusters AS c
        SET
            centroid_embedding = v.centroid_embedding,
            medoid_label = v.medoid_label,
            medoid_global_label_id = v.medoid_global_label_id,
            medoid_similarity_to_centroid = v.medoid_similarity_to_centroid,
            representative_labels = v.representative_labels,
            updated_at = CURRENT_TIMESTAMP
        FROM (VALUES %s) AS v (
            centroid_embedding,
            medoid_label,
            medoid_global_label_id,
            medoid_similarity_to_centroid,
            representative_labels,
            field_name,
            run_id,
            cluster_version,
            cluster_id
        )
        WHERE c.field_name = v.field_name
          AND c.run_id = v.run_id
          AND c.cluster_version = v.cluster_version
          AND c.cluster_id = v.cluster_id
          AND COALESCE(c.active, true) = true
          AND COALESCE(c.is_true_anomaly_cluster, false) = false;
    """

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            sql,
            rows,
            template="(%s::jsonb, %s::text, %s::bigint, %s::double precision, %s::jsonb, %s::text, %s::text, %s::text, %s::text)",
            page_size=page_size,
        )

    return len(updates)


def summarize(updates: List[dict], issues: List[dict]) -> None:
    print(f"Updates computed: {len(updates)}")
    print(f"Clusters with no usable labels/embeddings: {len(issues)}")

    by_field = defaultdict(int)
    issue_by_field = defaultdict(int)
    dims = defaultdict(int)
    min_sim = None
    max_sim = None

    for u in updates:
        by_field[u["field_name"]] += 1
        dims[u["embedding_dim"]] += 1
        sim = float(u["medoid_similarity_to_centroid"])
        min_sim = sim if min_sim is None else min(min_sim, sim)
        max_sim = sim if max_sim is None else max(max_sim, sim)

    for issue in issues:
        issue_by_field[issue["field_name"]] += 1

    print("Updates by field:")
    for field in sorted(by_field):
        print(f"  {field}: {by_field[field]}")

    if issue_by_field:
        print("Issues by field:")
        for field in sorted(issue_by_field):
            print(f"  {field}: {issue_by_field[field]}")

    print(f"Centroid dimensions found: {sorted(dims.keys())}")

    if min_sim is not None and max_sim is not None:
        print(f"Medoid similarity range: {min_sim:.6f} - {max_sim:.6f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--field", help="Optional field filter, e.g. additional_tags")
    parser.add_argument("--run-id", help="Optional run_id filter")
    parser.add_argument("--cluster-version", help="Optional cluster_version filter")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--representative-limit", type=int, default=DEFAULT_REPRESENTATIVE_LIMIT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--page-size", type=int, default=500)

    args = parser.parse_args()

    if args.dry_run == args.apply:
        raise RuntimeError("Choose exactly one: --dry-run or --apply")

    output_dir = Path(args.output_dir)

    conn = get_conn()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database(), current_schema(), current_user;")
                print("DB connection:", cur.fetchone())

            print(
                f"Target: field={args.field or 'ALL'}, "
                f"run_id={args.run_id or 'ALL'}, "
                f"cluster_version={args.cluster_version or 'ALL'}"
            )

            targets = fetch_targets(
                conn=conn,
                field=args.field,
                run_id=args.run_id,
                cluster_version=args.cluster_version,
            )

            print(f"Active standard clusters targeted: {len(targets)}")

            label_rows_by_key = fetch_label_embedding_rows(conn, targets)

            updates: List[dict] = []
            issues: List[dict] = []

            for target in targets:
                key = (
                    target["field_name"],
                    target["run_id"],
                    target["cluster_version"],
                    target["cluster_id"],
                )
                update, issue = compute_update_for_cluster(
                    target=target,
                    label_rows=label_rows_by_key.get(key, []),
                    representative_limit=args.representative_limit,
                )
                if update is not None:
                    updates.append(update)
                if issue is not None:
                    issues.append(issue)

            summarize(updates, issues)

            review_path, issues_path = write_review_csv(output_dir, updates, issues)
            print(f"Review CSV written: {review_path}")
            print(f"Issues CSV written: {issues_path}")

            if args.dry_run:
                print("Dry run complete. No DB changes made.")
                conn.rollback()
                return

            if issues:
                raise RuntimeError(
                    f"Refusing to apply because {len(issues)} clusters have no usable embeddings. "
                    f"Review: {issues_path}"
                )

            updated = apply_updates(conn, updates, page_size=args.page_size)

            print(f"Committed successfully. Updated rows requested: {updated}")

    except Exception:
        conn.rollback()
        print("Rolled back due to error.")
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    main()
