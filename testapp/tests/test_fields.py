# Copyright (c) Microsoft Corporation.
# Licensed under the BSD license.

from django.test import TestCase

from testapp.tests.models import UUIDModel, AutoDecimalModel, BigAutoFieldModel, NCharFieldModel


class TestUUIDField(TestCase):
    def test_create(self):
        UUIDModel.objects.create()


class TestNewFields(TestCase):
    def test_create(self):
        NCharFieldModel.objects.create()

    def test_deciaml_auto_field(self):
        auto_decimal = AutoDecimalModel.objects.create()
        self.assertEqual(auto_decimal.pk, 1)
        auto_decimal = AutoDecimalModel.objects.create()
        self.assertEqual(auto_decimal.pk, 2)

    def test_big_auto_field(self):
        big_auto = BigAutoFieldModel.objects.create()
        self.assertEqual(big_auto.pk, 1)
        big_auto = BigAutoFieldModel.objects.create()
        self.assertEqual(big_auto.pk, 2)




