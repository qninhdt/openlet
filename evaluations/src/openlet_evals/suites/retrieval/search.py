"""Qdrant hybrid/dense/bm25 search mirroring `apps/letfs/internal/storage/search.go`."""

from __future__ import annotations

import posixpath
from typing import Literal

from qdrant_client import QdrantClient, models

from .corpus import COLLECTION

SearchMode = Literal["hybrid", "dense", "bm25"]


def search_qdrant(
    client: QdrantClient,
    bid_to_path: dict[str, str],
    *,
    query: str,
    vector: list[float],
    workspace: str,
    mode: SearchMode = "hybrid",
    top_k: int = 5,
    prefetch_limit: int = 50,
) -> list[dict[str, object]]:
    """Run Qdrant search scoped to one workspace's full `/shared` storage and dedup hits."""
    qf = models.Filter(
        must=[
            models.FieldCondition(
                key="workspace_id", match=models.MatchValue(value=workspace)
            )
        ]
    )
    bm25 = models.TextQuery(
        text=models.TextQueryInput(
            query=query, scoring=models.Bm25Scoring(bm25=models.Bm25Params())
        )
    )
    fetch = max(10, top_k)

    if mode == "bm25":
        pts = client.query_points(
            COLLECTION,
            query=bm25,
            using="text",
            query_filter=qf,
            limit=fetch,
            with_payload=["blob_id", "artifact_path", "text"],
        ).points
    elif mode == "dense":
        pts = client.query_points(
            COLLECTION,
            query=vector,
            query_filter=qf,
            limit=fetch,
            with_payload=["blob_id", "artifact_path", "text"],
        ).points
    else:
        pts = client.query_points(
            COLLECTION,
            prefetch=[
                models.Prefetch(query=vector, filter=qf, limit=prefetch_limit),
                models.Prefetch(
                    query=bm25, using="text", filter=qf, limit=prefetch_limit
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=fetch,
            with_payload=["blob_id", "artifact_path", "text"],
        ).points

    seen: set[tuple[str, str, str]] = set()
    hits: list[dict[str, object]] = []
    for pt in pts:
        pl = pt.payload or {}
        bid, ap, txt = (
            str(pl["blob_id"]),
            str(pl.get("artifact_path", "")),
            str(pl.get("text", "")),
        )
        key = (bid, ap, txt)
        if key in seen:
            continue
        seen.add(key)
        bp = bid_to_path[bid]
        hits.append(
            {
                "file": posixpath.join(bp, ap) if ap else bp,
                "score": float(pt.score),
                "text": txt,
            }
        )
        if len(hits) >= top_k:
            break
    return hits
