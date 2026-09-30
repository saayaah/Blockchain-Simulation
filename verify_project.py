"""Preflight checker for the submission-ready blockchain simulation.
Run after installing requirements: python verify_project.py
"""
from __future__ import annotations
import ast
import importlib.util
from pathlib import Path
import socket

ROOT = Path(__file__).resolve().parent
REQUIRED_MODULES = [
    ("ecdsa", "ecdsa"),
    ("flask", "Flask"),
    ("flask_cors", "flask-cors"),
    ("websockets", "websockets"),
    ("base58", "base58"),
    ("RestrictedPython", "RestrictedPython"),
    ("cryptography", "cryptography"),
]


def main():
    ok = True
    print("=== Blockchain Simulation Preflight ===")
    for rel in ["start_peer.py", "signalling_server.py", "signalling_client.py", "web_interface.py", "tests_pos.py"]:
        path = ROOT / rel
        if not path.exists():
            print(f"FAIL  missing {rel}")
            ok = False
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"))
            print(f"PASS  syntax {rel}")
        except Exception as exc:
            print(f"FAIL  syntax {rel}: {exc}")
            ok = False

    for path in ROOT.rglob("*.py"):
        if "__pycache__" in path.parts or ".venv" in path.parts:
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"FAIL  syntax {path.relative_to(ROOT)}: {exc}")
            ok = False

    for module, package in REQUIRED_MODULES:
        if importlib.util.find_spec(module) is None:
            print(f"FAIL  dependency {package} is not installed")
            ok = False
        else:
            print(f"PASS  dependency {package}")

    for host, port, label in [("127.0.0.1", 8765, "signalling"), ("127.0.0.1", 8000, "web")]:
        sock = socket.socket()
        try:
            sock.bind((host, port))
            print(f"PASS  {label} port {port} is available")
        except OSError as exc:
            print(f"WARN  {label} port {port} is already in use ({exc})")
        finally:
            sock.close()

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
