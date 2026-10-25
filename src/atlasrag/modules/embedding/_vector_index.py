import uuid

from atlasrag.contracts.types.embedding import VectorDistanceMetric

VECTOR_INDEX_NAME_PREFIX = "ix_chunk_embeddings_hnsw_"
MAX_VECTOR_INDEX_DIMENSION = 2000
MAX_HALFVEC_INDEX_DIMENSION = 4000

_OPERATOR_CLASS_SUFFIX = {
    VectorDistanceMetric.COSINE: "cosine_ops",
    VectorDistanceMetric.INNER_PRODUCT: "ip_ops",
    VectorDistanceMetric.EUCLIDEAN: "l2_ops",
}


def vector_index_name(*, model_id: uuid.UUID) -> str:
    return f"{VECTOR_INDEX_NAME_PREFIX}{model_id.hex}"


def vector_index_type(*, dimension: int) -> str | None:
    if dimension <= MAX_VECTOR_INDEX_DIMENSION:
        return "vector"
    if dimension <= MAX_HALFVEC_INDEX_DIMENSION:
        return "halfvec"
    return None


def vector_index_expression(*, dimension: int) -> str | None:
    index_type = vector_index_type(dimension=dimension)
    if index_type is None:
        return None
    return f"(embedding::{index_type}({dimension}))"


def create_vector_index_sql(
    *,
    model_id: uuid.UUID,
    dimension: int,
    distance_metric: VectorDistanceMetric,
) -> str | None:
    index_type = vector_index_type(dimension=dimension)
    if index_type is None:
        return None
    operator_class = f"{index_type}_{_OPERATOR_CLASS_SUFFIX[distance_metric]}"
    return (
        f"CREATE INDEX IF NOT EXISTS {vector_index_name(model_id=model_id)} "
        f"ON knowledge.chunk_embeddings "
        f"USING hnsw ({vector_index_expression(dimension=dimension)} {operator_class}) "
        f"WHERE embedding_model_id = '{model_id}'"
    )


__all__ = [
    "MAX_HALFVEC_INDEX_DIMENSION",
    "MAX_VECTOR_INDEX_DIMENSION",
    "VECTOR_INDEX_NAME_PREFIX",
    "create_vector_index_sql",
    "vector_index_expression",
    "vector_index_name",
    "vector_index_type",
]
