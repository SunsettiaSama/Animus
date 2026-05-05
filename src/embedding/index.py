from __future__ import annotations

import os

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document


def build_faiss_index(
    docs: list[Document],
    embeddings: HuggingFaceEmbeddings,
) -> FAISS:
    return FAISS.from_documents(docs, embeddings)


def save(
    vectorstore: FAISS,
    output_dir: str,
    index_name: str = "index",
) -> None:
    os.makedirs(output_dir, exist_ok=True)
    vectorstore.save_local(output_dir, index_name)


def load(
    output_dir: str,
    embeddings: HuggingFaceEmbeddings,
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
