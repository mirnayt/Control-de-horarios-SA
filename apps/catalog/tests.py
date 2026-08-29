from django.test import TestCase

from apps.catalog.models import Profesor, Salon


class CatalogModelsTests(TestCase):
    def test_crear_salon_y_profesor(self):
        salon = Salon.objects.create(nombre="Salón A")
        profesor = Profesor.objects.create(nombre="Ana López")
        self.assertTrue(salon.activo)
        self.assertTrue(profesor.activo)
        self.assertEqual(str(salon), "Salón A")
        self.assertEqual(str(profesor), "Ana López")
