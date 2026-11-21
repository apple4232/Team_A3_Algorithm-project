"""Export the saved-results viewer as a static site.

Run from the project root: python3 -m demo.export_static OUTPUT_DIRECTORY
"""
import json
from pathlib import Path
import shutil
import sys

from demo.__main__ import ALGORITHMS, DATA, Dataset, STATIC


def export(output):
    output = Path(output)
    for split in ('dev', 'eval'):
        for mode in ('candidate', 'request'):
            for suffix in ('', '-additional'):
                path = DATA / f'{split}-{mode}{suffix}.jsonl'
                if not path.is_file():
                    raise FileNotFoundError(f'실험 데이터가 없습니다: {path}')
    dataset = Dataset()
    for mode, records in dataset.rows.items():
        for task_id in dataset.tasks:
            if set(records.get(task_id, {}).get('results', {})) != set(ALGORITHMS):
                raise ValueError(f'실험 결과 누락: {task_id} / {mode}')
    output.mkdir(parents=True, exist_ok=False)
    data_dir = output / 'data'
    data_dir.mkdir()
    for name in ('app.js', 'style.css', 'static_api.js'):
        shutil.copyfile(STATIC / name, output / name)
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    html = html.replace('<script src="/app.js" defer></script>', '<script src="/static_api.js" defer></script>\n  <script src="/app.js" defer></script>')
    html = html.replace('LOCAL DEMO', 'SAVED RESULTS').replace('재계산하면 이번 측정 결과를 보여줍니다.', '미리 계산한 실험 결과를 표시합니다.')
    (output / 'index.html').write_text(html, encoding='utf-8')
    (data_dir / 'tasks.json').write_text(json.dumps(list(dataset.tasks.values()), ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    for mode in ('request', 'candidate'):
        for split in ('dev', 'eval'):
            seeds = sorted({t['seed'] for t in dataset.tasks.values() if t['split'] == split})
            summary = {}
            for seed in seeds:
                selected = [t for t in dataset.tasks.values() if t['split'] == split and t['seed'] == seed]
                details = {t['id']: dataset.detail(t['id'], mode) for t in selected}
                for task_id, detail in details.items():
                    summary[task_id] = [{key: row[key] for key in ('algorithm', 'status', 'budget_exceeded', 'distance', 'seconds')} for row in detail['results']]
                (data_dir / f'{split}-{mode}-{seed}.json').write_text(json.dumps(details, ensure_ascii=False, allow_nan=False, separators=(',', ':')), encoding='utf-8')
                print(f'{split} {mode} {seed}: {len(details)}개 작업', flush=True)
            (data_dir / f'{split}-{mode}-summary.json').write_text(json.dumps(summary, ensure_ascii=False, allow_nan=False, separators=(',', ':')), encoding='utf-8')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('사용법: python3 -m demo.export_static OUTPUT_DIRECTORY')
    export(sys.argv[1])
