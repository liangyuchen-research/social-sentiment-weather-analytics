"""Build Fission deployment archives with vendored Python dependencies.

This avoids Fission builder permission issues on Windows-generated zip files.
Run from backend/fission:

    python build_deploy_archives.py
"""

# COMP90024 Team 2

from __future__ import annotations

import shutil
import subprocess
import sys
from uuid import uuid4
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parent
FUNCTIONS_ROOT = ROOT / "functions"
BUILD_ROOT = ROOT / ".fission_build"

PACKAGES = ("api_query", "clean_posts", "harvest_reddit", "harvest_social", "harvest_weather")


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def copy_sources(src: Path, dst: Path) -> None:
    for item in src.iterdir():
        if item.name == "__pycache__":
            continue
        if item.is_file():
            shutil.copy2(item, dst / item.name)


def portable_wheel_args() -> list[str]:
    return [
        "--platform", "any",
        "--implementation", "py",
        "--python-version", "39",
        "--abi", "none",
        "--only-binary=:all:",
    ]


def install_requirements(name: str, stage: Path) -> None:
    req = FUNCTIONS_ROOT / name / "requirements.txt"
    if not req.exists() or not req.read_text(encoding="utf-8").strip():
        return

    requirements = [line.strip() for line in req.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
    # The Fission Python 3.9 runtime uses Alpine (musl), not glibc. These
    # functions require no native extensions, so use universal wheels only.
    # langdetect is distributed as pure-Python source; six is listed explicitly.
    source_requirements = [line for line in requirements if line.startswith("langdetect==")]
    binary_requirements = [line for line in requirements if line not in source_requirements]
    if binary_requirements:
        run([
            sys.executable, "-m", "pip", "install",
            "--no-compile", "--target", str(stage),
            *portable_wheel_args(), *binary_requirements,
        ])
    if source_requirements:
        run([sys.executable, "-m", "pip", "install", "--no-compile",
             "--target", str(stage), "--no-deps", *source_requirements])


def zip_stage(stage: Path, zip_path: Path) -> None:
    if zip_path.exists():
        # Preserve earlier generated archives for comparison instead of deleting.
        backup = stage.parent / (zip_path.stem + "-previous-" + uuid4().hex + ".zip")
        shutil.copy2(zip_path, backup)
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as zf:
        for path in sorted(stage.rglob("*")):
            if not path.is_file():
                continue
            relative_path = path.relative_to(stage)
            # pip creates host-specific console launchers even from universal
            # wheels. Functions import libraries directly and need no launchers.
            if relative_path.parts[0] in {"bin", "Scripts"} or "__pycache__" in relative_path.parts:
                continue
            rel = relative_path.as_posix()
            info = ZipInfo(rel)
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.date_time = (2026, 5, 7, 0, 0, 0)
            info.external_attr = (0o755 if path.suffix == ".sh" else 0o644) << 16
            zf.writestr(info, path.read_bytes())
    print(f"wrote {zip_path.name} ({zip_path.stat().st_size} bytes)")


def main() -> None:
    if not FUNCTIONS_ROOT.exists():
        raise FileNotFoundError(f"Fission functions directory not found: {FUNCTIONS_ROOT}")

    build_root = BUILD_ROOT / uuid4().hex
    build_root.mkdir(parents=True)

    for name in PACKAGES:
        print(f"\n== {name} ==")
        src = FUNCTIONS_ROOT / name
        if not src.exists():
            raise FileNotFoundError(f"Fission function package not found: {src}")

        stage = build_root / name
        stage.mkdir(parents=True)
        copy_sources(src, stage)
        install_requirements(name, stage)
        zip_stage(stage, ROOT / f"{name}.zip")


if __name__ == "__main__":
    main()
