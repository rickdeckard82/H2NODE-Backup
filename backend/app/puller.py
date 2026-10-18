"""Coletor (container próprio, mesma imagem do backend): busca a configuração dos
equipamentos que não enviam sozinhos — hoje MikroTik por SSH (services/mikrotik.py).

Fica separado do worker de propósito: precisa de saída para a rede (alcançar os
equipamentos) e o worker, que guarda a chave PRIVADA, fica sem saída. Aqui só há a
chave pública (cifra o que coleta, nunca decifra).

Uso: python -m app.puller
"""

import signal
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.logging import configure_logging, logger
from app.services import mikrotik, storage

_stop = False


def _on_signal(signum, _frame) -> None:  # noqa: ANN001
    global _stop
    _stop = True
    logger.info("puller_stopping", signal=signum)


def run_once(db, pool: ThreadPoolExecutor) -> int:
    jobs = mikrotik.claim_due(db)
    if not jobs:
        return 0
    for j in jobs:
        storage.ensure_client_dirs(j.slug)
    futures = {pool.submit(mikrotik.fetch_export, j): j for j in jobs}
    # a sessão do banco fica só nesta thread; as threads só fazem rede
    for f in as_completed(futures):
        job = futures[f]
        exc = f.exception()
        try:
            mikrotik.record(db, job, exc if exc is not None else f.result())
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logger.error("mikrotik_record_error", device=job.slug, error=str(e))
    return len(jobs)


def main() -> None:
    configure_logging()
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    logger.info("puller_started", concurrency=settings.pull_concurrency)
    with ThreadPoolExecutor(max_workers=settings.pull_concurrency, thread_name_prefix="pull") as pool:
        while not _stop:
            try:
                with SessionLocal() as db:
                    n = run_once(db, pool)
                    if n:
                        logger.info("puller_cycle", devices=n)
            except Exception as exc:  # noqa: BLE001
                logger.error("puller_cycle_error", error=str(exc))
            for _ in range(settings.worker_poll_seconds):
                if _stop:
                    break
                time.sleep(1)
    logger.info("puller_stopped")


if __name__ == "__main__":
    main()
