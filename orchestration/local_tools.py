"""Scoped local file, container terminal, and temporary browser capabilities."""

import hashlib
import ipaddress
import os
import selectors
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from orchestration.policy import PolicyDenied, PolicyStore


MAX_FILE_BYTES = 1_048_576


@dataclass(frozen=True)
class ToolResult:
    status: str
    output: str
    exit_code: int | None = None
    untrusted: bool = True


def _under_root(root: Path, candidate: Path) -> bool:
    return candidate == root or root in candidate.parents


def _open_beneath(root: Path, relative: Path, flags: int, mode: int = 0o600) -> int:
    """Walk every component with O_NOFOLLOW to reject symlink escapes."""
    parts = relative.parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise PolicyDenied("Invalid scoped path")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        return os.open(parts[-1], flags | os.O_NOFOLLOW, mode, dir_fd=directory)
    finally:
        os.close(directory)


def _validate_parent(root: Path, relative: Path) -> None:
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
    finally:
        os.close(directory)


class ScopedFileSystem:
    def __init__(self, policy: PolicyStore, owner: str):
        self.policy = policy
        self.owner = owner

    def _scope(self, path: Path, operation: str) -> tuple[Path, Path, Path]:
        if not Path(path).is_absolute():
            raise PolicyDenied("An absolute path is required")
        candidate = Path(os.path.abspath(os.path.normpath(str(path))))
        for root in self.policy.roots(self.owner, operation):
            if _under_root(root, candidate) and candidate != root:
                return root, candidate.relative_to(root), candidate
        raise PolicyDenied("Path is outside approved filesystem roots")

    def read(self, path: Path, max_bytes: int = MAX_FILE_BYTES) -> bytes:
        if not 1 <= max_bytes <= MAX_FILE_BYTES:
            raise ValueError("Invalid read limit")
        root, relative, _ = self._scope(path, "read")
        self.policy.authorize(self.owner, "filesystem", "read")
        try:
            descriptor = _open_beneath(root, relative, os.O_RDONLY)
            with os.fdopen(descriptor, "rb") as stream:
                content = stream.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise ValueError("File exceeds read limit")
        except (OSError, ValueError):
            self.policy.audit(self.owner, "filesystem", "read", "failed", "path or size")
            raise
        self.policy.audit(self.owner, "filesystem", "read", "completed")
        return content

    def write_new(self, path: Path, content: bytes, approval_id: str) -> None:
        if not isinstance(content, bytes) or len(content) > MAX_FILE_BYTES:
            raise ValueError("New file content must be bytes within the file limit")
        root, relative, candidate = self._scope(path, "write")
        parameters = {"path": str(candidate), "sha256": hashlib.sha256(content).hexdigest()}
        # Validate the parent chain before consuming approval. O_NOFOLLOW is
        # repeated at the actual write, so a later symlink swap cannot escape.
        _validate_parent(root, relative)
        self.policy.authorize(self.owner, "filesystem", "write", parameters, approval_id)
        try:
            descriptor = _open_beneath(root, relative, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
        except OSError:
            self.policy.audit(self.owner, "filesystem", "write", "failed", "path or already exists")
            raise
        self.policy.audit(self.owner, "filesystem", "write", "completed")

    @staticmethod
    def write_parameters(path: Path, content: bytes) -> dict:
        candidate = Path(os.path.abspath(os.path.normpath(str(path))))
        return {"path": str(candidate), "sha256": hashlib.sha256(content).hexdigest()}


def _run_bounded(argv: list[str], timeout_seconds: float, max_output_bytes: int,
                 env: dict[str, str]) -> ToolResult:
    if not 1 <= timeout_seconds <= 30 or not 1 <= max_output_bytes <= 65536:
        raise ValueError("Tool limits are out of range")
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, env=env, start_new_session=True)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    chunks = bytearray()
    deadline = time.monotonic() + timeout_seconds
    status = "completed"
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status = "timeout"
                break
            for key, _ in selector.select(timeout=remaining):
                chunk = os.read(key.fd, min(8192, max_output_bytes + 1 - len(chunks)))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                chunks.extend(chunk)
                if len(chunks) > max_output_bytes:
                    status = "output_limit"
                    break
            if status != "completed":
                break
    finally:
        selector.close()
        if status != "completed" or process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=5)
        process.stdout.close()
    output = bytes(chunks[:max_output_bytes]).decode("utf-8", errors="replace")
    if status == "completed" and process.returncode != 0:
        status = "failed"
    return ToolResult(status, output, process.returncode)


