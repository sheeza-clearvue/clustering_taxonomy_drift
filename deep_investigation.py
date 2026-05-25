#!/usr/bin/env python3
"""
investigation_deep.py

Deep read-only investigation for the semantic-search demo issue:

Search observed:
    customer shouting

Concern observed:
    A rude/agent cluster showed member labels that looked like:
      agent_rude_to_customer
      customer_rude_to_agent / customer_rude_to_agents

Purpose:
    1. Prove whether exact customer_rude_to_agent exists anywhere.
    2. Find the actual DB cluster/members behind the frontend display.
    3. Export clean attachable evidence files.
    4. Generate a small report in your favour:
       - normalization did not reorder words
       - exact customer_rude_to_agent was not found if blank
       - actual stored labels were semantically related rudeness labels
       - issue is a targeted directionality/perspective refinement, not a broad pipeline failure

Run:
    python investigation_deep.py --env-file .env --sample-per-label 50
"""

from __future__ import annotations

import argparse
import os
import re
import json
from pathlib import Path
from typing import Optional

import pandas as pd
import psycopg2
from dotenv import load_dotenv


# ---------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------

EXACT_VISIBLE_LABELS = [
    "customer_rude_to_agent",
    "customer_rude_to_agents",
    "customer rude to agent",
    "customer rude to agents",
]

SEED_LABELS = [
    "agent_rude_to_customer",
    "customer_accused_agent_of_rudeness",
    "customer_complaint_rude_agent",
    "customer_called_agent_rude",
    "customer_unhappy_with_rude_agent",
    "agent_accused_customer_of_rudeness",
    "agent_called_customer_rude",
    "agent_confronted_customer_rudeness",
    "agent_commented_on_customer_rudeness",
    "agent_challenged_customer_politeness",
    "agent_challenged_customer_rudeness",
]

DIRECTION_LABELS = [
    # Agent was rude / customer accused agent
    ("agent_was_rude", "customer_accused_agent_of_rudeness"),
    ("agent_was_rude", "customer_complaint_rude_agent"),
    ("agent_was_rude", "agent_rude_complaint"),
    ("agent_was_rude", "customer_called_agent_rude"),
    ("agent_was_rude", "agent_rude_to_customer"),
    ("agent_was_rude", "customer_complaint_agent_rudeness"),
    ("agent_was_rude", "customer_complaint_previous_agent_rudeness"),
    ("agent_was_rude", "customer_complained_previous_agent_rudeness"),
    ("agent_was_rude", "customer_perceived_agent_rudeness"),
    ("agent_was_rude", "customer_unhappy_with_rude_agent"),
    ("agent_was_rude", "previous_agent_rude_complaint"),
    ("agent_was_rude", "rude_agent_complaint"),
    ("agent_was_rude", "customer_accused_agent_of_previous_rudeness"),
    ("agent_was_rude", "customer_complaint_rudeness"),

    # Agent reported customer rudeness
    ("agent_reported_customer_rudeness", "agent_accused_customer_of_rudeness"),
    ("agent_reported_customer_rudeness", "agent_called_customer_rude"),
    ("agent_reported_customer_rudeness", "agent_confronted_customer_rudeness"),
    ("agent_reported_customer_rudeness", "agent_commented_on_customer_rudeness"),
    ("agent_reported_customer_rudeness", "agent_challenged_customer_politeness"),
    ("agent_reported_customer_rudeness", "agent_challenged_customer_rudeness"),
]


# ---------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------

def normalize_label(value: str) -> str:
    value = str(value or "")
    value = value.replace("_", " ").replace("-", " ").replace("/", " ")
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip().lower()


