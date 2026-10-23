"""Test helper: make ``datetime.fromisoformat`` behave like Python < 3.11.

Before 3.11 a trailing ``Z`` is rejected. Patching the ``datetime`` name used
by ``fleetbroker.timeutil`` lets every Python version in the CI matrix detect
a probe that bypasses ``parse_iso_timestamp``.
"""

from datetime import datetime
from unittest import mock

from fleetbroker import timeutil


class _Pre311Datetime(datetime):
    @classmethod
    def fromisoformat(cls, value):
        if value.endswith(("Z", "z")):
            raise ValueError(f"Invalid isoformat string: {value!r}")
        return super().fromisoformat(value)


def pre_311_fromisoformat():
    """Context manager: ``timeutil``'s ``fromisoformat`` rejects a trailing Z."""
    return mock.patch.object(timeutil, "datetime", _Pre311Datetime)
