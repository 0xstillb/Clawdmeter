from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).with_name("usage_payload_harness.cpp")
BUILD_DIR = Path(__file__).with_name(".build")
BINARY = BUILD_DIR / ("usage_payload_harness.exe" if __import__("os").name == "nt" else "usage_payload_harness")


def build_harness() -> Path:
    BUILD_DIR.mkdir(exist_ok=True)
    compile_cmd = [
        "g++",
        "-std=c++17",
        "-Wall",
        "-Wextra",
        "-pedantic",
        "-I",
        str(REPO_ROOT / "firmware" / "src"),
        str(HARNESS),
        str(REPO_ROOT / "firmware" / "src" / "usage_payload.cpp"),
        "-o",
        str(BINARY),
    ]
    subprocess.run(compile_cmd, check=True, cwd=REPO_ROOT)
    return BINARY


@pytest.mark.parametrize(
    "scenario",
    [
        "legacy",
        "provider_window",
        "provider_claude_window",
        "provider_wallet_subtext",
        "invalid_payload",
        "zen_prepaid",
        "codex_weekly_only",
    ],
)
def test_usage_payload_harness_scenarios(scenario: str) -> None:
    binary = build_harness()
    subprocess.run([str(binary), scenario], check=True, cwd=REPO_ROOT)
