from __future__ import annotations

import argparse
import logging
import time

from ryan.autonomy import run_autonomy_cycle
from ryan.autonomy.wordpress import WordPressDraftPublisher
from ryan.config import Settings, get_settings
from ryan.db import SessionLocal
from ryan.payments.router import _payment_provider_from_settings
from ryan.seed import seed_mvp_data

logger = logging.getLogger("ryan.autonomy")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Ryan's autonomous business loop.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one autonomy cycle and exit.",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Seed configured MVP data before running the cycle.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    if not settings.autonomy_enabled and not args.once:
        logger.info("Ryan autonomy is disabled; set RYAN_AUTONOMY_ENABLED=true to run continuously")
        return

    while True:
        _run_once(settings=settings, seed=args.seed)
        if args.once:
            return
        time.sleep(settings.autonomy_cycle_seconds)


def _run_once(*, settings: Settings, seed: bool) -> None:
    with SessionLocal() as session:
        if seed:
            seed_mvp_data(session, settings)
            session.commit()

        result = run_autonomy_cycle(
            session,
            settings=settings,
            checkout_provider=_payment_provider_from_settings(settings),
            wordpress_publisher=_wordpress_publisher_from_settings(settings),
        )
        session.commit()
        logger.info(
            "autonomy cycle selected_offer=%s mrr=%s second_offer_unlocked=%s blockers=%s",
            result.selected_offer_id,
            result.mrr,
            result.second_offer_unlocked,
            list(result.blockers),
        )


def _wordpress_publisher_from_settings(settings: Settings):
    if not settings.wordpress_drafts_enabled:
        return None
    if settings.wordpress_username is None or settings.wordpress_password is None:
        return None
    return WordPressDraftPublisher(
        site_url=settings.wordpress_site_url,
        username=settings.wordpress_username,
        password=settings.wordpress_password,
    )


if __name__ == "__main__":
    main()
