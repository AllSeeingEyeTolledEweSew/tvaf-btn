# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.

import importlib


def name_to_global(name):
    split = name.rsplit(".", 1)
    if len(split) < 2:
        raise ValueError("%r not a valid global name" % name)
    module_name, function_name = split
    return getattr(importlib.import_module(module_name), function_name)


def global_to_name(obj):
    module = importlib.import_module(obj.__module__)
    if getattr(module, obj.__name__, None) is not obj:
        raise ValueError("%r not a global" % obj)
    return "%s.%s" % (obj.__module__, obj.__name__)
