"""Portable RAG stack: chunker, embeddings, sqlite-vec index, BM25, hybrid retriever, PCA.

Ported from the author's easyagent project and adapted for this repo:
single shared sqlite file, no profile plumbing, optional embedding leg.
"""
