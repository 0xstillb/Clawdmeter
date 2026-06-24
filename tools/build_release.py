from __future__ import annotations

import argparse
import shutil
import tarfile
from pathlib import Path
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]


HOST_COMMON_FILES = [
    "README.md",
]

HOST_COMMON_DIRS = [
    "daemon",
]

HOST_PACKAGE_LAYOUT = {
    "windows": {
        "files": ["docs/user/windows-daemon.md"],
        "dirs": ["scripts/windows"],
        "archive_ext": ".zip",
    },
    "macos": {
        "files": [],
        "dirs": ["scripts/macos"],
        "archive_ext": ".tar.gz",
    },
    "linux": {
        "files": [],
        "dirs": ["scripts/linux"],
        "archive_ext": ".tar.gz",
    },
}

EXCLUDE_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    ".codex-tmp",
}

EXCLUDE_FILE_SUFFIXES = {".pyc", ".pyo"}


def copy_path(src_rel: str, dst_root: Path) -> None:
    src = REPO_ROOT / src_rel
    dst = dst_root / src_rel
    if src.is_dir():
        shutil.copytree(
            src,
            dst,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(*EXCLUDE_DIR_NAMES, "*.pyc", "*.pyo"),
        )
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def build_host_package(version: str, platform: str, out_dir: Path) -> Path:
    spec = HOST_PACKAGE_LAYOUT[platform]
    package_root = out_dir / f"Clawdmeter-{platform}-{version}"
    if package_root.exists():
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True, exist_ok=True)

    for rel in HOST_COMMON_FILES + spec["files"]:
        copy_path(rel, package_root)
    for rel in HOST_COMMON_DIRS + spec["dirs"]:
        copy_path(rel, package_root)

    if platform == "windows":
        archive = out_dir / f"{package_root.name}.zip"
        if archive.exists():
            archive.unlink()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(package_root.rglob("*")):
                if path.is_dir():
                    continue
                zf.write(path, path.relative_to(out_dir))
        return archive

    archive = out_dir / f"{package_root.name}.tar.gz"
    if archive.exists():
        archive.unlink()
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(package_root, arcname=package_root.name)
    return archive


def copy_firmware_asset(version: str, env: str, source: Path, out_dir: Path) -> Path:
    asset_name = f"Clawdmeter-{env}-{version}{source.suffix}"
    dst = out_dir / asset_name
    shutil.copy2(source, dst)
    return dst


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Clawdmeter release assets")
    parser.add_argument("version", help="Release version/tag, e.g. v0.1.0")
    parser.add_argument(
        "--firmware",
        nargs=2,
        metavar=("ENV", "PATH"),
        action="append",
        default=[],
        help="Firmware asset pair: PlatformIO env name and source binary path",
    )
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / ".codex-tmp" / "release-assets"),
        help="Output directory for archives/assets",
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    assets: list[Path] = []
    for platform in ("windows", "macos", "linux"):
        assets.append(build_host_package(args.version, platform, out_dir))

    for env, src in args.firmware:
        assets.append(copy_firmware_asset(args.version, env, Path(src), out_dir))

    for asset in assets:
        print(asset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
