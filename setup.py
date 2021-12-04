# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from os import path

from setuptools import find_packages, setup

CLASSIFIERS = [
    'License :: OSI Approved :: BSD License',
    'Framework :: Django',
    "Operating System :: MacOS",
    "Operating System :: POSIX :: Linux",
    "Operating System :: Microsoft :: Windows",
    'Programming Language :: Python',
    'Programming Language :: Python :: 3.8',
    'Programming Language :: Python :: 3.9',
    'Framework :: Django :: 3.2',
    'Framework :: Django :: 4.0',
]

this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='django-mssql-arm',
    version='0.1',
    description='Django backend for Microsoft SQL Server',
    long_description=long_description,
    long_description_content_type='django-mssql-arm',
    author='tede12',
    url='https://github.com/tede12/django_mssql_arm',
    license='BSD',
    packages=find_packages(),
    install_requires=[
        'django>=3.2,<4.1',
        'pymssql==2.2.2',
        'pytz',
        'six',
    ],
    package_data={'mssql_arm': ['regex_clr.dll']},
    classifiers=CLASSIFIERS,
    keywords='django',
)
