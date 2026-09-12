import asyncio
import uuid
from collections.abc import Callable, Coroutine
from datetime import timedelta
from typing import Protocol

RenewLease = Callable[..., Coroutine[object, object, bool]]


class LeaseLostFactory(Protocol):
    def __call__(self, message: str, /) -> BaseException:
        ...


class LeasedJobHeartbeat:
    def __init__(
        self,
        renew: RenewLease,
        *,
        interval: timedelta,
        lease_lost: LeaseLostFactory,
        job_id_keyword: str,
    ) -> None:
        if interval.total_seconds() <= 0:
            raise ValueError("Heartbeat interval must be positive")

        self._renew = renew
        self._interval = interval
        self._lease_lost = lease_lost
        self._job_id_keyword = job_id_keyword

    async def run(
        self,
        *,
        job_id: uuid.UUID,
        attempt_number: int,
        stop_event: asyncio.Event,
        lease_lost_event: asyncio.Event,
    ) -> None:
        while True:
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self._interval.total_seconds(),
                )
                return
            except TimeoutError:
                pass

            try:
                renewed = await self._renew(
                    **{self._job_id_keyword: job_id},
                    attempt_number=attempt_number,
                )
            except Exception as error:
                lease_lost_event.set()
                raise self._lease_lost("Unable to renew the job lease.") from error

            if not renewed:
                lease_lost_event.set()
                raise self._lease_lost("Job lease is no longer owned by this worker.")


__all__ = ["LeasedJobHeartbeat", "RenewLease"]
