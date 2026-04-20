from __future__ import annotations

import os

from langchain_community.embeddings import HuggingFaceBgeEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document


def load(
    output_dir: str,
    embeddings: HuggingFaceBgeEmbeddings,
    index_name: str = "index",
) -> FAISS:
    return FAISS.load_local(
        output_dir,
        embeddings,
        index_name,
        allow_dangerous_deserialization=True,
    )


def search(
    vectorstore: FAISS,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    results = vectorstore.similarity_search_with_relevance_scores(query, k=top_k)
    output: list[dict] = []
    for doc, score in results:
        item = dict(doc.metadata)
        item["text"] = doc.page_content
        item["score"] = float(score)
        output.append(item)
    return output
