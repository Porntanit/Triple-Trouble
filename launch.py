"""Prepare and launch a private local copy. Standard-library bootstrap only."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import venv
import webbrowser

ROOT = Path(__file__).resolve().parent
MODELS = ("gemma3:1b", "nomic-embed-text")
REQUIRED = (
    "app.py",
    "requirements.txt",
    "food_images.py",
    "energy.py",
    "templates/base.html",
    "static/images.js",
)


def validate_bundle(root=ROOT):
    missing = [name for name in REQUIRED if not (root / name).is_file()]
    if missing:
        raise RuntimeError("Extract the entire ZIP first. Missing files: " + ", ".join(missing))


def read_json(url, timeout=3):
    with urlopen(url, timeout=timeout) as response:
        return json.load(response)


def ollama_cli():
    candidate = shutil.which("ollama")
    if candidate:
        return candidate
    for path in (
        Path("/Applications/Ollama.app/Contents/Resources/ollama"),
        Path.home() / "Applications/Ollama.app/Contents/Resources/ollama",
    ):
        if path.is_file():
            return str(path)
    return None


def installed_models():
    data = read_json("http://127.0.0.1:11434/api/tags")
    return {item.get("name", "") for item in data.get("models", []) if isinstance(item, dict)}


def model_is_installed(name, names):
    return name in names or name + ":latest" in names


def ensure_ollama():
    cli = ollama_cli()
    try:
        names = installed_models()
    except (OSError, ValueError, URLError):
        apps = (Path("/Applications/Ollama.app"), Path.home() / "Applications/Ollama.app")
        app = next((path for path in apps if path.is_dir()), None)
        if app:
            print("Opening the installed Ollama app…", flush=True)
            subprocess.run(["open", str(app)], check=True)
        else:
            raise RuntimeError(
                "Install and open Ollama from https://ollama.com/download/mac, then run this launcher again."
            )
        for _ in range(30):
            try:
                names = installed_models()
                break
            except (OSError, ValueError, URLError):
                time.sleep(1)
        else:
            raise RuntimeError(
                "Ollama did not start. Open it manually, complete its setup, and retry."
            )
    missing = [name for name in MODELS if not model_is_installed(name, names)]
    if missing:
        if not cli:
            raise RuntimeError("Open Ollama and install these models first: " + ", ".join(missing))
        print("First-time download needed: " + ", ".join(missing), flush=True)
        print(
            "Both required models use about 1–2 GB in total. Internet is needed for downloads.",
            flush=True,
        )
        answer = input("Download the missing model(s) now? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes"):
            raise RuntimeError("Download postponed. Run this launcher again when ready.")
        for name in missing:
            subprocess.run([cli, "pull", name], check=True)
        names = installed_models()
        if any(not model_is_installed(name, names) for name in MODELS):
            raise RuntimeError("Some models are still missing. Check Ollama and retry.")


def environment_python():
    folder = ROOT / ".venv"
    executable = folder / "bin" / "python"
    if not executable.is_file():
        print("Creating a Python environment for this copy…", flush=True)
        venv.EnvBuilder(with_pip=True).create(folder)
    check = subprocess.run(
        [
            str(executable),
            "-c",
            "import sys; raise SystemExit(not ((3,10) <= sys.version_info[:2] < (3,14)))",
        ],
        check=False,
    )
    if check.returncode:
        raise RuntimeError(
            "This folder contains an incompatible .venv. Extract a fresh ZIP and launch that copy."
        )
    requirements = ROOT / "requirements.txt"
    fingerprint = hashlib.sha256(requirements.read_bytes()).hexdigest()
    stamp = folder / ".triple-trouble-requirements"
    smoke = subprocess.run(
        [str(executable), "-c", "import flask, requests, fitz, PIL, Vision, Foundation, Quartz"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if smoke.returncode or not stamp.is_file() or stamp.read_text().strip() != fingerprint:
        print("Installing the project's packages. First launch needs internet…", flush=True)
        subprocess.run(
            [str(executable), "-m", "pip", "install", "-r", str(requirements)], check=True
        )
        subprocess.run(
            [
                str(executable),
                "-c",
                "import flask, requests, fitz, PIL, Vision, Foundation, Quartz",
            ],
            check=True,
        )
        stamp.write_text(fingerprint)
    return executable


def choose_port():
    for port in (5055, 5056, 5057, 5058, 5059):
        try:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
    raise RuntimeError("Ports 5055–5059 are busy. Close previous copies of the website and retry.")


def run_server(executable):
    port = choose_port()
    data_dir = Path.home() / "Library" / "Application Support" / "Triple-Trouble"
    data_dir.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(PORT=str(port), TT_DATA_DIR=str(data_dir))
    url = f"http://127.0.0.1:{port}"
    print(f"Starting Triple-Trouble at {url}", flush=True)
    print(f"Your local data: {data_dir}", flush=True)
    print("Keep this Terminal window open. Press Control+C to stop the website.", flush=True)
    child = subprocess.Popen([str(executable), str(ROOT / "app.py")], cwd=ROOT, env=environment)
    try:
        for _ in range(45):
            if child.poll() is not None:
                raise RuntimeError("The website stopped during startup. See the error above.")
            try:
                with urlopen(url, timeout=1) as response:
                    if response.status == 200:
                        print("Website ready. Opening your browser…", flush=True)
                        webbrowser.open(url)
                        break
            except (OSError, URLError):
                time.sleep(1)
        else:
            raise RuntimeError("The website did not become ready. See the Terminal error above.")
        child.wait()
    except KeyboardInterrupt:
        print("\nStopping the website…", flush=True)
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def main():
    parser = argparse.ArgumentParser(description="Set up and open Triple-Trouble on a Mac.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the bundle only; no installations or downloads.",
    )
    args = parser.parse_args()
    validate_bundle()
    if args.check:
        print("Bundle structure OK. Setup/inference have not been run by this check.")
        return
    if platform.system() != "Darwin":
        raise RuntimeError("This photo-enabled bundle requires macOS.")
    if not (3, 10) <= sys.version_info[:2] < (3, 14):
        raise RuntimeError(
            "Install Python 3.12 (supported: 3.10–3.13), then use Start-on-Mac.command."
        )
    executable = environment_python()
    ensure_ollama()
    run_server(executable)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError, EOFError) as error:
        print(f"\nCould not start: {error}", file=sys.stderr, flush=True)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nSetup stopped. Run the launcher again to continue.", flush=True)
        sys.exit(130)
