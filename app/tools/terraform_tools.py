import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from app.models.config import get_settings
from app.models.schemas import TerraformPlanResponse
from app.utils.logger import get_logger
from app.utils.retry import async_retry

logger = get_logger(__name__)


class TerraformTool:
    def __init__(self, work_dir: Optional[str] = None) -> None:
        settings = get_settings()
        self._binary = settings.terraform_binary
        self._work_dir = work_dir or settings.terraform_dir

    @async_retry(max_retries=2, delay=0.5)
    async def init(self) -> TerraformPlanResponse:
        logger.info("terraform_init_starting", directory=self._work_dir)
        result = await self._run_command(["init", "-no-color", "-input=false"])
        logger.info(
            "terraform_init_completed",
            exit_code=result.exit_code,
            error=result.error,
        )
        return result

    @async_retry(max_retries=2, delay=0.5)
    async def plan(self) -> TerraformPlanResponse:
        logger.info("terraform_plan_starting", directory=self._work_dir)
        result = await self._run_command(
            ["plan", "-no-color", "-input=false", "-detailed-exitcode"]
        )
        logger.info(
            "terraform_plan_completed",
            exit_code=result.exit_code,
            has_changes=(result.exit_code == 2),
            error=result.error,
        )
        return result

    async def run_full_plan(self) -> TerraformPlanResponse:
        init_result = await self.init()
        if init_result.exit_code != 0:
            return init_result

        plan_result = await self.plan()
        return plan_result

    async def _run_command(self, args: list[str]) -> TerraformPlanResponse:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary,
                *args,
                cwd=self._work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "TF_IN_AUTOMATION": "true"},
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=300.0
            )

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            return TerraformPlanResponse(
                init_stdout=stdout if "init" in args else "",
                init_stderr=stderr if "init" in args else "",
                plan_stdout=stdout if "plan" in args else "",
                plan_stderr=stderr if "plan" in args else "",
                exit_code=proc.returncode or 0,
            )

        except asyncio.TimeoutError:
            logger.error("terraform_command_timeout", args=args)
            return TerraformPlanResponse(
                exit_code=-1,
                error=f"Command timed out after 300s: {' '.join(args)}",
            )
        except FileNotFoundError:
            logger.error("terraform_binary_not_found", binary=self._binary)
            return TerraformPlanResponse(
                exit_code=-1,
                error=f"Terraform binary not found: {self._binary}. Install terraform and ensure it is on PATH.",
            )
        except Exception as e:
            logger.error("terraform_command_failed", args=args, error=str(e))
            return TerraformPlanResponse(exit_code=-1, error=str(e))

    def parse_plan_resources(self, plan_stdout: str) -> list[dict]:
        resources: list[dict] = []
        for line in plan_stdout.splitlines():
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            if "will be" in line and ("created" in line or "destroyed" in line or "replaced" in line):
                resources.append({
                    "raw": line,
                    "action": self._classify_action(line),
                    "address": self._extract_address(line),
                })
        return resources

    def _classify_action(self, line: str) -> str:
        if "created" in line:
            return "create"
        if "destroyed" in line and "replaced" not in line:
            return "destroy"
        if "replaced" in line:
            return "replace"
        if "changed" in line or "updated" in line:
            return "update"
        if "read" in line:
            return "read"
        return "unknown"

    def _extract_address(self, line: str) -> str:
        parts = line.split()
        if parts:
            addr = parts[0]
            return addr.strip('"')
        return "unknown"
