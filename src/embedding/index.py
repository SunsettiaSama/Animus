from __future__ import annotations

import os
from typing import TYPE_CHECKING

from langchain_core.documents import Document
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from embedding.embedder import infer_dim

if TYPE_CHECKING:
    from langchain_huggingface import HuggingFaceEmbeddings


def build_index(
    docs: list[Document],
    embeddings: HuggingFaceEmbeddings,
    output_dir: str,
    collection_name: str = "corpus",
) -> QdrantClient:
    """Embed *docs* and persist them to a local Qdrant collection.

    Creates (or recreates) *collection_name* inside *output_dir* and
    returns the connected QdrantClient.
    """
    os.makedirs(output_dir, exist_ok=True)
    client = QdrantClient(path=output_dir)

    model_name = embeddings.model_name
    dim = infer_dim(model_name)

    existing = {c.name for c in client.get_collections().collections}
    if collection_name in existing:
        client.delete_collection(collection_name)
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )

    texts = [doc.page_content for doc in docs]
    vectors = embeddings.embed_documents(texts)

    points = [
        PointStruct(
            id=i,
            vector=vec,
            payload={"text": doc.page_content, **doc.metadata},
        )
        for i, (doc, vec) in enumerate(zip(docs, vectors))
    ]
    client.upsert(collection_name=collection_name, points=points)
    return client


def load(
    output_dir: str,
    collection_name: str = "corpus",
) -> QdrantClient:
    """Return a QdrantClient pointed at an existing local collection."""
    return QdrantClient(path=output_dir)


def search(
    client: QdrantClient,
    embeddings: HuggingFaceEmbeddings,
    query: str,
    collection_name: str = "corpus",
    top_k: int = 5,
) -> list[dict]:
    """Semantic search over *collection_name*; returns a list of result dicts."""
    vector = embeddings.embed_query(query)
    hits = client.query_points(
        collection_name=collection_name,
        query=vector,
        limit=top_k,
        with_payload=True,
    ).points
    output: list[dict] = []
    for hit in hits:
        item = dict(hit.payload or {})
        item["score"] = float(hit.score)
        output.append(item)
    return output
