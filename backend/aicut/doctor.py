"""``python -m aicut doctor`` — environment diagnostics.

Every hardware feature degrades gracefully: GPU is an optimization, not a
requirement. Nothing here ever raises; it reports and returns an exit code.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass

from .config import get_settings

OK = "  ok  "
WARN = " warn "
FAIL = " fail "


@dataclass
class Check:
    name: str
    status: str
    detail: str
    hint: str = ""


def _run(cmd: list[str], timeout: float = 8.0) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "not found"
    except Exception as e:  # pragma: no cover
        return 1, str(e)


def _install_hint(tool: str) -> str:
    if sys.platform.startswith("win"):
        return f"install {tool}: `winget install {tool}` or add it to PATH"
    if sys.platform == "darwin":
        return f"install {tool}: `brew install {tool}`"
    return f"install {tool}: `sudo apt install {tool}` (or your distro's package)"


def check_python() -> Check:
    v = sys.version_info
    ok = v >= (3, 11)
    return Check(
        "Python >= 3.11",
        OK if ok else FAIL,
        f"{v.major}.{v.minor}.{v.micro}",
        "" if ok else "aicut requires Python 3.11+",
    )


def check_ffmpeg() -> list[Check]:
    checks: list[Check] = []
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        if path:
            rc, out = _run([tool, "-version"])
            ver = out.splitlines()[0] if out else ""
            checks.append(Check(tool, OK, ver[:60]))
        else:
            checks.append(Check(tool, FAIL, "not on PATH", _install_hint("ffmpeg")))
    return checks


def check_nvenc() -> Check:
    if not shutil.which("ffmpeg"):
        return Check("NVENC encoder", WARN, "ffmpeg missing; can't check")
    rc, out = _run(["ffmpeg", "-hide_banner", "-encoders"])
    if "h264_nvenc" in out:
        return Check("NVENC (h264_nvenc)", OK, "hardware H.264 encode available")
    return Check(
        "NVENC (h264_nvenc)",
        WARN,
        "not available — will fall back to libx264 (CPU)",
    )


def check_cuda() -> Check:
    try:
        import ctranslate2  # type: ignore

        try:
            n = ctranslate2.get_cuda_device_count()
        except Exception:
            n = 0
        if n > 0:
            return Check("CUDA (CTranslate2)", OK, f"{n} CUDA device(s) — GPU transcription")
        return Check("CUDA (CTranslate2)", WARN, "no CUDA device — CPU transcription (slower)")
    except ModuleNotFoundError:
        return Check(
            "CUDA (CTranslate2)",
            WARN,
            "faster-whisper not installed",
            "install ML deps: `uv sync --extra ml`",
        )


def check_ollama() -> Check:
    settings = get_settings()
    try:
        import httpx

        r = httpx.get(f"{settings.ollama_host}/api/tags", timeout=2.0)
        if r.status_code == 200:
            models = [m.get("name", "") for m in r.json().get("models", [])]
            has = settings.llm_model in models
            detail = f"reachable; {len(models)} model(s)"
            if not has:
                return Check(
                    "Ollama",
                    WARN,
                    f"{detail}; '{settings.llm_model}' not pulled",
                    f"run `ollama pull {settings.llm_model}` for the AI command bar",
                )
            return Check("Ollama", OK, f"{detail}; '{settings.llm_model}' ready")
        return Check("Ollama", WARN, f"HTTP {r.status_code}")
    except Exception:
        return Check(
            "Ollama",
            WARN,
            "not reachable — AI command bar disabled; manual editing still works",
            "install from https://ollama.com and `ollama serve`",
        )


def check_node() -> Check:
    path = shutil.which("node")
    if not path:
        return Check("Node >= 20", WARN, "not found — needed only to build the frontend",
                     _install_hint("node"))
    rc, out = _run(["node", "--version"])
    ver = out.strip()
    try:
        major = int(ver.lstrip("v").split(".")[0])
        ok = major >= 20
    except Exception:
        ok = False
    return Check("Node >= 20", OK if ok else WARN, ver,
                 "" if ok else "frontend build needs Node 20+")


def check_disk() -> Check:
    settings = get_settings()
    settings.ensure_dirs()
    total, used, free = shutil.disk_usage(settings.home)
    gb = free / (1024**3)
    status = OK if gb > 5 else WARN
    return Check("Disk space", status, f"{gb:.1f} GB free at {settings.home}",
                 "" if gb > 5 else "low disk space for media + exports")


def run_all() -> list[Check]:
    checks: list[Check] = [check_python()]
    checks += check_ffmpeg()
    checks.append(check_nvenc())
    checks.append(check_cuda())
    checks.append(check_ollama())
    checks.append(check_node())
    checks.append(check_disk())
    return checks


def main() -> int:
    checks = run_all()
    print("\n  aicut doctor\n  " + "-" * 48)
    for c in checks:
        line = f"  [{c.status}] {c.name:<26} {c.detail}"
        print(line)
        if c.hint:
            print(f"           -> {c.hint}")
    print("  " + "-" * 48)
    has_fail = any(c.status == FAIL for c in checks)
    if has_fail:
        print("  [X] Some required components are missing (see [fail] above).\n")
        return 1
    print("  [OK] Ready. GPU/Ollama features degrade gracefully if warned.\n")
    return 0
