import sys
from importlib import import_module, invalidate_caches
from select import PIPE_BUF


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print('usage: MODULE ACTOR')
        exit(10)
    mod = import_module(sys.argv[1])
    actor = getattr(mod, sys.argv[2])
    print(actor)
