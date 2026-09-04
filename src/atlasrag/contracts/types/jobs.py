from enum import StrEnum


class JobType(StrEnum):
    PROCESS_INGESTION_ITEM = "ingestion.process_item"


__all__ = ["JobType"]
