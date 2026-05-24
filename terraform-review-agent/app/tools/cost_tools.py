import asyncio
import json
import os
import tempfile
from typing import Optional
from app.models.config import get_settings
from app.models.schemas import CostEstimate
from app.utils.logger import get_logger

logger = get_logger(__name__)

_RESOURCE_COST_MAP: dict[str, float] = {
    # ── GCP ──────────────────────────────────────────────────────────────────
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
    "google_project_iam_binding": 0.00,
    "google_service_account": 0.00,
    "google_service_account_key": 0.00,
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
    # ── AWS ──────────────────────────────────────────────────────────────────
    "aws_instance": 30.00,
    "aws_db_instance": 50.00,
    "aws_rds_cluster": 100.00,
    "aws_elasticache_cluster": 25.00,
    "aws_elasticache_replication_group": 50.00,
    "aws_eks_cluster": 73.00,
    "aws_eks_node_group": 50.00,
    "aws_nat_gateway": 32.40,
    "aws_lb": 18.00,
    "aws_alb": 18.00,
    "aws_elb": 18.00,
    "aws_eip": 3.60,
    "aws_ebs_volume": 10.00,
    "aws_s3_bucket": 2.60,
    "aws_cloudfront_distribution": 10.00,
    "aws_lambda_function": 0.00,
    "aws_sqs_queue": 0.00,
    "aws_sns_topic": 0.00,
    "aws_dynamodb_table": 5.00,
    "aws_kms_key": 1.00,
    "aws_secretsmanager_secret": 0.40,
    "aws_route53_zone": 0.50,
    "aws_route53_record": 0.00,
    "aws_vpc": 0.00,
    "aws_subnet": 0.00,
    "aws_security_group": 0.00,
    "aws_security_group_rule": 0.00,
    "aws_iam_role": 0.00,
    "aws_iam_policy": 0.00,
    "aws_iam_role_policy_attachment": 0.00,
    "aws_iam_user": 0.00,
    "aws_iam_access_key": 0.00,
    "aws_cloudwatch_log_group": 0.50,
    "aws_cloudwatch_metric_alarm": 0.10,
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
            return "No direct cost (usage-based charges may still apply)."
        calculator = "AWS Pricing Calculator" if resource_type.startswith("aws_") else "GCP Pricing Calculator"
        return f"~${cost:.2f}/month — static approximation, verify with {calculator} for your region/SKU."

    async def run_infracost(self, work_dir: str) -> list[CostEstimate]:
        """Try to run infracost CLI and return real cost estimates.

        Returns an empty list if infracost is not installed or fails.
        The caller falls back to the static map in that case.
        """
        settings = get_settings()
        binary = settings.infracost_binary
        api_key = settings.infracost_api_key

        env = {**os.environ}
        if api_key:
            env["INFRACOST_API_KEY"] = api_key

        output_file: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
                output_file = f.name

            proc = await asyncio.create_subprocess_exec(
                binary,
                "breakdown",
                "--path", work_dir,
                "--format", "json",
                "--out-file", output_file,
                "--no-color",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            _, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=120.0)

            if proc.returncode != 0:
                stderr = stderr_bytes.decode("utf-8", errors="replace")
                logger.debug("infracost_failed", returncode=proc.returncode, stderr=stderr[:300])
                return []

            with open(output_file) as f:
                data = json.load(f)

            return self._parse_infracost_output(data)

        except FileNotFoundError:
            logger.debug("infracost_not_installed", binary=binary)
            return []
        except asyncio.TimeoutError:
            logger.warning("infracost_timeout")
            return []
        except Exception as e:
            logger.warning("infracost_error", error=str(e))
            return []
        finally:
            if output_file:
                try:
                    os.unlink(output_file)
                except OSError:
                    pass

    def _parse_infracost_output(self, data: dict) -> list[CostEstimate]:
        estimates: list[CostEstimate] = []
        try:
            for project in data.get("projects", []):
                for resource in project.get("breakdown", {}).get("resources", []):
                    name = resource.get("name", "unknown")
                    res_type = name.split(".")[0] if "." in name else name
                    monthly = resource.get("monthlyCost")
                    if monthly is None:
                        monthly = 0.0
                    estimates.append(
                        CostEstimate(
                            resource=name,
                            resource_type=res_type,
                            estimated_monthly_cost=float(monthly),
                            details=f"${float(monthly):.2f}/month — from Infracost (live pricing)",
                            is_estimate=False,
                        )
                    )
        except Exception as e:
            logger.warning("infracost_parse_failed", error=str(e))
        return estimates
