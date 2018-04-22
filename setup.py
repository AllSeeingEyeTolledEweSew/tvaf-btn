# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.

from __future__ import with_statement

from setuptools import setup, find_packages

with open("README") as readme:
    documentation = readme.read()

setup(
    name="tvaf",
    version="0.0.1",
    description="Tools for filling a Plex server with private tracker metadata",
    long_description=documentation,
    author="AllSeeingEyeTolledEweSew",
    author_email="allseeingeyetolledewesew@protonmail.com",
    url="http://github.com/AllSeeingEyeTolledEweSew/tvaf",
    license="Unlicense",
    packages=find_packages(),
    use_2to3=True,
    use_2to3_exclude_fixers=[
        "lib2to3.fixes.fix_import",
    ],
    install_requires=[
        "btn>=0.1.2",
        "promise>=2.1",
    ],
    entry_points={
        "console_scripts": [
            "tvaf_btn_sync = tvaf.cli.btn_sync:main",
            "tvaf_btn_config = tvaf.cli.btn_config:main",
            "tvaf_plex_media_scanner_shim_wrapper = tvaf.cli.plex_media_scanner_shim_wrapper:main",
            "tvaf_plex_media_scanner_shim = tvaf.cli.plex_media_scanner_shim:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: End Users/Desktop",
        "License :: Public Domain",
        "Programming Language :: Python",
        "Topic :: Communications :: File Sharing",
        "Topic :: Database",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Networking",
        "Operating System :: OS Independent",
    ],
)
