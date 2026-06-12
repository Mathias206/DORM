"""Stub signal module for the extracted ORM.

These signals are kept as no-op objects so that code importing or connecting
to them continues to work. Sends are no-ops.
"""


class _Signal:
    def __init__(self):
        self._receivers = []

    def connect(self, receiver, sender=None, weak=True, dispatch_uid=None):
        self._receivers.append(receiver)

    def disconnect(self, receiver=None, sender=None, dispatch_uid=None):
        pass

    def send(self, sender, **named):
        return []

    def send_robust(self, sender, **named):
        return []

    def has_listeners(self, sender=None):
        return False


request_started = _Signal()
request_finished = _Signal()
got_request_exception = _Signal()
connection_created = _Signal()
setting_changed = _Signal()
