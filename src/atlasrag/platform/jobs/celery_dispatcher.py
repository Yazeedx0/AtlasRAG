from celery import Celery


class CeleryTaskDispatcher:
    def __init__(self, celery_app: Celery) -> None:
        self._celery_app = celery_app

    def publish(self, *, task_name: str, payload: dict[str, object]) -> None:
        self._celery_app.send_task(task_name, kwargs=payload)
