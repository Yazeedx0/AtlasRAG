from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from anthropic import omit

from atlasrag.contracts.types.ai_types import EmbeddingInputType, GeneratedText, RankedDocument
from atlasrag.platform.ai.embeddings.providers import (
    CohereEmbedder,
    GeminiEmbedder,
    OpenAIEmbedder,
)
from atlasrag.platform.ai.generation.providers import (
    AnthropicTextGenerator,
    GeminiTextGenerator,
    OpenAITextGenerator,
)
from atlasrag.platform.ai.reranking.providers import CohereReranker

pytestmark = pytest.mark.unit


async def test_openai_generator_calls_the_sdk_and_returns_the_contract_type():
    create = AsyncMock(return_value=SimpleNamespace(output_text="hello"))
    client = SimpleNamespace(responses=SimpleNamespace(create=create))

    result = await OpenAITextGenerator(client=client, model="gpt-4o").generate(
        prompt="hi",
        system="be brief",
        max_output_tokens=128,
    )

    assert result == GeneratedText(text="hello", model="gpt-4o")
    assert create.await_args.kwargs["model"] == "gpt-4o"
    assert create.await_args.kwargs["input"] == "hi"
    assert create.await_args.kwargs["instructions"] == "be brief"
    assert create.await_args.kwargs["max_output_tokens"] == 128


async def test_anthropic_generator_joins_text_blocks():
    content = [
        SimpleNamespace(type="text", text="part-1 "),
        SimpleNamespace(type="thinking", text="ignored"),
        SimpleNamespace(type="text", text="part-2"),
    ]
    create = AsyncMock(return_value=SimpleNamespace(content=content))
    client = SimpleNamespace(messages=SimpleNamespace(create=create))

    result = await AnthropicTextGenerator(client=client, model="claude-opus-5").generate(
        prompt="hi",
        system="be brief",
        max_output_tokens=64,
    )

    assert result == GeneratedText(text="part-1 part-2", model="claude-opus-5")
    assert create.await_args.kwargs["max_tokens"] == 64
    assert create.await_args.kwargs["system"] == "be brief"


async def test_anthropic_generator_omits_system_when_not_given():
    create = AsyncMock(return_value=SimpleNamespace(content=[]))
    client = SimpleNamespace(messages=SimpleNamespace(create=create))

    await AnthropicTextGenerator(client=client, model="m").generate(
        prompt="hi",
        max_output_tokens=8,
    )

    assert create.await_args.kwargs["system"] is omit


async def test_gemini_generator_passes_config():
    generate_content = AsyncMock(return_value=SimpleNamespace(text="answer"))
    models = SimpleNamespace(generate_content=generate_content)
    client = SimpleNamespace(aio=SimpleNamespace(models=models))

    result = await GeminiTextGenerator(client=client, model="gemini-2.0-flash").generate(
        prompt="hi",
        system="be brief",
        max_output_tokens=32,
    )

    config = generate_content.await_args.kwargs["config"]

    assert result.text == "answer"
    assert config.system_instruction == "be brief"
    assert config.max_output_tokens == 32


async def test_openai_embedder_returns_plain_vectors():
    data = [SimpleNamespace(embedding=[0.1, 0.2]), SimpleNamespace(embedding=[0.3, 0.4])]
    create = AsyncMock(return_value=SimpleNamespace(data=data))
    client = SimpleNamespace(embeddings=SimpleNamespace(create=create))

    vectors = await OpenAIEmbedder(client=client, model="text-embedding-3-small").embed(
        texts=["a", "b"],
    )

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert create.await_args.kwargs["input"] == ["a", "b"]


@pytest.mark.parametrize(
    ("input_type", "expected"),
    [
        (EmbeddingInputType.DOCUMENT, "search_document"),
        (EmbeddingInputType.QUERY, "search_query"),
    ],
)
async def test_cohere_embedder_maps_input_type(input_type, expected):
    response = SimpleNamespace(embeddings=SimpleNamespace(float_=[[0.5, 0.6]]))
    embed = AsyncMock(return_value=response)
    client = SimpleNamespace(embed=embed)

    vectors = await CohereEmbedder(client=client, model="embed-v4.0").embed(
        texts=["a"],
        input_type=input_type,
    )

    assert vectors == [[0.5, 0.6]]
    assert embed.await_args.kwargs["input_type"] == expected


async def test_gemini_embedder_maps_task_type():
    response = SimpleNamespace(embeddings=[SimpleNamespace(values=[0.7, 0.8])])
    embed_content = AsyncMock(return_value=response)
    models = SimpleNamespace(embed_content=embed_content)
    client = SimpleNamespace(aio=SimpleNamespace(models=models))

    vectors = await GeminiEmbedder(client=client, model="text-embedding-004").embed(
        texts=["a"],
        input_type=EmbeddingInputType.QUERY,
    )

    assert vectors == [[0.7, 0.8]]
    assert embed_content.await_args.kwargs["config"].task_type == "RETRIEVAL_QUERY"


async def test_cohere_reranker_returns_ranked_documents():
    results = [
        SimpleNamespace(index=2, relevance_score=0.9),
        SimpleNamespace(index=0, relevance_score=0.4),
    ]
    rerank = AsyncMock(return_value=SimpleNamespace(results=results))
    client = SimpleNamespace(rerank=rerank)

    ranked = await CohereReranker(client=client, model="rerank-v3.5").rerank(
        query="q",
        documents=["a", "b", "c"],
        top_n=2,
    )

    assert ranked == [
        RankedDocument(index=2, relevance_score=0.9),
        RankedDocument(index=0, relevance_score=0.4),
    ]
    assert rerank.await_args.kwargs["top_n"] == 2
