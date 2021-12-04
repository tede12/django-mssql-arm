import datetime

import six
from django.db import models
from django.db.models.fields import AutoFieldMixin, AutoFieldMeta, DecimalField  # noqa
from django.forms import ValidationError
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

__all__ = (
    'AutoDecimalField',
    'BigAutoField',
    'BigForeignKey',
    'BigIntegerField',
    'DateField',
    'DateTimeField',
    'DateTimeOffsetField',
    'LegacyTimeField',
    'LegacyDateField',
    'LegacyDateTimeField',
    'TimeField',
    'NCharField',
)


class NCharField(models.CharField):
    """A nchar field"""

    def get_internal_type(self):
        return "NCharField"


class AutoDecimalField(AutoFieldMixin, DecimalField, metaclass=AutoFieldMeta):
    """A Decimal increment field"""

    def get_internal_type(self):
        return 'AutoDecimalField'

    def rel_db_type(self, connection):
        return DecimalField().db_type(connection=connection)


# The following code to add new fields in Django is taken from django-mssql
# see https://bitbucket.org/Manfre/django-mssql

class BigAutoField(models.AutoField):
    """A bigint IDENTITY field"""

    def get_internal_type(self):
        return "BigAutoField"

    def to_python(self, value):
        if value is None:
            return value
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValidationError(
                _("This value must be a int."))

    def get_db_prep_value(self, value, connection=None, prepared=False):
        if value is None:
            return None
        return int(value)


class BigForeignKey(models.ForeignKey):
    """A ForeignKey field that points to a BigAutoField or BigIntegerField"""

    def db_type(self, connection=None):
        return models.BigIntegerField().db_type(connection=connection)


BigIntegerField = models.BigIntegerField


def convert_microsoft_date_to_isoformat(value):
    if isinstance(value, six.string_types):
        value = value.replace(' +', '+').replace(' -', '-')
    return value


class DateField(models.DateField):
    """
    A DateField backed by a 'date' database field.
    """

    def get_internal_type(self):
        return 'NewDateField'

    def to_python(self, value):
        val = super(DateField, self).to_python(
            convert_microsoft_date_to_isoformat(value)
        )
        if isinstance(val, datetime.datetime):
            val = datetime.date(day=val.day, month=val.month, year=val.year)
        return val


class DateTimeField(models.DateTimeField):
    """
    A DateTimeField backed by a 'datetime2' database field.
    """

    def get_internal_type(self):
        return 'NewDateTimeField'

    def to_python(self, value):
        from django.conf import settings
        result = super(DateTimeField, self).to_python(
            convert_microsoft_date_to_isoformat(value)
        )
        if result:
            if timezone.is_aware(result) and not settings.USE_TZ:
                result = timezone.make_naive(result, timezone.utc)
            elif settings.USE_TZ:
                result = timezone.make_aware(result, timezone.utc)
        return result

    def get_db_prep_value(self, value, connection, prepared=False):
        if not prepared:
            value = self.get_prep_value(value)
        return connection.ops._new_value_to_db_datetime(value)  # noqa


class DateTimeOffsetField(models.DateTimeField):
    """
    A DateTimeOffsetField backed by a 'datetimeoffset' database field.
    """

    def get_internal_type(self):
        return 'DateTimeOffsetField'

    def to_python(self, value):
        return super(DateTimeOffsetField, self).to_python(
            convert_microsoft_date_to_isoformat(value)
        )

    def get_db_prep_value(self, value, connection, prepared=False):
        if not prepared:
            value = self.get_prep_value(value)
        if value is None:
            return None
        return value.isoformat()


class TimeField(models.TimeField):
    """
    A TimeField backed by a 'time' database field.
    """

    def get_internal_type(self):
        return 'NewTimeField'

    def to_python(self, value):
        return super(TimeField, self).to_python(
            convert_microsoft_date_to_isoformat(value)
        )

    def get_db_prep_value(self, value, connection, prepared=False):
        if not prepared:
            value = self.get_prep_value(value)
        return connection.ops._new_value_to_db_time(value)  # noqa


class LegacyDateField(models.DateField):
    """
    A DateField that is backed by a 'datetime' database field.
    """

    def get_internal_type(self):
        return 'LegacyDateField'

    def to_python(self, value):
        val = super(LegacyDateField, self).to_python(
            convert_microsoft_date_to_isoformat(value)
        )
        if isinstance(val, datetime.datetime):
            val = datetime.date(day=val.day, month=val.month, year=val.year)
        return val


class LegacyDateTimeField(models.DateTimeField):
    """
    A DateTimeField that is backed by a 'datetime' database field.
    """

    def get_internal_type(self):
        return 'LegacyDateTimeField'

    def to_python(self, value):
        return super(LegacyDateTimeField, self).to_python(
            convert_microsoft_date_to_isoformat(value)
        )

    def get_db_prep_value(self, value, connection, prepared=False):
        if not prepared:
            value = self.get_prep_value(value)
        return connection.ops._legacy_value_to_db_datetime(value)  # noqa


class LegacyTimeField(models.TimeField):
    """
    A TimeField that is backed by a 'datetime' database field.
    """

    def get_internal_type(self):
        return 'LegacyTimeField'

    def to_python(self, value):
        val = super(LegacyTimeField, self).to_python(
            convert_microsoft_date_to_isoformat(value)
        )
        if isinstance(val, datetime.datetime):
            val = val.time()
        return val

    def get_db_prep_value(self, value, connection, prepared=False):
        if not prepared:
            value = self.get_prep_value(value)
        return connection.ops._legacy_value_to_db_time(value)  # noqa
