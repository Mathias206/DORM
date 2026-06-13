import functools
import os

import dorm


@functools.cache
def django_file_prefixes():
    file = getattr(dorm, "__file__", None)
    if file is None:
        return ()
    return (os.path.join(os.path.dirname(file), ""),)
