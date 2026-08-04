# The spec runner. stdlib only, no framework.
#
# A spec file is tests/spec_*.py; a spec is a zero-argument function in it whose
# name starts with 'spec_'. Function names carry the SPEC id they pin
# (e.g. spec_G7_entry_never_rearms_while_lot_unexited), which is how docs/SPEC.md's
# `test:` column and the suite stay one vocabulary (T1, T5).
#
# Usage:  python3 tests/run.py            # every spec file
#         python3 tests/run.py spec_foo   # one file
# Exit code 0 iff every spec passed. A spec fails by raising; AssertionError or
# otherwise — an error IS a failure, never a skip.

import importlib.util
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # make `gridgremlin` importable


def _load(path):
    module_spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def main(argv):
    if argv:
        files = [HERE / (name if name.endswith('.py') else name + '.py') for name in argv]
        missing = [str(f) for f in files if not f.exists()]
        if missing:
            print('no such spec file: ' + ', '.join(missing))
            return 2
    else:
        files = sorted(HERE.glob('spec_*.py'))

    ran = failed = 0
    start = time.monotonic()
    for path in files:
        try:
            module = _load(path)
        except Exception:
            print(f'FAIL {path.name} (import)')
            traceback.print_exc()
            failed += 1
            ran += 1
            continue
        specs = [name for name in sorted(dir(module))
                 if name.startswith('spec_') and callable(getattr(module, name))]
        for name in specs:
            ran += 1
            try:
                getattr(module, name)()
            except Exception:
                failed += 1
                print(f'FAIL {path.name}::{name}')
                traceback.print_exc()

    elapsed = time.monotonic() - start
    print(f'{ran} specs, {failed} failed ({elapsed:.2f}s)')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
