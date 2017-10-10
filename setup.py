#!/usr/bin/env python3
from setuptools import setup

setup(
    name='pinhook',
    version='0.2.0',
    license="MIT",
    description="A pluggable IRC bot framework in Python",
    install_requires=[
        'irc',
    ],
    packages=[
        'pinhook',
    ]
)
