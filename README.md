# Django database backend for MSSQL working for ARM architecture

*django-mssql-arm* is a fork of [mssql-django](https://github.com/microsoft/mssql-django). This project is the official
Microsoft SQL Server 3rd Party Backend for Django that provides a connectivity layer for Django on SQL Server or Azure
SQL DB.

## Goals

django-mssql-arm is a Django database backend for Microsoft SQL Server.

It's a small wrapper that uses [pymssql](https://github.com/pymssql/pymssql) to connect to SQL Server. pymssql is simple
database interface for Python that builds on top of FreeTDS
avoiding [ODBC](https://docs.microsoft.com/it-it/sql/connect/odbc/download-odbc-driver-for-sql-server) driver that is
not supported by ARM devices.

The original use case was to connect to SQL Server from a Django project written in Python 3 and running on macOS
with [Apple Silicon](https://support.apple.com/it-it/HT211814).

## Features

- Supports Django >= 3.2
- Tested on Microsoft SQL Server 2019

## Dependencies

- Tested version

| Python Version | Platforms          | Status | Notes          |
|---------|--------------------|--------|----------------|
| 3.9.7   | macOS(arm64)       |   ✅   | pymssql==2.2.2 |
| 3.9.7   | macOS(x86_64)      |   ✅   | pymssql==2.1.5 |
| 3.9.7   | Windows 10(x86_64) |   ✅   | pymssql==2.2.2 |

## Installation

1. Clone the repo 
        
        git clone 'https://github.com/tede12/django-mssql-arm'
2. Install pymssql (check [Dependencies](#Dependencies) for the right version) and Django 
3. Set the `ENGINE` setting in the `settings.py` file used by your Django application or project to `'mssql_arm'`:

       'ENGINE': 'mssql_arm'

## Configuration

### Standard Django settings

The following entries in a database-level settings dictionary in DATABASES control the behavior of the backend:

- ENGINE

  String. It must be `"mssql_arm"`.

- NAME

  String. Database name. Required.

- HOST

  String. SQL Server instance in `"server\instance"` format.

- PORT

  String. Server instance port. An empty string means the default port.

- USER

  String. Database username in `"user"` format. If not given then MS Integrated Security will be used.

- PASSWORD

  String. Database user password.

- AUTOCOMMIT

  Boolean. Set this to `False` if you want to disable Django's transaction management and implement your own.


and the following entries are also available in the `TEST` dictionary for any given database-level settings dictionary:

- NAME

  String. The name of database to use when running the test suite. If the default value (`None`) is used, the test
  database will use the name `"test_" + NAME`.


### OPTIONS

Dictionary. Current available keys are:

- connection_timeout

  Integer. Sets the timeout in seconds for the database connection process. Default value is ``0`` which disables the
  timeout.

- connection_retries

  Integer. Sets the times to retry the database connection process. Default value is ``5``.

- connection_retry_backoff_time

  Integer. Sets the back off time in seconds for retries of the database connection process. Default value is ``5``.

- query_timeout

  Integer. Sets the timeout in seconds for the database query. Default value is ``0`` which disables the timeout.


### Example

Here is an example of the database settings:

```python
DATABASES = {
    'default': {
        'ENGINE': 'mssql_arm',
        'NAME': 'my_db',
        'USER': 'user@myserver',
        'PASSWORD': 'password',
        'HOST': 'my_server.database.windows.net',
        'PORT': '1433',

        'OPTIONS': {},
    },
}
```

## Fields
To facilitate the use of some types, some fields have been added or replaced.

- AutoDecimalField ``decimal(%(max_digits)s, %(decimal_places)s) IDENTITY (1, 1)``
- BigForeignKey
- DateField ``date``
- DateTimeField ``datetime2``
- DateTimeOffsetField ``datetimeoffset``
- LegacyTimeField ``time``
- LegacyDateField ``datetime``
- LegacyDateTimeField ``datetime``
- NCharField ``nchar(%(max_length)s)``
- TimeField ``time``

### Example use of new fields
```python
from mssql_arm.fields import NCharField
from django.db.models import Model

class NCharFieldModel(Model):
    val = NCharField(max_length=8)

NCharField.objcets.create(val='a')
```


## Limitations

The following features are currently not fully supported:

- Altering a model field from or to AutoField at migration
- Django annotate functions have floating point arithmetic problems in some cases
- Annotate function with exists
- Exists function in order_by
- Right-hand power and arithmetic with datatimes
- Timezones, timedeltas not fully supported
- Rename field/model with foreign key constraint
- Database level constraints
- Math degrees power or radians
- Bit-shift operators
- Filtered index
- Date extract function
- Hashing functions

JSONField lookups have limitations, more details [here](https://github.com/microsoft/mssql-django/wiki/JSONField).



