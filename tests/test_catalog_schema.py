import json
import unittest
from pathlib import Path


class CatalogSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        catalog_path = Path(__file__).parents[1] / "data.json"
        cls.catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    def test_root_catalog_memiliki_dataset(self):
        self.assertIsInstance(self.catalog, dict)
        self.assertIsInstance(self.catalog.get("dataset"), list)
        self.assertGreater(len(self.catalog["dataset"]), 0)

    def test_dataset_memiliki_metadata_yang_dibutuhkan(self):
        for dataset in self.catalog["dataset"]:
            with self.subTest(identifier=dataset.get("identifier")):
                self.assertIsInstance(dataset.get("title"), str)
                self.assertIsInstance(dataset.get("identifier"), str)
                self.assertIsInstance(dataset.get("distribution"), list)
                self.assertTrue(dataset["distribution"])

                distribution = dataset["distribution"][0]
                self.assertIsInstance(distribution, dict)
                self.assertTrue(
                    distribution.get("accessURL") or distribution.get("downloadURL")
                )

    def test_distribution_portal_menggunakan_access_url_html(self):
        distributions = [
            distribution
            for dataset in self.catalog["dataset"]
            for distribution in dataset.get("distribution", [])
        ]
        self.assertTrue(distributions)
        self.assertTrue(all(distribution.get("accessURL") for distribution in distributions))
        self.assertTrue(all(distribution.get("format") == "html" for distribution in distributions))


if __name__ == "__main__":
    unittest.main()
