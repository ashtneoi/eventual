#!/usr/bin/env python3

import importlib

z = importlib.import_module('z')
print(z.a, z.b)
input('modify z.py')
z = importlib.import_module('z')
importlib.reload(z)
print(z.a, z.b)
