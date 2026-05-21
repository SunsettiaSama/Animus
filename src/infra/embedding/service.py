from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from embedding.embedder import Embedder


class EmbeddingService:
    """嵌入基础设施：懒加载 ``embedding.Embedder``，避免 import 时拉取 torch。"""

    def __init__(
        self,
        *,
        model_name_or_path: str,
        device: str = "auto",
        use_fp16: bool = True,
        batch_size: int = 32,
        query_prefix: str = "query: ",
        passage_prefix: str = "",
    ) -> None:
        self._model_name_or_path = model_name_or_path
        self._device = device
        self._use_fp16 = use_fp16
        self._batch_size = batch_size
        self._query_prefix = query_prefix
        self._passage_prefix = passage_prefix
        self._embedder: Embedder | None = None

    def _get(self) -> Embedder:
        if self._embedder is None:
            from embedding.embedder import Embedder

            self._embedder = Embedder(
                model_name=self._model_name_or_path,
                device=self._device,
                use_fp16=self._use_fp16,
                batch_size=self._batch_size,
                query_prefix=self._query_prefix,
                passage_prefix=self._passage_prefix,
            )
        return self._embedder

    def warm_up(self) -> None:
        self._get().warm_up()

    def embed_query(self, text: str) -> list[float]:
        return self._get().embed_query(text)

    def embed_passage(self, text: str) -> list[float]:
        return self._get().embed_documents([text])[0]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._get().embed_documents(texts)
