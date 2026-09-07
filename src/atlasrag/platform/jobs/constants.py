INGESTION_QUEUE = "atlasrag.ingestion"
EMBEDDING_QUEUE = "atlasrag.embedding"
MAINTENANCE_QUEUE = "atlasrag.maintenance"


PROCESS_INGESTION_TASK = "atlasrag.ingestion.process"
PROCESS_EMBEDDING_TASK = "atlasrag.embedding.process"
PUBLISH_OUTBOX_TASK = "atlasrag.maintenance.publish_outbox"
RECOVER_INGESTION_LEASES_TASK = "atlasrag.maintenance.recover_ingestion_leases"


PUBLISH_OUTBOX_SCHEDULE = "publish-outbox"
RECOVER_INGESTION_LEASES_SCHEDULE = "recover-ingestion-leases"


__all__ = [
    "EMBEDDING_QUEUE",
    "INGESTION_QUEUE",
    "MAINTENANCE_QUEUE",
    "PROCESS_EMBEDDING_TASK",
    "PROCESS_INGESTION_TASK",
    "PUBLISH_OUTBOX_SCHEDULE",
    "PUBLISH_OUTBOX_TASK",
    "RECOVER_INGESTION_LEASES_SCHEDULE",
    "RECOVER_INGESTION_LEASES_TASK",
]
