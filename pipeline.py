#!/usr/bin/env python3
"""
pipeline.py

Full production-style taxonomy clustering pipeline.

Pipeline:
    1. Load the FULL input dataset. No sampling.
    2. Normalize labels.
    3. Create/reuse local embeddings with metadata validation.
    4. Run base HDBSCAN semantic clustering.
    5. Send HDBSCAN anomalies/noise to anomaly bucket.
    6. Run strict graph recovery only on the anomaly bucket.
    7. Generate final production mapping.
    8. Optionally generate HTML cluster views.
    9. Optionally auto-tune HDBSCAN parameters.

Outputs:
    - base clustered values
    - base cluster summary
    - base anomaly bucket
    - strict graph recovered anomaly clusters
    - strict graph summary
    - strict graph edges
    - true anomaly review queue
    - production cluster mapping
    - production cluster summary
    - JSON run report
    - optional searchable HTML table
    - optional 3D UMAP cluster visualization
    - optional embedding cache + metadata

Expected input columns:
    Required:
        source_column
        raw_value

    Optional:
        value_count
        normalized_value

Install:
    pip install pandas numpy scikit-learn sentence-transformers networkx umap-learn plotly psycopg2-binary python-dotenv

Optional:
    pip install hdbscan

Example using DB:
    python pipeline.py \
        --from-db \
        --env-file .env \
        --db-query-file full_labels_query.sql \
        --base-output-dir taxonomy_cluster_output \
        --batch-size 128 \
        --reuse-embeddings \
        --embeddings-cache-name main_reason \
        --generate-html \
        --min-cluster-size 8 \
        --min-samples 3 \
        --graph-k-values 7 \
        --graph-threshold-values 0.85

Example with auto-tune:
    python pipeline.py \
        --from-db \
        --env-file .env \
        --db-query-file full_labels_query.sql \
        --base-output-dir taxonomy_cluster_output \
        --batch-size 128 \
        --reuse-embeddings \
        --embeddings-cache-name main_reason \
        --auto-tune-hdbscan \
        --generate-html

Recommended stronger model test:
    python pipeline.py \
        --from-db \
        --env-file .env \
        --db-query-file full_labels_query.sql \
        --base-output-dir taxonomy_cluster_output \
        --model BAAI/bge-small-en-v1.5 \
        --batch-size 128

Important:
    This script does NOT sample your data.
    It processes the whole input file returned by the SQL query.
    Embedding reuse is only allowed when cached metadata exactly matches the current labels.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import subprocess
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any
import requests
import networkx as nx
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import normalize
from sklearn.metrics import silhouette_score

try:
    import faiss
except:
    faiss = None

try:
    import torch
except ImportError:
    torch = None



from sklearn.cluster import HDBSCAN as HDBSCAN_CLASS


try:
    from sentence_transformers import SentenceTransformer
except ImportError as exc:
    raise RuntimeError(
        "sentence-transformers is missing. Install with:\n"
        "pip install sentence-transformers"
    ) from exc

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    import umap
except ImportError:
    umap = None

try:
    import plotly.express as px
except ImportError:
    px = None
try:
    import xlsxwriter
except ImportError:
    raise RuntimeError("Install xlsxwriter: pip install xlsxwriter")


def resolve_torch_device(device: str) -> str:
    requested = str(device or "auto").strip().lower()

    if requested == "auto":
        if torch is not None and torch.cuda.is_available():
            return "cuda"
        return "cpu"

    if requested in {"npu", "openvino-gpu", "openvino-cpu"}:
        if importlib.util.find_spec("openvino") is None or importlib.util.find_spec("optimum.intel") is None:
            raise RuntimeError(
                f"{requested} was requested but OpenVINO/Optimum Intel is not installed. "
                "Install with: pip install \"sentence-transformers[openvino]\""
            )
        return requested

    if requested.startswith("cuda"):
        if torch is None:
            raise RuntimeError("PyTorch is not installed, so CUDA embeddings cannot be used.")
        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA was requested but this Python environment cannot see a CUDA GPU. "
                "Install a CUDA-enabled PyTorch build and NVIDIA drivers, or use --device cpu."
            )
        return requested

    if requested != "cpu":
        raise ValueError("Unsupported --device value. Use auto, cpu, cuda, cuda:N, npu, openvino-gpu, or openvino-cpu.")

    return "cpu"


def print_acceleration_status(device: str) -> None:
    if torch is None:
        print("PyTorch not installed; embedding acceleration unavailable.")
    elif device in {"npu", "openvino-gpu", "openvino-cpu"}:
        ov_device = {"npu": "NPU", "openvino-gpu": "GPU", "openvino-cpu": "CPU"}[device]
        print(f"Embedding device: {ov_device} via OpenVINO")
    elif device.startswith("cuda"):
        device_index = int(device.split(":", 1)[1]) if ":" in device else torch.cuda.current_device()
        print(f"Embedding device: {device} ({torch.cuda.get_device_name(device_index)})")
    else:
        print("Embedding device: cpu")

    if faiss is None:
        print("FAISS not installed; graph kNN will use sklearn CPU fallback.")
    elif hasattr(faiss, "StandardGpuResources"):
        print("FAISS GPU support detected; graph kNN will use GPU when possible.")
    else:
        print("FAISS installed without GPU support; graph kNN will use FAISS CPU.")


def build_faiss_index(dim: int, prefer_gpu: bool):
    index = faiss.IndexFlatIP(dim)
    if not prefer_gpu:
        return index, "FAISS CPU"

    if hasattr(faiss, "StandardGpuResources"):
        try:
            resources = faiss.StandardGpuResources()
            gpu_index = faiss.index_cpu_to_gpu(resources, 0, index)
            return gpu_index, "FAISS GPU"
        except Exception as exc:
            print(f"FAISS GPU index unavailable, falling back to CPU: {exc}")

    return index, "FAISS CPU"


def build_sentence_transformer(model_name: str, device: str) -> SentenceTransformer:
    if device in {"npu", "openvino-gpu", "openvino-cpu"}:
        ov_device = {"npu": "NPU", "openvino-gpu": "GPU", "openvino-cpu": "CPU"}[device]
        try:
            return SentenceTransformer(
                model_name,
                backend="openvino",
                model_kwargs={"device": ov_device},
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load the embedding model on OpenVINO {ov_device}. "
                "Install the OpenVINO extras with: pip install \"sentence-transformers[openvino]\". "
                "If the model does not export or compile for that device, use --device openvino-gpu, --device cpu, or --device cuda."
            ) from exc

    return SentenceTransformer(model_name, device=device)
FIELD_EMBEDDING_CONTEXT = {
    "call_type": "call type category",
    "call_type_sub": "secondary call type category",
    "main_reason": "main business reason for call",
    "main_reason_sub": "secondary business reason for call",
    "outcome": "call result or commercial outcome",
    "outcome_sub": "secondary call result",
    "tags": "structured call modifier",
    "additional_tags": "free-form business intelligence tag",
    "descriptive_keywords": "search keyword or notable call topic",
    "coaching_tags": "agent coaching tag indicating either a skill weakness requiring improvement (Coaching_Poor_* or Coaching_Unclear_*) or a demonstrated strength (Training_Good_* or Training_Clear_*)",
    "next_step": "next action after call",
    "tone": "customer tone or sentiment",
    "outcome_base": "broad outcome family",
    "call_type_base": "broad call type family",
}
FIELD_BUSINESS_DEFINITIONS = {
    "call_type": (
        "Main broad category describing what type of call occurred in the NGP B2B energy sales lifecycle. "
        "This should capture the dominant call mode, such as Cold Call, Prospecting, Pitch, Discovery, "
        "Renewal, Proposal, Closing, Admin, Complaint, Service, LOA Chase, Contract Chase, or Close Chase. "
        "LOA Chase means following up to get the Letter of Authority signed or returned. "
        "Contract Chase means following up on a contract/proposal document that has already been sent. "
        "Close Chase means post-proposal follow-up to secure signed contract return. "
        "This field describes the call type, not the final result."
    ),

    "call_type_sub": (
        "Secondary call categories that occurred in the call but were not the dominant call type. "
        "Use this to capture supporting stages or side interactions, such as Admin, Risk, Discovery, "
        "Complaint, Contract Chase, LOA Chase, or Service, when they were present but not the main call purpose."
    ),

    "main_reason": (
        "Primary specific business reason for the call. This explains why the call happened or what the main "
        "topic was. Examples include Rates Discussion, Bill Query, Contract Review, Contract Amendment, "
        "Contract Chase, LOA Follow-Up, Renewal Discussion, Payment Issue, Cancellation, Complaint Billing, "
        "Customer Timing Issue, or CoT issue. Bare vague bases like Contract, Rates, Complaint, Amend, or Agreed "
        "should be treated as incomplete unless qualified."
    ),

    "main_reason_sub": (
        "Secondary business reasons discussed in the call. These are additional topics that matter but did not "
        "outrank the primary main_reason by duration, business impact, or emphasis."
    ),

    "outcome": (
        "Most commercially significant result of the call. Deal lifecycle outcomes must outrank administrative "
        "actions. Examples include customer_agreed_in_principle, customer_awaiting_contract, "
        "customer_seeks_internal_approval, customer_recv_contract, ngp_awaiting_contract_return, sale_closed, "
        "Information_Gathered, Gatekeeper_Blocked, Not_Interested, Voicemail, No_Answer, Callback_Scheduled, "
        "Information_Sent, or Follow_Up_Scheduled. If a customer is engaged with real proposal prices, the "
        "outcome should reflect commercial progression, not merely that an email was sent."
    ),

    "outcome_sub": (
        "Secondary call results that support the main outcome. Use this for lower-priority results such as "
        "Information Sent, Callback Requested, Follow-Up Scheduled, Customer Action Required, Voicemail, "
        "Gatekeeper Blocked, or Admin Update when a stronger commercial outcome is also present."
    ),

    "tags": (
        "Reusable structured modifiers that describe the state, relationship, or context of the call. "
        "Examples include Warm Lead, Cold Call, Renewal, Follow Up, Awaiting, Risk, Compliance, Chase, "
        "Dead Lead, Customer Unhappy, Contract modifier, or LOA progress marker. Tags should modify the "
        "classification, not replace call_type, main_reason, or outcome."
    ),

    "additional_tags": (
        "Free-form business intelligence tags for cases that do not fit strict base-plus-two-word tagging. "
        "This includes condition_* tags explaining why a conditional sale is blocked, open_sale_high_urgency, "
        "discover_opportunities, discovery_* revenue signals, missed_* agent failure signals, competitor pain, "
        "multi-site potential, internal review flags, technical issues, language barrier, escalation, or other "
        "high-value searchable edge cases."
    ),

    "descriptive_keywords": (
        "Searchable keywords describing notable entities, objections, sales signals, business facts, competitor "
        "mentions, rates, suppliers, MPAN/MPRN references, contract dates, customer concerns, or important call "
        "moments. These support search and analysis, not final classification."
    ),

    "coaching_tags": (
        "Agent performance and training tags. Use for objection handling, missed opportunity, poor close, "
        "rapport issue, compliance concern, call efficiency, time wasting, unclear pitch, strong discovery, "
        "good commercial acumen, or process adherence."
    ),

    "next_step": (
        "Operational next action required after the call. Examples include send LOA, chase LOA return, send bill "
        "request, send proposal, send contract, chase contract return, schedule callback, follow up with Decision "
        "Maker, manager review, or no action. LOA chase and contract chase must stay separate: LOA chase is before "
        "quotes/proposal authority is secured; contract chase is after a contract/proposal document exists."
    ),

    "tone": (
        "Customer tone or sentiment during the call in a short label, such as Friendly, Interested, Engaged, "
        "Neutral, Rushed, Skeptical, Dismissive, Hostile, Cold, Warm, or Frustrated."
    ),

    "outcome_base": (
        "Broad outcome family used to group detailed outcome labels. Examples include Sale, Follow Up, "
        "Information, Gatekeeper, No Answer, Voicemail, Not Interested, Failed, Contract, Customer, Lead, "
        "Unproductive, or Positive."
    ),

    "call_type_base": (
        "Broad call-type family used to group detailed call_type labels. Examples include Cold Call, Pitch, "
        "Discovery, Prospecting, Renewal, Closing, Admin, Service, Complaint, Contract Chase, LOA Chase, "
        "Close Chase, Fraud, Internal, or Account Management."
    ),
}
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

_HDBSCAN_METRIC           = "euclidean"
_TEXT_MODE                = "field_label"

_GRAPH_RESOLUTION         = 1.15
_GRAPH_MIN_COMMUNITY_SIZE = 3

_HTML_MAX_POINTS          = 20000
_CLUSTER_RUN_TABLE        = "taxonomy_cluster_runs"
_CLUSTER_TABLE            = "taxonomy_clusters"
_CLUSTER_LABEL_MAP_TABLE  = "taxonomy_label_cluster_map"
_PG_IDENT_RE              = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


# ---------------------------------------------------------------------
# Basic text handling
# ---------------------------------------------------------------------

def normalize_label(value: str) -> str:
    value = str(value or "")
    value = value.replace("_", " ").replace("-", " ").replace("/", " ")
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip().lower()

def coaching_aware_embedding_text(label: str) -> str:
    label_lower = label.lower()

    if any(w in label_lower for w in ["fraud", "compliance", "deceptive", "time_gaming"]):
        tier = "COMPLIANCE_RISK"
    elif any(w in label_lower for w in ["non_business", "personal_call", "audio_quality", "data_quality", "time_management"]):
        tier = "PROCESS_DISCIPLINE"
    else:
        tier = "AGENT_SKILL"

    if any(w in label_lower for w in ["good", "training", "clear", "strength"]):
        direction = "STRENGTH_DEMONSTRATED"
    elif any(w in label_lower for w in ["poor", "coaching", "unclear", "weakness"]):
        direction = "IMPROVEMENT_NEEDED"
    else:
        direction = "NEUTRAL"

    skill = label
    for prefix in ["Training_Good_", "Training_Clear_", "Coaching_Poor_", "Coaching_Unclear_", "Coaching_", "Training_"]:
        if label.startswith(prefix):
            skill = label[len(prefix):]
            break

    return f"tier: {tier} | skill: {skill} | direction: {direction} | label: {normalize_label(label)}"
def next_step_aware_embedding_text(label: str) -> str:
    """
    Inject outcome polarity so opposite next steps don't cluster.
    """
    label_lower = label.lower()
    
    # Detect polarity
    if any(w in label_lower for w in ['sent', 'scheduled', 'confirmed', 'received', 'quote', 'proposal', 'pending', 'closed', 'date_found']):
        polarity = 'FORWARD_PROGRESS'
    elif any(w in label_lower for w in ['blocked', 'do_not_call', 'not_interested', 'wrong_number', 'ivr_failure']):
        polarity = 'DEAD_END'
    elif any(w in label_lower for w in ['research', 'try_later', 'internal', 'transfer', 'admin', 'message', 'na']):
        polarity = 'HOLDING_PATTERN'
    else:
        polarity = 'UNKNOWN'
    
    # Construct embedding text
    return f"next_step_outcome: {polarity} | label: {normalize_label(label)}"

# Examples:
texts = [
    next_step_aware_embedding_text("DM_Name_Secured"),      # → "next_step_outcome: FORWARD_PROGRESS | label: dm name secured"
    next_step_aware_embedding_text("Callback_Scheduled"),   # → "next_step_outcome: FORWARD_PROGRESS | label: callback scheduled"
    next_step_aware_embedding_text("Access_Blocked"),       # → "next_step_outcome: DEAD_END | label: access blocked"
    next_step_aware_embedding_text("Try_Later"),            # → "next_step_outcome: HOLDING_PATTERN | label: try later"
]
"""
def embedding_text(source_column: str, raw_value: str, mode: str = "field_label") -> str:
    cleaned = normalize_label(raw_value)
    source_column_clean = str(source_column or "").strip()

    if mode == "label_only":
        return cleaned

    if mode == "field_label":
        if source_column_clean == "coaching_tags":
            return coaching_aware_embedding_text(raw_value)
        if source_column_clean == "next_step":
            return next_step_aware_embedding_text(raw_value)

        short_context = FIELD_EMBEDDING_CONTEXT.get(
            source_column_clean,
            "call classification field",
        )
        return (
            f"field: {source_column_clean}; "
            f"meaning: {short_context}; "
            f"label: {cleaned}"
        )

    raise ValueError(f"Unknown embedding text mode: {mode}")
