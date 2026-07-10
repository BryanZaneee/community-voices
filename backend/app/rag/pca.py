"""PCA projection of chunk embeddings to 2-D for the embeddings scatter."""
from __future__ import annotations

from app.rag.vector_index import VectorIndex


def compute_pca(
    vector_index: VectorIndex,
    *,
    model: str,
    dim: int,
) -> dict | None:
    """Project all chunk embeddings to 2-D. Returns a JSON-able payload
    (stored in the meta table) or None when there is too little data."""
    import numpy as np

    pairs = vector_index.all_embeddings()
    if len(pairs) < 3:
        return None

    X = np.array([emb for _, emb in pairs])
    mean = X.mean(axis=0)
    _, _, vt = np.linalg.svd(X - mean, full_matrices=False)
    components = vt[:2]
    coords = (X - mean) @ components.T

    points = []
    for i, (chunk, _) in enumerate(pairs):
        points.append(
            {
                "id": chunk.chunk_id,
                "path": chunk.path,
                "heading": " > ".join(h for h in chunk.heading_path if h),
                "x": round(float(coords[i, 0]), 5),
                "y": round(float(coords[i, 1]), 5),
            }
        )

    return {
        "embedding_model": model,
        "embedding_dim": dim,
        "points": points,
    }
