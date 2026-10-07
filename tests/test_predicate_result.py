import unittest
from oracle.predicate_result import scalar_predicate_result


class PredicateResultTests(unittest.TestCase):
    def test_empty_and_null(self):
        self.assertIsNone(scalar_predicate_result('[]', 'all-null first'))
        self.assertIsNone(scalar_predicate_result('[{"val": null}]', 'all-null median'))

    def test_values(self):
        self.assertEqual(scalar_predicate_result('[{"val": 0}]', 'zero'), 0)
        self.assertEqual(scalar_predicate_result('[{"val": ""}]', 'empty-string'), '')
        self.assertEqual(scalar_predicate_result('[{"val": 17}]', 'integer'), 17)

    def test_bad_response_context(self):
        for payload in ['oops', '{}', '[{"other": 1}]', '[{"val": 1}, {"val": 2}]']:
            with self.assertRaisesRegex(RuntimeError, 'test-key'):
                scalar_predicate_result(payload, 'test-key')


if __name__ == '__main__':
    unittest.main()
