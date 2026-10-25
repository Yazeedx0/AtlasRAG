from uuid import UUID

import pytest

from atlasrag.contracts.types.embedding import VectorDistanceMetric
from atlasrag.modules.embedding._vector_index import (
    create_vector_index_sql,
    vector_index_name,
)

MODEL_ID = UUID("11111111-1111-1111-1111-111111111111")


@pytest.mark.parametrize(
    ("metric", "operator_class"),
    [
        (VectorDistanceMetric.COSINE, "vector_cosine_ops"),
        (VectorDistanceMetric.INNER_PRODUCT, "vector_ip_ops"),
        (VectorDistanceMetric.EUCLIDEAN, "vector_l2_ops"),
    ],
)
def test_index_uses_operator_class_for_metric(
    metric: VectorDistanceMetric, operator_class: str
) -> None:
    statement = create_vector_index_sql(model_id=MODEL_ID, dimension=1536, distance_metric=metric)

    assert statement is not None
    assert f"(embedding::vector(1536)) {operator_class}" in statement
    assert f"WHERE embedding_model_id = '{MODEL_ID}'" in statement
    assert vector_index_name(model_id=MODEL_ID) in statement


def test_index_switches_to_halfvec_above_vector_limit() -> None:
    statement = create_vector_index_sql(
        model_id=MODEL_ID, dimension=3072, distance_metric=VectorDistanceMetric.COSINE
    )

    assert statement is not None
    assert "(embedding::halfvec(3072)) halfvec_cosine_ops" in statement


def test_index_is_skipped_above_halfvec_limit() -> None:
    statement = create_vector_index_sql(
        model_id=MODEL_ID, dimension=4001, distance_metric=VectorDistanceMetric.COSINE
    )

    assert statement is None


def test_index_name_fits_postgres_identifier_limit() -> None:
    assert len(vector_index_name(model_id=MODEL_ID)) <= 63
