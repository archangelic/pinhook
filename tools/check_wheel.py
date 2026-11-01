"""Check that a built wheel holds every module in the source tree, and py.typed.

    python tools/check_wheel.py dist/pinhook-2.0.0-py3-none-any.whl
"""
import pathlib
import sys
import zipfile


def main(wheel):
    inside = set(zipfile.ZipFile(wheel).namelist())
    wanted = {path.as_posix() for path in pathlib.Path('pinhook').rglob('*.py')}
    wanted.add('pinhook/py.typed')
    missing = sorted(wanted - inside)
    for name in missing:
        print('{} is missing {}'.format(wheel, name))
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
