from __future__ import annotations

import json

import pytest

from lazymind.chat.engine.agent_runtime.cancellation import (
    ExecutionCancelledError,
    UserCancelledError,
    make_cancel_stop_condition,
    request_cancel,
)


def test_user_cancel_signal_raises_domain_cancellation(monkeypatch):
    from lazyllm.common import queue as queue_module

    class FakeQueue:
        def __init__(self, *, klass):
            assert klass == 'cancel'

        def dequeue(self):
            return [json.dumps({'tag': 'cancel'})]

    monkeypatch.setattr(queue_module, 'FileSystemQueue', FakeQueue)

    with pytest.raises(UserCancelledError, match='stopped by user'):
        make_cancel_stop_condition()(None)


def test_non_user_queue_failure_does_not_cancel(monkeypatch):
    from lazyllm.common import queue as queue_module

    class BrokenQueue:
        def __init__(self, *, klass):
            assert klass == 'cancel'

        def dequeue(self):
            raise RuntimeError('state unavailable')

    monkeypatch.setattr(queue_module, 'FileSystemQueue', BrokenQueue)

    assert make_cancel_stop_condition()(None) is False


def test_execution_cancel_is_scoped_to_attempt_generation(monkeypatch):
    import lazyllm
    from lazyllm.common import queue as queue_module

    messages = {}

    class FakeQueue:
        def __init__(self, *, klass):
            assert klass == 'cancel'
            self.sid = lazyllm.globals._sid

        def enqueue(self, value):
            messages.setdefault(self.sid, []).append(value)

        def dequeue(self):
            return messages.pop(self.sid, [])

    monkeypatch.setattr(queue_module, 'FileSystemQueue', FakeQueue)
    first = {'attempt_id': 'attempt-1', 'generation': '1'}
    replacement = {'attempt_id': 'attempt-1', 'generation': '2'}

    request_cancel('task-1', execution=first, reason='lease_lost')

    assert make_cancel_stop_condition(sid='task-1', execution=replacement)(None) is False
    with pytest.raises(ExecutionCancelledError, match='executor lease lost'):
        make_cancel_stop_condition(sid='task-1', execution=first)(None)
