"""2-D projection of chunk embeddings for the embeddings scatter.

Uses UMAP when umap-learn is installed (much better cluster separation on
text embeddings); falls back to plain PCA otherwise. Either way the payload
carries k-means cluster assignments with TF-IDF term labels so the map can
color and name topic clusters. Recompute on the configured DB without
re-ingesting:  python -m app.rag.pca
"""
from __future__ import annotations

import math
import re
from collections import Counter

from app.rag.vector_index import VectorIndex

# English function words plus the post-markdown boilerplate every chunk shares.
STOPWORDS = frozenset(
    "the a an and or but if then else for to of in on at by with from as is "
    "are was were be been being this that these those it its they them their "
    "he she his her you your we our i my me not no nor do does did done have "
    "has had having will would can could should may might must shall about "
    "into over under more most some any all each both few just also than "
    "when what who whom how why where which there here out up down off so "
    "very too only own same other another new after before because while "
    "during between against through don didn doesn isn wasn aren won "
    "points comments comment top pts flair week post posts thread threads "
    "game games gaming like get got one really".split()
)

_WORD = re.compile(r"[a-z][a-z0-9']{2,}")


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in STOPWORDS]


def _kmeans(coords, k: int, seed: int = 42):
    """Plain numpy k-means (k-means++ seeding, 50 iters). Deterministic."""
    import numpy as np

    rng = np.random.default_rng(seed)
    centers = [coords[int(rng.integers(len(coords)))]]
    for _ in range(k - 1):
        d2 = np.min(
            [((coords - c) ** 2).sum(axis=1) for c in centers], axis=0
        )
        total = d2.sum()
        idx = (
            int(rng.choice(len(coords), p=d2 / total))
            if total > 0
            else int(rng.integers(len(coords)))
        )
        centers.append(coords[idx])
    centers = np.array(centers)

    labels = None
    for _ in range(50):
        dists = ((coords[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        new_labels = dists.argmin(axis=1)
        if labels is not None and (new_labels == labels).all():
            break
        labels = new_labels
        for j in range(k):
            members = coords[labels == j]
            if len(members):
                centers[j] = members.mean(axis=0)
    return labels


def _cluster_meta(chunks, labels, k: int) -> list[dict]:
    """Name each cluster by its top TF-IDF terms."""
    n = len(chunks)
    df: Counter = Counter()
    per_chunk_tokens = [_tokens(c.content) for c in chunks]
    for toks in per_chunk_tokens:
        df.update(set(toks))

    out = []
    for j in range(k):
        members = [i for i in range(n) if labels[i] == j]
        tf: Counter = Counter()
        for i in members:
            tf.update(per_chunk_tokens[i])
        scored = sorted(
            tf.items(),
            key=lambda kv: -(kv[1] * math.log(1 + n / (1 + df[kv[0]]))),
        )
        terms = [w for w, _ in scored[:2]]
        out.append(
            {
                "id": j,
                "label": " · ".join(terms) if terms else f"cluster {j}",
                "n": len(members),
            }
        )
    return out


def compute_pca(
    vector_index: VectorIndex,
    *,
    model: str,
    dim: int,
) -> dict | None:
    """Project all chunk embeddings to 2-D with cluster assignments.
    Returns a JSON-able payload (stored in the meta table) or None when
    there is too little data. (Name kept from the PCA-only era.)"""
    import numpy as np

    pairs = vector_index.all_embeddings()
    if len(pairs) < 3:
        return None

    X = np.array([emb for _, emb in pairs])
    method = "pca"
    try:
        import umap  # optional: pip install umap-learn

        coords = umap.UMAP(
            n_components=2,
            n_neighbors=min(15, len(pairs) - 1),
            min_dist=0.1,
            metric="cosine",
            random_state=42,
        ).fit_transform(X)
        coords = np.asarray(coords, dtype=float)
        method = "umap"
    except ImportError:
        mean = X.mean(axis=0)
        _, _, vt = np.linalg.svd(X - mean, full_matrices=False)
        coords = (X - mean) @ vt[:2].T

    chunks = [chunk for chunk, _ in pairs]
    k = min(6, max(2, len(chunks) // 25))
    labels = _kmeans(coords, k)
    clusters = _cluster_meta(chunks, labels, k)

    points = []
    for i, chunk in enumerate(chunks):
        points.append(
            {
                "id": chunk.chunk_id,
                "path": chunk.path,
                "heading": " > ".join(h for h in chunk.heading_path if h),
                "x": round(float(coords[i, 0]), 5),
                "y": round(float(coords[i, 1]), 5),
                "cluster": int(labels[i]),
            }
        )

    return {
        "embedding_model": model,
        "embedding_dim": dim,
        "method": method,
        "points": points,
        "clusters": clusters,
    }


def main() -> None:
    """Recompute the stored projection for the configured DB (no re-embed)."""
    import json

    from app import config, db

    conn = db.connect(config.DB_PATH)
    dim = int(db.get_meta(conn, "embedding_dim") or config.EMBEDDING_DIM)
    model = db.get_meta(conn, "embedding_model") or config.EMBEDDING_MODEL
    vec = VectorIndex(config.DB_PATH, dim=dim)
    payload = compute_pca(vec, model=model, dim=dim)
    if payload is None:
        print("too few embeddings to project")
        return
    db.set_meta(conn, "pca", json.dumps(payload))
    print(
        f"reprojected {len(payload['points'])} points ({payload['method']}) "
        f"into {len(payload['clusters'])} clusters"
    )
    conn.close()
    vec.close()


if __name__ == "__main__":
    main()