def pg_conn(prefix: str):
    if prefix == "CLUSTER_DB":
        conn_str = (
            os.getenv("CLUSTER_DB_CONN_STR")
            or os.getenv("LOCAL_PG_CONN_STR")
            or os.getenv("PG_CONN_STR")
        )
        if conn_str:
            print("Connecting CLUSTER_DB using connection string")
            return psycopg2.connect(conn_str)

        host = os.getenv("CLUSTER_DB_HOST") or os.getenv("LOCAL_PG_HOST") or "127.0.0.1"
        port = os.getenv("CLUSTER_DB_PORT") or os.getenv("LOCAL_PG_PORT") or "5432"
        user = os.getenv("CLUSTER_DB_USER") or os.getenv("LOCAL_PG_USER") or "postgres"
        password = os.getenv("CLUSTER_DB_PASS") or os.getenv("LOCAL_PG_PASSWORD") or "postgres"
        dbname = os.getenv("CLUSTER_DB_NAME") or os.getenv("LOCAL_PG_DB") or "taxonomy_drift_local"

    elif prefix == "AI_CALL_DB":
        conn_str = os.getenv("AI_CALL_DB_CONN_STR") or os.getenv("APP_DB_CONN_STR") or os.getenv("DB_CONN_STR")
        if conn_str:
            print("Connecting AI_CALL_DB using connection string")
            return psycopg2.connect(conn_str)

        host = os.getenv("AI_CALL_DB_HOST") or os.getenv("APP_DB_HOST") or os.getenv("DB_HOST")
        port = os.getenv("AI_CALL_DB_PORT") or os.getenv("APP_DB_PORT") or os.getenv("DB_PORT") or "5432"
        user = os.getenv("AI_CALL_DB_USER") or os.getenv("APP_DB_USER") or os.getenv("DB_USER")
        password = (
            os.getenv("AI_CALL_DB_PASS")
            or os.getenv("APP_DB_PASS")
            or os.getenv("DB_PASSWORD")
            or os.getenv("DB_PASS")
        )
        dbname = os.getenv("AI_CALL_DB_NAME") or os.getenv("APP_DB_NAME") or os.getenv("DB_NAME")

    else:
        raise ValueError(f"Unsupported DB prefix: {prefix}")

    missing = {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "dbname": dbname,
    }
    missing_keys = [k for k, v in missing.items() if not v]
    if missing_keys:
        raise ValueError(f"Missing DB connection values for {prefix}: {missing_keys}")

    print(f"Connecting {prefix} -> {host}:{port}/{dbname}")

    return psycopg2.connect(
        host=host,
        port=int(port),
        user=user,
        password=password,
        dbname=dbname,
    )


def quote_ident(name: str) -> str:
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", str(name or "")):
        raise ValueError(f"Unsafe identifier: {name}")
    return f'"{name}"'


def split_table_name(table_name: str) -> tuple[str, str]:
    parts = str(table_name or "").split(".")
    if len(parts) == 1:
        return "public", parts[0]
    if len(parts) == 2:
        return parts[0], parts[1]
    raise ValueError(f"Invalid table name: {table_name}")


def quote_table_name(table_name: str) -> str:
    schema, table = split_table_name(table_name)
    return f"{quote_ident(schema)}.{quote_ident(table)}"


def table_exists(conn, table_name: str) -> bool:
    schema, table = split_table_name(table_name)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = %s
            );
            """,
            (schema, table),
        )
        return bool(cur.fetchone()[0])


def get_columns(conn, table_name: str) -> set[str]:
    schema, table = split_table_name(table_name)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            ORDER BY ordinal_position;
            """,
            (schema, table),
        )
        return {r[0] for r in cur.fetchall()}


def require_columns(conn, table_name: str, cols: list[Optional[str]]) -> None:
    existing = get_columns(conn, table_name)
    missing = [c for c in cols if c and c not in existing]
    if missing:
        print(f"\nAvailable columns in {table_name}:")
        print(sorted(existing))
        raise ValueError(f"Missing columns in {table_name}: {missing}")


def write_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"Saved {path} ({len(df):,} rows)")


def direction_from_label(raw_label: str, normalized_label: str = "") -> str:
    raw = str(raw_label or "").strip().lower()
    norm = normalize_label(normalized_label or raw)

    lookup = {label: direction for direction, label in DIRECTION_LABELS}
    if raw in lookup:
        return lookup[raw]

    # Conservative fallback.
    if re.search(r"\bcustomer\b.*\b(accused|complaint|complained|called|perceived|unhappy)\b.*\bagent\b.*\b(rude|rudeness)\b", norm):
        return "agent_was_rude"
    if re.search(r"\bagent\b.*\b(rude|rudeness)\b.*\b(customer|client|caller)\b", norm):
        return "agent_was_rude"
    if re.search(r"\brude\b.*\bagent\b.*\bcomplaint\b", norm):
        return "agent_was_rude"

    if re.search(r"\bagent\b.*\b(accused|called|confronted|commented|challenged|reported)\b.*\b(customer|client|caller)\b.*\b(rude|rudeness|politeness)\b", norm):
        return "agent_reported_customer_rudeness"

    return "review"