def _remove_container(docker: str, name: str) -> None:
    try:
        subprocess.run([docker, "rm", "-f", name], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


class ScopedTerminal:
    """Run commands in a read-only, networkless Docker container or fail closed."""

    def __init__(self, policy: PolicyStore, owner: str, image: str = "python:3.14-slim"):
        self.policy = policy
        self.owner = owner
        self.image = image

    def run(self, argv: list[str], root: Path, approval_id: str,
            timeout_seconds: float = 10, max_output_bytes: int = 8192) -> ToolResult:
        if not argv or any(not isinstance(part, str) or not part or "\x00" in part for part in argv):
            raise ValueError("Command must be a nonempty argument list")
        if len(argv) > 64 or sum(len(part) for part in argv) > 4096:
            raise ValueError("Command exceeds argument limit")
        root = Path(root).resolve(strict=True)
        if root not in self.policy.roots(self.owner, "read"):
            raise PolicyDenied("Terminal workspace root is not approved")
        if any(character in str(root) for character in ",\r\n"):
            raise PolicyDenied("Terminal workspace path cannot be mounted safely")
        if not self.image or self.image.startswith("-") or any(character.isspace() for character in self.image):
            raise ValueError("Invalid container image")
        docker = shutil.which("docker")
        if not docker:
            raise RuntimeError("Docker isolation is unavailable")
        probe = subprocess.run([docker, "info", "--format", "{{.ServerVersion}}"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=3, check=False)
        if probe.returncode:
            raise RuntimeError("Docker isolation is unavailable")
        parameters = {"argv": argv, "root": str(root), "image": self.image}
        self.policy.authorize(self.owner, "terminal", "write", parameters, approval_id)
        container_name = f"orin-{uuid4().hex}"
        command = [docker, "run", "--rm", "--pull=never", "--network=none",
                   "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                   "--pids-limit=32", "--memory=128m", "--memory-swap=128m",
                   "--cpus=0.5", "--ulimit=nofile=64:64",
                   "--name", container_name,
                   "--user=65534:65534", "--tmpfs=/tmp:rw,nosuid,noexec,size=16m",
                   "--mount", f"type=bind,src={root},dst=/workspace,readonly",
                   "--workdir=/workspace", "-e", "PYTHONDONTWRITEBYTECODE=1",
                   self.image, *argv]
        try:
            result = _run_bounded(command, timeout_seconds, max_output_bytes,
                                  {"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        except Exception:
            _remove_container(docker, container_name)
            self.policy.audit(self.owner, "terminal", "write", "failed", "isolation or launch")
            raise
        if result.status in ("timeout", "output_limit"):
            _remove_container(docker, container_name)
        self.policy.audit(self.owner, "terminal", "write", result.status)
        return result

    @staticmethod
    def run_parameters(argv: list[str], root: Path, image: str = "python:3.14-slim") -> dict:
        return {"argv": argv, "root": str(Path(root).resolve(strict=True)), "image": image}


def _public_https(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError:
        return False
    return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global for item in addresses)


class IsolatedBrowser:
    """Temporary Chrome profile, public HTTPS only, bounded output and lifetime."""

    def __init__(self, policy: PolicyStore, owner: str):
        self.policy = policy
        self.owner = owner

    def fetch(self, url: str, timeout_seconds: float = 10,
              max_output_bytes: int = 16384) -> ToolResult:
        if len(url) > 2048 or not _public_https(url):
            raise PolicyDenied("Browser URL must resolve to public HTTPS")
        chrome = shutil.which("google-chrome") or shutil.which("chromium")
        if not chrome:
            raise RuntimeError("Isolated Chrome is unavailable")
        self.policy.authorize(self.owner, "browser", "read", {"url": url})
        with tempfile.TemporaryDirectory(prefix="orin-browser-") as profile:
            command = [chrome, "--headless=new", "--disable-extensions",
                       "--disable-background-networking", "--no-first-run",
                       f"--user-data-dir={profile}", "--dump-dom", url]
            result = _run_bounded(command, timeout_seconds, max_output_bytes,
                                  {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                   "HOME": profile})
        self.policy.audit(self.owner, "browser", "read", result.status)
        return result
