#!/usr/bin/env python3
"""Wrapper: 在 thymio_control 路径下调用原始 thymio_tobii/wsl_tobii_bridge.py。"""

import runpy
import os
import sys


def main():
    script = os.path.join(os.getcwd(), 'thymio_tobii', 'wsl_tobii_bridge.py')
    if not os.path.exists(script):
        print('Error: source script not found:', script)
        sys.exit(1)
    runpy.run_path(script, run_name='__main__')


if __name__ == '__main__':
    main()
