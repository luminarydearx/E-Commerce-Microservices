"""Real Elasticsearch client with proper async, mapping, and bulk indexing."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk

from app.core.config import settings

logger = logging.getLogger("search_service.es_client")


class ElasticsearchClient:
    """Async Elasticsearch client with connection pooling and health checks."""

    def __init__(self) -> None:
        self._client: AsyncElasticsearch | None = None
        self._lock = asyncio.Lock()
        self._index_created = False

    async def get_client(self) -> AsyncElasticsearch:
        async with self._lock:
            if self._client is None:
                self._client = AsyncElasticsearch(
                    hosts=[settings.ELASTICSEARCH_URL],
                    request_timeout=10,
                    max_retries=3,
                    retry_on_timeout=True,
                    retry_on_status=[502, 503, 504],
                    verify_certs=settings.ENVIRONMENT == "production",
                    ssl_show_warn=settings.ENVIRONMENT != "production",
                    # For production with auth:
                    # basic_auth=(settings.ES_USERNAME, settings.ES_PASSWORD) if settings.ES_USERNAME else None,
                )
                # Verify connection
                try:
                    info = await self._client.info()
                    logger.info(
                        "Elasticsearch connected",
                        extra={"version": info.get("version", {}).get("number", "unknown")},
                    )
                except Exception as e:
                    logger.warning(f"Elasticsearch connection failed: {e}")
            return self._client

    async def ensure_index(self) -> None:
        """Create product index with proper mapping if not exists."""
        if self._index_created:
            return
        client = await self.get_client()
        index_name = settings.SEARCH_INDEX

        try:
            exists = await client.indices.exists(index=index_name)
            if exists:
                self._index_created = True
                return

            mapping = {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": settings.ES_REPLICAS,
                    "refresh_interval": "1s",
                    "analysis": {
                        "analyzer": {
                            "indonesian": {
                                "type": "custom",
                                "tokenizer": "standard",
                                "filter": [
                                    "lowercase",
                                    "indonesian_stop",
                                    "indonesian_keywords",
                                    "indonesian_stemmer",
                                ],
                            },
                            "edge_ngram_analyzer": {
                                "type": "custom",
                                "tokenizer": "standard",
                                "filter": ["lowercase", "edge_ngram"],
                            },
                        },
                        "filter": {
                            "indonesian_stop": {"type": "stop", "stopwords": "_indonesian_"},
                            "indonesian_keywords": {"type": "keyword_marker", "keywords": ["contoh"]},
                            "indonesian_stemmer": {"type": "stemmer", "language": "indonesian"},
                            "edge_ngram": {
                                "type": "edge_ngram",
                                "min_gram": 2,
                                "max_gram": 15,
                            },
                        },
                    },
                },
                "mappings": {
                    "properties": {
                        "id": {"type": "keyword"},
                        "name": {
                            "type": "text",
                            "analyzer": "indonesian",
                            "fields": {
                                "suggest": {"type": "completion"},
                                "keyword": {"type": "keyword", "ignore_above": 256},
                                "edge_ngram": {"type": "text", "analyzer": "edge_ngram_analyzer"},
                            },
                        },
                        "description": {"type": "text", "analyzer": "indonesian"},
                        "sku": {"type": "keyword"},
                        "slug": {"type": "keyword"},
                        "category_id": {"type": "keyword"},
                        "category_name": {"type": "keyword"},
                        "seller_id": {"type": "keyword"},
                        "seller_name": {"type": "text"},
                        "price": {"type": "long"},
                        "currency": {"type": "keyword"},
                        "stock": {"type": "integer"},
                        "available_stock": {"type": "integer"},
                        "weight_grams": {"type": "integer"},
                        "image_urls": {"type": "keyword"},
                        "status": {"type": "keyword"},
                        "is_active": {"type": "boolean"},
                        "rating_avg": {"type": "float"},
                        "rating_count": {"type": "integer"},
                        "sales_count": {"type": "integer"},
                        "created_at": {"type": "date"},
                        "updated_at": {"type": "date"},
                    }
                },
            }

            await client.indices.create(index=index_name, body=mapping)
            logger.info(f"ES index '{index_name}' created with Indonesian analyzer")
            self._index_created = True
        except Exception as e:
            logger.error(f"Failed to create index: {e}")

    async def index_product(self, product: dict) -> bool:
        """Index or update a single product."""
        client = await self.get_client()
        try:
            await client.index(
                index=settings.SEARCH_INDEX,
                id=product["id"],
                document=product,
                refresh="false",  # batch refresh for performance
            )
            return True
        except Exception as e:
            logger.error(f"Index product {product.get('id')} failed: {e}")
            return False

    async def bulk_index(self, products: list[dict]) -> int:
        """Bulk index multiple products. Returns number indexed."""
        if not products:
            return 0
        client = await self.get_client()
        actions = [
            {
                "_index": settings.SEARCH_INDEX,
                "_id": p["id"],
                "_source": p,
            }
            for p in products
        ]
        try:
            success, failed = await async_bulk(
                client, actions, raise_on_error=False, raise_on_exception=False
            )
            if failed:
                logger.warning(f"Bulk index: {len(failed)} failed, {success} succeeded")
            return success
        except Exception as e:
            logger.error(f"Bulk index failed: {e}")
            return 0

    async def delete_product(self, product_id: str) -> bool:
        """Remove product from index."""
        client = await self.get_client()
        try:
            await client.delete(index=settings.SEARCH_INDEX, id=product_id, ignore=[404])
            return True
        except Exception as e:
            logger.error(f"Delete product {product_id} failed: {e}")
            return False

    async def search(self, query: dict) -> dict:
        """Execute search query and return raw response."""
        client = await self.get_client()
        try:
            resp = await client.search(
                index=settings.SEARCH_INDEX,
                body=query,
                request_timeout=5,
            )
            return resp
        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise

    async def suggest(self, field: str, prefix: str, size: int = 10) -> list[dict]:
        """Completion suggester for autocomplete."""
        client = await self.get_client()
        query = {
            "suggest": {
                "product-suggest": {
                    "prefix": prefix,
                    "completion": {
                        "field": field,
                        "size": size,
                        "skip_duplicates": True,
                        "fuzzy": {"fuzziness": "AUTO"},
                    },
                }
            },
            "_source": ["id", "name", "price", "image_urls"],
        }
        try:
            resp = await client.search(index=settings.SEARCH_INDEX, body=query)
            options = (
                resp.get("suggest", {}).get("product-suggest", [{}])[0].get("options", [])
            )
            return [
                {
                    "text": opt["_source"]["name"],
                    "product_id": opt["_source"]["id"],
                    "price": opt["_source"].get("price"),
                    "image": opt["_source"].get("image_urls", [None])[0] if opt["_source"].get("image_urls") else None,
                    "score": opt["_score"],
                }
                for opt in options
            ]
        except Exception as e:
            logger.error(f"Suggest failed: {e}")
            return []

    async def count(self) -> int:
        """Get total documents in index."""
        client = await self.get_client()
        try:
            resp = await client.count(index=settings.SEARCH_INDEX)
            return resp.get("count", 0)
        except Exception:
            return 0

    async def close(self) -> None:
        if self._client:
            await self._client.close()


# Singleton
es_client = ElasticsearchClient()
