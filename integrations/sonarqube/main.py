from typing import Any

from loguru import logger

from client import SonarQubeClient
from port_ocean.context.ocean import ocean
from port_ocean.core.ocean_types import ASYNC_GENERATOR_RESYNC_TYPE


class ObjectKind:
    PROJECTS = "projects"
    ISSUES = "issues"
    ANALYSIS = "analysis"


def init_sonar_client() -> SonarQubeClient:
    return SonarQubeClient(
        ocean.integration_config.get("sonar_url", "https://sonarcloud.io"),
        ocean.integration_config["sonar_api_token"],
        ocean.integration_config.get("sonar_organization_id"),
        ocean.integration_config.get("app_host"),
        ocean.integration_config["sonar_is_on_premise"],
    )


@ocean.on_resync(ObjectKind.PROJECTS)
async def on_project_resync(kind: str) -> list[dict[str, Any]]:
    logger.info(f"Listing Sonarqube resource: {kind}")
    sonar_client = init_sonar_client()
    return await sonar_client.get_all_projects()


@ocean.on_resync(ObjectKind.ISSUES)
async def on_issues_resync(kind: str) -> ASYNC_GENERATOR_RESYNC_TYPE:
    logger.info(f"Listing Sonarqube resource: {kind}")

    sonar_client = init_sonar_client()
    async for issues_list in sonar_client.get_all_issues():
        yield issues_list


@ocean.on_resync(ObjectKind.ANALYSIS)
async def on_analysis_resync(kind: str) -> ASYNC_GENERATOR_RESYNC_TYPE:
    logger.info(f"Listing Sonarqube resource: {kind}")

    sonar_client = init_sonar_client()
    if ocean.integration_config["sonar_is_on_premise"]:
        async for analyses_list in sonar_client.get_all_sonarqube_analyses():
            yield analyses_list
    else:
        async for analyses_list in sonar_client.get_all_sonarcloud_analyses():
            yield analyses_list


@ocean.router.post("/webhook")
async def handle_sonarqube_webhook(webhook_data: dict[str, Any]) -> None:
    logger.info(
        f"Processing Sonarqube webhook for event type: {webhook_data.get('project', {}).get('key')}"
    )
    sonar_client = init_sonar_client()

    project = await sonar_client.get_single_component(
        webhook_data.get("project", {})
    )  ## making sure we're getting the right project details
    project_data = await sonar_client.get_single_project(project)
    issues_data = await sonar_client.get_issues_by_component(project)
    await ocean.register_raw(ObjectKind.PROJECTS, [project_data])
    await ocean.register_raw(ObjectKind.ISSUES, issues_data)

    if ocean.integration_config["sonar_is_on_premise"]:
        onprem_analysis_data = await sonar_client.get_measures_for_all_pull_requests(
            project_key=project["key"]
        )
        await ocean.register_raw(ObjectKind.ANALYSIS, onprem_analysis_data)
    else:
        cloud_analysis_data = await sonar_client.get_analysis_for_task(
            webhook_data=webhook_data
        )
        await ocean.register_raw(ObjectKind.ANALYSIS, [cloud_analysis_data])

    logger.info("Webhook event processed")


@ocean.on_start()
async def on_start() -> None:
    if not ocean.integration_config.get("sonar_organization_id"):
        if not ocean.integration_config["sonar_is_on_premise"]:
            raise ValueError(
                "Organization ID is required for SonarCloud. Please specify a valid sonarOrganizationId"
            )
        logger.warning("Organization key is missing for an on-premise Sonarqube setup")

    sonar_client = init_sonar_client()
    sonar_client.sanity_check()

    if ocean.event_listener_type == "ONCE":
        logger.info("Skipping webhook creation because the event listener is ONCE")
        return

    # We are making the real-time subscription of Sonar webhook events optional. That said,
    # we only subscribe to webhook events when the user supplies the app_host config variable
    if ocean.integration_config.get("app_host"):
        await sonar_client.get_or_create_webhook_url()
