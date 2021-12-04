# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

"""
MS SQL Server database backend for Django.
"""
import os
import re
import sys
import time
import warnings

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_ipv46_address
from pymssql._mssql import MSSQLDatabaseException

try:
    # import pyodbc as Database
    import pymssql as Database  # noqa
except ImportError as e:
    raise ImproperlyConfigured("Error loading pyodbc module: %s" % e)

from django.utils.version import get_version_tuple  # noqa

PYMSSQL_VERSION = tuple(map(int, Database.__version__.split('.')))
if PYMSSQL_VERSION < (2, 2, 2):
    raise ImproperlyConfigured("pymssql 2.2.2 or newer is required; you have %s" % Database.__version__)

from django.conf import settings  # noqa
from django.db import NotSupportedError  # noqa
from django.db.backends.base.base import BaseDatabaseWrapper  # noqa
from django.utils.encoding import smart_str  # noqa
from django.utils.functional import cached_property  # noqa


from .client import DatabaseClient  # noqa
from .creation import DatabaseCreation  # noqa
from .features import DatabaseFeatures  # noqa
from .introspection import DatabaseIntrospection  # noqa
from .operations import DatabaseOperations  # noqa
from .schema import DatabaseSchemaEditor  # noqa

EDITION_AZURE_SQL_DB = 5
auto_field_types = {'AutoField', 'BigAutoField', 'AutoDecimalField'}


def encode_connection_string(fields):
    """Encode dictionary of keys and values as an ODBC connection String.

    See [MS-ODBCSTR] document:
    https://msdn.microsoft.com/en-us/library/ee208909%28v=sql.105%29.aspx
    """
    # As the keys are all provided by us, don't need to encode them as we know
    # they are ok.
    return ';'.join(
        '%s=%s' % (k, encode_value(v))
        for k, v in fields.items()
    )


def encode_value(v):
    """If the value contains a semicolon, or starts with a left curly brace,
    then enclose it in curly braces and escape all right curly braces.
    """
    if ';' in v or v.strip(' ').startswith('{'):
        return '{%s}' % (v.replace('}', '}}'),)
    return v


