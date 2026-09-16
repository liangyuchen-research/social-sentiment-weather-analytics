"""Validate Python syntax, notebook code, and deployment documents offline."""
import ast
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    count = 0
    for directory in ('backend', 'database', 'frontend', 'installation', 'scripts', 'test'):
        for path in sorted((ROOT / directory).rglob('*')):
            if not path.is_file() or any(part in {'__pycache__', '.build', 'build', '.fission_build'} for part in path.parts):
                continue
            if path.suffix == '.py':
                ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path.relative_to(ROOT)))
            elif path.suffix == '.ipynb':
                notebook = json.loads(path.read_text(encoding='utf-8-sig'))
                for i, cell in enumerate(notebook['cells']):
                    if cell['cell_type'] == 'code':
                        ast.parse(''.join(cell['source']), filename=f'{path.name}:cell-{i + 1}')
            elif path.suffix == '.json':
                json.loads(path.read_text(encoding='utf-8-sig'))
            elif path.suffix in {'.yaml', '.yml'}:
                yaml.safe_load(path.read_text(encoding='utf-8-sig'))
            else:
                continue
            count += 1
    print(f'Validated {count} source, notebook, mapping, and deployment files.')


if __name__ == '__main__':
    main()
