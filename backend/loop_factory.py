"""Event-loop factory for uvicorn that survives aborted client connections.

Why this exists
---------------
On Windows, uvicorn's default "asyncio" loop is the Proactor loop, whose
``accept()`` raises ``OSError [WinError 64] "The specified network name is no
longer available"`` when a client disconnects abruptly. In Forge that happens
constantly: the browser (or a test client) aborts the long-running
``POST /api/generate`` request, and the very next request (for example
fetching the freshly generated site) was then refused, because the listening
socket had been left in a broken state.

The Selector loop does not use overlapped I/O and survives an aborted accept
cleanly, which removes the whole class of failure.

Usage
-----
    uvicorn main:app --port 8000 --loop loop_factory:windows_safe_loop_factory

uvicorn imports the target and uses it directly as the loop factory, so this
module must expose a zero-argument callable that returns a fresh event loop.

On non-Windows platforms the Selector loop is not needed and the standard
asyncio loop is returned, so the same command line works everywhere.
"""
import asyncio
import sys


def windows_safe_loop_factory():
    """Return a new event loop: Selector on Windows, plain asyncio elsewhere.

    Note: uvicorn calls this with no arguments (it imports the name and uses
    it as the loop_factory for asyncio.Runner), so it must stay zero-arg.
    """
    if sys.platform == "win32":
        try:
            # asyncio.SelectorEventLoop on Windows is the non-overlapped
            # loop. Constructing it directly avoids the deprecated
            # WindowsSelectorEventLoopPolicy.
            return asyncio.SelectorEventLoop()
        except Exception:
            pass
    return asyncio.new_event_loop()