class DatabaseWrapper(BaseDatabaseWrapper):
    vendor = 'microsoft'
    display_name = 'SQL Server'
    # This dictionary maps Field objects to their associated MS SQL column
    # types, as strings. Column-type strings can contain format strings; they'll
    # be interpolated against the values of Field.__dict__ before being output.
    # If a column type is set to None, it won't be included in the output.
    data_types = {
        # single # is an addition, # with comment is a possible substitution
        'AutoDecimalField': 'decimal(%(max_digits)s, %(decimal_places)s)',  #
        'AutoField': 'int',  # 'int IDENTITY (1, 1)',
        'BigAutoField': 'bigint',  # 'bigint IDENTITY (1, 1)',
        'BigIntegerField': 'bigint',
        'BinaryField': 'varbinary(%(max_length)s)',  # 'varbinary(max)',
        'BooleanField': 'bit',
        'CharField': 'nvarchar(%(max_length)s)',
        'CommaSeparatedIntegerField': 'nvarchar(%(max_length)s)',  #
        'DateField': 'date',
        'DateTimeField': 'datetime2',
        'DateTimeOffsetField': 'datetimeoffset',  #
        'DecimalField': 'numeric(%(max_digits)s, %(decimal_places)s)',  # 'decimal(%(max_digits)s, %(decimal_places)s)',
        'DurationField': 'bigint',
        'FileField': 'nvarchar(%(max_length)s)',
        'FilePathField': 'nvarchar(%(max_length)s)',
        'FloatField': 'double precision',
        'IntegerField': 'int',
        'IPAddressField': 'nvarchar(15)',
        'LegacyDateField': 'datetime',  #
        'LegacyDateTimeField': 'datetime',  #
        'LegacyTimeField': 'time',  #
        'GenericIPAddressField': 'nvarchar(39)',
        'JSONField': 'nvarchar(max)',
        'NCharField': 'nchar(%(max_length)s)',  #
        'NewDateField': 'date',  #
        'NewDateTimeField': 'datetime2',  #
        'NewTimeField': 'time',  #
        'NullBooleanField': 'bit',
        'OneToOneField': 'int',
        'PositiveIntegerField': 'int',
        'PositiveSmallIntegerField': 'smallint',
        'PositiveBigIntegerField': 'bigint',
        'SlugField': 'nvarchar(%(max_length)s)',
        'SmallAutoField': 'smallint',
        'SmallIntegerField': 'smallint',
        'TextField': 'nvarchar(max)',
        'TimeField': 'time',
        'URLField': 'nvarchar(%(max_length)s)',  #
        'UUIDField': 'char(32)',  # uniqueidentifier
    }

    data_types_suffix = {
        'AutoDecimalField': 'IDENTITY (1, 1)',  #
        'AutoField': 'IDENTITY (1, 1)',
        'BigAutoField': 'IDENTITY (1, 1)',
        'SmallAutoField': 'IDENTITY (1, 1)',
    }
    data_type_check_constraints = {
        'JSONField': '(ISJSON ("%(column)s") = 1)',
        'PositiveIntegerField': '[%(column)s] >= 0',
        'PositiveSmallIntegerField': '[%(column)s] >= 0',
        'PositiveBigIntegerField': '[%(column)s] >= 0',
    }
    operators = {
        # Since '=' is used not only for string comparision there is no way
        # to make it case (in)sensitive.
        'exact': '= %s',
        'iexact': "= UPPER(%s)",
        'contains': "LIKE %s ESCAPE '\\'",
        'icontains': "LIKE UPPER(%s) ESCAPE '\\'",
        'gt': '> %s',
        'gte': '>= %s',
        'lt': '< %s',
        'lte': '<= %s',
        'startswith': "LIKE %s ESCAPE '\\'",
        'endswith': "LIKE %s ESCAPE '\\'",
        'istartswith': "LIKE UPPER(%s) ESCAPE '\\'",
        'iendswith': "LIKE UPPER(%s) ESCAPE '\\'",
    }

    # The patterns below are used to generate SQL pattern lookup clauses when
    # the right-hand side of the lookup isn't a raw string (it might be an expression
    # or the result of a bilateral transformation).
    # In those cases, special characters for LIKE operators (e.g. \, *, _) should be
    # escaped on database side.
    #
    # Note: we use str.format() here for readability as '%' is used as a wildcard for
    # the LIKE operator.
    pattern_esc = r"REPLACE(REPLACE(REPLACE({}, '\', '[\]'), '%%', '[%%]'), '_', '[_]')"
    pattern_ops = {
        'contains': "LIKE '%%' + {} + '%%'",
        'icontains': "LIKE '%%' + UPPER({}) + '%%'",
        'startswith': "LIKE {} + '%%'",
        'istartswith': "LIKE UPPER({}) + '%%'",
        'endswith': "LIKE '%%' + {}",
        'iendswith': "LIKE '%%' + UPPER({})",
    }

    Database = Database
    SchemaEditorClass = DatabaseSchemaEditor
    # Classes instantiated in __init__().
    client_class = DatabaseClient
    creation_class = DatabaseCreation
    features_class = DatabaseFeatures
    introspection_class = DatabaseIntrospection
    ops_class = DatabaseOperations

    _codes_for_networkerror = (
        '08S01',
        '08S02',
    )
    _sql_server_versions = {
        9: 2005,
        10: 2008,
        11: 2012,
        12: 2014,
        13: 2016,
        14: 2017,
        15: 2019,
    }

    # https://azure.microsoft.com/en-us/documentation/articles/sql-database-develop-csharp-retry-windows/
    _transient_error_numbers = (
        '4060',
        '10928',
        '10929',
        '40197',
        '40501',
        '40613',
        '49918',
        '49919',
        '49920',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_sql_azure = False

        opts = self.settings_dict["OPTIONS"]

        # capability for multiple result sets or cursors
        self.supports_mars = False

        # Some drivers need unicode encoded as UTF8. If this is left as
        # None, it will be determined based on the driver, namely it'll be
        # False if the driver is a windows driver and True otherwise.
        #
        # However, recent versions of FreeTDS and pyodbc (0.91 and 3.0.6 as
        # of writing) are perfectly okay being fed unicode, which is why
        # this option is configurable.
        if 'driver_needs_utf8' in opts:
            self.driver_charset = 'utf-8'
        else:
            self.driver_charset = opts.get('driver_charset', None)

        # interval to wait for recovery from network error
        interval = opts.get('connection_recovery_interval_msec', 0.0)
        self.connection_recovery_interval_msec = float(interval) / 1000

        # make lookup operators to be collation-sensitive if needed
        collation = opts.get('collation', None)
        if collation:
            self.operators = dict(self.__class__.operators)
            ops = {}
            for op in self.operators:
                sql = self.operators[op]
                if sql.startswith('LIKE '):
                    ops[op] = '%s COLLATE %s' % (sql, collation)
            self.operators.update(ops)

    def create_cursor(self, name=None):
        return CursorWrapper(self.connection.cursor(), self)

    def _cursor(self):
        new_conn = False

        if self.connection is None:
            new_conn = True

        conn = super()._cursor()
        if new_conn:
            if self.sql_server_version <= 2005:
                self.data_types['DateField'] = 'datetime'
                self.data_types['DateTimeField'] = 'datetime'
                self.data_types['TimeField'] = 'datetime'

        return conn

    def get_connection_params(self):
        settings_dict = self.settings_dict
        if settings_dict['NAME'] == '':
            raise ImproperlyConfigured(
                "settings.DATABASES is improperly configured. "
                "Please supply the NAME value.")
        conn_params = settings_dict.copy()
        if conn_params['NAME'] is None:
            conn_params['NAME'] = 'master'
        return conn_params

    def get_new_connection(self, conn_params):
        """
        # pymssql connection
        :param conn_params: => {
            'host': 'localhost',
            'port': 1433,
            'database': 'master',
            'user': 'sa',
            'password': 'MyPass@word',
            'timeout': 0,
            'autocommit': False
        }
        """
        database = conn_params['NAME']
        host = conn_params.get('HOST', 'localhost')
        user = conn_params.get('USER', None)
        password = conn_params.get('PASSWORD', None)
        port = conn_params.get('PORT', None)
        trusted_connection = conn_params.get('Trusted_Connection', 'yes')

        # validation
        if isinstance(database, str) and database == "":
            raise ImproperlyConfigured(
                "settings.DATABASES is improperly configured. "
                "Please supply the NAME value.")
        if not database:
            raise ImproperlyConfigured("You need to specify a DATABASE NAME in your Django settings file.")

        try:
            if host == 'localhost':
                host = '127.0.0.1'
            validate_ipv46_address(host)
        except ValidationError:
            raise ImproperlyConfigured("When using DATABASE PORT, DATABASE HOST must be an IP address.")

        try:
            port = int(port)
        except ValueError:
            raise ImproperlyConfigured("DATABASE PORT must be a number.")

        options = conn_params.get('OPTIONS', {})
        driver = options.get('driver', 'ODBC Driver 17 for SQL Server')
        dsn = options.get('dsn', None)
        options_extra_params = options.get('extra_params', '')

        # Microsoft driver names assumed here are:
        # * SQL Server Native Client 10.0/11.0
        # * ODBC Driver 11/13 for SQL Server
        ms_drivers = re.compile('^ODBC Driver .* for SQL Server$|^SQL Server Native Client')

        # available ODBC connection string keywords:
        # (Microsoft drivers for Windows)
        # https://docs.microsoft.com/en-us/sql/relational-databases/native-client/applications/using-connection-string-keywords-with-sql-server-native-client
        # (Microsoft drivers for Linux/Mac)
        # https://docs.microsoft.com/en-us/sql/connect/odbc/linux-mac/connection-string-keywords-and-data-source-names-dsns
        # (FreeTDS)
        # http://www.freetds.org/userguide/odbcconnattr.htm
        cstr_parts = {}
        if dsn:
            cstr_parts['DSN'] = dsn
        else:
            # Only append DRIVER if DATABASE_ODBC_DSN hasn't been set
            cstr_parts['DRIVER'] = driver

            if ms_drivers.match(driver):
                if port:
                    host = ','.join((host, str(port)))
                cstr_parts['SERVER'] = host
            elif options.get('host_is_server', False):
                if port:
                    cstr_parts['PORT'] = port
                cstr_parts['SERVER'] = host
            else:
                cstr_parts['SERVERNAME'] = host

        if user:
            cstr_parts['UID'] = user
            if 'Authentication=ActiveDirectoryInteractive' not in options_extra_params:
                cstr_parts['PWD'] = password
        else:
            if ms_drivers.match(driver) and 'Authentication=ActiveDirectoryMsi' not in options_extra_params:
                cstr_parts['Trusted_Connection'] = trusted_connection
            else:
                cstr_parts['Integrated Security'] = 'SSPI'

        cstr_parts['DATABASE'] = database

        if ms_drivers.match(driver) and os.name == 'nt':
            cstr_parts['MARS_Connection'] = 'yes'

        connstr = encode_connection_string(cstr_parts)

        # extra_params are glued on the end of the string without encoding,
        # so it's up to the settings writer to make sure they're appropriate -
        # use encode_connection_string if constructing from external input.
        if options.get('extra_params', None):
            connstr += ';' + options['extra_params']

        unicode_results = options.get('unicode_results', False)
        timeout = options.get('connection_timeout', 0)
        retries = options.get('connection_retries', 5)
        backoff_time = options.get('connection_retry_backoff_time', 5)
        query_timeout = options.get('query_timeout', 0)

        conn = None
        retry_count = 0
        need_to_retry = False
        while conn is None:
            try:
                # diff names
                conn_params['TIMEOUT'] = timeout
                conn_params['PORT'] = int(conn_params['PORT'])
                conn_params['DATABASE'] = conn_params['NAME']

                allowed_params = [
                    'HOST', 'PORT', 'DATABASE', 'USER', 'PASSWORD', 'TIMEOUT', 'AUTOCOMMIT'
                ]
                conn_params = {k.lower(): v for k, v in conn_params.items() if k.upper() in allowed_params}
                return Database.connect(**conn_params)

            except Exception as conn_error:
                for error_number in self._transient_error_numbers:
                    try:
                        err_no = conn_error.args[1]
                    except IndexError:
                        err_no = conn_error.args[0][1].decode()

                    if error_number in err_no:
                        if error_number in err_no and retry_count < retries:
                            time.sleep(backoff_time)
                            need_to_retry = True
                            retry_count = retry_count + 1
                        else:
                            need_to_retry = False
                        break
                if not need_to_retry:
                    raise

        conn.timeout = query_timeout
        return conn

    def init_connection_state(self):
        try:
            int(self._sql_server_version.split('.', 2)[0])
            self.is_sql_azure = bool(self.sql_server_edition in [6, 8, 9, 11])
        except (IndexError, ValueError):
            warnings.warn("Unable to determine MSSQL server version.", DeprecationWarning)

        settings_dict = self.settings_dict

        with self.temporary_connection() as cursor:
            options = settings_dict.get('OPTIONS', {})
            isolation_level = options.get('isolation_level', None)
            if isolation_level:
                cursor.execute('SET TRANSACTION ISOLATION LEVEL %s' % isolation_level)

            # Set date format for the connection. Also, make sure Sunday is
            # considered the first day of the week (to be consistent with the
            # Django convention for the 'week_day' Django lookup) if the user
            # hasn't told us otherwise
            datefirst = options.get('datefirst', 7)
            cursor.execute('SET DATEFORMAT ymd; SET DATEFIRST %s' % datefirst)

            val = self.get_system_datetime()
            if isinstance(val, str):
                raise ImproperlyConfigured("The database driver doesn't support modern datatime types.")

    def row_decode_all(self, row):
        new_row = []
        for r in row:
            try:
                str_r = r.decode('utf-8')
                if len(r) in [1, 2, 4, 8] and not str_r.isprintable():
                    new_row.append(self.row_decode_int(r))
                else:
                    new_row.append(str_r)
            except (UnicodeDecodeError, AttributeError):
                new_row.append(self.row_decode_int(r))

        return new_row

    @staticmethod
    def row_decode_str(row):
        if isinstance(row, bytes):
            try:
                return row.decode('utf-8')
            except UnicodeDecodeError:
                pass
        return row

    @staticmethod
    def row_decode_int(row, byteorder=sys.byteorder, signed=False):
        if isinstance(row, bytes):
            try:
                return int.from_bytes(bytes=row, byteorder=byteorder, signed=signed)
            except UnicodeDecodeError:
                pass
        return row

    @cached_property
    def sql_server_data(self):
        with self.temporary_connection() as cursor:
            # Other @@VERSION, SYSDATETIME()
            server_properties = [
                "BuildClrVersion", "Collation", "CollationID", "ComparisonStyle", "ComputerNamePhysicalNetBIOS",
                "Edition", "EditionID", "EngineEdition", "InstanceName", "IsClustered", "IsFullTextInstalled",
                "IsIntegratedSecurityOnly", "IsSingleUser", "LCID", "LicenseType", "MachineName", "NumLicenses",
                "ProcessID", "ProductVersion", "ProductLevel", "ResourceLastUpdateDateTime", "ResourceVersion",
                "ServerName", "SqlCharSet", "SqlCharSetName", "SqlSortOrder", "SqlSortOrderName", "FilestreamShareName",
                "FilestreamConfiguredLevel", "FilestreamEffectiveLevel"
            ]
            result = ""
            for s in server_properties:
                result += f"SERVERPROPERTY('{s}'), "  # noqa

            cursor.execute(f"""SELECT {result[:-2]}""")  # [:-2] remove last comma and space
            row = cursor.fetchone()
            row = self.row_decode_all(row=row)
        return {s: row[num] for num, s in enumerate(server_properties)}

    @cached_property
    def _sql_server_version(self):
        """-- '15.0.2000'"""
        return self.sql_server_data['ProductVersion']

    @cached_property
    def sql_server_clr(self):
        """-- 'v4.0.30319'"""
        return self.sql_server_data['BuildClrVersion']

    @cached_property
    def sql_server_level(self):
        """-- 'RTM'"""
        return self.sql_server_data['ProductLevel']

    @cached_property
    def sql_server_edition_id(self):
        """-- 9"""
        return self.sql_server_data['EditionID']

    @cached_property
    def sql_server_edition(self):
        """-- 'Azure SQL Edge Developer (64-bit)'"""
        return self.sql_server_data['EngineEdition']

    def is_usable(self):
        try:
            self.create_cursor().execute("SELECT 1")
        except Database.Error:
            return False
        else:
            return True

    def get_system_datetime(self):
        # http://blogs.msdn.com/b/sqlnativeclient/archive/2008/02/27/microsoft-sql-server-native-client-and-microsoft-sql-server-2008-native-client.aspx
        with self.temporary_connection() as cursor:
            if self.sql_server_version <= 2005:
                cursor.execute('SELECT GETDATE()')
                return cursor.fetchone()[0]
            else:
                cursor.execute('SELECT SYSDATETIME()')
                return cursor.fetchone()[0]

    @cached_property
    def sql_server_version(self, _known_versions=None):
        """
        Get the SQL server version

        The _known_versions default dictionary is created on the class. This is
        intentional - it allows us to cache this property's value across instances.
        Therefore, when Django creates a new database connection using the same
        alias, we won't need query the server again.
        """
        if _known_versions is None:
            _known_versions = {}
        if self.alias not in _known_versions:
            with self.temporary_connection() as cursor:
                cursor.execute("SELECT CAST(SERVERPROPERTY('ProductVersion') AS varchar)")
                ver = cursor.fetchone()[0]
                ver = int(ver.split('.')[0])
                if ver not in self._sql_server_versions:
                    raise NotSupportedError('SQL Server v%d is not supported.' % ver)
                _known_versions[self.alias] = self._sql_server_versions[ver]
        return _known_versions[self.alias]

    @cached_property
    def to_azure_sql_db(self, _known_azures=None):
        """
        Whether this connection is to a Microsoft Azure database server

        The _known_azures default dictionary is created on the class. This is
        intentional - it allows us to cache this property's value across instances.
        Therefore, when Django creates a new database connection using the same
        alias, we won't need query the server again.
        """
        if _known_azures is None:
            _known_azures = {}
        if self.alias not in _known_azures:
            with self.temporary_connection() as cursor:
                cursor.execute("SELECT CAST(SERVERPROPERTY('EngineEdition') AS integer)")
                _known_azures[self.alias] = cursor.fetchone()[0] == EDITION_AZURE_SQL_DB
        return _known_azures[self.alias]

    def _execute_foreach(self, sql, table_names=None):
        cursor = self.cursor()
        if table_names is None:
            table_names = self.introspection.table_names(cursor)
        for table_name in table_names:
            cursor.execute(sql % self.ops.quote_name(table_name))

    def _get_trancount(self):
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT @@TRANCOUNT')
            return cursor.fetchone()[0]

    def _on_error(self, e):
        if e.args[0] in self._codes_for_networkerror:
            try:
                # close the stale connection
                self.close()
                # wait a moment for recovery from network error
                time.sleep(self.connection_recovery_interval_msec)
            except Exception:
                pass
            self.connection = None

    def _savepoint(self, sid):
        with self.cursor() as cursor:
            cursor.execute('SELECT @@TRANCOUNT')
            trancount = cursor.fetchone()[0]
            if trancount == 0:
                cursor.execute(self.ops.start_transaction_sql())
            cursor.execute(self.ops.savepoint_create_sql(sid))

    def _savepoint_commit(self, sid):
        """
        SQL Server has no support for partial commit in a transaction
        The ANSI standard syntax is SAVEPOINT , ROLLBACK TO SAVEPOINT , and RELEASE SAVEPOINT.
        SQL Server has a different syntax and no "RELEASE".
        """
        pass

    def _savepoint_rollback(self, sid):
        with self.cursor() as cursor:
            # FreeTDS requires TRANCOUNT that is greater than 0
            cursor.execute('SELECT @@TRANCOUNT')
            trancount = cursor.fetchone()[0]
            if trancount > 0:
                cursor.execute(self.ops.savepoint_rollback_sql(sid))

    def _set_autocommit(self, autocommit):
        with self.wrap_database_errors:
            allowed = not autocommit
            if not allowed:
                # FreeTDS requires TRANCOUNT that is greater than 0
                allowed = self._get_trancount() > 0
            if allowed:
                try:
                    self.connection.autocommit = autocommit
                except AttributeError:
                    pass

    def check_constraints(self, table_names=None):
        self._execute_foreach('ALTER TABLE %s WITH CHECK CHECK CONSTRAINT ALL',
                              table_names)

    def disable_constraint_checking(self):
        if not self.needs_rollback:
            self._execute_foreach('ALTER TABLE %s NOCHECK CONSTRAINT ALL')
        return not self.needs_rollback

    def enable_constraint_checking(self):
        if not self.needs_rollback:
            self._execute_foreach('ALTER TABLE %s WITH NOCHECK CHECK CONSTRAINT ALL')


class CursorWrapper(object):
    """
    A wrapper around the pymssql cursor that takes in account a) some pymssql
    DB-API 2.0 implementation and b) some common FreeTDS driver particularities.
    """

    def __init__(self, cursor, connection):
        self.active = True
        self.cursor = cursor
        self.connection = connection
        self.driver_charset = connection.driver_charset
        self.last_sql = ''
        self.last_params = ()

    def close(self):
        if self.active:
            self.active = False
            self.cursor.close()

    def format_sql2(self, sql, params):
        if self.driver_charset and isinstance(sql, str):
            # FreeTDS (and other ODBC drivers?) doesn't support Unicode
            # yet, so we need to encode the SQL clause itself in utf-8
            sql = smart_str(sql, self.driver_charset)

        # pyodbc uses '?' instead of '%s' as parameter placeholder.
        if params is not None:
            sql = sql % tuple('?' * len(params))

        return sql

    @staticmethod
    def format_sql(query, params):
        # For Django's inspectdb tests -- a model has a non-ASCII column name.
        if not isinstance(query, str):
            query = query.encode('utf-8')
        # For Django's backends and expressions_regress tests.
        query = query.replace('%%', '%')
        return query

    def format_params(self, params):
        fp = []
        if params is not None:
            for p in params:
                if isinstance(p, str):
                    if self.driver_charset:
                        # FreeTDS (and other ODBC drivers?) doesn't support Unicode
                        # yet, so we need to encode parameters in utf-8
                        fp.append(smart_str(p, self.driver_charset))
                    else:
                        fp.append(p)

                elif isinstance(p, bytes):
                    fp.append(p)

                elif isinstance(p, type(True)):
                    if p:
                        fp.append(1)
                    else:
                        fp.append(0)

                else:
                    fp.append(p)

        return tuple(fp)

    def execute(self, sql, params=None):
        self.last_sql = sql
        sql = self.format_sql(sql, params)
        params = self.format_params(params)
        self.last_params = params
        try:
            # sql = sql.replace('SET NOCOUNT ON', "")
            # if 'SET NOCOUNT ON INSERT INTO [testapp_testuniquenullablemodel] ([test_field],' in sql:
            #     print()
            return self.cursor.execute(sql, params)
        except (Database.Error, Database.ProgrammingError, MSSQLDatabaseException) as e:
            # if e.args[0] in [1801, 2714, 1913]:     # silent codes
            #     return
            # print(f"ERROR_EXECUTE: {e}\nQUERY: {sql}\nPARAMS: {params}")
            self.connection._on_error(e)
            raise

    def executemany(self, sql, params_list=()):
        if not params_list:
            return None
        raw_pll = [p for p in params_list]
        sql = self.format_sql(sql, raw_pll[0])
        params_list = [self.format_params(p) for p in raw_pll]
        try:
            return self.cursor.executemany(sql, params_list)
        except Database.Error as e:
            self.connection._on_error(e)
            raise

    def format_rows(self, rows):
        return list(map(self.format_row, rows))

    def format_row(self, row):
        """
        Decode data coming from the database if needed and convert rows to tuples
        (pyodbc Rows are not hashable).
        """
        if self.driver_charset:
            for i in range(len(row)):
                f = row[i]
                # FreeTDS (and other ODBC drivers?) doesn't support Unicode
                # yet, so we need to decode utf-8 data coming from the DB
                if isinstance(f, bytes):
                    row[i] = f.decode(self.driver_charset)
        return tuple(row)

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is not None:
            row = self.format_row(row)
        # Any remaining rows in the current set must be discarded
        # before changing autocommit mode when you use FreeTDS
        if not self.connection.supports_mars:
            self.cursor.nextset()
        return row

    def fetchmany(self, chunk):
        return self.format_rows(self.cursor.fetchmany(chunk))

    def fetchall(self):
        return self.format_rows(self.cursor.fetchall())

    def __getattr__(self, attr):
        if attr in self.__dict__:
            return self.__dict__[attr]
        return getattr(self.cursor, attr)

    def __iter__(self):
        return iter(self.cursor)