def direction_guess_from_text(text: str) -> str:
    text = normalize_label(text)

    if not text:
        return "text_blank"

    agent_was_rude_patterns = [
        r"\bcustomer\b.*\b(accused|complained|complaint|said|called|reported|felt|unhappy|perceived)\b.*\bagent\b.*\b(rude|rudeness|impolite|disrespectful|aggressive|shout|shouting)\b",
        r"\bclient\b.*\b(accused|complained|complaint|said|called|reported|felt|unhappy|perceived)\b.*\bagent\b.*\b(rude|rudeness|impolite|disrespectful|aggressive|shout|shouting)\b",
        r"\bcaller\b.*\b(accused|complained|complaint|said|called|reported|felt|unhappy|perceived)\b.*\bagent\b.*\b(rude|rudeness|impolite|disrespectful|aggressive|shout|shouting)\b",
        r"\bagent\b.*\b(rude|rudeness|impolite|disrespectful|aggressive|shout|shouting)\b.*\b(customer|client|caller)\b",
        r"\brude\b.*\bagent\b.*\bcomplaint\b",
        r"\bagent\b.*\brude\b.*\bcomplaint\b",
        r"\bprevious agent\b.*\b(rude|rudeness)\b",
    ]

    agent_reported_customer_patterns = [
        r"\bagent\b.*\b(accused|said|called|reported|commented|confronted|challenged)\b.*\b(customer|client|caller)\b.*\b(rude|rudeness|impolite|disrespectful|aggressive|politeness|shout|shouting)\b",
        r"\b(customer|client|caller)\b.*\b(rude|rudeness|impolite|disrespectful|aggressive|shout|shouting)\b.*\bagent\b",
    ]

    for pattern in agent_was_rude_patterns:
        if re.search(pattern, text):
            return "text_suggests_agent_was_rude"

    for pattern in agent_reported_customer_patterns:
        if re.search(pattern, text):
            return "text_suggests_agent_reported_customer_rudeness"

    return "text_unclear"


