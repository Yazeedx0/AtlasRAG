INGESTION_QUEUE = "atlasrag.ingestion"
EMBEDDING_QUEUE = "atlasrag.embedding"
MAINTENANCE_QUEUE = "atlasrag.maintenance"


PROCESS_INGESTION_TASK = "atlasrag.ingestion.process"
PROCESS_EMBEDDING_TASK = "atlasrag.embedding.process"
PUBLISH_OUTBOX_TASK = "atlasrag.maintenance.publish_outbox"


__all__ = [
    "EMBEDDING_QUEUE",
    "INGESTION_QUEUE",
    "MAINTENANCE_QUEUE",
    "PROCESS_EMBEDDING_TASK",
    "PROCESS_INGESTION_TASK",
    "PUBLISH_OUTBOX_TASK",
]