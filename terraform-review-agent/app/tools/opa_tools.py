import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from app.models.config import get_settings
from app.models.schemas import OpaViolation
from app.utils.logger import get_logger
from app.utils.retry import async_retry

logger = get_logger(__name__)


class OpaTool:
    def __init__(self, policy_dir: Optional[str] = None) -> None:
        settings = get_settings()
        self._binary = settings.opa_binary
        self._policy_dir = policy_dir or settings.opa_policy_dir

    @async_retry(max_retries=2, delay=0.5)
    async def evaluate(
        self, input_data: dict, policy_name: str
    ) -> list[OpaViolation]:
        logger.info(
            "opa_evaluation_starting",
            policy=policy_name,
            policy_dir=self._policy_dir,
        )

        result = await self._run_eval(policy_name, input_data)
        violations = self._parse_result(result)

        logger.info(
            "opa_evaluation_completed",
            policy=policy_name,
            violations_count=len(violations),
        )
        return violations

    async def evaluate_all(
        self, input_data: dict, policy_files: Optional[list[str]] = None
    ) -> list[OpaViolation]:
        if policy_files is None:
            policy_dir = Path(self._policy_dir)
            policy_files = sorted(
                [f.name for f in policy_dir.glob("*.rego") if f.is_file()]
            )

        all_violations: list[OpaViolation] = []
        for policy_file in policy_files:
            violations = await self.evaluate(input_data, policy_file)
            all_violations.extend(violations)

        return all_violations

    async def _run_eval(self, policy_file: str, input_data: dict) -> str:
        import tempfile

        policy_dir = Path(self._policy_dir).resolve()
        policy_path = policy_dir / policy_file

        if not policy_path.exists():
            logger.warning("opa_policy_not_found", path=str(policy_path))
            return "{}"

        input_path: str | None = None
        try:
            input_json = json.dumps(input_data)
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as tmp:
                tmp.write(input_json)
                input_path = tmp.name

            proc = await asyncio.create_subprocess_exec(
                self._binary,
                "eval",
                "--data", policy_file,
                "--input", input_path,
                "--format", "json",
                "data.terraform.deny",
                cwd=str(policy_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=30.0
            )

            stderr = stderr_bytes.decode("utf-8", errors="replace")
            if proc.returncode != 0 and stderr:
                logger.warning(
                    "opa_eval_stderr",
                    policy=policy_file,
                    stderr=stderr,
                )

            return stdout_bytes.decode("utf-8", errors="replace")
        except FileNotFoundError:
            logger.error("opa_binary_not_found", binary=self._binary)
            return "{}"
        except asyncio.TimeoutError:
            logger.error("opa_eval_timeout", policy=policy_file)
            return "{}"
        except Exception as e:
            logger.error("opa_eval_failed", policy=policy_file, error=str(e))
            return "{}"
        finally:
            if input_path is not None:
                try:
                    os.unlink(input_path)
                except OSError:
                    pass

    def _parse_result(self, raw_output: str) -> list[OpaViolation]:
        violations: list[OpaViolation] = []
        try:
            data = json.loads(raw_output)
            results = data.get("result", [])
            for item in results:
                expressions = item.get("expressions", [])
                for expr in expressions:
                    value = expr.get("value", [])
                    if isinstance(value, list):
                        for v in value:
                            if isinstance(v, dict):
                                violations.append(
                                    OpaViolation(
                                        policy=v.get("policy", "unknown"),
                                        resource=v.get("resource", "unknown"),
                                        message=v.get("message", "No detail"),
                                        severity=v.get("severity", "MEDIUM"),
                                    )
                                )
                            elif isinstance(v, str):
                                violations.append(
                                    OpaViolation(
                                        policy="custom",
                                        resource="unknown",
                                        message=v,
                                    )
                                )
        except json.JSONDecodeError:
            logger.warning("opa_parse_failed", raw=raw_output[:200])
        return violations
