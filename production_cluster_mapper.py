"""
production_cluster_mapper.py

Production-style mapper for post-classification call rows.

This version supports two PostgreSQL connections:
- --input-db app   reads classified call rows from APP_DB / ai-calls-analysis-db
- local taxonomy DB reads cluster centroids and writes mapper output

Required env values in .env:

APP_DB_HOST=...
APP_DB_PORT=5432
APP_DB_USER=...
APP_DB_PASS=...
APP_DB_NAME=ai-calls-analysis-db

LOCAL_PG_HOST=127.0.0.1
LOCAL_PG_PORT=5432
LOCAL_PG_DB=taxonomy_drift_local
LOCAL_PG_USER=postgres
LOCAL_PG_PASSWORD=postgres

Example:
python production_cluster_mapper.py ^
  --input-db app ^
  --input-table classification_sample ^
  --call-id-column call_id ^
  --fields call_type ^
  --env-file .env ^
  --cluster-table taxonomy_clusters ^
  --output-table taxonomy_call_cluster_outputs ^
  --ensure-schema ^
  --write-output ^
  --preview-csv taxonomy_cluster_output/call_type/production_mapper_call_type_preview.csv
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
from sklearn.preprocessing import normalize as sk_normalize

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

try:
    import torch
except ImportError:  # pragma: no cover
    torch = None


DEFAULT_CLUSTER_TABLE = "taxonomy_clusters"
DEFAULT_OUTPUT_TABLE = "taxonomy_call_cluster_outputs"
DEFAULT_EXISTING_CLUSTER_THRESHOLD = 0.82
DEFAULT_NEW_CLUSTER_CANDIDATE_THRESHOLD = 0.72
DEFAULT_TOP_K = 5


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


@dataclass(frozen=True)
class ClusterReference:
    field_name: str
    cluster_id: str
    cluster_name: Optional[str]
    display_name: Optional[str]
    centroid_embedding: np.ndarray
    cluster_version: str
    similarity_threshold: float
    cluster_size: Optional[int] = None
    is_true_anomaly_cluster: bool = False


@dataclass(frozen=True)
class MappingResult:
    mapper_run_id: str
    source_record_id: str
    field_name: str
    raw_label: str
    normalized_label: str
    label_embedding: List[float]
    mapped_cluster_id: Optional[str]
    mapped_cluster_name: Optional[str]
    mapped_display_name: Optional[str]
    similarity_score: Optional[float]
    mapping_status: str
    cluster_version: Optional[str]
    top_candidates: List[Dict[str, Any]]
    created_at: datetime


# -----------------------------------------------------------------------------
# Text handling
# -----------------------------------------------------------------------------


def normalize_label(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "n/a", "na", "unknown"}:
        return ""

    text = text.lower()
    text = text.replace("_", " ").replace("-", " ").replace("/", " ")
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def coaching_aware_embedding_text(label: Any) -> str:
    """
    Must stay aligned with pipeline.py.

    This separates coaching direction so Training_Good_* does not collapse into
    Coaching_Poor_* simply because the skill word is similar.
    """
    label_text = str(label or "")
    label_lower = label_text.lower()

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

    skill = label_text
    for prefix in [
        "Training_Good_",
        "Training_Clear_",
        "Coaching_Poor_",
        "Coaching_Unclear_",
        "Coaching_",
        "Training_",
    ]:
        if label_text.startswith(prefix):
            skill = label_text[len(prefix):]
            break

    return f"tier: {tier} | skill: {skill} | direction: {direction} | label: {normalize_label(label_text)}"


def next_step_aware_embedding_text(label: Any) -> str:
    """
    Must stay aligned with pipeline.py.

    Injects broad next-step polarity so operational actions that are semantically
    opposite do not collapse just because wording overlaps.
    """
    label_text = str(label or "")
    label_lower = label_text.lower()

    if any(w in label_lower for w in ["sent", "scheduled", "confirmed", "received", "quote", "proposal", "pending", "closed", "date_found"]):
        polarity = "FORWARD_PROGRESS"
    elif any(w in label_lower for w in ["blocked", "do_not_call", "not_interested", "wrong_number", "ivr_failure"]):
        polarity = "DEAD_END"
    elif any(w in label_lower for w in ["research", "try_later", "internal", "transfer", "admin", "message", "na"]):
        polarity = "HOLDING_PATTERN"
    else:
        polarity = "UNKNOWN"

    return f"next_step_outcome: {polarity} | label: {normalize_label(label_text)}"


def embedding_text(source_column: str, raw_value: Any, mode: str = "field_label") -> str:
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


def split_labels(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, float) and np.isnan(value):
        return []
    if isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "null", "n/a", "na"}:
            return []

        parsed = None
        if (text.startswith("[") and text.endswith("]")) or (text.startswith("(") and text.endswith(")")):
            try:
                parsed = json.loads(text)
            except Exception:
                try:
                    parsed = ast.literal_eval(text)
                except Exception:
                    parsed = None

        if isinstance(parsed, (list, tuple, set)):
            items = list(parsed)
        else:
            if "|" in text:
                items = text.split("|")
            elif ";" in text:
                items = text.split(";")
            elif "," in text:
                items = text.split(",")
            else:
                items = [text]

    cleaned: List[str] = []
    seen = set()
    for item in items:
        raw = str(item).strip()
        normalized = normalize_label(raw)
        if normalized and normalized not in seen:
            cleaned.append(raw)
            seen.add(normalized)
    return cleaned


def stable_record_id(row_index: int, row: pd.Series) -> str:
    payload = json.dumps(row.fillna("").to_dict(), sort_keys=True, default=str)
    digest = hashlib.sha256(f"{row_index}:{payload}".encode("utf-8")).hexdigest()[:24]
    return f"generated_{digest}"


# -----------------------------------------------------------------------------
# Embeddings
# -----------------------------------------------------------------------------


class EmbeddingProvider:
    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        raise NotImplementedError


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model_name: str, device: str):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed. Install it with: "
                "pip install sentence-transformers"
            ) from exc

        self.model_name = model_name
        self.device = device
        if device in {"npu", "openvino-gpu", "openvino-cpu"}:
            ov_device = {"npu": "NPU", "openvino-gpu": "GPU", "openvino-cpu": "CPU"}[device]
            try:
                self.model = SentenceTransformer(
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
        else:
            self.model = SentenceTransformer(model_name, device=device)

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        vectors = self.model.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return sk_normalize(np.asarray(vectors, dtype=np.float32)).astype(float).tolist()


class DeterministicTestEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions

    def embed(self, texts: Sequence[str]) -> List[List[float]]:
        vectors: List[List[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            values = []
            while len(values) < self.dimensions:
                digest = hashlib.sha256(digest).digest()
                values.extend([(byte / 255.0) - 0.5 for byte in digest])
            arr = np.array(values[: self.dimensions], dtype=float)
            norm = np.linalg.norm(arr)
            if norm > 0:
                arr = arr / norm
            vectors.append(arr.tolist())
        return vectors


def build_embedding_provider(args: argparse.Namespace) -> EmbeddingProvider:
    if args.embedding_provider == "sentence-transformers":
        device = resolve_torch_device(args.device)
        print_acceleration_status(device)
        return SentenceTransformerEmbeddingProvider(args.embedding_model, device=device)
    if args.embedding_provider == "deterministic-test":
        return DeterministicTestEmbeddingProvider(args.embedding_dimensions)
    raise ValueError(f"Unsupported embedding provider: {args.embedding_provider}")


# -----------------------------------------------------------------------------
# PostgreSQL connections and schema
# -----------------------------------------------------------------------------


def load_environment(env_file: Optional[str]) -> None:
    if load_dotenv is None:
        return
    if env_file:
        load_dotenv(env_file)
    else:
        load_dotenv()


def get_local_pg_connection():
    conn_str = os.getenv("LOCAL_PG_CONN_STR") or os.getenv("PG_CONN_STR")
    if conn_str:
        return psycopg2.connect(conn_str)

    return psycopg2.connect(
        host=os.getenv("LOCAL_PG_HOST", "127.0.0.1"),
        port=int(os.getenv("LOCAL_PG_PORT", "5432")),
        dbname=os.getenv("LOCAL_PG_DB", "taxonomy_drift_local"),
        user=os.getenv("LOCAL_PG_USER", "postgres"),
        password=os.getenv("LOCAL_PG_PASSWORD", "postgres"),
    )


def get_app_db_connection():
    conn_str = os.getenv("APP_DB_CONN_STR")
    if conn_str:
        return psycopg2.connect(conn_str)

    required = {
        "APP_DB_HOST": os.getenv("APP_DB_HOST"),
        "APP_DB_USER": os.getenv("APP_DB_USER"),
        "APP_DB_PASS": os.getenv("APP_DB_PASS"),
        "APP_DB_NAME": os.getenv("APP_DB_NAME"),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise ValueError(f"Missing APP DB env values: {missing}")

    return psycopg2.connect(
        host=os.getenv("APP_DB_HOST"),
        port=int(os.getenv("APP_DB_PORT", "5432")),
        dbname=os.getenv("APP_DB_NAME"),
        user=os.getenv("APP_DB_USER"),
        password=os.getenv("APP_DB_PASS"),
    )


def safe_pg_identifier(name: str) -> str:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        raise ValueError(f"Unsafe SQL identifier: {name}")
    return f'"{name}"'


def safe_pg_qualified_name(name: str) -> str:
    parts = name.split(".")
    if not parts or any(not part for part in parts):
        raise ValueError(f"Unsafe SQL table name: {name}")
    return ".".join(safe_pg_identifier(part) for part in parts)


def ensure_schema(conn, cluster_table: str, output_table: str) -> None:
    cluster_t = safe_pg_qualified_name(cluster_table)
    output_t = safe_pg_qualified_name(output_table)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {cluster_t} (
                id BIGSERIAL PRIMARY KEY,
                field_name TEXT NOT NULL,
                cluster_id TEXT NOT NULL,
                cluster_name TEXT,
                display_name TEXT,
                cluster_summary TEXT,
                centroid_embedding JSONB,
                cluster_size INTEGER,
                cluster_version TEXT DEFAULT 'v1',
                similarity_threshold NUMERIC,
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {output_t} (
                id BIGSERIAL PRIMARY KEY,
                mapper_run_id TEXT NOT NULL,
                source_record_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                raw_label TEXT NOT NULL,
                normalized_label TEXT NOT NULL,
                label_embedding JSONB NOT NULL,
                mapped_cluster_id TEXT,
                mapped_cluster_name TEXT,
                mapped_display_name TEXT,
                similarity_score NUMERIC,
                mapping_status TEXT NOT NULL,
                cluster_version TEXT,
                top_candidates JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        for column, definition in {
            "mapped_display_name": "TEXT",
            "top_candidates": "JSONB",
        }.items():
            cur.execute(f"ALTER TABLE {output_t} ADD COLUMN IF NOT EXISTS {column} {definition};")

        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{output_table}_record_field ON {output_t}(source_record_id, field_name);"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{output_table}_status ON {output_t}(mapping_status);"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{output_table}_run ON {output_t}(mapper_run_id);"
        )

    conn.commit()


def read_input_from_postgres(
    conn,
    input_table: str,
    call_id_column: str,
    fields: Sequence[str],
    where_clause: Optional[str],
    limit: Optional[int],
) -> pd.DataFrame:
    selected_columns = [call_id_column] + [field for field in fields if field != call_id_column]
    column_sql = ", ".join([safe_pg_identifier(col) for col in selected_columns])
    table_sql = safe_pg_qualified_name(input_table)

    sql = f"SELECT {column_sql} FROM {table_sql}"
    if where_clause:
        sql += f" WHERE {where_clause}"
    if limit:
        sql += f" LIMIT {int(limit)}"

    print(f"Reading input rows from table: {input_table}")
    print(f"Input SQL: {sql}")
    return pd.read_sql_query(sql, conn)


def parse_embedding(value: Any) -> np.ndarray:
    if value is None:
        raise ValueError("centroid_embedding is null")
    if isinstance(value, np.ndarray):
        arr = value.astype(float)
    elif isinstance(value, list):
        arr = np.array(value, dtype=float)
    elif isinstance(value, str):
        arr = np.array(json.loads(value), dtype=float)
    else:
        arr = np.array(value, dtype=float)
    if arr.ndim != 1:
        raise ValueError("centroid_embedding must be a 1D vector")
    norm = np.linalg.norm(arr)
    if norm > 0:
        arr = arr / norm
    return arr.astype(np.float32)


def load_active_clusters(
    conn,
    cluster_table: str,
    fields: Sequence[str],
    default_existing_threshold: float,
    cluster_version: Optional[str],
) -> Dict[str, List[ClusterReference]]:
    cluster_t = safe_pg_qualified_name(cluster_table)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        params: List[Any] = [list(fields)]
        version_filter = ""
        if cluster_version:
            version_filter = "AND COALESCE(c.cluster_version, 'v1') = %s"
            params.append(cluster_version)

        cur.execute(
            f"""
            SELECT
                c.field_name,
                c.cluster_id,
                n.display_name AS cluster_name,
                n.display_name AS display_name,
                c.centroid_embedding,
                COALESCE(c.cluster_version, 'v1') AS cluster_version,
                c.similarity_threshold,
                c.cluster_size,
                COALESCE(c.is_true_anomaly_cluster, false) AS is_true_anomaly_cluster
            FROM {cluster_t} c
            LEFT JOIN taxonomy_cluster_names n
            ON c.field_name = n.field_name
            AND c.run_id = n.run_id
            AND c.cluster_version = n.cluster_version
            AND c.cluster_id = n.cluster_id
            WHERE c.active = TRUE
            AND c.field_name = ANY(%s)
            AND c.centroid_embedding IS NOT NULL
            {version_filter}
            ORDER BY c.field_name, c.cluster_id;
            """,
            params,
        )
        rows = cur.fetchall()

    by_field: Dict[str, List[ClusterReference]] = {field: [] for field in fields}
    for row in rows:
        try:
            centroid = parse_embedding(row["centroid_embedding"])
        except Exception as exc:
            print(
                f"Skipping invalid centroid field={row.get('field_name')} cluster_id={row.get('cluster_id')}: {exc}",
                file=sys.stderr,
            )
            continue

        threshold = row.get("similarity_threshold")
        if threshold is None:
            threshold = default_existing_threshold

        ref = ClusterReference(
            field_name=row["field_name"],
            cluster_id=str(row["cluster_id"]),
            cluster_name=row.get("cluster_name"),
            display_name=row.get("display_name"),
            centroid_embedding=centroid,
            cluster_version=row.get("cluster_version") or "v1",
            similarity_threshold=float(threshold),
            cluster_size=row.get("cluster_size"),
            is_true_anomaly_cluster=bool(row.get("is_true_anomaly_cluster")),
        )
        by_field.setdefault(ref.field_name, []).append(ref)

    return by_field


def insert_mapping_results(conn, output_table: str, results: Sequence[MappingResult], batch_size: int = 1000) -> None:
    if not results:
        return

    output_t = safe_pg_qualified_name(output_table)
    rows = [
        (
            result.mapper_run_id,
            result.source_record_id,
            result.field_name,
            result.raw_label,
            result.normalized_label,
            psycopg2.extras.Json(result.label_embedding),
            result.mapped_cluster_id,
            result.mapped_cluster_name,
            result.mapped_display_name,
            result.similarity_score,
            result.mapping_status,
            result.cluster_version,
            psycopg2.extras.Json(result.top_candidates),
            result.created_at,
        )
        for result in results
    ]

    sql = f"""
        INSERT INTO {output_t} (
            mapper_run_id,
            source_record_id,
            field_name,
            raw_label,
            normalized_label,
            label_embedding,
            mapped_cluster_id,
            mapped_cluster_name,
            mapped_display_name,
            similarity_score,
            mapping_status,
            cluster_version,
            top_candidates,
            created_at
        ) VALUES %s
    """

    with conn.cursor() as cur:
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            psycopg2.extras.execute_values(cur, sql, batch, page_size=batch_size)
    conn.commit()


# -----------------------------------------------------------------------------
# Mapping
# -----------------------------------------------------------------------------


def cosine_similarity_matrix(query: np.ndarray, candidates: np.ndarray) -> np.ndarray:
    query = np.asarray(query, dtype=np.float32)
    q_norm = np.linalg.norm(query)
    if q_norm > 0:
        query = query / q_norm
    candidates = np.asarray(candidates, dtype=np.float32)
    c_norms = np.linalg.norm(candidates, axis=1, keepdims=True)
    c_norms[c_norms == 0] = 1.0
    return (candidates / c_norms) @ query


def parse_field_threshold_overrides(value: Optional[str]) -> Dict[str, float]:
    """
    Parse comma-separated field threshold overrides.

    Example:
        next_step=0.75,coaching_tags=0.82
    """
    overrides: Dict[str, float] = {}
    if not value:
        return overrides

    for part in str(value).split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(
                f"Invalid --field-existing-thresholds entry: {part}. "
                "Expected format field=value, e.g. next_step=0.75"
            )
        field_name, threshold_text = part.split("=", 1)
        field_name = field_name.strip()
        if not field_name:
            raise ValueError(f"Invalid empty field name in --field-existing-thresholds: {part}")
        threshold = float(threshold_text.strip())
        if threshold < 0 or threshold > 1:
            raise ValueError(f"Threshold must be between 0 and 1 for {field_name}: {threshold}")
        overrides[field_name] = threshold

    return overrides


def effective_existing_threshold(
    *,
    field_name: str,
    cluster_threshold: float,
    field_threshold_overrides: Dict[str, float],
) -> float:
    return float(field_threshold_overrides.get(field_name, cluster_threshold))


def map_label_to_cluster(
    *,
    mapper_run_id: str,
    source_record_id: str,
    field_name: str,
    raw_label: str,
    normalized_label: str,
    label_embedding: List[float],
    clusters: Sequence[ClusterReference],
    new_cluster_candidate_threshold: float,
    top_k: int,
    field_existing_thresholds: Dict[str, float],
) -> MappingResult:
    created_at = datetime.now(timezone.utc)

    if not clusters:
        return MappingResult(
            mapper_run_id=mapper_run_id,
            source_record_id=source_record_id,
            field_name=field_name,
            raw_label=raw_label,
            normalized_label=normalized_label,
            label_embedding=label_embedding,
            mapped_cluster_id=None,
            mapped_cluster_name=None,
            mapped_display_name=None,
            similarity_score=None,
            mapping_status="NO_CLUSTER_REFERENCE",
            cluster_version=None,
            top_candidates=[],
            created_at=created_at,
        )

    query = np.array(label_embedding, dtype=np.float32)
    centroids = np.vstack([cluster.centroid_embedding for cluster in clusters])
    scores = cosine_similarity_matrix(query, centroids)
    order = np.argsort(scores)[::-1]

    top_candidates: List[Dict[str, Any]] = []
    for idx in order[:top_k]:
        cluster = clusters[int(idx)]
        top_candidates.append(
            {
                "cluster_id": cluster.cluster_id,
                "cluster_name": cluster.cluster_name,
                "display_name": cluster.display_name,
                "similarity_score": float(scores[int(idx)]),
                "cluster_version": cluster.cluster_version,
                "cluster_size": cluster.cluster_size,
                "similarity_threshold": effective_existing_threshold(
                    field_name=field_name,
                    cluster_threshold=cluster.similarity_threshold,
                    field_threshold_overrides=field_existing_thresholds,
                ),
                "is_true_anomaly_cluster": cluster.is_true_anomaly_cluster,
            }
        )

    best_idx = int(order[0])
    best_cluster = clusters[best_idx]
    best_score = float(scores[best_idx])
    best_threshold = effective_existing_threshold(
        field_name=field_name,
        cluster_threshold=best_cluster.similarity_threshold,
        field_threshold_overrides=field_existing_thresholds,
    )

    if best_score >= best_threshold:
        status = "EXISTING_CLUSTER"
        mapped_cluster_id = best_cluster.cluster_id
        mapped_cluster_name = best_cluster.cluster_name
        mapped_display_name = best_cluster.display_name
    elif best_score >= new_cluster_candidate_threshold:
        status = "NEW_CLUSTER_CANDIDATE"
        mapped_cluster_id = None
        mapped_cluster_name = None
        mapped_display_name = None
    else:
        status = "TRUE_ANOMALY"
        mapped_cluster_id = None
        mapped_cluster_name = None
        mapped_display_name = None

    return MappingResult(
        mapper_run_id=mapper_run_id,
        source_record_id=source_record_id,
        field_name=field_name,
        raw_label=raw_label,
        normalized_label=normalized_label,
        label_embedding=label_embedding,
        mapped_cluster_id=mapped_cluster_id,
        mapped_cluster_name=mapped_cluster_name,
        mapped_display_name=mapped_display_name,
        similarity_score=best_score,
        mapping_status=status,
        cluster_version=best_cluster.cluster_version,
        top_candidates=top_candidates,
        created_at=created_at,
    )


def explode_call_rows(df: pd.DataFrame, call_id_column: str, fields: Sequence[str]) -> pd.DataFrame:
    records: List[Dict[str, Any]] = []

    for row_index, row in df.iterrows():
        source_record_id = row.get(call_id_column)
        if source_record_id is None or str(source_record_id).strip() == "" or str(source_record_id).lower() == "nan":
            source_record_id = stable_record_id(int(row_index), row)
        else:
            source_record_id = str(source_record_id)

        for field_name in fields:
            if field_name not in df.columns:
                continue
            raw_values = split_labels(row.get(field_name))
            for raw_label in raw_values:
                normalized_label = normalize_label(raw_label)
                if not normalized_label:
                    continue
                records.append(
                    {
                        "source_record_id": source_record_id,
                        "field_name": field_name,
                        "raw_label": raw_label,
                        "normalized_label": normalized_label,
                    }
                )

    if not records:
        return pd.DataFrame(columns=["source_record_id", "field_name", "raw_label", "normalized_label"])

    return (
        pd.DataFrame(records)
        .drop_duplicates(subset=["source_record_id", "field_name", "normalized_label"])
        .reset_index(drop=True)
    )


def run_mapping(
    *,
    df: pd.DataFrame,
    call_id_column: str,
    fields: Sequence[str],
    embedding_provider: EmbeddingProvider,
    clusters_by_field: Dict[str, List[ClusterReference]],
    mapper_run_id: str,
    new_cluster_candidate_threshold: float,
    top_k: int,
    embedding_batch_size: int,
    text_mode: str,
    field_existing_thresholds: Dict[str, float],
) -> List[MappingResult]:
    exploded = explode_call_rows(df, call_id_column, fields)
    if exploded.empty:
        return []

    exploded["embedding_text"] = [
        embedding_text(row.field_name, row.raw_label, mode=text_mode)
        for row in exploded.itertuples(index=False)
    ]

    print(f"Exploded call-field labels: {len(exploded):,}")
    unique_texts = sorted(exploded["embedding_text"].unique().tolist())
    print(f"Unique embedding texts to embed/map: {len(unique_texts):,}")
    print(f"Embedding text mode: {text_mode}")

    embedding_lookup: Dict[str, List[float]] = {}
    for start in range(0, len(unique_texts), embedding_batch_size):
        batch_texts = unique_texts[start : start + embedding_batch_size]
        batch_embeddings = embedding_provider.embed(batch_texts)
        for text, embedding in zip(batch_texts, batch_embeddings):
            embedding_lookup[text] = embedding

    results: List[MappingResult] = []
    for _, item in exploded.iterrows():
        normalized_label = item["normalized_label"]
        field_name = item["field_name"]
        result = map_label_to_cluster(
            mapper_run_id=mapper_run_id,
            source_record_id=item["source_record_id"],
            field_name=field_name,
            raw_label=item["raw_label"],
            normalized_label=normalized_label,
            label_embedding=embedding_lookup[item["embedding_text"]],
            clusters=clusters_by_field.get(field_name, []),
            new_cluster_candidate_threshold=new_cluster_candidate_threshold,
            top_k=top_k,
            field_existing_thresholds=field_existing_thresholds,
        )
        results.append(result)

    return results


# -----------------------------------------------------------------------------
# Output helpers
# -----------------------------------------------------------------------------


def summarize_results(results: Sequence[MappingResult]) -> pd.DataFrame:
    if not results:
        return pd.DataFrame(columns=["field_name", "mapping_status", "count"])
    df = pd.DataFrame(
        [
            {
                "field_name": result.field_name,
                "mapping_status": result.mapping_status,
                "mapped_display_name": result.mapped_display_name,
            }
            for result in results
        ]
    )
    return (
        df.groupby(["field_name", "mapping_status"])
        .size()
        .reset_index(name="count")
        .sort_values(["field_name", "count"], ascending=[True, False])
    )


def write_preview_csv(results: Sequence[MappingResult], output_path: str) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "mapper_run_id": result.mapper_run_id,
            "source_record_id": result.source_record_id,
            "field_name": result.field_name,
            "raw_label": result.raw_label,
            "normalized_label": result.normalized_label,
            "mapped_cluster_id": result.mapped_cluster_id,
            "mapped_cluster_name": result.mapped_cluster_name,
            "mapped_display_name": result.mapped_display_name,
            "similarity_score": result.similarity_score,
            "mapping_status": result.mapping_status,
            "cluster_version": result.cluster_version,
            "top_candidates": json.dumps(result.top_candidates, ensure_ascii=False),
            "mapped_to_anomaly_cluster": bool((result.top_candidates or [{}])[0].get("is_true_anomaly_cluster")) if result.mapped_cluster_id else False,
            "created_at": result.created_at.isoformat(),
        }
        for result in results
    ]
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8")


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Map post-classification call field labels to existing taxonomy clusters."
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input-file", help="CSV file containing post-classification call rows.")
    input_group.add_argument("--input-table", help="PostgreSQL table containing post-classification call rows.")

    parser.add_argument(
        "--input-db",
        choices=["local", "app"],
        default="local",
        help="Database to read --input-table from. Use app for ai-calls-analysis-db; local for taxonomy_drift_local.",
    )
    parser.add_argument("--where", help="Optional SQL WHERE clause for --input-table. Do not include WHERE.")
    parser.add_argument("--limit", type=int, help="Optional row limit for PostgreSQL input.")
    parser.add_argument("--call-id-column", default="call_id", help="Column containing the call/source record id.")
    parser.add_argument("--fields", required=True, help="Comma-separated classified fields to process.")

    parser.add_argument("--env-file", help="Optional .env file path.")
    parser.add_argument("--cluster-table", default=DEFAULT_CLUSTER_TABLE)
    parser.add_argument("--output-table", default=DEFAULT_OUTPUT_TABLE)
    parser.add_argument("--cluster-version", help="Optional cluster version to use. If omitted, all active versions are eligible.")
    parser.add_argument("--ensure-schema", action="store_true", help="Create/patch required local PostgreSQL output table.")
    parser.add_argument("--write-output", action="store_true", help="Insert mapping results into local PostgreSQL output table.")
    parser.add_argument("--preview-csv", help="Optional path to save mapping results as CSV.")

    parser.add_argument("--existing-cluster-threshold", type=float, default=DEFAULT_EXISTING_CLUSTER_THRESHOLD)
    parser.add_argument(
        "--field-existing-thresholds",
        help="Optional comma-separated per-field existing-cluster thresholds, e.g. next_step=0.75,coaching_tags=0.82",
    )
    parser.add_argument("--new-cluster-candidate-threshold", type=float, default=DEFAULT_NEW_CLUSTER_CANDIDATE_THRESHOLD)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--embedding-batch-size", type=int, default=128)
    parser.add_argument(
        "--text-mode",
        choices=["field_label", "label_only"],
        default="field_label",
        help="Embedding text format. Must match offline clustering. Default field_label matches pipeline.py default.",
    )

    parser.add_argument(
        "--embedding-provider",
        choices=["sentence-transformers", "deterministic-test"],
        default="sentence-transformers",
    )
    parser.add_argument(
        "--embedding-model",
        default=os.getenv("EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2"),
        help="Must match the model used by offline clustering.",
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="Embedding device: auto, cpu, cuda, cuda:N, npu, openvino-gpu, or openvino-cpu.",
    )
    parser.add_argument("--embedding-dimensions", type=int, default=384)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_environment(args.env_file)

    fields = [field.strip() for field in args.fields.split(",") if field.strip()]
    field_existing_thresholds = parse_field_threshold_overrides(args.field_existing_thresholds)
    if field_existing_thresholds:
        print(f"Per-field existing-cluster thresholds: {field_existing_thresholds}")
    if not fields:
        raise ValueError("At least one field is required in --fields.")

    mapper_run_id = f"mapper_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    local_conn = get_local_pg_connection()
    input_conn = None
    try:
        if args.ensure_schema:
            ensure_schema(local_conn, args.cluster_table, args.output_table)

        if args.input_file:
            df = pd.read_csv(args.input_file)
        else:
            if args.input_db == "app":
                input_conn = get_app_db_connection()
                print("Input DB: APP_DB / ai-calls-analysis-db")
            else:
                input_conn = local_conn
                print("Input DB: LOCAL_PG / taxonomy_drift_local")

            df = read_input_from_postgres(
                conn=input_conn,
                input_table=args.input_table,
                call_id_column=args.call_id_column,
                fields=fields,
                where_clause=args.where,
                limit=args.limit,
            )

        print(f"Loaded input rows: {len(df):,}")
        missing_fields = [field for field in fields if field not in df.columns]
        if missing_fields:
            print(f"Warning: fields not found in input and skipped: {missing_fields}", file=sys.stderr)

        clusters_by_field = load_active_clusters(
            conn=local_conn,
            cluster_table=args.cluster_table,
            fields=fields,
            default_existing_threshold=args.existing_cluster_threshold,
            cluster_version=args.cluster_version,
        )

        for field in fields:
            print(f"Loaded active clusters for {field}: {len(clusters_by_field.get(field, [])):,}")

        embedding_provider = build_embedding_provider(args)
        results = run_mapping(
            df=df,
            call_id_column=args.call_id_column,
            fields=fields,
            embedding_provider=embedding_provider,
            clusters_by_field=clusters_by_field,
            mapper_run_id=mapper_run_id,
            new_cluster_candidate_threshold=args.new_cluster_candidate_threshold,
            top_k=args.top_k,
            embedding_batch_size=args.embedding_batch_size,
            text_mode=args.text_mode,
            field_existing_thresholds=field_existing_thresholds,
        )

        summary = summarize_results(results)
        print("\nMapper run id:", mapper_run_id)
        print("\nMapping summary:")
        if summary.empty:
            print("No labels were mapped.")
        else:
            print(summary.to_string(index=False))

        if args.write_output:
            insert_mapping_results(local_conn, args.output_table, results)
            print(f"\nInserted {len(results):,} rows into local table: {args.output_table}")
        else:
            print("\nOutput not written. Add --write-output to insert results.")

        if args.preview_csv:
            write_preview_csv(results, args.preview_csv)
            print(f"Saved preview CSV: {args.preview_csv}")

        return 0

    finally:
        if input_conn is not None and input_conn is not local_conn:
            input_conn.close()
        local_conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
