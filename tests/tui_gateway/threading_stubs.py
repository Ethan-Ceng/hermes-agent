"""Preserve synchronous app-thread fixtures without replacing subprocess pipe readers."""
import subprocess
import threading
from types import SimpleNamespace

_REAL_THREAD, _REAL_LOCK = threading.Thread, threading.Lock


def patch_server_thread(monkeypatch, server, factory):
    monkeypatch.setattr(subprocess, "threading", SimpleNamespace(Thread=_REAL_THREAD, Lock=_REAL_LOCK))
    monkeypatch.setattr(server.threading, "Thread", factory)
