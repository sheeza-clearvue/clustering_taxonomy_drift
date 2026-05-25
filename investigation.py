#!/usr/bin/env python3
"""
investigation.py

Read-only investigation for the rude-direction cluster case:

additional_tags / base_1657
Customer Accused Agent Of Rudeness

Checks:
1. Cluster members from local taxonomy DB.
2. Target label occurrences.
3. Real calls from ai-calls-analysis-db where those tags appear.
4. Optional transcript join from separate transcripts table.
5. Exports CSV files for manual decision.

Run:
    python investigation.py --env-file .env --call-table ngp_call_classification --call-id-col call_id --tags-col additional_tags --summary-col call_summary --transcript-table transcripts --transcript-call-id-col call_id --transcript-text-col transcript --sample-per-label 25
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Optional

import pandas as pd
import psycopg2
from dotenv import load_dotenv


CLUSTER_LABELS = [
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

    # Customer was rude / agent accused customer
    ("customer_was_rude", "agent_accused_customer_of_rudeness"),
    ("customer_was_rude", "agent_called_customer_rude"),
    ("customer_was_rude", "agent_confronted_customer_rudeness"),
    ("customer_was_rude", "agent_commented_on_customer_rudeness"),
    ("customer_was_rude", "agent_challenged_customer_politeness"),
    ("customer_was_rude", "agent_challenged_customer_rudeness"),
]


def normalize_label(value: str) -> str:
    value = str(value or "")
    value = value.replace("_", " ").replace("-", " ").replace("/", " ")
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip().lower()


def pg_conn(prefix: str):
    """
    Uses your existing .env keys.

    Taxonomy / local cluster DB:
      LOCAL_PG_HOST
      LOCAL_PG_PORT
      LOCAL_PG_DB
      LOCAL_PG_USER
      LOCAL_PG_PASSWORD

    Real calls / app DB:
      APP_DB_HOST
      APP_DB_PORT
      APP_DB_USER
      APP_DB_PASS
      APP_DB_NAME
    """

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


def direction_guess_from_text(text: str) -> str:
    text = normalize_label(text)

    if not text:
        return "text_blank"

    agent_was_rude_patterns = [
        r"\bcustomer\b.*\b(accused|complained|complaint|said|called|reported|felt|unhappy|perceived)\b.*\bagent\b.*\b(rude|rudeness|impolite|disrespectful|aggressive)\b",
        r"\bclient\b.*\b(accused|complained|complaint|said|called|reported|felt|unhappy|perceived)\b.*\bagent\b.*\b(rude|rudeness|impolite|disrespectful|aggressive)\b",
        r"\bcaller\b.*\b(accused|complained|complaint|said|called|reported|felt|unhappy|perceived)\b.*\bagent\b.*\b(rude|rudeness|impolite|disrespectful|aggressive)\b",
        r"\bagent\b.*\b(rude|rudeness|impolite|disrespectful|aggressive)\b.*\b(customer|client|caller)\b",
        r"\brude\b.*\bagent\b.*\bcomplaint\b",
        r"\bagent\b.*\brude\b.*\bcomplaint\b",
        r"\bprevious agent\b.*\b(rude|rudeness)\b",
    ]

    customer_was_rude_patterns = [
        r"\bagent\b.*\b(accused|said|called|reported|commented|confronted|challenged)\b.*\b(customer|client|caller)\b.*\b(rude|rudeness|impolite|disrespectful|aggressive|politeness)\b",
        r"\b(customer|client|caller)\b.*\b(rude|rudeness|impolite|disrespectful|aggressive)\b.*\bagent\b",
        r"\brude\b.*\b(customer|client|caller)\b.*\bagent\b",
    ]

    for pattern in agent_was_rude_patterns:
        if re.search(pattern, text):
            return "summary_suggests_agent_was_rude"

    for pattern in customer_was_rude_patterns:
        if re.search(pattern, text):
            return "summary_suggests_customer_was_rude"

    return "summary_unclear"


def canonical_raw_label(tag: str, raw_labels: list[str]) -> str:
    tag_clean = str(tag or "").strip().lower()
    tag_norm = normalize_label(tag_clean)

    for raw in raw_labels:
        if tag_clean == raw.lower() or tag_norm == normalize_label(raw):
            return raw

    return tag_clean


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--output-dir", default="rude_direction_investigation")
    parser.add_argument("--transcript-main-join-col", default="filename")
    parser.add_argument("--call-table", default="ngp_call_classification")
    parser.add_argument("--call-id-col", default="call_id")
    parser.add_argument("--tags-col", default="additional_tags")
    parser.add_argument("--summary-col", default="call_summary")

    # Separate transcript table support.
    parser.add_argument("--transcript-table", default="transcripts")
    parser.add_argument("--transcript-call-id-col", default="call_id")
    parser.add_argument("--transcript-text-col", default="transcript")
    parser.add_argument("--no-transcripts", action="store_true")

    parser.add_argument("--sample-per-label", type=int, default=25)

    parser.add_argument("--field-name", default="additional_tags")
    parser.add_argument("--cluster-version", default="20260513_093749")
    parser.add_argument("--cluster-id", default="base_1657")

    args = parser.parse_args()

    load_dotenv(args.env_file)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    label_to_direction = {label: direction for direction, label in CLUSTER_LABELS}
    raw_labels = [label for _, label in CLUSTER_LABELS]
    normalized_labels = [normalize_label(label) for label in raw_labels]

    # ------------------------------------------------------------------
    # 1. Pull taxonomy cluster evidence from local DB.
    # ------------------------------------------------------------------
    cluster_conn = pg_conn("CLUSTER_DB")

    for required_table in [
        "taxonomy_label_cluster_map",
        "taxonomy_clusters",
        "taxonomy_cluster_names",
    ]:
        if not table_exists(cluster_conn, required_table):
            raise ValueError(f"Missing taxonomy table in CLUSTER_DB: {required_table}")

    taxonomy_sql = """
        SELECT
            m.id,
            m.run_id,
            m.field_name,
            m.cluster_version,
            m.final_cluster_id,
            m.final_cluster_source,
            m.base_cluster_id,
            m.strict_graph_community_id,
            m.raw_label,
            m.normalized_label,
            m.value_count,
            n.display_name AS cluster_display_name,
            c.medoid_label,
            c.cluster_size,
            c.total_occurrences,
            c.representative_labels
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
          AND m.cluster_version = %s
          AND m.final_cluster_id = %s
        ORDER BY m.value_count DESC;
    """

    taxonomy_df = pd.read_sql_query(
        taxonomy_sql,
        cluster_conn,
        params=(args.field_name, args.cluster_version, args.cluster_id),
    )

    taxonomy_df["manual_expected_direction"] = (
        taxonomy_df["raw_label"]
        .astype(str)
        .map(label_to_direction)
        .fillna("review_manually")
    )

    taxonomy_df["direction_guess_from_label_text"] = (
        taxonomy_df["normalized_label"]
        .astype(str)
        .map(direction_guess_from_text)
    )

    taxonomy_path = out_dir / "01_taxonomy_cluster_members.csv"
    taxonomy_df.to_csv(taxonomy_path, index=False)

    label_counts_df = taxonomy_df[taxonomy_df["raw_label"].isin(raw_labels)].copy()
    label_counts_path = out_dir / "02_target_label_occurrences.csv"
    label_counts_df.to_csv(label_counts_path, index=False)

    cluster_conn.close()

    print("\nTarget label counts:")
    display_cols = [
        "raw_label",
        "normalized_label",
        "value_count",
        "manual_expected_direction",
        "final_cluster_source",
        "base_cluster_id",
        "cluster_display_name",
        "medoid_label",
    ]
    print(label_counts_df[display_cols].to_string(index=False))

    # ------------------------------------------------------------------
    # 2. Pull real calls from app DB.
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
                    args.transcript_call_id_col,
                    args.transcript_text_col,
                ],
            )

    call_table = quote_table_name(args.call_table)
    call_id_col = quote_ident(args.call_id_col)
    tags_col = quote_ident(args.tags_col)
    summary_col = quote_ident(args.summary_col)

    transcript_cte = ""
    transcript_join = ""
    transcript_select = ""

    if use_transcripts:
        transcript_table = quote_table_name(args.transcript_table)
        transcript_main_join_col = quote_ident(args.transcript_main_join_col)
        transcript_table_join_col = quote_ident(args.transcript_call_id_col)
        transcript_text_col = quote_ident(args.transcript_text_col)

        transcript_cte = f"""
            transcript_agg AS (
                SELECT
                    t.{transcript_table_join_col} AS transcript_join_key,
                    STRING_AGG(t.{transcript_text_col}::text, E'\\n\\n') AS transcript
                FROM {transcript_table} t
                GROUP BY t.{transcript_table_join_col}
            ),
        """

        transcript_join = f"""
            LEFT JOIN transcript_agg tx
            ON tx.transcript_join_key = c.{transcript_main_join_col}
        """

        transcript_select = ", tx.transcript AS transcript"

    match_values = sorted(set([x.lower() for x in raw_labels + normalized_labels]))

    calls_sql = f"""
        WITH
        {transcript_cte}
        exploded AS (
            SELECT
                c.{call_id_col} AS call_id,
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

    if calls_df.empty:
        print("\nNo matching real calls found for the target labels.")
        empty_path = out_dir / "03_real_call_samples_by_tag.csv"
        calls_df.to_csv(empty_path, index=False)
        print(f"Saved empty call sample file: {empty_path}")
        return

    calls_df["canonical_raw_label"] = calls_df["matched_tag"].map(
        lambda x: canonical_raw_label(x, raw_labels)
    )

    calls_df["tag_expected_direction"] = (
        calls_df["canonical_raw_label"]
        .map(label_to_direction)
        .fillna("review_manually")
    )

    calls_df["summary_direction_guess"] = (
        calls_df["call_summary"]
        .fillna("")
        .map(direction_guess_from_text)
    )

    if "transcript" in calls_df.columns:
        calls_df["transcript_direction_guess"] = (
            calls_df["transcript"]
            .fillna("")
            .map(direction_guess_from_text)
        )

    calls_path = out_dir / "03_real_call_samples_by_tag.csv"
    calls_df.to_csv(calls_path, index=False)

    # ------------------------------------------------------------------
    # 3. Decision summary.
    # ------------------------------------------------------------------
    group_cols = [
        "canonical_raw_label",
        "tag_expected_direction",
        "summary_direction_guess",
    ]

    if "transcript_direction_guess" in calls_df.columns:
        group_cols.append("transcript_direction_guess")

    decision_df = (
        calls_df.groupby(group_cols, dropna=False)
        .agg(
            sampled_calls=("call_id", "nunique"),
            example_call_id=("call_id", "first"),
            example_summary=("call_summary", "first"),
        )
        .reset_index()
        .sort_values(
            ["tag_expected_direction", "canonical_raw_label", "sampled_calls"],
            ascending=[True, True, False],
        )
    )

    decision_path = out_dir / "04_decision_summary.csv"
    decision_df.to_csv(decision_path, index=False)

    # ------------------------------------------------------------------
    # 4. Label-level sampled call counts.
    # ------------------------------------------------------------------
    sampled_counts_df = (
        calls_df.groupby(["canonical_raw_label", "tag_expected_direction"], dropna=False)
        .agg(
            sampled_calls=("call_id", "nunique"),
            matched_tag_examples=("matched_tag", lambda x: " | ".join(sorted(set(map(str, x)))[:10])),
        )
        .reset_index()
        .sort_values(["tag_expected_direction", "sampled_calls"], ascending=[True, False])
    )

    sampled_counts_path = out_dir / "05_sampled_call_counts_by_label.csv"
    sampled_counts_df.to_csv(sampled_counts_path, index=False)

    print("\nSaved:")
    print(taxonomy_path)
    print(label_counts_path)
    print(calls_path)
    print(decision_path)
    print(sampled_counts_path)

    print("\nDecision summary:")
    print(decision_df.to_string(index=False))


if __name__ == "__main__":
    main()