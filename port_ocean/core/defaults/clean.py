import asyncio
from typing import Type

import httpx
from loguru import logger

from port_ocean.context.ocean import ocean
from port_ocean.core.handlers.port_app_config.models import PortAppConfig


from port_ocean.core.defaults.common import (
    get_port_integration_defaults,
    is_integration_exists,
)


def clean_defaults(
    config_class: Type[PortAppConfig],
    force: bool,
    wait: bool,
) -> None:
    try:
        asyncio.new_event_loop().run_until_complete(
            _clean_defaults(config_class, force, wait)
        )

    except Exception as e:
        logger.error(f"Failed to clear defaults, skipping... Error: {e}")


async def _clean_defaults(
    config_class: Type[PortAppConfig], force: bool, wait: bool
) -> None:
    port_client = ocean.port_client
    is_exists = await is_integration_exists(port_client)
    if not is_exists:
        return None
    defaults = get_port_integration_defaults(config_class)
    if not defaults:
        return None

    try:
        migration_ids = await asyncio.gather(
            *(
                port_client.delete_blueprint(
                    blueprint["identifier"], should_raise=True, delete_entities=force
                )
                for blueprint in defaults.blueprints
            )
        )

        if not force:
            logger.info(
                "Finished deleting blueprints and configurations! ⚓️",
            )
            return None

        migration_ids = [migration_id for migration_id in migration_ids if migration_id]

        if migration_ids and len(migration_ids) > 0 and not wait:
            logger.info(
                f"Migration started. To check the status of the migration, track these ids using /migrations/:id route {migration_ids}",
            )
        elif migration_ids and len(migration_ids) > 0 and wait:
            await asyncio.gather(
                *(
                    ocean.port_client.wait_for_migration_to_complete(migration_id)
                    for migration_id in migration_ids
                )
            )
    except httpx.HTTPStatusError as e:
        logger.error(f"Failed to delete blueprints: {e.response.text}.")
        raise e
