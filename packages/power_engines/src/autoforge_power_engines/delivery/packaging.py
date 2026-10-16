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


class ArtifactEntry(BaseModel):
    artifact_id: str
    logical_version: int = 1
    physical_path: str = ""
    sha256: str = ""
    size_bytes: int = 0
    lineage: Dict[str, Any] = Field(default_factory=dict)


class DeliverableManifest(BaseModel):
    """Cryptographic manifest of packaged customer deliverables."""
    project_name: str
    delivery_id: str
    delivery_dir: str
    created_at: str
    project_id: Optional[str] = None
    execution_id: Optional[str] = None
    workflow_id: Optional[str] = None
    files_created: List[str] = Field(default_factory=list)
    directories_created: List[str] = Field(default_factory=list)
    total_bytes: int = 0
    sha256_checksums: Dict[str, str] = Field(default_factory=dict)
    file_sizes: Dict[str, int] = Field(default_factory=dict)
    artifacts: List[ArtifactEntry] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    verification_status: str = "VERIFIED"
    test_evidence: Dict[str, Any] = Field(default_factory=dict)
    sanitizer_result: Dict[str, Any] = Field(default_factory=dict)
    deployment_verification_result: Dict[str, Any] = Field(default_factory=dict)
    manifest_signature: Optional[str] = None

    def compute_manifest_hash(self) -> str:
        """Compute cryptographic SHA-256 hash of manifest contents excluding the signature itself."""
        import json
        data = self.model_dump(exclude={"manifest_signature"})
        dumped = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(dumped.encode("utf-8")).hexdigest()

    def sign_manifest(self) -> str:
        """Signs the manifest with its own cryptographic hash."""
        sig = self.compute_manifest_hash()
        self.manifest_signature = sig
        return sig


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

    def create_manifest(
        self,
        fixed_timestamp: Optional[str] = None,
        project_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        artifacts: Optional[List[ArtifactEntry]] = None,
        provenance: Optional[Dict[str, Any]] = None,
        verification_status: str = "VERIFIED",
        test_evidence: Optional[Dict[str, Any]] = None,
        sanitizer_result: Optional[Dict[str, Any]] = None,
        deployment_verification_result: Optional[Dict[str, Any]] = None,
        auto_sign: bool = True,
    ) -> DeliverableManifest:
        """Generates a complete manifest with cryptographic checksums and sizes."""
        files_created = []
        dirs_created = []
        checksums = {}
        file_sizes = {}
        total_bytes = 0

        for root, dirs, files in os.walk(self.delivery_dir):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache", ".git")]
            for d in dirs:
                dirs_created.append(str(Path(root, d).relative_to(self.delivery_dir)))
            for f in files:
                if f.endswith(".pyc") or f.endswith(".pyo") or f == ".DS_Store":
                    continue
                fpath = Path(root, f)
                rel = str(fpath.relative_to(self.delivery_dir))
                if rel in ("artifacts/manifest.json", "artifacts/checksums.sha256"):
                    continue
                files_created.append(rel)
                b = fpath.read_bytes()
                total_bytes += len(b)
                checksums[rel] = hashlib.sha256(b).hexdigest()
                file_sizes[rel] = len(b)

        project_name = self.delivery_dir.parent.name
        delivery_id = self.delivery_dir.name

        manifest = DeliverableManifest(
            project_name=project_name,
            delivery_id=delivery_id,
            delivery_dir=str(self.delivery_dir),
            created_at=fixed_timestamp or datetime.now(timezone.utc).isoformat(),
            project_id=project_id,
            execution_id=execution_id,
            workflow_id=workflow_id,
            files_created=sorted(files_created),
            directories_created=sorted(dirs_created),
            total_bytes=total_bytes,
            sha256_checksums=checksums,
            file_sizes=file_sizes,
            artifacts=artifacts or [],
            provenance=provenance or {},
            verification_status=verification_status,
            test_evidence=test_evidence or {},
            sanitizer_result=sanitizer_result or {},
            deployment_verification_result=deployment_verification_result or {},
        )

        if auto_sign:
            manifest.sign_manifest()

        return manifest

    def create_archive(
        self,
        archive_path: Optional[Path | str] = None,
        reproducible: bool = True,
        fixed_mtime: int = 1700000000,
    ) -> tuple[Path, str]:
        """Creates a .tar.gz distribution archive of the delivery directory.

        When reproducible=True, normalizes file metadata (fixed mtime, uid=0, gid=0,
        uname='', gname='', normalized permissions, files sorted lexicographically, and fixed gzip header mtime)
        so that archiving the same unchanged directory twice produces byte-identical archives.
        Returns (archive_path, sha256_checksum).
        """
        import gzip
        import tarfile

        if archive_path is None:
            name = f"{self.delivery_dir.name}.tar.gz"
            out_path = self.delivery_dir.parent / name
        else:
            out_path = Path(archive_path).resolve()

        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = out_path.with_suffix(".tmp.tar.gz")

        try:
            if reproducible:
                with open(tmp_path, "wb") as f_raw:
                    with gzip.GzipFile(filename="", mode="wb", fileobj=f_raw, mtime=fixed_mtime) as gz_out:
                        with tarfile.open(fileobj=gz_out, mode="w:") as tar:
                            for root, dirs, files in os.walk(self.delivery_dir):
                                dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache", ".git")]
                                dirs.sort()
                                for f in sorted(files):
                                    if f.endswith(".pyc") or f.endswith(".pyo") or f == ".DS_Store":
                                        continue
                                    full_p = Path(root, f)
                                    rel_p = full_p.relative_to(self.delivery_dir)
                                    ti = tar.gettarinfo(str(full_p), arcname=str(rel_p))
                                    ti.uid = 0
                                    ti.gid = 0
                                    ti.uname = ""
                                    ti.gname = ""
                                    ti.mtime = fixed_mtime
                                    if ti.isreg():
                                        is_exec = bool(ti.mode & 0o111)
                                        ti.mode = 0o755 if is_exec else 0o644
                                        with open(full_p, "rb") as f_in:
                                            tar.addfile(ti, f_in)
                                    elif ti.isdir():
                                        ti.mode = 0o755
                                        tar.addfile(ti)
                                    else:
                                        tar.addfile(ti)
            else:
                with tarfile.open(tmp_path, "w:gz") as tar:
                    for child in sorted(self.delivery_dir.iterdir()):
                        tar.add(child, arcname=child.name, recursive=True)

            sha = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
            tmp_path.replace(out_path)
            return out_path, sha
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
