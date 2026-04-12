"""
Lazy-initialized icon finder. The original version eagerly builds a ChromaDB
embedding index at import time, which OOMs on small Railway instances.

This patched version defers ALL heavy work (chromadb + onnx model + embedding
generation) until the first time search_icons() is actually called. On startup
we only keep a lightweight JSON lookup available as a fallback so that search
always returns something even if the embeddings never get built.
"""

import asyncio
import json
import os


class IconFinderService:
    def __init__(self):
        self.collection_name = "icons"
        self._client = None
        self._collection = None
        self._embedding_function = None
        self._init_started = False
        self._init_lock = asyncio.Lock()

        # Load a lightweight in-memory name index up front so we can respond
        # with a reasonable match even before the embeddings are built.
        self._fallback_index = []
        try:
            asset_path = os.path.join(
                os.path.dirname(__file__), "..", "assets", "icons.json"
            )
            with open(asset_path, "r") as f:
                icons = json.load(f)
            for each in icons.get("icons", []):
                name = each.get("name", "")
                if name.endswith("-bold"):
                    self._fallback_index.append(
                        (name, f"{name} {each.get('tags', '')}")
                    )
        except Exception as exc:  # noqa: BLE001
            print(f"[icon-finder] fallback index load failed: {exc}")

    async def _ensure_initialized(self):
        if self._collection is not None:
            return
        async with self._init_lock:
            if self._collection is not None:
                return
            try:
                import chromadb  # noqa: WPS433
                from chromadb.config import Settings
                from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

                self._client = chromadb.PersistentClient(
                    path="chroma", settings=Settings(anonymized_telemetry=False)
                )
                self._embedding_function = ONNXMiniLM_L6_V2()
                self._embedding_function.DOWNLOAD_PATH = "chroma/models"
                self._embedding_function._download_model_if_not_exists()

                try:
                    self._collection = self._client.get_collection(
                        self.collection_name,
                        embedding_function=self._embedding_function,
                    )
                except Exception:
                    documents = []
                    ids = []
                    for name, doc in self._fallback_index:
                        documents.append(doc)
                        ids.append(name)
                    if documents:
                        self._collection = self._client.create_collection(
                            name=self.collection_name,
                            embedding_function=self._embedding_function,
                            metadata={"hnsw:space": "cosine"},
                        )
                        self._collection.add(documents=documents, ids=ids)
            except Exception as exc:  # noqa: BLE001
                # Can't initialize — fall back to keyword search below.
                print(f"[icon-finder] semantic init failed, using fallback: {exc}")
                self._collection = None

    async def search_icons(self, query: str, k: int = 1):
        await self._ensure_initialized()

        if self._collection is not None:
            try:
                result = await asyncio.to_thread(
                    self._collection.query,
                    query_texts=[query],
                    n_results=k,
                )
                if result and result.get("ids") and result["ids"][0]:
                    return [f"/static/icons/bold/{each}.svg" for each in result["ids"][0]]
            except Exception as exc:  # noqa: BLE001
                print(f"[icon-finder] semantic query failed: {exc}")

        # Keyword fallback: lowercase substring match
        q = (query or "").lower().strip()
        scored = []
        for name, doc in self._fallback_index:
            score = 0
            if q and q in doc.lower():
                score = 1
                if q in name.lower():
                    score = 2
            if score:
                scored.append((score, name))
        scored.sort(reverse=True)
        top = [name for _, name in scored[:k]] or [self._fallback_index[0][0]] if self._fallback_index else []
        return [f"/static/icons/bold/{name}.svg" for name in top[:k]]


ICON_FINDER_SERVICE = IconFinderService()