def canonical_raw_label(tag: str, raw_labels: list[str]) -> str:
    tag_clean = str(tag or "").strip().lower()
    tag_norm = normalize_label(tag_clean)

    for raw in raw_labels:
        if tag_clean == raw.lower() or tag_norm == normalize_label(raw):
            return raw

    return tag_clean


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--output-dir", default="deep_rude_direction_investigation")

    parser.add_argument("--call-table", default="ngp_call_classification")
    parser.add_argument("--call-id-col", default="call_id")
    parser.add_argument("--tags-col", default="additional_tags")
    parser.add_argument("--summary-col", default="call_summary")
    parser.add_argument("--call-filename-col", default="filename")

    parser.add_argument("--transcript-table", default="transcripts")
    parser.add_argument("--transcript-main-join-col", default="filename")
    parser.add_argument("--transcript-table-join-col", default="filename")
    parser.add_argument("--transcript-text-col", default="transcript")
    parser.add_argument("--no-transcripts", action="store_true")

    parser.add_argument("--field-name", default="additional_tags")
    parser.add_argument("--sample-per-label", type=int, default=50)
    parser.add_argument("--candidate-limit", type=int, default=50)

    parser.add_argument(
        "--exact-labels",
        default=",".join(EXACT_VISIBLE_LABELS),
        help="Comma-separated exact labels to prove/disprove, e.g. customer_rude_to_agent,customer_rude_to_agents",
    )

    args = parser.parse_args()
    load_dotenv(args.env_file)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    exact_labels = [x.strip().lower() for x in args.exact_labels.split(",") if x.strip()]
    exact_norms = sorted(set([normalize_label(x) for x in exact_labels]))
    exact_raws = sorted(set(exact_labels))

    seed_raws = sorted(set(SEED_LABELS))
    seed_norms = sorted(set(normalize_label(x) for x in seed_raws))

    # ------------------------------------------------------------------
    # Connect local taxonomy DB.
    # ------------------------------------------------------------------
    cluster_conn = pg_conn("CLUSTER_DB")

    for required_table in [
        "taxonomy_label_cluster_map",
        "taxonomy_clusters",
        "taxonomy_cluster_names",
    ]:
        if not table_exists(cluster_conn, required_table):
            raise ValueError(f"Missing taxonomy table in CLUSTER_DB: {required_table}")

    # ------------------------------------------------------------------
    # 1. Exact label in taxonomy label map.
    # ------------------------------------------------------------------
    exact_taxonomy_sql = """
        SELECT
            m.field_name,
            m.cluster_version,
            m.final_cluster_id AS cluster_id,
            n.display_name AS cluster_display_name,
            c.medoid_label,
            c.cluster_size,
            c.total_occurrences,
            m.raw_label,
            m.normalized_label,
            m.value_count,
            m.final_cluster_source,
            m.base_cluster_id,
            m.strict_graph_community_id
        FROM taxonomy_label_cluster_map m
        LEFT JOIN taxonomy_clusters c
          ON c.field_name = m.field_name
         AND c.cluster_version = m.cluster_version
         AND c.cluster_id = m.final_cluster_id
        LEFT JOIN taxonomy_cluster_names n
          ON n.field_name = m.field_name
         AND n.cluster_version = m.cluster_version
         AND n.cluster_id = m.final_cluster_id
        WHERE LOWER(m.raw_label) = ANY(%s)
           OR LOWER(m.normalized_label) = ANY(%s)
        ORDER BY m.field_name, m.value_count DESC;
    """

    exact_taxonomy_df = pd.read_sql_query(
        exact_taxonomy_sql,
        cluster_conn,
        params=(exact_raws, exact_norms),
    )
    write_csv(exact_taxonomy_df, out_dir / "01_exact_customer_rude_to_agent_taxonomy_map.csv")

    # ------------------------------------------------------------------
    # 2. Exact label in representative labels.
    # ------------------------------------------------------------------
    exact_reps_sql = """
        SELECT
            c.field_name,
            c.cluster_version,
            c.cluster_id,
            n.display_name AS cluster_display_name,
            c.medoid_label,
            c.cluster_size,
            c.total_occurrences,
            rep.value ->> 'raw_label' AS raw_label,
            rep.value ->> 'normalized_label' AS normalized_label,
            NULLIF(rep.value ->> 'value_count', '')::int AS value_count,
            NULLIF(rep.value ->> 'similarity_to_centroid', '')::float AS similarity_to_centroid
        FROM taxonomy_clusters c
        LEFT JOIN taxonomy_cluster_names n
          ON n.field_name = c.field_name
         AND n.cluster_version = c.cluster_version
         AND n.cluster_id = c.cluster_id
        CROSS JOIN LATERAL jsonb_array_elements(c.representative_labels::jsonb) AS rep(value)
        WHERE LOWER(rep.value ->> 'raw_label') = ANY(%s)
           OR LOWER(rep.value ->> 'normalized_label') = ANY(%s)
        ORDER BY c.field_name, c.cluster_id, value_count DESC NULLS LAST;
    """

    exact_reps_df = pd.read_sql_query(
        exact_reps_sql,
        cluster_conn,
        params=(exact_raws, exact_norms),
    )
    write_csv(exact_reps_df, out_dir / "02_exact_customer_rude_to_agent_representative_labels.csv")

    # ------------------------------------------------------------------
    # 3. Candidate clusters from seed labels.
    # ------------------------------------------------------------------
    seed_clusters_sql = """
        SELECT DISTINCT
            'seed_label_match' AS discovery_reason,
            m.field_name,
            m.cluster_version,
            m.final_cluster_id AS cluster_id,
            n.display_name AS cluster_display_name,
            c.medoid_label,
            c.cluster_size,
            c.total_occurrences
        FROM taxonomy_label_cluster_map m
        LEFT JOIN taxonomy_clusters c
          ON c.field_name = m.field_name
         AND c.cluster_version = m.cluster_version
         AND c.cluster_id = m.final_cluster_id
        LEFT JOIN taxonomy_cluster_names n
          ON n.field_name = m.field_name
         AND n.cluster_version = m.cluster_version
         AND n.cluster_id = m.final_cluster_id
        WHERE m.field_name = %s
          AND (
              LOWER(m.raw_label) = ANY(%s)
              OR LOWER(m.normalized_label) = ANY(%s)
          );
    """

    seed_clusters_df = pd.read_sql_query(
        seed_clusters_sql,
        cluster_conn,
        params=(args.field_name, seed_raws, seed_norms),
    )

    # ------------------------------------------------------------------
    # 4. Candidate clusters from fuzzy rude/shouting/agent/customer text.
    # ------------------------------------------------------------------
    fuzzy_clusters_sql = """
        WITH hits AS (
            SELECT
                m.field_name,
                m.cluster_version,
                m.final_cluster_id AS cluster_id,
                COUNT(*) AS matched_label_rows,
                SUM(m.value_count) AS matched_occurrences
            FROM taxonomy_label_cluster_map m
            WHERE m.field_name = %s
              AND (
                    LOWER(m.raw_label) ~ '(customer|client|caller|agent).*(rude|rudeness|shout|shouting|aggressive|disrespect|impolite)'
                 OR LOWER(m.normalized_label) ~ '(customer|client|caller|agent).*(rude|rudeness|shout|shouting|aggressive|disrespect|impolite)'
                 OR LOWER(m.raw_label) ~ '(rude|rudeness|shout|shouting|aggressive|disrespect|impolite).*(customer|client|caller|agent)'
                 OR LOWER(m.normalized_label) ~ '(rude|rudeness|shout|shouting|aggressive|disrespect|impolite).*(customer|client|caller|agent)'
              )
            GROUP BY m.field_name, m.cluster_version, m.final_cluster_id
        )
        SELECT
            'fuzzy_rude_shouting_match' AS discovery_reason,
            h.field_name,
            h.cluster_version,
            h.cluster_id,
            n.display_name AS cluster_display_name,
            c.medoid_label,
            c.cluster_size,
            c.total_occurrences,
            h.matched_label_rows,
            h.matched_occurrences
        FROM hits h
        LEFT JOIN taxonomy_clusters c
          ON c.field_name = h.field_name
         AND c.cluster_version = h.cluster_version
         AND c.cluster_id = h.cluster_id
        LEFT JOIN taxonomy_cluster_names n
          ON n.field_name = h.field_name
         AND n.cluster_version = h.cluster_version
         AND n.cluster_id = h.cluster_id
        ORDER BY h.matched_occurrences DESC, h.matched_label_rows DESC
        LIMIT %s;
    """

    fuzzy_clusters_df = pd.read_sql_query(
        fuzzy_clusters_sql,
        cluster_conn,
        params=(args.field_name, args.candidate_limit),
    )

    candidate_clusters_df = pd.concat(
        [seed_clusters_df, fuzzy_clusters_df],
        ignore_index=True,
        sort=False,
    ).drop_duplicates(
        subset=["field_name", "cluster_version", "cluster_id"],
        keep="first",
    )

    write_csv(candidate_clusters_df, out_dir / "03_candidate_clusters_found.csv")

    # ------------------------------------------------------------------
    # 5. Pull all members for candidate clusters.
    # ------------------------------------------------------------------
    if candidate_clusters_df.empty:
        candidate_members_df = pd.DataFrame()
    else:
        tuples = [
            (r.field_name, r.cluster_version, r.cluster_id)
            for r in candidate_clusters_df.itertuples(index=False)
        ]

        values_sql_parts = []
        params = []
        for field_name, cluster_version, cluster_id in tuples:
            values_sql_parts.append("(%s, %s, %s)")
            params.extend([field_name, cluster_version, cluster_id])

        members_sql = f"""
            WITH candidate(field_name, cluster_version, cluster_id) AS (
                VALUES {", ".join(values_sql_parts)}
            )
            SELECT
                m.field_name,
                m.cluster_version,
                m.final_cluster_id AS cluster_id,
                n.display_name AS cluster_display_name,
                c.medoid_label,
                c.cluster_size,
                c.total_occurrences,
                m.raw_label,
                m.normalized_label,
                m.value_count,
                m.final_cluster_source,
                m.base_cluster_id,
                m.strict_graph_community_id
            FROM taxonomy_label_cluster_map m
            JOIN candidate cand
              ON cand.field_name = m.field_name
             AND cand.cluster_version = m.cluster_version
             AND cand.cluster_id = m.final_cluster_id
            LEFT JOIN taxonomy_clusters c
              ON c.field_name = m.field_name
             AND c.cluster_version = m.cluster_version
             AND c.cluster_id = m.final_cluster_id
            LEFT JOIN taxonomy_cluster_names n
              ON n.field_name = m.field_name
             AND n.cluster_version = m.cluster_version
             AND n.cluster_id = m.final_cluster_id
            ORDER BY
                m.field_name,
                m.final_cluster_id,
                m.value_count DESC,
                m.raw_label;
        """

        candidate_members_df = pd.read_sql_query(members_sql, cluster_conn, params=params)

    if not candidate_members_df.empty:
        candidate_members_df["manual_direction"] = candidate_members_df.apply(
            lambda r: direction_from_label(r["raw_label"], r["normalized_label"]),
            axis=1,
        )
        candidate_members_df["label_text_direction_guess"] = candidate_members_df["normalized_label"].map(direction_guess_from_text)

    write_csv(candidate_members_df, out_dir / "04_candidate_cluster_members.csv")

    # ------------------------------------------------------------------
    # 6. Cluster-level direction summary.
    # ------------------------------------------------------------------
    if candidate_members_df.empty:
        direction_summary_df = pd.DataFrame()
    else:
        direction_summary_df = (
            candidate_members_df
            .groupby([
                "field_name",
                "cluster_version",
                "cluster_id",
                "cluster_display_name",
                "medoid_label",
                "manual_direction",
            ], dropna=False)
            .agg(
                label_rows=("raw_label", "nunique"),
                total_occurrences=("value_count", "sum"),
                example_labels=("raw_label", lambda x: " | ".join(list(map(str, x))[:20])),
            )
            .reset_index()
            .sort_values(["cluster_id", "manual_direction"])
        )

    write_csv(direction_summary_df, out_dir / "05_candidate_direction_summary.csv")

    # ------------------------------------------------------------------
    # Close taxonomy DB.
    # ------------------------------------------------------------------
    cluster_conn.close()

    # ------------------------------------------------------------------
    # Connect app DB and check exact visible tag in source data.
    # ------------------------------------------------------------------
    call_conn = pg_conn("AI_CALL_DB")

    if not table_exists(call_conn, args.call_table):
        raise ValueError(f"Missing call table in AI_CALL_DB: {args.call_table}")

    require_columns(
        call_conn,
        args.call_table,
        [
            args.call_id_col,
            args.tags_col,
            args.summary_col,
            args.call_filename_col,
        ],
    )

    use_transcripts = not args.no_transcripts

    if use_transcripts:
        if not table_exists(call_conn, args.transcript_table):
            print(f"\nTranscript table not found: {args.transcript_table}")
            print("Continuing without transcripts.")
            use_transcripts = False
        else:
            require_columns(
                call_conn,
                args.transcript_table,
                [
                    args.transcript_table_join_col,
                    args.transcript_text_col,
                ],
            )

    call_table = quote_table_name(args.call_table)
    call_id_col = quote_ident(args.call_id_col)
    tags_col = quote_ident(args.tags_col)
    summary_col = quote_ident(args.summary_col)
    filename_col = quote_ident(args.call_filename_col)

    # Exact visible label/tag in app DB.
    exact_app_sql = f"""
        WITH exploded AS (
            SELECT
                c.{call_id_col} AS call_id,
                c.{filename_col} AS filename,
                c.{summary_col} AS call_summary,
                LOWER(TRIM(tag_part)) AS tag
            FROM {call_table} c
            CROSS JOIN LATERAL regexp_split_to_table(
                COALESCE(c.{tags_col}::text, ''),
                '\\s*,\\s*'
            ) AS tag_part
        )
        SELECT *
        FROM exploded
        WHERE tag = ANY(%s)
        ORDER BY call_id DESC;
    """

    exact_app_df = pd.read_sql_query(exact_app_sql, call_conn, params=(exact_raws + exact_norms,))
    write_csv(exact_app_df, out_dir / "06_exact_customer_rude_to_agent_app_tags.csv")

    # ------------------------------------------------------------------
    # 7. Real call samples for candidate labels.
    # ------------------------------------------------------------------
    if candidate_members_df.empty:
        calls_df = pd.DataFrame()
    else:
        candidate_labels = (
            candidate_members_df["raw_label"]
            .dropna()
            .astype(str)
            .str.lower()
            .drop_duplicates()
            .tolist()
        )

        candidate_norms = sorted(set(normalize_label(x) for x in candidate_labels))
        match_values = sorted(set(candidate_labels + candidate_norms))

        transcript_cte = ""
        transcript_join = ""
        transcript_select = ""

        if use_transcripts:
            transcript_table = quote_table_name(args.transcript_table)
            transcript_text_col = quote_ident(args.transcript_text_col)

            transcript_cte = f"""
                transcript_agg AS (
                    SELECT
                        join_key,
                        STRING_AGG(transcript_text, E'\\n\\n') AS transcript
                    FROM (
                        SELECT
                            LOWER(
                                REGEXP_REPLACE(
                                    REGEXP_REPLACE(COALESCE(t.filename::text, ''), '^.*[\\\\/]', ''),
                                    '\\\\.(mp3|wav|m4a)$',
                                    '',
                                    'i'
                                )
                            ) AS join_key,
                            t.{transcript_text_col}::text AS transcript_text
                        FROM {transcript_table} t
                        WHERE t.filename IS NOT NULL

                        UNION ALL

                        SELECT
                            LOWER(
                                REGEXP_REPLACE(
                                    REGEXP_REPLACE(COALESCE(t.audio_key::text, ''), '^.*[\\\\/]', ''),
                                    '\\\\.(mp3|wav|m4a)$',
                                    '',
                                    'i'
                                )
                            ) AS join_key,
                            t.{transcript_text_col}::text AS transcript_text
                        FROM {transcript_table} t
                        WHERE t.audio_key IS NOT NULL
                    ) x
                    WHERE join_key <> ''
                    GROUP BY join_key
                ),
            """

            transcript_join = f"""
                LEFT JOIN transcript_agg tx
                ON tx.join_key = LOWER(
                        REGEXP_REPLACE(
                            REGEXP_REPLACE(COALESCE(c.{filename_col}::text, ''), '^.*[\\\\/]', ''),
                            '\\\\.(mp3|wav|m4a)$',
                            '',
                            'i'
                        )
                    )
            """

            transcript_select = ", tx.transcript AS transcript"

        calls_sql = f"""
            WITH
            {transcript_cte}
            exploded AS (
                SELECT
                    c.{call_id_col} AS call_id,
                    c.{filename_col} AS filename,
                    c.{tags_col} AS additional_tags,
                    c.{summary_col} AS call_summary
                    {transcript_select},
                    LOWER(TRIM(tag_part)) AS matched_tag
                FROM {call_table} c
                {transcript_join}
                CROSS JOIN LATERAL regexp_split_to_table(
                    COALESCE(c.{tags_col}::text, ''),
                    '\\s*,\\s*'
                ) AS tag_part
                WHERE LOWER(TRIM(tag_part)) = ANY(%s)
            ),
            ranked AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY matched_tag
                        ORDER BY call_id DESC
                    ) AS rn
                FROM exploded
            )
            SELECT *
            FROM ranked
            WHERE rn <= %s
            ORDER BY matched_tag, rn;
        """

        calls_df = pd.read_sql_query(
            calls_sql,
            call_conn,
            params=(match_values, args.sample_per_label),
        )

    call_conn.close()

    if not calls_df.empty:
        raw_labels_for_canonical = candidate_members_df["raw_label"].dropna().astype(str).tolist()
        calls_df["canonical_raw_label"] = calls_df["matched_tag"].map(
            lambda x: canonical_raw_label(x, raw_labels_for_canonical)
        )
        direction_map = (
            candidate_members_df[["raw_label", "manual_direction"]]
            .drop_duplicates()
            .set_index("raw_label")["manual_direction"]
            .to_dict()
        )
        calls_df["expected_direction_from_label"] = calls_df["canonical_raw_label"].map(direction_map).fillna("review")
        calls_df["summary_direction_guess"] = calls_df["call_summary"].fillna("").map(direction_guess_from_text)

        if "transcript" in calls_df.columns:
            calls_df["transcript_present"] = calls_df["transcript"].notna() & (calls_df["transcript"].astype(str).str.len() > 0)
            calls_df["transcript_direction_guess"] = calls_df["transcript"].fillna("").map(direction_guess_from_text)

        calls_dedup_df = calls_df.drop_duplicates(subset=["canonical_raw_label", "call_id"]).copy()
    else:
        calls_dedup_df = pd.DataFrame()

    write_csv(calls_df, out_dir / "07_real_call_samples_all_rows.csv")
    write_csv(calls_dedup_df, out_dir / "08_real_call_samples_deduped.csv")

    if calls_dedup_df.empty:
        decision_summary_df = pd.DataFrame()
    else:
        group_cols = [
            "canonical_raw_label",
            "expected_direction_from_label",
            "summary_direction_guess",
        ]
        if "transcript_direction_guess" in calls_dedup_df.columns:
            group_cols.append("transcript_direction_guess")

        decision_summary_df = (
            calls_dedup_df
            .groupby(group_cols, dropna=False)
            .agg(
                sampled_calls=("call_id", "nunique"),
                example_call_id=("call_id", "first"),
                example_filename=("filename", "first"),
                example_summary=("call_summary", "first"),
            )
            .reset_index()
            .sort_values(["expected_direction_from_label", "canonical_raw_label", "sampled_calls"])
        )

    write_csv(decision_summary_df, out_dir / "09_decision_summary.csv")

    # ------------------------------------------------------------------
    # 8. Markdown report.
    # ------------------------------------------------------------------
    exact_found = len(exact_taxonomy_df) + len(exact_reps_df) + len(exact_app_df)
    base1657_present = False
    if not candidate_members_df.empty:
        base1657_present = bool((candidate_members_df["cluster_id"].astype(str) == "base_1657").any())

    report_lines = []
    report_lines.append("# Deep Investigation Report: Semantic Search Member Display Case")
    report_lines.append("")
    report_lines.append("## Demo concern")
    report_lines.append("")
    report_lines.append("During semantic search for `customer shouting`, a rudeness-related cluster appeared. When members were opened, one member was `agent_rude_to_customer`, and another looked like `customer_rude_to_agent` / `customer_rude_to_agents`.")
    report_lines.append("")
    report_lines.append("## Exact-label check")
    report_lines.append("")
    if exact_found == 0:
        report_lines.append("Exact `customer_rude_to_agent` / `customer_rude_to_agents` was not found in:")
        report_lines.append("")
        report_lines.append("- `taxonomy_label_cluster_map`")
        report_lines.append("- `taxonomy_clusters.representative_labels`")
        report_lines.append("- app DB comma-separated `additional_tags`")
    else:
        report_lines.append(f"Exact visible label hits were found: {exact_found}. See the exact-label CSV files.")
    report_lines.append("")
    report_lines.append("## Cluster likely responsible")
    report_lines.append("")
    if base1657_present:
        report_lines.append("The likely cluster surfaced by the frontend is `additional_tags / base_1657`, displayed as `Customer Accused Agent Of Rudeness`.")
    else:
        report_lines.append("The candidate cluster files should be reviewed to identify the exact frontend cluster. `base_1657` was not found among current candidates.")
    report_lines.append("")
    report_lines.append("## Interpretation")
    report_lines.append("")
    report_lines.append("This is not evidence that normalization sorted or reversed label words. Normalization preserves word order and only cleans formatting such as underscores, hyphens, slashes, camel case, spaces, and lowercase.")
    report_lines.append("")
    report_lines.append("The likely issue is label/member representation plus semantic closeness. Stored labels use phrasing like `agent_accused_customer_of_rudeness` and `agent_called_customer_rude`, which are better interpreted as `Agent Reported Customer Rudeness`, not a literal confirmed `customer_rude_to_agent` label.")
    report_lines.append("")
    report_lines.append("## Recommended cleanup")
    report_lines.append("")
    report_lines.append("If `base_1657` is confirmed, keep customer-agent complaint labels in `Customer Accused Agent Of Rudeness`, and move agent-perspective customer-rudeness labels into a new manual cluster named `Agent Reported Customer Rudeness`.")
    report_lines.append("")
    report_lines.append("## Evidence files")
    report_lines.append("")
    for filename in [
        "01_exact_customer_rude_to_agent_taxonomy_map.csv",
        "02_exact_customer_rude_to_agent_representative_labels.csv",
        "03_candidate_clusters_found.csv",
        "04_candidate_cluster_members.csv",
        "05_candidate_direction_summary.csv",
        "06_exact_customer_rude_to_agent_app_tags.csv",
        "07_real_call_samples_all_rows.csv",
        "08_real_call_samples_deduped.csv",
        "09_decision_summary.csv",
    ]:
        report_lines.append(f"- `{filename}`")

    report_path = out_dir / "10_investigation_report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"Saved {report_path}")

    # ------------------------------------------------------------------
    # 9. Optional Excel pack.
    # ------------------------------------------------------------------
    excel_path = out_dir / "investigation_pack.xlsx"
    try:
        with pd.ExcelWriter(excel_path, engine="xlsxwriter") as writer:
            exact_taxonomy_df.to_excel(writer, sheet_name="exact_taxonomy", index=False)
            exact_reps_df.to_excel(writer, sheet_name="exact_representatives", index=False)
            exact_app_df.to_excel(writer, sheet_name="exact_app_tags", index=False)
            candidate_clusters_df.to_excel(writer, sheet_name="candidate_clusters", index=False)
            candidate_members_df.to_excel(writer, sheet_name="candidate_members", index=False)
            direction_summary_df.to_excel(writer, sheet_name="direction_summary", index=False)
            calls_dedup_df.to_excel(writer, sheet_name="call_samples_deduped", index=False)
            decision_summary_df.to_excel(writer, sheet_name="decision_summary", index=False)
        print(f"Saved {excel_path}")
    except Exception as exc:
        print(f"Excel export skipped: {exc}")

    print("\nDone.")
    print(f"Output folder: {out_dir.resolve()}")


if __name__ == "__main__":
    main()