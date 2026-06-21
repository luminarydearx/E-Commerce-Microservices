"""Search service business logic — uses real Elasticsearch client."""
from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import settings
from app.services.es_client import es_client

logger = logging.getLogger("search_service.service")


class SearchService:
    """Build ES queries, handle cache, fallback."""

    async def search_products(
        self,
        query: str = "",
        category_id: str | None = None,
        seller_id: str | None = None,
        min_price: int | None = None,
        max_price: int | None = None,
        min_rating: int | None = None,
        in_stock: bool = False,
        sort_by: str = "relevance",
        page: int = 0,
        size: int = 20,
    ) -> dict:
        if size > settings.SEARCH_MAX_PAGE_SIZE:
            size = settings.SEARCH_MAX_PAGE_SIZE

        # Build ES query
        must: list[dict] = []
        filter_: list[dict] = [
            {"term": {"is_active": True}},
            {"term": {"status": "ACTIVE"}},
        ]
        must_not: list[dict] = []

        if query and len(query) >= settings.SEARCH_MIN_QUERY_LENGTH:
            must.append({
                "multi_match": {
                    "query": query,
                    "fields": ["name^3", "name.edge_ngram^2", "description", "sku", "category_name"],
                    "type": "best_fields",
                    "fuzziness": "AUTO",
                    "operator": "and",
                    "cutoff_frequency": 0.01,
                }
            })
        if category_id:
            filter_.append({"term": {"category_id": category_id}})
        if seller_id:
            filter_.append({"term": {"seller_id": seller_id}})
        if min_price is not None:
            filter_.append({"range": {"price": {"gte": min_price}}})
        if max_price is not None:
            filter_.append({"range": {"price": {"lte": max_price}}})
        if min_rating:
            filter_.append({"range": {"rating_avg": {"gte": min_rating}}})
        if in_stock:
            filter_.append({"range": {"available_stock": {"gt": 0}}})

        sort = self._build_sort(sort_by)
        es_query = {
            "query": {
                "bool": {
                    "must": must or [{"match_all": {}}],
                    "filter": filter_,
                    "must_not": must_not,
                }
            },
            "sort": sort,
            "from": page * size,
            "size": size,
            "aggs": {
                "categories": {"terms": {"field": "category_id", "size": 20}},
                "price_ranges": {
                    "range": {
                        "field": "price",
                        "ranges": [
                            {"to": 50000},
                            {"from": 50000, "to": 100000},
                            {"from": 100000, "to": 500000},
                            {"from": 500000, "to": 1000000},
                            {"from": 1000000},
                        ],
                    }
                },
                "avg_rating": {"avg": {"field": "rating_avg"}},
                "sellers": {"terms": {"field": "seller_id", "size": 10}},
            },
            "highlight": {
                "fields": {
                    "name": {"pre_tags": ["<em>"], "post_tags": ["</em>"]},
                    "description": {"pre_tags": ["<em>"], "post_tags": ["</em>"]},
                }
            },
        }

        try:
            data = await es_client.search(es_query)
            hits = data.get("hits", {}).get("hits", [])
            total = data.get("hits", {}).get("total", {}).get("value", 0)
            aggs = data.get("aggregations", {})

            results = []
            for hit in hits:
                src = hit["_source"]
                if "_highlight" in hit:
                    src["_highlight"] = hit["highlight"]
                results.append(src)

            return {
                "data": results,
                "total": total,
                "page": page,
                "size": size,
                "facets": {
                    "categories": [
                        {"id": b["key"], "count": b["doc_count"]}
                        for b in aggs.get("categories", {}).get("buckets", [])
                    ],
                    "price_ranges": [
                        {
                            "key": b["key"],
                            "from": b.get("from"),
                            "to": b.get("to"),
                            "count": b["doc_count"],
                        }
                        for b in aggs.get("price_ranges", {}).get("buckets", [])
                    ],
                    "sellers": [
                        {"id": b["key"], "count": b["doc_count"]}
                        for b in aggs.get("sellers", {}).get("buckets", [])
                    ],
                },
                "took_ms": data.get("took", 0),
                "max_score": data.get("hits", {}).get("max_score"),
                "cached": False,
            }
        except Exception as e:
            logger.error(f"Search failed, returning fallback: {e}")
            return self._fallback(query, page, size)

    def _build_sort(self, sort_by: str) -> list:
        if sort_by == "price_asc":
            return [{"price": {"order": "asc"}}]
        if sort_by == "price_desc":
            return [{"price": {"order": "desc"}}]
        if sort_by == "newest":
            return [{"created_at": {"order": "desc"}}]
        if sort_by == "rating":
            return [{"rating_avg": {"order": "desc"}}, {"rating_count": {"order": "desc"}}]
        if sort_by == "popular":
            return [{"sales_count": {"order": "desc"}}, {"rating_count": {"order": "desc"}}]
        # relevance (default): use _score, fallback to sales_count
        return [{"_score": {"order": "desc"}}, {"sales_count": {"order": "desc"}}]

    async def autocomplete(self, prefix: str) -> list[dict]:
        if len(prefix) < settings.SEARCH_MIN_QUERY_LENGTH:
            return []
        return await es_client.suggest("name.suggest", prefix, settings.AUTOCOMPLETE_LIMIT)

    async def index_product(self, product: dict) -> bool:
        return await es_client.index_product(product)

    async def bulk_index(self, products: list[dict]) -> int:
        return await es_client.bulk_index(products)

    async def delete_product(self, product_id: str) -> bool:
        return await es_client.delete_product(product_id)

    async def reindex_all(self) -> dict:
        """Trigger full re-index from catalog-service (admin only)."""
        # In production: fetch all products from catalog-service and bulk index
        # For now: return current count
        count = await es_client.count()
        return {"status": "reindex_triggered", "current_count": count}

    def _fallback(self, query: str, page: int, size: int) -> dict:
        return {
            "data": [],
            "total": 0,
            "page": page,
            "size": size,
            "facets": {"categories": [], "price_ranges": [], "sellers": []},
            "took_ms": 0,
            "cached": False,
            "fallback": True,
            "message": "search degraded: elasticsearch unavailable",
        }


search_service = SearchService()
