import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from demo import export_static


class StaticExportTests(unittest.TestCase):
    def test_export_fails_on_missing_data_and_exports_complete_rows(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / 'data'
            data.mkdir()
            output = root / 'public'
            with patch.object(export_static, 'DATA', data):
                with self.assertRaises(FileNotFoundError):
                    export_static.export(output)
                self.assertFalse(output.exists())
                for split in ('dev', 'eval'):
                    for mode in ('candidate', 'request'):
                        for suffix in ('', '-additional'):
                            (data / f'{split}-{mode}{suffix}.jsonl').touch()
                class FakeDataset:
                    tasks = {'101:3:clustered:0': {'id': '101:3:clustered:0', 'split': 'eval', 'seed': 101}}
                    rows = {mode: {'101:3:clustered:0': {'results': {'nn': {}}}} for mode in ('candidate', 'request')}
                    def detail(self, task_id, mode):
                        return {'task': self.tasks[task_id], 'results': [{'algorithm': 'nn', 'status': 'completed', 'budget_exceeded': False, 'distance': 5, 'seconds': .1, 'path': [[0, 0], [4, 0]]}]}
                with patch.object(export_static, 'Dataset', FakeDataset), patch.object(export_static, 'ALGORITHMS', ('nn',)):
                    export_static.export(output)
                details = json.loads((output / 'data/eval-request-101.json').read_text())
                summary = json.loads((output / 'data/eval-request-summary.json').read_text())
                self.assertEqual(details['101:3:clustered:0']['results'][0]['path'], [[0, 0], [4, 0]])
                self.assertEqual(summary['101:3:clustered:0'][0]['distance'], 5)
                self.assertNotIn('path', summary['101:3:clustered:0'][0])
                self.assertIn('/static_api.js', (output / 'index.html').read_text())
                with self.assertRaises(FileExistsError):
                    with patch.object(export_static, 'Dataset', FakeDataset), patch.object(export_static, 'ALGORITHMS', ('nn',)):
                        export_static.export(output)


if __name__ == '__main__':
    unittest.main()
