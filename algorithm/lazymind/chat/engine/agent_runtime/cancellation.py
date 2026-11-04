from __future__ import annotations

import json
from asyncio import CancelledError


class UserCancelledError(CancelledError):
    """The active Agent run was explicitly stopped by the user."""


class ExecutionCancelledError(CancelledError):
    """One exact fenced Workflow execution must stop without implying user intent."""


def _execution_cancel_sid(sid: str, execution=None) -> str:
    value = execution if isinstance(execution, dict) else {}
    attempt_id = str(value.get('attempt_id') or '').strip()
    generation = str(value.get('generation') or '').strip()
    if not attempt_id or not generation:
        return ''
    return f'{sid}:workflow-execution:{attempt_id}:{generation}'


def request_cancel(sid: str, *, execution=None, reason: str = 'user') -> None:
    """Signal a whole run or one fenced Workflow execution."""
    import lazyllm
    from lazyllm.common.queue import FileSystemQueue

    target_sid = _execution_cancel_sid(sid, execution) or sid
    with lazyllm.globals._bind_sid(target_sid):
        FileSystemQueue(klass='cancel').enqueue(json.dumps({
            'tag': 'cancel', 'reason': reason,
        }))


def make_cancel_stop_condition(*, sid: str = '', execution=None):
    """Stop on user cancellation or cancellation of this exact execution."""
    import lazyllm

    run_sid = str(sid or lazyllm.globals._sid)
    if execution is None:
        config = lazyllm.globals.get('agentic_config') or {}
        execution = config.get('_workspace_execution')
    execution_sid = _execution_cancel_sid(run_sid, execution)

    def _check(_output) -> bool:
        try:
            from lazyllm.common.queue import FileSystemQueue
            scopes = [value for value in (execution_sid, run_sid) if value]
            for scope in dict.fromkeys(scopes):
                with lazyllm.globals._bind_sid(scope):
                    messages = FileSystemQueue(klass='cancel').dequeue() or []
                for raw in messages:
                    try:
                        message = json.loads(raw)
                    except (ValueError, TypeError):
                        continue
                    if message.get('tag') != 'cancel':
                        continue
                    reason = str(message.get('reason') or 'user')
                    if reason == 'lease_lost':
                        raise ExecutionCancelledError('executor lease lost')
                    if reason == 'execution_timeout':
                        raise ExecutionCancelledError('workflow execution timed out')
                    raise UserCancelledError('stopped by user')
        except (UserCancelledError, ExecutionCancelledError):
            raise
        except Exception:
            pass
        return False

    return _check
