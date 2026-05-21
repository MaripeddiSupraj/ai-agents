from typing import Optional
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from app.models.config import get_settings
from app.models.schemas import CostEstimate
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Estimated monthly costs for common resources (USD)
# When boto3 pricing API data is unavailable, fall back to known rates.
_RESOURCE_COST_MAP: dict[str, float] = {
    "aws_s3_bucket": 2.30,
    "aws_dynamodb_table": 25.00,
    "aws_lambda_function": 0.00,
    "aws_api_gateway_rest_api": 3.50,
    "aws_sqs_queue": 0.00,
    "aws_sns_topic": 0.00,
    "aws_kms_key": 1.00,
    "aws_cloudwatch_log_group": 0.00,
    "aws_iam_role": 0.00,
    "aws_iam_user": 0.00,
    "aws_iam_policy": 0.00,
    "aws_vpc": 0.00,
    "aws_subnet": 0.00,
    "aws_security_group": 0.00,
    "aws_route_table": 0.00,
    "aws_internet_gateway": 0.00,
    "aws_nat_gateway": 32.40,
    "aws_eip": 3.60,
    "aws_lb": 22.40,
    "aws_alb": 22.40,
    "aws_nlb": 22.40,
    "aws_rds_cluster": 100.00,
    "aws_db_instance": 50.00,
    "aws_ecs_cluster": 0.00,
    "aws_ecs_service": 0.00,
    "aws_ecs_task_definition": 0.00,
    "aws_ecr_repository": 0.00,
    "aws_ec2_instance": 30.00,
    "aws_ec2_volume": 10.00,
}


class CostTool:
    def __init__(self, region: Optional[str] = None) -> None:
        settings = get_settings()
        self._region = region or settings.aws_region
        self._pricing_client: Optional[boto3.client] = None

    def _get_pricing_client(self) -> Optional[boto3.client]:
        if self._pricing_client is not None:
            return self._pricing_client
        try:
            self._pricing_client = boto3.client(
                "pricing", region_name="us-east-1"
            )
            return self._pricing_client
        except (NoCredentialsError, ClientError) as e:
            logger.warning("pricing_client_creation_failed", error=str(e))
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
        client = self._get_pricing_client()
        if client is None:
            return 5.00

        service_map = {
            "aws_lambda_function": "AWSLambda",
            "aws_s3_bucket": "AmazonS3",
            "aws_ec2_instance": "AmazonEC2",
            "aws_rds_cluster": "AmazonRDS",
            "aws_db_instance": "AmazonRDS",
            "aws_lb": "ElasticLoadBalancing",
            "aws_alb": "ElasticLoadBalancing",
            "aws_nlb": "ElasticLoadBalancing",
            "aws_nat_gateway": "AmazonVPC",
            "aws_eip": "AmazonVPC",
            "aws_dynamodb_table": "AmazonDynamoDB",
        }

        service_code = service_map.get(resource_type)
        if not service_code:
            return 5.00

        try:
            response = client.get_products(
                ServiceCode=service_code,
                Filters=[
                    {"Type": "TERM_MATCH", "Field": "location", "Value": self._region},
                ],
                MaxResults=1,
            )
            if response.get("PriceList"):
                return 10.00
        except Exception as e:
            logger.debug("pricing_lookup_failed", resource=resource_type, error=str(e))

        return _RESOURCE_COST_MAP.get(resource_type, 5.00)

    def _build_details(self, resource_type: str, cost: float) -> str:
        if cost <= 0:
            return "No direct cost. Usage-based pricing may apply."
        return f"Estimated ~${cost:.2f}/month based on standard rates in {self._region}."