"""
def embedding_text(source_column: str, raw_value: str, mode: str = "field_label") -> str:
    cleaned = normalize_label(raw_value)
    source_column_clean = str(source_column or "").strip()

    if mode == "label_only":
        return cleaned

    if mode == "field_label":
        if source_column_clean == "coaching_tags":
            return coaching_aware_embedding_text(raw_value)

        if source_column_clean == "next_step":
            return next_step_aware_embedding_text(raw_value)

        business_definition = FIELD_BUSINESS_DEFINITIONS.get(
            source_column_clean,
            FIELD_EMBEDDING_CONTEXT.get(source_column_clean, "call classification field"),
        )

        return (
            f"field: {source_column_clean}; "
            f"business_definition: {business_definition}; "
            f"label: {cleaned}"
        )

    raise ValueError(f"Unknown embedding text mode: {mode}")

def safe_filename_part(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value))
    return value.strip("_")[:80] or "value"

# ---------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------

def prepare_loaded_df(df: pd.DataFrame) -> pd.DataFrame:
    required = {"source_column", "raw_value"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Input data missing required columns: {sorted(missing)}")

    if "value_count" not in df.columns:
        df["value_count"] = 1

    if "normalized_value" not in df.columns:
        df["normalized_value"] = df["raw_value"].map(normalize_label)

    df["source_column"] = df["source_column"].fillna("unknown").astype(str)
    df["raw_value"] = df["raw_value"].fillna("").astype(str)
    df["normalized_value"] = df["normalized_value"].fillna("").astype(str)
    df["value_count"] = pd.to_numeric(df["value_count"], errors="coerce").fillna(1).astype(int)

    df = df[df["raw_value"].str.strip() != ""].copy()
    df = df.reset_index(drop=True)
    df["global_label_id"] = np.arange(len(df))

    return df


def load_input(input_path: Path) -> pd.DataFrame:
    return prepare_loaded_df(pd.read_csv(input_path))


def load_from_app_db(args: argparse.Namespace) -> pd.DataFrame:
    """
    Loads full label values directly from the app DB.

    Supported modes:
      1. --db-query-file custom_query.sql
         Query must return: source_column, raw_value, value_count

      2. --db-table table_name --db-label-columns col1,col2,col3
         Script builds a UNION ALL aggregation across those columns.

    .env expected keys:
      APP_DB_HOST
      APP_DB_PORT
      APP_DB_USER
      APP_DB_PASS
      APP_DB_NAME
    """
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is missing. Install with: pip install psycopg2-binary")

    if load_dotenv is not None:
        load_dotenv(args.env_file)

    host = os.getenv("APP_DB_HOST")
    port = os.getenv("APP_DB_PORT", "5432")
    user = os.getenv("APP_DB_USER")
    password = os.getenv("APP_DB_PASS")
    dbname = os.getenv("APP_DB_NAME")

    missing = [
        k for k, v in {
            "APP_DB_HOST": host,
            "APP_DB_USER": user,
            "APP_DB_PASS": password,
            "APP_DB_NAME": dbname,
        }.items()
        if not v
    ]

    if missing:
        raise ValueError(f"Missing DB env values: {missing}")

    if not args.db_query_file:
        raise ValueError("--db-query-file is required when using --from-db.")

    query = Path(args.db_query_file).read_text(encoding="utf-8")

    print("\nConnecting to APP DB and loading FULL label dataset...")
    print(f"Host: {host}:{port}")
    print(f"Database: {dbname}")
    print("Sampling: DISABLED. Query should return the full grouped label set.")

    conn = psycopg2.connect(
        host=host,
        port=int(port),
        user=user,
        password=password,
        dbname=dbname,
    )

    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()

    return prepare_loaded_df(df)

# ---------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------

def create_embeddings(
    df: pd.DataFrame,
    model_name: str,
    batch_size: int,
    text_mode: str,
    device: str,
    texts: "list[str] | None" = None,
) -> np.ndarray:
    print(f"\nLoading embedding model: {model_name}")
    model = build_sentence_transformer(model_name, device)

    if texts is None:
        texts = [
            embedding_text(row.source_column, row.raw_value, mode=text_mode)
            for row in df.itertuples(index=False)
        ]

    print(f"Embedding FULL dataset: {len(texts):,} labels on {device}")
    X = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )

    return normalize(np.asarray(X, dtype=np.float32))

# ---------------------------------------------------------------------
# Auto tuning and HTML visualization
# ---------------------------------------------------------------------

def auto_tune_hdbscan(
    df: pd.DataFrame,
    X: np.ndarray,
    output_dir: Path,
    run_id: str,
    min_cluster_size_values: list[int],
    min_samples_values: list[int],
    seed: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Searches multiple HDBSCAN parameter combinations and returns:
      - base_values_df for the best config
      - best_config dict
      - X_for_hdbscan used by the best config

    Scoring goal:
      - prefer good silhouette where possible
      - avoid too many anomalies
      - avoid giant over-merged clusters
      - avoid too few clusters
    """
    n_points = len(df)
    if n_points < 10:
        print("Dataset too small for auto-tuning. Falling back to default HDBSCAN params.")
        base_values_df = run_hdbscan(df, X, min_cluster_size=5, min_samples=2, metric=_HDBSCAN_METRIC)
        return base_values_df, {
            "auto_tuned": False,
            "reason": "dataset_too_small",
            "min_cluster_size": 5,
            "min_samples": 2,
        }

    # Keep only sensible values for this dataset.
    min_cluster_size_values = [
        v for v in min_cluster_size_values
        if 2 <= v < max(10, n_points // 2)
    ]
    min_samples_values = [v for v in min_samples_values if v >= 1]

    if not min_cluster_size_values:
        min_cluster_size_values = [5]
    if not min_samples_values:
        min_samples_values = [2]

    print("\nAuto-tuning HDBSCAN parameters...")
    print(f"min_cluster_size_values={min_cluster_size_values}")
    print(f"min_samples_values={min_samples_values}")

    results: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None

    for min_cluster_size in min_cluster_size_values:
        for min_samples in min_samples_values:
            if min_samples > min_cluster_size:
                continue

            try:
                clusterer = HDBSCAN_CLASS(
                    min_cluster_size=int(min_cluster_size),
                    min_samples=int(min_samples),
                    metric=_HDBSCAN_METRIC,
                    cluster_selection_method="eom",
                )
                labels = clusterer.fit_predict(X)

                n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
                anomaly_count = int((labels == -1).sum())
                anomaly_ratio = anomaly_count / n_points if n_points else 0.0
                clustered_mask = labels != -1
                clustered_count = int(clustered_mask.sum())

                if n_clusters < 2 or clustered_count < max(10, min(50, n_points // 10)):
                    sil = -1.0
                else:
                    # Sample silhouette to avoid making tuning painfully slow on large fields.
                    sil = float(
                        silhouette_score(
                            X[clustered_mask],
                            labels[clustered_mask],
                            metric=_HDBSCAN_METRIC,
                            sample_size=min(3000, clustered_count),
                            random_state=seed,
                        )
                    )

                grouped_labels_arr = labels[labels != -1]
                largest_cluster_size = int(np.bincount(grouped_labels_arr).max()) if len(grouped_labels_arr) else 0
                largest_cluster_ratio = largest_cluster_size / n_points if n_points else 0.0

                # Balanced score:
                # - reward silhouette
                # - reward reasonable coverage
                # - punish giant clusters
                # - punish extreme anomaly ratios
                # - punish very low number of clusters
                coverage = 1.0 - anomaly_ratio
                too_many_anomalies_penalty = max(0.0, anomaly_ratio - 0.65) * 0.8
                too_few_anomalies_penalty = max(0.0, 0.03 - anomaly_ratio) * 1.0
                giant_cluster_penalty = max(0.0, largest_cluster_ratio - 0.20) * 1.2
                too_few_clusters_penalty = max(0, 8 - n_clusters) * 0.03

                score = (
                    sil
                    + coverage * 0.25
                    - too_many_anomalies_penalty
                    - too_few_anomalies_penalty
                    - giant_cluster_penalty
                    - too_few_clusters_penalty
                )

                row = {
                    "min_cluster_size": int(min_cluster_size),
                    "min_samples": int(min_samples),
                    "metric": _HDBSCAN_METRIC,
                    "n_clusters": int(n_clusters),
                    "clustered_count": int(clustered_count),
                    "anomaly_count": int(anomaly_count),
                    "anomaly_ratio": float(anomaly_ratio),
                    "largest_cluster_size": int(largest_cluster_size),
                    "largest_cluster_ratio": float(largest_cluster_ratio),
                    "silhouette": float(sil),
                    "score": float(score),
                }
                results.append(row)

                if best is None or score > best["score"]:
                    best = {**row, "labels": labels}

                print(
                    f"mcs={min_cluster_size}, ms={min_samples}, "
                    f"clusters={n_clusters}, anomalies={anomaly_count}, "
                    f"largest_ratio={largest_cluster_ratio:.3f}, "
                    f"sil={sil:.3f}, score={score:.3f}"
                )

            except Exception as exc:
                print(
                    f"Failed HDBSCAN combo min_cluster_size={min_cluster_size}, "
                    f"min_samples={min_samples}: {exc}"
                )

    search_df = pd.DataFrame(results).sort_values("score", ascending=False)
    search_path = output_dir / f"hdbscan_auto_tune_search_{run_id}.csv"
    search_df.to_csv(search_path, index=False)

    if best is None:
        raise RuntimeError("Auto-tune could not find a valid HDBSCAN setup.")

    print("\nBest HDBSCAN auto-tune config:")
    for k, v in best.items():
        if k != "labels":
            print(f"{k}: {v}")
    print(f"Saved HDBSCAN auto-tune search: {search_path}")

    out = df.copy()
    out["base_cluster_id"] = best["labels"]
    out["base_is_anomaly"] = out["base_cluster_id"].eq(-1)
    out["base_cluster_probability"] = np.nan

    best_config = {k: v for k, v in best.items() if k != "labels"}
    best_config["auto_tuned"] = True
    best_config["search_output"] = str(search_path)

    return out, best_config

def generate_cluster_html_views(
    final_mapping_df: pd.DataFrame,
    X: np.ndarray,
    run_id: str,
    output_dir: Path,
    max_points: int,
    seed: int,
) -> dict[str, str]:
    outputs: dict[str, str] = {}

    if px is None:
        print("3D cluster plot skipped: plotly not installed (pip install plotly)")
        return outputs

    if umap is None:
        print("3D cluster plot skipped: umap-learn not installed (pip install umap-learn)")
        return outputs

    if final_mapping_df is None or final_mapping_df.empty:
        print("3D cluster plot skipped: final mapping is empty.")
        return outputs

    output_dir.mkdir(parents=True, exist_ok=True)

    print("\nGenerating 3D UMAP cluster view...")

    # -----------------------------
    # 3D Plotly cluster scatter
    # -----------------------------
    plot_df = final_mapping_df.copy()

    if "global_label_id" not in plot_df.columns:
        print("3D cluster plot skipped: global_label_id column is missing.")
        return outputs

    # Keep only rows with valid global_label_id values.
    plot_df["global_label_id"] = pd.to_numeric(
        plot_df["global_label_id"],
        errors="coerce",
    )

    plot_df = plot_df.dropna(subset=["global_label_id"]).copy()
    plot_df["global_label_id"] = plot_df["global_label_id"].astype(int)

    # Prevent invalid indexing into X.
    plot_df = plot_df[
        (plot_df["global_label_id"] >= 0)
        & (plot_df["global_label_id"] < len(X))
    ].copy()

    if plot_df.empty:
        print("3D cluster plot skipped: no valid rows after global_label_id validation.")
        return outputs

    if len(plot_df) > max_points:
        sampled_note = (
            f"Sampled {max_points:,} of {len(final_mapping_df):,} labels "
            f"for browser performance."
        )

        if "value_count" in plot_df.columns:
            weights = (
                pd.to_numeric(plot_df["value_count"], errors="coerce")
                .replace([np.inf, -np.inf], np.nan)
                .fillna(1)
                .clip(lower=1)
            )

            try:
                plot_df = plot_df.sample(
                    n=max_points,
                    random_state=seed,
                    weights=weights,
                    replace=False,
                )
            except ValueError as exc:
                print(
                    "Weighted plot sampling failed, falling back to unweighted sample: "
                    f"{exc}"
                )
                plot_df = plot_df.sample(
                    n=max_points,
                    random_state=seed,
                    replace=False,
                )
        else:
            plot_df = plot_df.sample(
                n=max_points,
                random_state=seed,
                replace=False,
            )

        if "value_count" in plot_df.columns:
            plot_df = plot_df.sort_values("value_count", ascending=False)

        X_plot = X[plot_df["global_label_id"].astype(int).to_numpy()]

    else:
        X_plot = X[plot_df["global_label_id"].astype(int).to_numpy()]
        sampled_note = f"Showing all {len(plot_df):,} labels."

    if len(plot_df) < 3:
        print("3D cluster plot skipped: need at least 3 valid points for UMAP.")
        return outputs

    n_neighbors = max(5, min(30, int(math.sqrt(len(plot_df)))))
    n_neighbors = min(n_neighbors, max(2, len(plot_df) - 1))

    print(
        f"Generating 3D UMAP HTML plot: "
        f"{len(plot_df):,} points, n_neighbors={n_neighbors}"
    )

    reducer = umap.UMAP(
        n_neighbors=n_neighbors,
        n_components=3,
        min_dist=0.40,
        spread=2.0,
        metric="cosine",
        random_state=seed,
    )

    X_3d = reducer.fit_transform(X_plot)

    plot_df["x"] = X_3d[:, 0]
    plot_df["y"] = X_3d[:, 1]
    plot_df["z"] = X_3d[:, 2]

    if "final_cluster_id" in plot_df.columns:
        plot_df["final_cluster_id"] = plot_df["final_cluster_id"].astype(str)
    else:
        plot_df["final_cluster_id"] = "unknown"

    hover_cols = [
        c for c in [
            "source_column",
            "raw_value",
            "normalized_value",
            "value_count",
            "final_cluster_source",
            "final_cluster_id",
            "final_is_true_anomaly",
            "base_cluster_id",
            "strict_graph_community_id",
        ]
        if c in plot_df.columns
    ]

    fig = px.scatter_3d(
        plot_df,
        x="x",
        y="y",
        z="z",
        color="final_cluster_id",
        hover_data=hover_cols,
        size=[5] * len(plot_df),
        opacity=0.78,
        title=f"Final Taxonomy Clusters - {run_id}<br><sup>{sampled_note}</sup>",
    )

    fig.update_traces(
        marker=dict(
            line=dict(
                width=0.1,
                color="black",
            )
        )
    )

    fig.update_layout(
        width=1900,
        height=1000,
        showlegend=True,
        margin=dict(l=0, r=350, t=80, b=0),
        legend=dict(
            title="Cluster ID",
            x=1.02,
            y=1,
            xanchor="left",
            yanchor="top",
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="black",
            borderwidth=1,
            font=dict(size=10),
            itemsizing="constant",
        ),
        scene=dict(
            xaxis_title="UMAP Axis 1",
            yaxis_title="UMAP Axis 2",
            zaxis_title="UMAP Axis 3",
        ),
    )

    plot_path = output_dir / f"final_cluster_3d_{run_id}.html"
    fig.write_html(plot_path)

    outputs["html_3d_plot"] = str(plot_path)

    print(f"Saved 3D cluster plot: {plot_path}")

    return outputs
# ---------------------------------------------------------------------
# Stage 1: HDBSCAN base clustering
# ---------------------------------------------------------------------

def run_hdbscan(
    df: pd.DataFrame,
    X_for_cluster: np.ndarray,
    min_cluster_size: int,
    min_samples: int | None,
    metric: str,
) -> pd.DataFrame:
    print(
        f"\nRunning base HDBSCAN on FULL dataset: "
        f"min_cluster_size={min_cluster_size}, min_samples={min_samples}, metric={metric}"
    )

    clusterer = HDBSCAN_CLASS(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric=metric,
        cluster_selection_method="eom",
     
    )

    labels = clusterer.fit_predict(X_for_cluster)

    out = df.copy()
    out["base_cluster_id"] = labels
    out["base_is_anomaly"] = out["base_cluster_id"].eq(-1)

    if hasattr(clusterer, "probabilities_"):
        out["base_cluster_probability"] = clusterer.probabilities_
    else:
        out["base_cluster_probability"] = np.nan

    return out

def summarize_base_clusters(values_df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for cluster_id, g in values_df.groupby("base_cluster_id", dropna=False):
        labels = g["raw_value"].astype(str).tolist()
        rows.append(
            {
                "base_cluster_id": int(cluster_id),
                "is_anomaly": int(cluster_id) == -1,
                "label_count": len(g),
                "total_occurrences": int(g["value_count"].sum()),
                "source_columns": " | ".join(sorted(g["source_column"].astype(str).unique())),
                "sample_labels": " | ".join(labels[:25]),
            }
        )

    return pd.DataFrame(rows).sort_values(
        ["is_anomaly", "label_count", "total_occurrences"],
        ascending=[True, False, False],
    )

# ---------------------------------------------------------------------
# Stage 2: Strict graph recovery on anomaly bucket only
# ---------------------------------------------------------------------
def nearest_neighbor_tables(X: np.ndarray, max_k: int) -> tuple[np.ndarray, np.ndarray]:
    n = len(X)
    if n < 2:
        raise ValueError("Need at least 2 labels for nearest neighbors.")

    k = min(max_k + 1, n)

    X = np.asarray(X, dtype=np.float32)

    if faiss is not None:
        prefer_gpu = torch is not None and torch.cuda.is_available()
        dim = X.shape[1]
        index, index_name = build_faiss_index(dim, prefer_gpu=prefer_gpu)
        print(f"Using {index_name} for kNN search...")

        index.add(X)
        similarities, indices = index.search(X, k)

        return indices, similarities

    print("FAISS not installed. Falling back to sklearn brute kNN...")

    nn = NearestNeighbors(
        n_neighbors=k,
        metric="cosine",
        algorithm="brute",
    )
    nn.fit(X)

    distances, indices = nn.kneighbors(X)
    similarities = 1.0 - distances

    return indices, similarities
def build_strict_graph(
    df: pd.DataFrame,
    indices: np.ndarray,
    similarities: np.ndarray,
    k_neighbors: int,
    similarity_threshold: float,
    mutual_knn: bool,
    same_field_only: bool,
    return_edges: bool = True,
) -> tuple[nx.Graph, pd.DataFrame]:
    n = len(df)
    k = min(k_neighbors + 1, indices.shape[1])

    src_cols = df["source_column"].astype(str).tolist()
    raw_vals = df["raw_value"].tolist()
    gbl_ids = df["global_label_id"].astype(int).tolist()

    G = nx.Graph()
    G.add_nodes_from(range(n))

    neighbor_sets: dict[int, set[int]] = {}
    directed_candidates: list[tuple[int, int, int, float, str, str]] = []

    for i in range(n):
        source_field = src_cols[i]
        current_set: set[int] = set()

        for rank in range(1, k):
            j = int(indices[i, rank])
            sim = float(similarities[i, rank])

            if sim < similarity_threshold:
                continue

            target_field = src_cols[j]

            if same_field_only and source_field != target_field:
                continue

            current_set.add(j)
            directed_candidates.append(
                (i, j, rank, sim, source_field, target_field)
            )

        neighbor_sets[i] = current_set

    edge_rows: list[dict[str, Any]] = []
    seen_edges: set[tuple[int, int]] = set()

    for i, j, rank, sim, source_field, target_field in directed_candidates:
        if mutual_knn and i not in neighbor_sets.get(j, ()):
            continue

        edge = tuple(sorted((i, j)))

        if edge in seen_edges:
            continue

        seen_edges.add(edge)
        G.add_edge(i, j, weight=sim)

        if return_edges:
            edge_rows.append(
                {
                    "source_index": i,
                    "target_index": j,
                    "source_global_label_id": gbl_ids[i],
                    "target_global_label_id": gbl_ids[j],
                    "source_column": source_field,
                    "target_column": target_field,
                    "source_raw_value": raw_vals[i],
                    "target_raw_value": raw_vals[j],
                    "cosine_similarity": sim,
                    "mutual_knn": mutual_knn,
                    "same_field_only": same_field_only,
                }
            )

    edges_df = pd.DataFrame(edge_rows) if return_edges else pd.DataFrame()

    return G, edges_df

def detect_louvain_communities(
    G: nx.Graph,
    seed: int,
    resolution: float,
    min_community_size: int,
) -> dict[int, int]:
    node_to_community = {int(n): -1 for n in G.nodes}

    connected_nodes = [n for n in G.nodes if G.degree(n) > 0]
    if not connected_nodes:
        return node_to_community

    subgraph = G.subgraph(connected_nodes).copy()

    try:
        communities = nx.algorithms.community.louvain_communities(
            subgraph,
            weight="weight",
            resolution=resolution,
            seed=seed,
        )
    except Exception:
        communities = nx.algorithms.community.greedy_modularity_communities(
            subgraph,
            weight="weight",
        )

    community_id = 0
    for members in communities:
        members = sorted(int(m) for m in members)
        if len(members) < min_community_size:
            continue

        for node in members:
            node_to_community[node] = community_id

        community_id += 1

    return node_to_community

def graph_metrics(
    df: pd.DataFrame,
    G: nx.Graph,
    node_to_community: dict[int, int],
    k_neighbors: int,
    similarity_threshold: float,
    resolution: float,
    min_community_size: int,
) -> dict[str, Any]:
    total_labels = len(df)
    total_occurrences = int(df["value_count"].sum()) if total_labels else 0

    # Single pass over node_to_community for all derived stats.
    groups: dict[int, set] = defaultdict(set)
    for node, comm in node_to_community.items():
        if comm != -1:
            groups[comm].add(node)

    grouped_node_set = set().union(*groups.values()) if groups else set()
    grouped_labels = len(grouped_node_set)
    isolated_labels = total_labels - grouped_labels

    value_counts_arr = df["value_count"].to_numpy()
    grouped_mask = np.array([i in grouped_node_set for i in range(total_labels)], dtype=bool)
    grouped_occurrences = int(value_counts_arr[grouped_mask].sum()) if total_labels else 0
    isolated_occurrences = int(total_occurrences - grouped_occurrences)

    community_sets = list(groups.values())
    communities = list(groups.keys())
    largest_community_size = max(len(s) for s in community_sets) if community_sets else 0
    largest_community_ratio = largest_community_size / total_labels if total_labels else 0.0


    modularity = 0.0

    label_recovery_rate = grouped_labels / total_labels if total_labels else 0.0
    occurrence_recovery_rate = grouped_occurrences / total_occurrences if total_occurrences else 0.0
    isolated_ratio = isolated_labels / total_labels if total_labels else 0.0

    # Conservative scoring: prefer recovery, but punish over-grouping and giant communities.
    score = (
        label_recovery_rate
        - isolated_ratio * 0.4
        - largest_community_ratio * 1.5
    )

    return {
        "k_neighbors": k_neighbors,
        "similarity_threshold": similarity_threshold,
        "resolution": resolution,
        "min_community_size": min_community_size,
        "total_labels": total_labels,
        "total_occurrences": total_occurrences,
        "edges": int(G.number_of_edges()),
        "graph_communities_found": len(communities),
        "grouped_labels": grouped_labels,
        "isolated_labels": isolated_labels,
        "grouped_occurrences": grouped_occurrences,
        "isolated_occurrences": isolated_occurrences,
        "label_recovery_rate": label_recovery_rate,
        "occurrence_recovery_rate": occurrence_recovery_rate,
        "isolated_ratio": isolated_ratio,
        "largest_community_size": largest_community_size,
        "largest_community_ratio": largest_community_ratio,
        "modularity": float(modularity),
        "score": float(score),
    }

def strict_graph_sweep(
    anomaly_df: pd.DataFrame,
    X_anomaly: np.ndarray,
    k_values: list[int],
    threshold_values: list[float],
    resolution: float,
    min_community_size: int,
    mutual_knn: bool,
    same_field_only: bool,
    seed: int,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame, pd.DataFrame]:
    if len(anomaly_df) < 2:
        empty_values = anomaly_df.copy()
        empty_values["strict_graph_community_id"] = -1
        empty_edges = pd.DataFrame()
        empty_sweep = pd.DataFrame()
        best_config = {
            "total_labels": len(anomaly_df),
            "grouped_labels": 0,
            "isolated_labels": len(anomaly_df),
            "score": 0.0,
        }
        return empty_values, best_config, empty_edges, empty_sweep

    max_k = max(k_values)
    indices, similarities = nearest_neighbor_tables(X_anomaly, max_k=max_k)

    sweep_rows: list[dict[str, Any]] = []

    print("\nRunning strict graph parameter sweep on HDBSCAN anomaly bucket only...")

    total_runs = len(k_values) * len(threshold_values)
    run_no = 0

    best_metrics: dict[str, Any] | None = None
    best_key: tuple[int, float] | None = None

    for k in k_values:
        for threshold in threshold_values:
            run_no += 1
            started = time.time()

            print(
                f"Strict graph sweep {run_no}/{total_runs}: "
                f"k={k}, threshold={threshold}",
                flush=True,
            )

            G, _ = build_strict_graph(
                anomaly_df,
                indices,
                similarities,
                k_neighbors=k,
                similarity_threshold=threshold,
                mutual_knn=mutual_knn,
                same_field_only=same_field_only,
                return_edges=False,
            )

            node_to_community = detect_louvain_communities(
                G,
                seed=seed,
                resolution=resolution,
                min_community_size=min_community_size,
            )

            metrics = graph_metrics(
                anomaly_df,
                G,
                node_to_community,
                k_neighbors=k,
                similarity_threshold=threshold,
                resolution=resolution,
                min_community_size=min_community_size,
            )

            elapsed = time.time() - started
            metrics["elapsed_seconds"] = float(elapsed)

            sweep_rows.append(metrics)

            if best_metrics is None or metrics["score"] > best_metrics["score"]:
                best_metrics = metrics
                best_key = (int(k), float(threshold))

            avg_seconds = sum(row["elapsed_seconds"] for row in sweep_rows) / len(sweep_rows)
            remaining_runs = total_runs - run_no
            eta_minutes = (avg_seconds * remaining_runs) / 60

            print(
                f"Finished sweep {run_no}/{total_runs} in {elapsed:.1f}s. "
                f"Estimated remaining: {eta_minutes:.1f} min",
                flush=True,
            )

            del G
            del node_to_community

    if best_key is None or best_metrics is None:
        raise RuntimeError("Strict graph sweep did not produce any valid graph configuration.")

    sweep_df = pd.DataFrame(sweep_rows).sort_values("score", ascending=False).reset_index(drop=True)

    best_k, best_threshold = best_key

    print(
        f"\nRebuilding best strict graph once: "
        f"k={best_k}, threshold={best_threshold}",
        flush=True,
    )

    rebuild_started = time.time()

    best_G, best_edges_df = build_strict_graph(
        anomaly_df,
        indices,
        similarities,
        k_neighbors=best_k,
        similarity_threshold=best_threshold,
        mutual_knn=mutual_knn,
        same_field_only=same_field_only,
        return_edges=False,
    )

    print(
        f"Best strict graph rebuilt without edge export in "
        f"{time.time() - rebuild_started:.1f}s",
        flush=True,
    )

    best_node_to_community = detect_louvain_communities(
        best_G,
        seed=seed,
        resolution=resolution,
        min_community_size=min_community_size,
    )

    values_df = anomaly_df.copy()
    values_df["strict_graph_community_id"] = [
        int(best_node_to_community.get(i, -1))
        for i in range(len(values_df))
    ]
    values_df["strict_graph_recovered"] = values_df["strict_graph_community_id"].ne(-1)
    values_df["strict_graph_config_k"] = int(best_k)
    values_df["strict_graph_config_threshold"] = float(best_threshold)

    return values_df, best_metrics, best_edges_df, sweep_df

def summarize_strict_graph(values_df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    if values_df.empty:
        return pd.DataFrame()

    for community_id, g in values_df.groupby("strict_graph_community_id", dropna=False):
        labels = g["raw_value"].astype(str).tolist()
        rows.append(
            {
                "strict_graph_community_id": int(community_id),
                "is_still_isolated": int(community_id) == -1,
                "label_count": len(g),
                "total_occurrences": int(g["value_count"].sum()),
                "source_columns": " | ".join(sorted(g["source_column"].astype(str).unique())),
                "sample_labels": " | ".join(labels[:30]),
            }
        )

    return pd.DataFrame(rows).sort_values(
        ["is_still_isolated", "label_count", "total_occurrences"],
        ascending=[True, False, False],
    )

def family_tests(values_df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    if values_df.empty:
        return pd.DataFrame()

    def first_token(label: str) -> str:
        norm = normalize_label(label)
        parts = norm.split()
        return parts[0] if parts else ""

    tmp = values_df.copy()
    tmp["family_token"] = tmp["raw_value"].map(first_token)

    for token, g in tmp.groupby("family_token"):
        if not token:
            continue

        communities = sorted(set(int(x) for x in g["strict_graph_community_id"].tolist()))
        isolated_count = int(g["strict_graph_community_id"].eq(-1).sum())
        grouped_count = int(len(g) - isolated_count)

        if len(g) < 3:
            continue

        rows.append(
            {
                "family_token": token,
                "label_count": len(g),
                "total_occurrences": int(g["value_count"].sum()),
                "communities_seen": ", ".join(map(str, communities[:20])),
                "community_count": len(communities),
                "grouped_count": grouped_count,
                "isolated_count": isolated_count,
                "isolated_ratio": isolated_count / len(g) if len(g) else 0.0,
                "sample_labels": " | ".join(g["raw_value"].astype(str).tolist()[:25]),
            }
        )

    if not rows:
        return pd.DataFrame(columns=[
            "family_token",
            "label_count",
            "total_occurrences",
            "communities_seen",
            "community_count",
            "grouped_count",
            "isolated_count",
            "isolated_ratio",
            "sample_labels",
        ])

    return pd.DataFrame(rows).sort_values(
        ["label_count", "total_occurrences"],
        ascending=[False, False],
    )
# ---------------------------------------------------------------------
# Cluster registry utilities (naming removed from clustering pipeline)
# ---------------------------------------------------------------------

def cluster_centroid(X_cluster: np.ndarray) -> np.ndarray:
    centroid = np.mean(X_cluster, axis=0)
    norm = np.linalg.norm(centroid)
    if norm == 0:
        return centroid.astype(np.float32)
    return (centroid / norm).astype(np.float32)


def prepare_cluster_label_counts(cluster_df: pd.DataFrame) -> pd.DataFrame:
    df = cluster_df[["raw_value", "value_count"]].dropna().copy()
    df["raw_value"] = df["raw_value"].astype(str).str.strip()
    df = df[df["raw_value"] != ""]
    df["value_count"] = pd.to_numeric(df["value_count"], errors="coerce").fillna(1).astype(int)

    return (
        df.groupby("raw_value", as_index=False)["value_count"]
        .sum()
        .sort_values(["value_count", "raw_value"], ascending=[False, True])
        .reset_index(drop=True)
    )


def build_cluster_registry_without_names(
    final_mapping_df: pd.DataFrame,
    X: np.ndarray,
    source_column: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Build final cluster registry rows without assigning names.

    Naming is intentionally separated from clustering. This pipeline now writes:
      - taxonomy_clusters: cluster IDs and technical metadata only
      - taxonomy_label_cluster_map: raw label to final cluster mapping only

    Cluster naming should be handled by a separate naming job/table.
    """
    final_mapping_df = final_mapping_df.copy()

    non_anomaly_mapping_df = final_mapping_df[
        ~final_mapping_df["final_is_true_anomaly"].fillna(False).astype(bool)
    ].copy()

    registry_rows: list[dict[str, Any]] = []

    cluster_groups = list(non_anomaly_mapping_df.groupby("final_cluster_id", dropna=False))
    total_cluster_groups = len(cluster_groups)

    for idx, (final_cluster_id, g) in enumerate(cluster_groups, start=1):
        if idx == 1 or idx % 50 == 0 or idx == total_cluster_groups:
            print(
                f"Preparing cluster registry {idx}/{total_cluster_groups}",
                flush=True,
            )

        g = g.copy()

        cluster_source_columns = sorted(g["source_column"].astype(str).unique())
        cluster_source_column = cluster_source_columns[0] if len(cluster_source_columns) == 1 else source_column

        ids = g["global_label_id"].astype(int).to_numpy()
        X_cluster = X[ids]
        centroid = cluster_centroid(X_cluster)

        label_counts = prepare_cluster_label_counts(g)
        medoid_label = None
        if not label_counts.empty:
            medoid_label = str(label_counts.iloc[0]["raw_value"])

        registry_rows.append({
            "source_column": cluster_source_column,
            "final_cluster_id": str(final_cluster_id),
            "label_count": int(g["raw_value"].nunique()),
            "total_occurrences": int(g["value_count"].sum()),
            "final_cluster_source": " | ".join(sorted(g["final_cluster_source"].astype(str).unique())),
            "is_true_anomaly_cluster": False,
            "centroid_embedding_json": json.dumps(centroid.tolist()),
            "medoid_label": medoid_label,
        })

    cluster_registry_df = pd.DataFrame(registry_rows)
    return final_mapping_df, cluster_registry_df

# ---------------------------------------------------------------------
# PostgreSQL storage for production cluster lookup
# ---------------------------------------------------------------------

def quote_pg_identifier(identifier: str) -> str:
    """Safely quote a PostgreSQL identifier, allowing schema.table names."""
    parts = str(identifier or "").split(".")
    if not parts or not all(_PG_IDENT_RE.match(part) for part in parts):
        raise ValueError(f"Unsafe PostgreSQL identifier: {identifier}")
    return ".".join(f'"{part}"' for part in parts)


def pg_object_name(prefix: str, table_name: str, suffix: str) -> str:
    base = f"{prefix}_{table_name.replace('.', '_')}_{suffix}"
    return safe_filename_part(base.lower())[:60]


def ensure_db_ready(args: argparse.Namespace, retries: int = 12, delay: float = 5.0) -> bool:
    if psycopg2 is None:
        print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
        return False

    if load_dotenv is not None:
        load_dotenv(args.env_file)

    host     = os.getenv("CLUSTER_DB_HOST") or os.getenv("LOCAL_PG_HOST") or "localhost"
    port     = int(os.getenv("CLUSTER_DB_PORT") or os.getenv("LOCAL_PG_PORT") or "5432")
    user     = os.getenv("CLUSTER_DB_USER") or os.getenv("LOCAL_PG_USER") or "postgres"
    password = os.getenv("CLUSTER_DB_PASS") or os.getenv("LOCAL_PG_PASSWORD") or "postgres"
    dbname   = os.getenv("CLUSTER_DB_NAME") or os.getenv("LOCAL_PG_DB") or "taxonomy_drift_local"

    def _can_connect() -> bool:
        try:
            c = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=dbname, connect_timeout=3)
            c.close()
            return True
        except Exception:
            return False

    if _can_connect():
        return True

    print("DB not reachable — attempting to start Docker container...")
    try:
        result = subprocess.run(
            ["docker", "compose", "up", "-d"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            # try legacy docker-compose
            result = subprocess.run(
                ["docker-compose", "up", "-d"],
                capture_output=True, text=True,
            )
        if result.returncode != 0:
            print(f"ERROR: docker compose failed:\n{result.stderr.strip()}")
            return False
    except FileNotFoundError:
        print("ERROR: 'docker' command not found. Start the DB container manually: docker compose up -d")
        return False

    print(f"Waiting for PostgreSQL to be ready (up to {int(retries * delay)}s)...")
    for i in range(retries):
        time.sleep(delay)
        if _can_connect():
            print("DB is ready.")
            return True
        print(f"  still waiting... ({i + 1}/{retries})")

    print("ERROR: DB did not become ready in time. DB outputs will be skipped.")
    return False


def get_cluster_db_connection(args: argparse.Namespace):
    """
    Connect to the local/cluster PostgreSQL database used for taxonomy storage.

    Preferred .env values:
      CLUSTER_DB_CONN_STR
      or
      CLUSTER_DB_HOST, CLUSTER_DB_PORT, CLUSTER_DB_USER, CLUSTER_DB_PASS, CLUSTER_DB_NAME

    Local fallback .env values:
      LOCAL_PG_CONN_STR
      or
      LOCAL_PG_HOST, LOCAL_PG_PORT, LOCAL_PG_USER, LOCAL_PG_PASSWORD, LOCAL_PG_DB
    """
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is missing. Install with: pip install psycopg2-binary")

    if load_dotenv is not None:
        load_dotenv(args.env_file)

    conn_str = os.getenv("CLUSTER_DB_CONN_STR") or os.getenv("LOCAL_PG_CONN_STR") or os.getenv("PG_CONN_STR")
    if conn_str:
        return psycopg2.connect(conn_str)

    host = os.getenv("CLUSTER_DB_HOST") or os.getenv("LOCAL_PG_HOST") or "localhost"
    port = os.getenv("CLUSTER_DB_PORT") or os.getenv("LOCAL_PG_PORT") or "5432"
    user = os.getenv("CLUSTER_DB_USER") or os.getenv("LOCAL_PG_USER") or "postgres"
    password = os.getenv("CLUSTER_DB_PASS") or os.getenv("LOCAL_PG_PASSWORD") or "postgres"
    dbname = os.getenv("CLUSTER_DB_NAME") or os.getenv("LOCAL_PG_DB") or "taxonomy_drift_local"

    return psycopg2.connect(
        host=host,
        port=int(port),
        user=user,
        password=password,
        dbname=dbname,
    )


def ensure_cluster_storage_schema(
    conn,
    run_table: str,
    cluster_table: str,
    label_map_table: str,
) -> None:
    """Create/patch tables required by the offline cluster builder and production mapper."""
    run_t = quote_pg_identifier(run_table)
    cluster_t = quote_pg_identifier(cluster_table)
    label_map_t = quote_pg_identifier(label_map_table)

    cluster_idx = pg_object_name("ux", cluster_table, "field_cluster_version")
    cluster_active_idx = pg_object_name("idx", cluster_table, "field_active")
    label_map_idx = pg_object_name("idx", label_map_table, "run_field_cluster")

    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {run_t} (
                run_id TEXT PRIMARY KEY,
                field_name TEXT NOT NULL,
                cluster_version TEXT NOT NULL,
                model_name TEXT,
                text_mode TEXT,
                input_file TEXT,
                total_labels INTEGER,
                total_occurrences BIGINT,
                source_column_count INTEGER,
                base_min_cluster_size INTEGER,
                base_min_samples INTEGER,
                hdbscan_metric TEXT,
                use_umap BOOLEAN,
                graph_config JSONB,
                hdbscan_auto_tune_config JSONB,
                run_report JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {cluster_t} (
                id BIGSERIAL PRIMARY KEY,
                run_id TEXT,
                field_name TEXT NOT NULL,
                cluster_id TEXT NOT NULL,
                cluster_source TEXT,
                centroid_embedding JSONB,
                cluster_size INTEGER,
                total_occurrences BIGINT,
                medoid_label TEXT,
                is_true_anomaly_cluster BOOLEAN DEFAULT FALSE,
                similarity_threshold NUMERIC,
                cluster_version TEXT DEFAULT 'v1',
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        cluster_columns = {
            "run_id": "TEXT",
            "cluster_source": "TEXT",
            "centroid_embedding": "JSONB",
            "cluster_size": "INTEGER",
            "total_occurrences": "BIGINT",
            "medoid_label": "TEXT",
            "is_true_anomaly_cluster": "BOOLEAN DEFAULT FALSE",
            "similarity_threshold": "NUMERIC",
            "cluster_version": "TEXT DEFAULT 'v1'",
            "active": "BOOLEAN DEFAULT TRUE",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        }
        for column, definition in cluster_columns.items():
            cur.execute(f"ALTER TABLE {cluster_t} ADD COLUMN IF NOT EXISTS {column} {definition};")

        cur.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS {quote_pg_identifier(cluster_idx)}
            ON {cluster_t}(field_name, cluster_id, cluster_version);
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {quote_pg_identifier(cluster_active_idx)}
            ON {cluster_t}(field_name, active, cluster_version);
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {label_map_t} (
                id BIGSERIAL PRIMARY KEY,
                run_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                raw_label TEXT NOT NULL,
                normalized_label TEXT,
                value_count BIGINT,
                final_cluster_id TEXT,
                final_cluster_source TEXT,
                final_is_true_anomaly BOOLEAN,
                base_cluster_id TEXT,
                strict_graph_community_id TEXT,
                cluster_version TEXT,
                label_embedding JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {quote_pg_identifier(label_map_idx)}
            ON {label_map_t}(run_id, field_name, final_cluster_id);
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS taxonomy_label_embeddings (
                id          BIGSERIAL PRIMARY KEY,
                cache_key   TEXT NOT NULL,
                field_name  TEXT NOT NULL,
                raw_label   TEXT NOT NULL,
                emb_text    TEXT,
                embedding   FLOAT4[] NOT NULL,
                model_name  TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_taxonomy_label_embeddings_key_label
            ON taxonomy_label_embeddings(cache_key, field_name, raw_label);
            """
        )

    conn.commit()

def parse_pipe_list(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return []
    return [item.strip() for item in str(value).split("|") if item.strip()]


def json_loads_or_none(value: Any) -> Any:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return None


def db_safe_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if np.isnan(value):
            return None
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


def deactivate_existing_cluster_rows(conn, cluster_table: str, field_names: list[str]) -> int:
    if not field_names:
        return 0
    cluster_t = quote_pg_identifier(cluster_table)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {cluster_t}
            SET active = FALSE,
                updated_at = CURRENT_TIMESTAMP
            WHERE field_name = ANY(%s)
              AND active = TRUE;
            """,
            (field_names,),
        )
        updated = cur.rowcount
    conn.commit()
    return int(updated)


def insert_cluster_run_row(
    conn,
    run_table: str,
    run_id: str,
    cluster_version: str,
    field_name: str,
    input_path: Any,
    args: argparse.Namespace,
    df: pd.DataFrame,
    best_graph_config: dict[str, Any],
    hdbscan_auto_tune_config: dict[str, Any] | None,
    report: dict[str, Any],
) -> None:
    run_t = quote_pg_identifier(run_table)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {run_t} (
                run_id,
                field_name,
                cluster_version,
                model_name,
                text_mode,
                input_file,
                total_labels,
                total_occurrences,
                source_column_count,
                base_min_cluster_size,
                base_min_samples,
                hdbscan_metric,
                use_umap,
                graph_config,
                hdbscan_auto_tune_config,
                run_report,
                created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (run_id) DO UPDATE SET
                field_name = EXCLUDED.field_name,
                cluster_version = EXCLUDED.cluster_version,
                model_name = EXCLUDED.model_name,
                text_mode = EXCLUDED.text_mode,
                input_file = EXCLUDED.input_file,
                total_labels = EXCLUDED.total_labels,
                total_occurrences = EXCLUDED.total_occurrences,
                source_column_count = EXCLUDED.source_column_count,
                base_min_cluster_size = EXCLUDED.base_min_cluster_size,
                base_min_samples = EXCLUDED.base_min_samples,
                hdbscan_metric = EXCLUDED.hdbscan_metric,
                use_umap = EXCLUDED.use_umap,
                graph_config = EXCLUDED.graph_config,
                hdbscan_auto_tune_config = EXCLUDED.hdbscan_auto_tune_config,
                run_report = EXCLUDED.run_report;
            """,
            (
                run_id,
                field_name,
                cluster_version,
                args.model,
                _TEXT_MODE,
                str(input_path),
                int(len(df)),
                int(df["value_count"].sum()),
                int(df["source_column"].nunique()),
                int(args.min_cluster_size),
                int(args.min_samples) if args.min_samples is not None else None,
                _HDBSCAN_METRIC,
                False,
                psycopg2.extras.Json(best_graph_config),
                psycopg2.extras.Json(hdbscan_auto_tune_config or {}),
                psycopg2.extras.Json(report),
            ),
        )
    conn.commit()


def insert_cluster_rows(
    conn,
    cluster_table: str,
    cluster_registry_df: pd.DataFrame,
    run_id: str,
    cluster_version: str,
    similarity_threshold: float,
    activate_true_anomaly_clusters: bool,
) -> int:
    if cluster_registry_df.empty:
        return 0

    cluster_t = quote_pg_identifier(cluster_table)
    rows = []

    for row in cluster_registry_df.to_dict(orient="records"):
        field_name = str(row.get("source_column") or "unknown")
        final_cluster_id = str(row.get("final_cluster_id"))
        is_true_anomaly = bool(row.get("is_true_anomaly_cluster"))
        active = bool(activate_true_anomaly_clusters or not is_true_anomaly)
        centroid = json_loads_or_none(row.get("centroid_embedding_json"))

        rows.append(
            (
                run_id,
                field_name,
                final_cluster_id,
                db_safe_value(row.get("final_cluster_source")),
                psycopg2.extras.Json(centroid),
                int(row.get("label_count") or 0),
                int(row.get("total_occurrences") or 0),
                db_safe_value(row.get("medoid_label")),
                is_true_anomaly,
                float(similarity_threshold),
                cluster_version,
                active,
            )
        )

    sql = f"""
        INSERT INTO {cluster_t} (
            run_id,
            field_name,
            cluster_id,
            cluster_source,
            centroid_embedding,
            cluster_size,
            total_occurrences,
            medoid_label,
            is_true_anomaly_cluster,
            similarity_threshold,
            cluster_version,
            active
        ) VALUES %s
        ON CONFLICT (field_name, cluster_id, cluster_version) DO UPDATE SET
            run_id = EXCLUDED.run_id,
            cluster_source = EXCLUDED.cluster_source,
            centroid_embedding = EXCLUDED.centroid_embedding,
            cluster_size = EXCLUDED.cluster_size,
            total_occurrences = EXCLUDED.total_occurrences,
            medoid_label = EXCLUDED.medoid_label,
            is_true_anomaly_cluster = EXCLUDED.is_true_anomaly_cluster,
            similarity_threshold = EXCLUDED.similarity_threshold,
            active = EXCLUDED.active,
            updated_at = CURRENT_TIMESTAMP;
    """

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=500)
    conn.commit()
    return len(rows)

def insert_label_cluster_map_rows(
    conn,
    label_map_table: str,
    final_mapping_df: pd.DataFrame,
    run_id: str,
    cluster_version: str,
) -> int:
    if final_mapping_df.empty:
        return 0

    label_map_t = quote_pg_identifier(label_map_table)
    rows = []

    for row in final_mapping_df.to_dict(orient="records"):
        raw_value = row.get("raw_value")
        if raw_value is None:
            continue

        raw_value = str(raw_value).strip()
        if raw_value == "" or raw_value.lower() in {"nan", "none", "null"}:
            continue

        rows.append(
            (
                run_id,
                str(row.get("source_column") or "unknown"),
                raw_value,
                db_safe_value(row.get("normalized_value")),
                int(row.get("value_count") or 0),
                db_safe_value(row.get("final_cluster_id")),
                db_safe_value(row.get("final_cluster_source")),
                bool(row.get("final_is_true_anomaly")),
                str(row.get("base_cluster_id")) if row.get("base_cluster_id") is not None else None,
                str(row.get("strict_graph_community_id")) if row.get("strict_graph_community_id") is not None else None,
                cluster_version,
            )
        )

    sql = f"""
        INSERT INTO {label_map_t} (
            run_id,
            field_name,
            raw_label,
            normalized_label,
            value_count,
            final_cluster_id,
            final_cluster_source,
            final_is_true_anomaly,
            base_cluster_id,
            strict_graph_community_id,
            cluster_version
        ) VALUES %s
    """

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=1000)
    conn.commit()
    return len(rows)

def save_embeddings_to_db(
    conn,
    df: pd.DataFrame,
    X: np.ndarray,
    cache_key: str,
    model_name: str,
    text_mode: str,
) -> int:
    rows = []
    for row in df.itertuples(index=False):
        gid = int(row.global_label_id)
        rows.append((
            cache_key,
            str(row.source_column),
            str(row.raw_value),
            embedding_text(row.source_column, row.raw_value, mode=text_mode),
            X[gid].astype(float).tolist(),
            model_name,
        ))
    sql = """
        INSERT INTO taxonomy_label_embeddings
            (cache_key, field_name, raw_label, emb_text, embedding, model_name)
        VALUES %s
        ON CONFLICT (cache_key, field_name, raw_label) DO UPDATE SET
            emb_text   = EXCLUDED.emb_text,
            embedding  = EXCLUDED.embedding,
            model_name = EXCLUDED.model_name,
            created_at = CURRENT_TIMESTAMP;
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=500)
    conn.commit()
    return len(rows)


def load_embeddings_from_db(
    conn,
    df: pd.DataFrame,
    cache_key: str,
) -> "np.ndarray | None":
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT field_name, raw_label, embedding FROM taxonomy_label_embeddings WHERE cache_key = %s",
                (cache_key,),
            )
            rows = cur.fetchall()
    except Exception:
        conn.rollback()
        return None

    if not rows:
        return None

    db_map: dict[tuple[str, str], list] = {(str(r[0]), str(r[1])): r[2] for r in rows}

    vectors = []
    for row in df.itertuples(index=False):
        vec = db_map.get((str(row.source_column), str(row.raw_value)))
        if vec is None:
            return None
        vectors.append(vec)

    return normalize(np.array(vectors, dtype=np.float32))


def write_clusters_to_postgres(
    args: argparse.Namespace,
    run_id: str,
    input_path: Any,
    df: pd.DataFrame,
    final_mapping_df: pd.DataFrame,
    cluster_registry_df: pd.DataFrame,
    X: np.ndarray,
    best_graph_config: dict[str, Any],
    hdbscan_auto_tune_config: dict[str, Any] | None,
    report: dict[str, Any],
) -> dict[str, Any]:
    if not ensure_db_ready(args):
        print("ERROR: DB unavailable — skipping all cluster DB writes.")
        return {"enabled": False, "cluster_rows_written": 0, "label_map_rows_written": 0}

    if cluster_registry_df.empty:
        return {"enabled": True, "cluster_rows_written": 0, "label_map_rows_written": 0}

    field_names = sorted(cluster_registry_df["source_column"].astype(str).unique().tolist())
    if "mixed_fields" in field_names:
        raise ValueError(
            "Refusing to write mixed_fields clusters to PostgreSQL. "
            "Run the pipeline one field at a time."
        )

    cluster_version = args.cluster_version or run_id
    conn = get_cluster_db_connection(args)

    try:
        ensure_cluster_storage_schema(
            conn=conn,
            run_table=_CLUSTER_RUN_TABLE,
            cluster_table=_CLUSTER_TABLE,
            label_map_table=_CLUSTER_LABEL_MAP_TABLE,
        )

        deactivated_count = 0
        if args.deactivate_existing_clusters:
            deactivated_count = deactivate_existing_cluster_rows(
                conn=conn,
                cluster_table=_CLUSTER_TABLE,
                field_names=field_names,
            )

        insert_cluster_run_row(
            conn=conn,
            run_table=_CLUSTER_RUN_TABLE,
            run_id=run_id,
            cluster_version=cluster_version,
            field_name=" | ".join(field_names),
            input_path=input_path,
            args=args,
            df=df,
            best_graph_config=best_graph_config,
            hdbscan_auto_tune_config=hdbscan_auto_tune_config,
            report=report,
        )

        cluster_rows_written = insert_cluster_rows(
            conn=conn,
            cluster_table=_CLUSTER_TABLE,
            cluster_registry_df=cluster_registry_df,
            run_id=run_id,
            cluster_version=cluster_version,
            similarity_threshold=args.cluster_similarity_threshold,
            activate_true_anomaly_clusters=False,
        )

        label_map_rows_written = 0
        if not args.no_write_label_map_to_db:
            print(f"Writing {len(final_mapping_df):,} label-map rows to DB...")
            try:
                label_map_rows_written = insert_label_cluster_map_rows(
                    conn=conn,
                    label_map_table=_CLUSTER_LABEL_MAP_TABLE,
                    final_mapping_df=final_mapping_df,
                    run_id=run_id,
                    cluster_version=cluster_version,
                )
            except Exception as exc:
                print(f"ERROR: label-map DB write failed: {exc}")
                raise

        return {
            "enabled": True,
            "cluster_version": cluster_version,
            "field_names": field_names,
            "run_table": _CLUSTER_RUN_TABLE,
            "cluster_table": _CLUSTER_TABLE,
            "label_map_table": _CLUSTER_LABEL_MAP_TABLE if not args.no_write_label_map_to_db else None,
            "deactivated_existing_clusters": int(deactivated_count),
            "cluster_rows_written": int(cluster_rows_written),
            "label_map_rows_written": int(label_map_rows_written),
            "similarity_threshold": float(args.cluster_similarity_threshold),
            "true_anomaly_clusters_active": False,
        }
    finally:
        conn.close()

# ---------------------------------------------------------------------
# Combined production mapping
# ---------------------------------------------------------------------

def build_combined_mapping(
    base_values_df: pd.DataFrame,
    strict_values_df: pd.DataFrame,
) -> pd.DataFrame:
    combined = base_values_df.copy()

    combined["final_cluster_source"] = np.where(
        combined["base_cluster_id"].ne(-1),
        "base_hdbscan",
        "true_anomaly",
    )

    combined["final_cluster_id"] = np.where(
        combined["base_cluster_id"].ne(-1),
        "base_" + combined["base_cluster_id"].astype(str),
        "anomaly",
    )

    if not strict_values_df.empty:
        recovered = strict_values_df[strict_values_df["strict_graph_community_id"].ne(-1)].copy()
        recovered_map = {
            int(row.global_label_id): f"strict_{int(row.strict_graph_community_id)}"
            for row in recovered.itertuples(index=False)
        }

        recovered_mask = combined["global_label_id"].isin(recovered_map)
        combined.loc[recovered_mask, "final_cluster_source"] = "strict_graph_recovery"
        combined.loc[recovered_mask, "final_cluster_id"] = (
            combined.loc[recovered_mask, "global_label_id"].map(recovered_map)
        )

    combined["final_is_true_anomaly"] = combined["final_cluster_source"].eq("true_anomaly")

    return combined

def enrich_mapping_with_graph_stats(
    final_mapping_df: pd.DataFrame,
    strict_edges_df: pd.DataFrame,
) -> pd.DataFrame:
    """Add max cosine similarity and mutual_knn flag from strict graph edges into the label mapping."""
    if strict_edges_df.empty or "cosine_similarity" not in strict_edges_df.columns:
        final_mapping_df["graph_max_cosine_sim"] = np.nan
        final_mapping_df["graph_mutual_knn"] = False
        return final_mapping_df

    src = strict_edges_df[["source_column", "source_raw_value", "cosine_similarity", "mutual_knn"]].rename(
        columns={"source_raw_value": "raw_value"}
    )
    tgt = strict_edges_df[["target_column", "target_raw_value", "cosine_similarity", "mutual_knn"]].rename(
        columns={"target_column": "source_column", "target_raw_value": "raw_value"}
    )
    edge_stats = (
        pd.concat([src, tgt], ignore_index=True)
        .groupby(["source_column", "raw_value"])
        .agg(graph_max_cosine_sim=("cosine_similarity", "max"), graph_mutual_knn=("mutual_knn", "any"))
        .reset_index()
    )

    final_mapping_df = final_mapping_df.merge(
        edge_stats, left_on=["source_column", "raw_value"], right_on=["source_column", "raw_value"], how="left"
    )
    recovered_mask = final_mapping_df["final_cluster_source"].eq("strict_graph_recovery")
    final_mapping_df.loc[~recovered_mask, "graph_max_cosine_sim"] = np.nan
    final_mapping_df["graph_mutual_knn"] = (
        final_mapping_df["graph_mutual_knn"].where(recovered_mask, other=False).fillna(False)
    )
    return final_mapping_df

def _make_cache_key(
    df: pd.DataFrame,
    model_name: str,
    text_mode: str,
    cache_name: str | None,
) -> str:
    if cache_name:
        return safe_filename_part(cache_name)
    fields = "_".join(sorted(df["source_column"].astype(str).unique()))
    safe_model = safe_filename_part(model_name.replace("/", "_"))
    return f"{safe_filename_part(fields)}_{safe_model}_{text_mode}"

def load_or_create_embeddings(
    df: pd.DataFrame,
    model_name: str,
    batch_size: int,
    text_mode: str,
    reuse_embeddings: bool,
    cache_name: str | None,
    device: str,
    args=None,
) -> np.ndarray:
    cache_key = _make_cache_key(df=df, model_name=model_name, text_mode=text_mode, cache_name=cache_name)

    use_db = (
        args is not None
        and not getattr(args, "no_write_clusters_to_db", False)
        and psycopg2 is not None
        and ensure_db_ready(args)
    )

    if reuse_embeddings and use_db:
        try:
            conn = get_cluster_db_connection(args)
            X = load_embeddings_from_db(conn, df, cache_key)
            conn.close()
            if X is not None:
                print(f"\nLoaded {len(df):,} embeddings from DB (cache_key={cache_key})")
                return X
            print("\nDB embedding cache miss — will recompute.")
        except Exception as exc:
            print(f"\nDB embedding load failed, will recompute: {exc}")

    texts = [
        embedding_text(row.source_column, row.raw_value, mode=text_mode)
        for row in df.itertuples(index=False)
    ]
    X = create_embeddings(df, model_name=model_name, batch_size=batch_size, text_mode=text_mode, device=device, texts=texts)

    if use_db:
        try:
            conn = get_cluster_db_connection(args)
            ensure_cluster_storage_schema(
                conn=conn,
                run_table=_CLUSTER_RUN_TABLE,
                cluster_table=_CLUSTER_TABLE,
                label_map_table=_CLUSTER_LABEL_MAP_TABLE,
            )
            n = save_embeddings_to_db(conn, df, X, cache_key, model_name, text_mode)
            conn.close()
            print(f"Saved {n:,} embeddings to DB (cache_key={cache_key})")
        except Exception as exc:
            print(f"DB embedding save failed: {exc}")

    return X
def flatten_report_for_excel(report: dict[str, Any]) -> pd.DataFrame:
    rows = []

    def walk(prefix: str, obj: Any):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(f"{prefix}.{k}" if prefix else str(k), v)
        elif isinstance(obj, list):
            rows.append({"metric": prefix, "value": json.dumps(obj, default=str)})
        else:
            rows.append({"metric": prefix, "value": obj})

    walk("", report)
    return pd.DataFrame(rows)


def write_iris_taxonomy_workbook(
    output_path: Path,
    final_mapping_df: pd.DataFrame,
    cluster_registry_df: pd.DataFrame,
    report: dict[str, Any],
    anomaly_df: pd.DataFrame,
    true_anomaly_df: pd.DataFrame,
    family_tests_df: pd.DataFrame,
) -> None:
    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
        final_mapping_df.to_excel(writer, sheet_name="Label Mapping", index=False)
        cluster_registry_df.to_excel(writer, sheet_name="Cluster Registry", index=False)
        flatten_report_for_excel(report).to_excel(writer, sheet_name="Run Report", index=False)
        anomaly_df.to_excel(writer, sheet_name="Anomaly Bucket", index=False)
        true_anomaly_df.to_excel(writer, sheet_name="True Anomaly Review", index=False)
        family_tests_df.to_excel(writer, sheet_name="Family Tests", index=False)

        workbook = writer.book
        header_fmt = workbook.add_format({"bold": True, "bg_color": "#D9EAF7", "border": 1})
        wrap_fmt = workbook.add_format({"text_wrap": True, "valign": "top"})

        for sheet_name, worksheet in writer.sheets.items():
            worksheet.set_default_row(14)
            worksheet.freeze_panes(1, 0)
            worksheet.set_row(0, None, header_fmt)
            worksheet.set_column(0, 50, 22, wrap_fmt)
# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def parse_int_list(value: str) -> list[int]:
    return [int(x.strip()) for x in value.split(",") if x.strip()]

def parse_float_list(value: str) -> list[float]:
    return [float(x.strip()) for x in value.split(",") if x.strip()]

def main() -> None:
    parser = argparse.ArgumentParser()

    # Input
    parser.add_argument("--input", required=False, help="Full input CSV path.")
    parser.add_argument("--from-db", action="store_true", help="Load data directly from APP DB using .env.")
    parser.add_argument("--env-file", default=".env", help="Path to .env file.")
    parser.add_argument("--db-query-file", help="SQL file returning source_column, raw_value, value_count.")

    # Output
    parser.add_argument("--base-output-dir", default="taxonomy_cluster_output")

    # Embeddings
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", default="auto", help="auto, cpu, cuda, cuda:N, npu, openvino-gpu, openvino-cpu.")
    parser.add_argument("--no-reuse-embeddings", action="store_true", help="Force recompute embeddings instead of loading from DB cache.")
    parser.add_argument("--embeddings-cache-name", default=None)

    # HDBSCAN
    parser.add_argument("--min-cluster-size", type=int, default=5)
    parser.add_argument("--min-samples", type=int, default=2)
    parser.add_argument("--auto-tune-hdbscan", action="store_true", help="Search HDBSCAN params and choose best config.")
    parser.add_argument("--auto-tune-min-cluster-sizes", default="5,8,12,20,30")
    parser.add_argument("--auto-tune-min-samples", default="1,2,3,5")

    # Strict graph recovery
    parser.add_argument("--graph-k-values", default="3,5")
    parser.add_argument("--graph-threshold-values", default="0.90,0.92,0.94")

    # Deprecated naming args retained for backward-compatible commands. Ignored by this clustering-only script.
    parser.add_argument("--no-llama-cluster-names", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--ollama-model", default="llama3.1:8b", help=argparse.SUPPRESS)
    parser.add_argument("--ollama-workers", type=int, default=1, help=argparse.SUPPRESS)
    parser.add_argument("--ollama-disable-generic-retry", action="store_true", help=argparse.SUPPRESS)

    # Outputs
    parser.add_argument("--no-generate-html", action="store_true", help="Skip 3D UMAP cluster plot.")
    parser.add_argument("--debug-outputs", action="store_true")

    # PostgreSQL cluster storage
    parser.add_argument("--no-write-clusters-to-db", action="store_true", help="Skip writing clusters and embeddings to PostgreSQL.")
    parser.add_argument("--cluster-version", default=None)
    parser.add_argument("--cluster-similarity-threshold", type=float, default=0.82)
    parser.add_argument("--deactivate-existing-clusters", action="store_true")
    parser.add_argument("--no-write-label-map-to-db", action="store_true", help="Skip writing label-to-cluster map to PostgreSQL.")

    parser.add_argument("--seed", type=int, default=42)

    args = parser.parse_args()

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.base_output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    embedding_device = resolve_torch_device(args.device)

    print("=" * 80)
    print("FULL TAXONOMY PIPELINE")
    print_acceleration_status(embedding_device)
    print("=" * 80)
    print(f"Run ID: {run_id}")
    print(f"Output dir: {out_dir}")
    print("Sampling: DISABLED. Full input will be processed.")

    if args.from_db:
        input_path = "APP_DB"
        df = load_from_app_db(args)
    else:
        if not args.input:
            raise ValueError("Provide --input full_data.csv OR use --from-db.")
        input_path = Path(args.input)
        print(f"Input CSV: {input_path}")
        df = load_input(input_path)
    print(f"\nLoaded FULL dataset: {len(df):,} labels")
    print(f"Total occurrences: {int(df['value_count'].sum()):,}")
    print(f"Source columns: {df['source_column'].nunique():,}")

    X = load_or_create_embeddings(
        df=df,
        model_name=args.model,
        batch_size=args.batch_size,
        text_mode=_TEXT_MODE,
        reuse_embeddings=not args.no_reuse_embeddings,
        cache_name=args.embeddings_cache_name,
        device=embedding_device,
        args=args,
    )

    hdbscan_auto_tune_config = None

    if args.auto_tune_hdbscan:
        base_values_df, hdbscan_auto_tune_config = auto_tune_hdbscan(
            df=df,
            X=X,
            output_dir=out_dir,
            run_id=run_id,
            min_cluster_size_values=parse_int_list(args.auto_tune_min_cluster_sizes),
            min_samples_values=parse_int_list(args.auto_tune_min_samples),
            seed=args.seed,
        )
    else:
        base_values_df = run_hdbscan(
            df,
            X_for_cluster=X,
            min_cluster_size=args.min_cluster_size,
            min_samples=args.min_samples,
            metric=_HDBSCAN_METRIC,
        )

    anomaly_df = base_values_df[base_values_df["base_cluster_id"].eq(-1)].copy().reset_index(drop=True)

    print("\nBase HDBSCAN complete.")
    print(f"Base grouped labels: {int(base_values_df['base_cluster_id'].ne(-1).sum()):,}")
    print(f"Base anomaly labels: {len(anomaly_df):,}")

    # Strict graph recovery uses original full-space embeddings for anomaly subset
    if len(anomaly_df) > 0:
        anomaly_global_ids = anomaly_df["global_label_id"].astype(int).tolist()
        X_anomaly = X[anomaly_global_ids]
    else:
        X_anomaly = np.empty((0, X.shape[1]), dtype=np.float32)

    k_values = parse_int_list(args.graph_k_values)
    threshold_values = parse_float_list(args.graph_threshold_values)

    strict_values_df, best_graph_config, strict_edges_df, sweep_df = strict_graph_sweep(
        anomaly_df=anomaly_df,
        X_anomaly=X_anomaly,
        k_values=k_values,
        threshold_values=threshold_values,
        resolution=_GRAPH_RESOLUTION,
        min_community_size=_GRAPH_MIN_COMMUNITY_SIZE,
        mutual_knn=True,
        same_field_only=True,
        seed=args.seed,
    )

    true_anomaly_df = strict_values_df[strict_values_df["strict_graph_community_id"].eq(-1)].copy()
    recovered_df = strict_values_df[strict_values_df["strict_graph_community_id"].ne(-1)].copy()
    family_tests_df = family_tests(strict_values_df)

    final_mapping_df = build_combined_mapping(base_values_df, strict_values_df)
    source_columns = sorted(final_mapping_df["source_column"].astype(str).unique())
    source_column_for_registry = source_columns[0] if len(source_columns) == 1 else "mixed_fields"

    final_mapping_df, cluster_registry_df = build_cluster_registry_without_names(
        final_mapping_df=final_mapping_df,
        X=X,
        source_column=source_column_for_registry,
    )

    final_mapping_df = enrich_mapping_with_graph_stats(final_mapping_df, strict_edges_df)

    iris_workbook_path = out_dir / f"iris_taxonomy_output_{run_id}.xlsx"
    report_path = out_dir / f"taxonomy_full_pipeline_report_{run_id}.json"

    # Debug CSV paths (only written when --debug-outputs)
    strict_values_path = out_dir / f"strict_graph_values_{run_id}.csv"
    strict_summary_path = out_dir / f"strict_graph_summary_{run_id}.csv"
    strict_edges_path = out_dir / f"strict_graph_edges_{run_id}.csv"
    strict_sweep_path = out_dir / f"strict_graph_parameter_sweep_{run_id}.csv"
    recovered_path = out_dir / f"strict_graph_recovered_values_{run_id}.csv"
    family_tests_path = out_dir / f"strict_graph_family_tests_{run_id}.csv"
    base_values_path = out_dir / f"base_hdbscan_values_{run_id}.csv"
    base_summary_path = out_dir / f"base_hdbscan_summary_{run_id}.csv"
    anomaly_path = out_dir / f"anomaly_review_values_{run_id}.csv"

    html_outputs = {} if args.no_generate_html else generate_cluster_html_views(
        final_mapping_df=final_mapping_df,
        X=X,
        run_id=run_id,
        output_dir=out_dir,
        max_points=_HTML_MAX_POINTS,
        seed=args.seed,
    )

    final_cluster_count = int((~cluster_registry_df["is_true_anomaly_cluster"]).sum())

    report = {
        "run_id": run_id,
        "input_file": str(input_path),
        "model_name": args.model,
        "embedding_device": embedding_device,
        "text_mode": _TEXT_MODE,
        "sampling": "disabled_full_input_processed",
        "total_labels": int(len(df)),
        "total_occurrences": int(df["value_count"].sum()),
        "source_column_count": int(df["source_column"].nunique()),
        "final_cluster_count": final_cluster_count,
        "base_hdbscan": {
            "min_cluster_size": args.min_cluster_size,
            "min_samples": args.min_samples,
            "metric": _HDBSCAN_METRIC,
            "auto_tune_hdbscan": bool(args.auto_tune_hdbscan),
            "auto_tune_config": hdbscan_auto_tune_config,
            "base_grouped_labels": int(base_values_df["base_cluster_id"].ne(-1).sum()),
            "base_anomaly_labels": int(len(anomaly_df)),
            "base_anomaly_ratio": float(len(anomaly_df) / len(df)) if len(df) else 0.0,
        },
        "strict_graph_recovery": {
            "best_config": best_graph_config,
            "recovered_labels": int(len(recovered_df)),
            "true_anomaly_labels": int(len(true_anomaly_df)),
            "recovered_occurrences": int(recovered_df["value_count"].sum()) if not recovered_df.empty else 0,
            "true_anomaly_occurrences": int(true_anomaly_df["value_count"].sum()) if not true_anomaly_df.empty else 0,
        },
        "outputs": {
            "iris_taxonomy_workbook": str(iris_workbook_path),
            **html_outputs,
        },
    }

    cluster_db_outputs = {"enabled": False}
    if not args.no_write_clusters_to_db:
        print("\nWriting final cluster registry to PostgreSQL for production lookup...")
        cluster_db_outputs = write_clusters_to_postgres(
            args=args,
            run_id=run_id,
            input_path=input_path,
            df=df,
            final_mapping_df=final_mapping_df,
            cluster_registry_df=cluster_registry_df,
            X=X,
            best_graph_config=best_graph_config,
            hdbscan_auto_tune_config=hdbscan_auto_tune_config,
            report=report,
        )
        report["outputs"]["cluster_db_storage"] = cluster_db_outputs
        print(
            f"Cluster DB write complete: "
            f"{cluster_db_outputs['cluster_rows_written']:,} clusters, "
            f"{cluster_db_outputs['label_map_rows_written']:,} label-map rows."
        )

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    write_iris_taxonomy_workbook(
        output_path=iris_workbook_path,
        final_mapping_df=final_mapping_df,
        cluster_registry_df=cluster_registry_df,
        report=report,
        anomaly_df=anomaly_df,
        true_anomaly_df=true_anomaly_df,
        family_tests_df=family_tests_df,
    )
    if args.debug_outputs:
        base_summary_df = summarize_base_clusters(base_values_df)
        strict_summary_df = summarize_strict_graph(strict_values_df)
        base_values_df.to_csv(base_values_path, index=False)
        base_summary_df.to_csv(base_summary_path, index=False)
        anomaly_df.to_csv(anomaly_path, index=False)
        strict_values_df.to_csv(strict_values_path, index=False)
        strict_summary_df.to_csv(strict_summary_path, index=False)
        strict_edges_df.to_csv(strict_edges_path, index=False)
        sweep_df.to_csv(strict_sweep_path, index=False)
        recovered_df.to_csv(recovered_path, index=False)
        family_tests_df.to_csv(family_tests_path, index=False)
    print("\n" + "=" * 80)
    print("PIPELINE COMPLETE")
    print("=" * 80)
    print(f"Base HDBSCAN grouped labels: {report['base_hdbscan']['base_grouped_labels']:,}")
    print(f"Base anomaly bucket: {report['base_hdbscan']['base_anomaly_labels']:,}")
    print(f"Strict graph recovered labels: {report['strict_graph_recovery']['recovered_labels']:,}")
    print(f"Final true anomaly labels: {report['strict_graph_recovery']['true_anomaly_labels']:,}")
    print(f"\nMain production output:")
    print(f"  Workbook: {iris_workbook_path}")
    if html_outputs:
        for html_name, html_path in html_outputs.items():
            print(f"  {html_name}: {html_path}")

if __name__ == "__main__":
    main()
