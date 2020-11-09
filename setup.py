# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.

import distutils.cmd
import subprocess
from typing import List
from typing import Tuple

import setuptools


class FormatCommand(distutils.cmd.Command):

    description = "Run autoflake and yapf on python source files"
    user_options: List[Tuple] = []

    def initialize_options(self) -> None:
        pass

    def finalize_options(self) -> None:
        pass

    def run_isort(self) -> None:
        subprocess.check_call(["isort", "."])

    def run_autoflake(self) -> None:
        subprocess.check_call(
            [
                "autoflake",
                "-i",
                "-r",
                "--remove-all-unused-imports",
                "--remove-duplicate-keys",
                "--remove-unused-variables",
                ".",
            ]
        )

    def run_black(self) -> None:
        subprocess.check_call(["black", "."])

    def run(self) -> None:
        self.run_isort()
        self.run_autoflake()
        self.run_black()


class LintCommand(distutils.cmd.Command):

    description = "Run autoflake and yapf on python source files"
    user_options: List[Tuple] = []

    def initialize_options(self) -> None:
        pass

    def finalize_options(self) -> None:
        pass

    def run_mypy(self) -> None:
        subprocess.check_call(["mypy", "tvaf"])

    def run(self) -> None:
        self.run_mypy()


with open("README") as readme:
    documentation = readme.read()

setuptools.setup(
    name="tvaf",
    version="0.1.0",
    description="A video-on-demand system for private torrent trackers",
    long_description=documentation,
    author="AllSeeingEyeTolledEweSew",
    author_email="allseeingeyetolledewesew@protonmail.com",
    url="http://github.com/AllSeeingEyeTolledEweSew/tvaf",
    license="Unlicense",
    packages=setuptools.find_packages(),
    cmdclass={
        "format": FormatCommand,
        "lint": LintCommand,
    },
    test_suite="tvaf.tests",
    python_requires=">=3.7",
    install_requires=[
        "dataclasses-json>=0.3.7",
        "btn>=1.0.4",
    ],
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
