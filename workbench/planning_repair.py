"""Bounded, redacted field feedback for a structured planning retry."""
import json
from pydantic import ValidationError
from .settings import redact


def repair_context(error, output_type, include_previous):
    previous = getattr(error, 'invalid_output', None)
    if previous is not None and not isinstance(previous, str):
        previous = json.dumps(previous, ensure_ascii=False, default=str)
    rows = []
    if previous and len(previous) <= 1000000:
        try:
            output_type.model_validate_json(previous)
        except ValidationError as invalid:
            for item in invalid.errors(include_url=False, include_context=False, include_input=False)[:32]:
                location = '.'.join(str(v) for v in item['loc']) or 'design'
                message = item['msg']
                if item['type'] == 'json_invalid':message = message[:1].lower() + message[1:]
                rows.append(location + ' [' + item['type'] + ']: ' + message)
    feedback = '\n'.join(rows) or str(getattr(error, 'validation_feedback', str(error)))
    # Invalid inputs can contain arbitrary long drafts. Field paths and error
    # messages give the planner actionable feedback without duplicating them.
    return redact(feedback)[:6000], redact(previous) if include_previous and previous else None
