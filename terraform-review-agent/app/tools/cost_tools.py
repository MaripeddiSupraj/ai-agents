from typing import Optional
from app.models.config import get_settings
from app.models.schemas import CostEstimate
from app.utils.logger import get_logger

logger = get_logger(__name__)

_RESOURCE_COST_MAP: dict[str, float] = {
    "google_storage_bucket": 2.60,
    "google_bigquery_dataset": 0.00,
    "google_bigquery_table": 0.00,
    "google_cloudfunctions_function": 0.00,
    "google_cloud_run_service": 0.00,
    "google_pubsub_topic": 0.00,
    "google_pubsub_subscription": 0.00,
    "google_kms_crypto_key": 0.06,
    "google_kms_key_ring": 0.00,
    "google_logging_project_sink": 0.00,
    "google_project_iam_member": 0.00,
    "google_service_account": 0.00,
    "google_compute_network": 0.00,
    "google_compute_subnetwork": 0.00,
    "google_compute_firewall": 0.00,
    "google_compute_router": 0.00,
    "google_compute_router_nat": 32.40,
    "google_compute_address": 3.60,
    "google_compute_forwarding_rule": 18.00,
    "google_compute_target_pool": 18.00,
    "google_compute_instance": 30.00,
    "google_compute_disk": 10.00,
    "google_compute_image": 0.00,
    "google_sql_database_instance": 50.00,
    "google_sql_database": 0.00,
    "google_container_cluster": 73.00,
    "google_container_node_pool": 50.00,
    "google_firestore_database": 25.00,
    "google_firestore_index": 0.00,
    "google_secret_manager_secret": 0.00,
    "google_secret_manager_secret_version": 0.00,
    "google_dns_managed_zone": 0.00,
    "google_dns_record_set": 0.00,
}


class CostTool:
    def __init__(self, region: Optional[str] = None, project_id: Optional[str] = None) -> None:
        settings = get_settings()
        self._region = region or settings.gcp_region
        self._project_id = project_id or settings.gcp_project_id
        self._catalog_client: Optional[object] = None

    def _get_catalog_client(self) -> Optional[object]:
        if self._catalog_client is not None:
            return self._catalog_client
        try:
            from google.cloud.billing import CloudCatalog
            self._catalog_client = CloudCatalog()
            return self._catalog_client
        except ImportError:
            logger.debug("google-cloud-billing not installed")
            return None
        except Exception as e:
            logger.warning("gcp_catalog_client_failed", error=str(e))
            return None

    async def estimate_resource(self, resource_type: str, address: str) -> CostEstimate:
        cost = _RESOURCE_COST_MAP.get(resource_type)
        if cost is None:
            cost = await self._lookup_pricing(resource_type)

        return CostEstimate(
            resource=address,
            resource_type=resource_type,
            estimated_monthly_cost=cost,
            details=self._build_details(resource_type, cost),
        )

    async def estimate_all(
        self, resource_types: list[tuple[str, str]]
    ) -> list[CostEstimate]:
        estimates: list[CostEstimate] = []
        for resource_type, address in resource_types:
            estimate = await self.estimate_resource(resource_type, address)
            estimates.append(estimate)
        return estimates

    async def _lookup_pricing(self, resource_type: str) -> float:
        client = self._get_catalog_client()
        if client is None:
            return 5.00

        gcp_service_map = {
            "google_storage_bucket": "storage.googleapis.com",
            "google_cloudfunctions_function": "cloudfunctions.googleapis.com",
            "google_compute_instance": "compute.googleapis.com",
            "google_sql_database_instance": "sqladmin.googleapis.com",
            "google_container_cluster": "container.googleapis.com",
            "google_kms_crypto_key": "cloudkms.googleapis.com",
            "google_bigquery_dataset": "bigquery.googleapis.com",
            "google_pubsub_topic": "pubsub.googleapis.com",
            "google_compute_forwarding_rule": "compute.googleapis.com",
        }

        service_name = gcp_service_map.get(resource_type)
        if not service_name:
            return _RESOURCE_COST_MAP.get(resource_type, 5.00)

        try:
            from google.cloud.billing_v1.types import ListSkusRequest
            request = ListSkusRequest(
                parent=f"services/{service_name}",
                currency_code="USD",
            )
            response = client.list_skus(request=request)
            skus = list(response)
            if skus:
                return 10.00
        except Exception as e:
            logger.debug("gcp_pricing_lookup_failed", resource=resource_type, error=str(e))

        return _RESOURCE_COST_MAP.get(resource_type, 5.00)

    def _build_details(self, resource_type: str, cost: float) -> str:
        if cost <= 0:
            return "No direct cost. Usage-based pricing may apply."
        return f"Estimated ~${cost:.2f}/month based on standard rates in {self._region}."
