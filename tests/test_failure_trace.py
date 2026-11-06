import json
import unittest
from workbench.failure_trace import failure_trace


class FailureTraceTests(unittest.TestCase):
    def test_wrapped_error_keeps_location_without_sensitive_values(self):
        try:
            try:
                raise PermissionError(13, 'private arbitrary credential value', 'private path')
            except PermissionError as original:
                raise RuntimeError('private prompt and response') from original
        except RuntimeError as wrapped:
            result = failure_trace(wrapped)
        self.assertEqual(result['type'], 'RuntimeError')
        self.assertEqual(result['cause']['type'], 'PermissionError')
        self.assertEqual(result['cause']['errno'], 13)
        self.assertTrue(result['cause']['frames'])
        encoded = json.dumps(result)
        self.assertNotIn('private', encoded)
        self.assertNotIn('PermissionError(13', encoded)

    def test_exception_group_preserves_each_cause_type(self):
        group = ExceptionGroup('secret group text', [ValueError('secret'), OSError('secret')])
        result = failure_trace(group)
        self.assertEqual([e['type'] for e in result['exceptions']], ['ValueError', 'OSError'])
        self.assertNotIn('secret', json.dumps(result))
