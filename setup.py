# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.

import distutils.cmd
import subprocess

import setuptools


class FormatCommand(distutils.cmd.Command):

    description = "Run autoflake and yapf on python source files"
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run_isort(self):
        subprocess.check_call(["isort", "-rc", "-y"])

    def run_yapf(self):
        subprocess.check_call(["yapf", "-i", "-r", "--style=google", "."])

    def run_autoflake(self):
        subprocess.check_call([
            "autoflake", "-i", "-r", "--remove-all-unused-imports",
            "--remove-duplicate-keys", "--remove-unused-variables", "."
        ])

    def run(self):
        self.run_isort()
        self.run_yapf()
        self.run_autoflake()


class LintCommand(distutils.cmd.Command):

    description = "Run autoflake and yapf on python source files"
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run_mypy(self):
        subprocess.check_call(["mypy", "tvaf"])

    def run(self):
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
        "intervaltree>=3.0.2",
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
