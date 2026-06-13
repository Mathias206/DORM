"""Stub signal module for the extracted ORM.

Only ``setting_changed`` is wired for real dispatch; the request-related
signals are no-ops because the HTTP stack has been removed.
"""


class _Signal:
    def __init__(self):
        self._receivers = []  # list of (dispatch_uid, receiver)

    def connect(self, receiver, sender=None, weak=True, dispatch_uid=None):
        if dispatch_uid is None:
            dispatch_uid = receiver
        self._receivers.append((dispatch_uid, receiver))

    def disconnect(self, receiver=None, sender=None, dispatch_uid=None):
        key = dispatch_uid if dispatch_uid is not None else receiver
        for i, (uid, rec) in enumerate(self._receivers):
            if uid == key or rec == key:
                self._receivers.pop(i)
                return True
        return False

    def send(self, sender, **named):
        responses = []
        for _uid, receiver in self._receivers:
            responses.append((receiver, receiver(sender=sender, **named)))
        return responses

    def send_robust(self, sender, **named):
        responses = []
        for _uid, receiver in self._receivers:
            try:
                responses.append((receiver, receiver(sender=sender, **named)))
            except Exception as err:
                responses.append((receiver, err))
        return responses

    def has_listeners(self, sender=None):
        return bool(self._receivers)


# Request/connection signals are kept as no-ops for the ORM extraction.
class _NoOpSignal:
    def __init__(self):
        self._receivers = []

    def connect(self, receiver, sender=None, weak=True, dispatch_uid=None):
        self._receivers.append(receiver)

    def disconnect(self, receiver=None, sender=None, dispatch_uid=None):
        return False

    def send(self, sender, **named):
        return []

    def send_robust(self, sender, **named):
        return []

    def has_listeners(self, sender=None):
        return False


request_started = _NoOpSignal()
request_finished = _NoOpSignal()
got_request_exception = _NoOpSignal()
connection_created = _NoOpSignal()
setting_changed = _Signal()
