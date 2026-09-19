"""Turnkey Customer Deliverable Packaging & Boundary Protection Engine."""

from __future__ import annotations

import os
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from autoforge_power_engines.delivery.spec import CustomerDeploymentSpec
from autoforge_power_engines.delivery.deployment import DeploymentBuilder
from autoforge_power_engines.delivery.health import HealthCheckBuilder
from autoforge_power_engines.delivery.sanitizer import (
    ProprietaryBoundarySanitizer,
    ProprietaryCodeViolationError,
)


class DeliverableManifest(BaseModel):
    """Cryptographic manifest of packaged customer deliverables."""
    project_name: str
    delivery_id: str
    delivery_dir: str
    created_at: str
    files_created: List[str] = Field(default_factory=list)
    directories_created: List[str] = Field(default_factory=list)
    total_bytes: int = 0
    sha256_checksums: Dict[str, str] = Field(default_factory=dict)


class CustomerDeliveryBuilder:
    """
    Constructs the turnkey customer deliverable project directory.
    Enforces strict isolation from AutoForge proprietary implementation.
    """

    def __init__(self, delivery_dir: Path | str):
        self.delivery_dir = Path(delivery_dir).resolve()
        self.sanitizer = ProprietaryBoundarySanitizer(self.delivery_dir)
        self.deployment_builder = DeploymentBuilder()
        self.health_builder = HealthCheckBuilder()

    def prepare_directories(self, extra_data_dirs: Optional[List[str]] = None) -> Dict[str, Path]:
        """Creates the standardized customer directory structure."""
        dirs = {
            "root": self.delivery_dir,
            "src": self.delivery_dir / "src",
            "tests": self.delivery_dir / "tests",
            "config": self.delivery_dir / "config",
            "scripts": self.delivery_dir / "scripts",
            "docs": self.delivery_dir / "docs",
            "artifacts": self.delivery_dir / "artifacts",
            "evidence": self.delivery_dir / "evidence",
            "verification": self.delivery_dir / "verification",
            "data": self.delivery_dir / "data",
            "data_logs": self.delivery_dir / "data" / "logs",
            "data_config": self.delivery_dir / "data" / "config",
            "docker": self.delivery_dir / "docker",
        }

        # Add any customer-specified persistent data directories
        if extra_data_dirs:
            for ed in extra_data_dirs:
                key = "data_" + ed.replace("/", "_").replace("data_", "")
                dirs[key] = self.delivery_dir / ed

        for d in dirs.values():
            d.mkdir(parents=True, exist_ok=True)
        return dirs

    def write_file(self, rel_path: str, content: str, make_executable: bool = False) -> Path:
        """Writes a deliverable file and sets permissions. Enforces path confinement."""
        target = (self.delivery_dir / rel_path).resolve()
        if not target.is_relative_to(self.delivery_dir.resolve()):
            raise ValueError(
                f"Path traversal detected: '{rel_path}' attempts to escape customer delivery root '{self.delivery_dir}'"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if make_executable:
            mode = os.stat(target).st_mode
            os.chmod(target, mode | 0o755)
        return target

    def build_deployment_files(
        self,
        spec: CustomerDeploymentSpec,
        dockerfile_entrypoint: str = "python3 src/app.py",
    ) -> Dict[str, Path]:
        """Generates all deployment scripts, docker config, and environment templates."""
        created = {}

        # 1. docker-compose.yml
        dc_text = self.deployment_builder.build_docker_compose(spec)
        created["docker-compose.yml"] = self.write_file("docker-compose.yml", dc_text)

        # 2. Dockerfile
        df_text = self.deployment_builder.build_dockerfile(
            entrypoint_cmd=dockerfile_entrypoint,
            expose_port=spec.get_primary_port(),
        )
        created["Dockerfile"] = self.write_file("Dockerfile", df_text)

        # 3. Launchers
        created["Deploy.command"] = self.write_file(
            "Deploy.command",
            self.deployment_builder.build_deploy_command(),
            make_executable=True,
        )
        created["deploy.sh"] = self.write_file(
            "deploy.sh",
            self.deployment_builder.build_deploy_sh(spec),
            make_executable=True,
        )
        created["Deploy.bat"] = self.write_file(
            "Deploy.bat",
            self.deployment_builder.build_deploy_bat(spec),
        )
        created["manage.sh"] = self.write_file(
            "manage.sh",
            self.deployment_builder.build_manage_sh(spec),
            make_executable=True,
        )

        # 4. Manifest
        manifest_data = self.deployment_builder.build_manifest(spec)
        import json
        created["config/deployment_manifest.json"] = self.write_file(
            "config/deployment_manifest.json",
            json.dumps(manifest_data, indent=2),
        )

        # 5. Environment templates
        env_ex, env_act = self.deployment_builder.build_env_files(spec)
        created[".env.example"] = self.write_file(".env.example", env_ex)
        created[".env"] = self.write_file(".env", env_act)

        # 6. Scripts: health_check.py
        created["scripts/health_check.py"] = self.write_file(
            "scripts/health_check.py",
            self.health_builder.build_health_script(spec),
            make_executable=True,
        )

        return created

    def sanitize_proprietary_boundary(self) -> List[str]:
        """Audits all files in the deliverable; raises ProprietaryCodeViolationError on violation."""
        return self.sanitizer.sanitize()

    def create_manifest(self, fixed_timestamp: Optional[str] = None) -> DeliverableManifest:
        """Generates a complete manifest with cryptographic checksums."""
        files_created = []
        dirs_created = []
        checksums = {}
        total_bytes = 0

        for root, dirs, files in os.walk(self.delivery_dir):
            for d in dirs:
                dirs_created.append(str(Path(root, d).relative_to(self.delivery_dir)))
            for f in files:
                fpath = Path(root, f)
                rel = str(fpath.relative_to(self.delivery_dir))
                files_created.append(rel)
                b = fpath.read_bytes()
                total_bytes += len(b)
                checksums[rel] = hashlib.sha256(b).hexdigest()

        project_name = self.delivery_dir.parent.name
        delivery_id = self.delivery_dir.name

        return DeliverableManifest(
            project_name=project_name,
            delivery_id=delivery_id,
            delivery_dir=str(self.delivery_dir),
            created_at=fixed_timestamp or datetime.now(timezone.utc).isoformat(),
            files_created=sorted(files_created),
            directories_created=sorted(dirs_created),
            total_bytes=total_bytes,
            sha256_checksums=checksums,
        )
