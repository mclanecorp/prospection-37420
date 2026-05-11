import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / 'src' / 'prospect_pipeline.py'
SPEC = importlib.util.spec_from_file_location('prospect_pipeline', MODULE_PATH)
prospect_pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prospect_pipeline)


class ResolvePostalAreaTests(unittest.TestCase):
    def test_build_job_config_from_nominatim_postcode_relation(self):
        nominatim_results = [
            {
                'osm_type': 'relation',
                'osm_id': 10564884,
                'type': 'postal_code',
                'display_name': '37420, Avoine, Chinon, Indre-et-Loire, Centre-Val de Loire, France',
            }
        ]

        config = prospect_pipeline.build_job_config('37420', '/tmp/prospection', nominatim_results)

        self.assertEqual(config['postal_code'], '37420')
        self.assertEqual(config['relation_id'], 10564884)
        self.assertEqual(config['area_id'], 3610564884)
        self.assertEqual(config['label'], '37420')
        self.assertEqual(config['job_dir'], '/tmp/prospection/37420')

    def test_build_job_config_rejects_missing_postcode_relation(self):
        with self.assertRaises(ValueError):
            prospect_pipeline.build_job_config('37420', '/tmp/prospection', [{'osm_type': 'way', 'osm_id': 1}])


class OutputPathTests(unittest.TestCase):
    def test_output_paths_are_namespaced_by_postal_code(self):
        config = {
            'postal_code': '37500',
            'job_dir': '/tmp/prospection/37500',
        }

        paths = prospect_pipeline.build_output_paths(config)

        self.assertEqual(paths['json'], '/tmp/prospection/37500/data/37500.json')
        self.assertEqual(paths['csv'], '/tmp/prospection/37500/data/37500.csv')
        self.assertEqual(paths['targets_csv'], '/tmp/prospection/37500/data/37500_targets_without_clear_website.csv')
        self.assertEqual(paths['html'], '/tmp/prospection/37500/reports/37500.html')


class ReverseGeocodeEnrichmentTests(unittest.TestCase):
    def test_reverse_geocode_fills_missing_address_commune_and_postcode(self):
        record = {
            'name': 'magpresse',
            'address': '',
            'commune': '',
            'postal_code': '37420',
        }
        reverse_result = {
            'address': {
                'road': 'Rue Marcel Vignaud',
                'village': 'Avoine',
                'postcode': '37420',
            }
        }

        prospect_pipeline.enrich_record_from_reverse_geocode(record, reverse_result)

        self.assertEqual(record['address'], 'Rue Marcel Vignaud, 37420 Avoine')
        self.assertEqual(record['commune'], 'Avoine')
        self.assertEqual(record['postal_code'], '37420')

    def test_reverse_geocode_does_not_overwrite_existing_address(self):
        record = {
            'name': 'Au fil de l\'eau',
            'address': '4 Rue du Val de l\'Indre',
            'commune': '',
            'postal_code': '37420',
        }
        reverse_result = {
            'address': {
                'road': 'Rue du Val de l\'Indre',
                'village': 'Huismes',
                'postcode': '37420',
            }
        }

        prospect_pipeline.enrich_record_from_reverse_geocode(record, reverse_result)

        self.assertEqual(record['address'], '4 Rue du Val de l\'Indre')
        self.assertEqual(record['commune'], 'Huismes')

    def test_reverse_geocode_corrects_mismatched_postcode(self):
        record = {
            'name': 'Domaine de la Roche Honneur',
            'address': '1 Rue de la Berthelonnière, 37240 Savigny en Véron',
            'commune': 'Savigny en Véron',
            'postal_code': '37240',
        }
        reverse_result = {
            'address': {
                'road': 'Rue de la Berthelonnière',
                'village': 'Savigny-en-Véron',
                'postcode': '37420',
            }
        }

        prospect_pipeline.enrich_record_from_reverse_geocode(record, reverse_result)

        self.assertEqual(record['postal_code'], '37420')

    def test_reverse_enrichment_is_fail_soft(self):
        record = {'name': 'Test', 'address': '', 'commune': '', 'postal_code': '37420', 'lat': 1.0, 'lon': 2.0}
        with mock.patch.object(prospect_pipeline, 'fetch_reverse_geocode', side_effect=RuntimeError('boom')):
            prospect_pipeline.enrich_records_with_reverse_geocoding([record], sleep_seconds=0)

        self.assertEqual(record['address'], '')


class CachedPostalConfigTests(unittest.TestCase):
    def test_resolve_job_config_uses_cache_without_calling_nominatim(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = pathlib.Path(tmpdir) / 'config' / 'postal_codes.json'
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                '{"37420": {"postal_code": "37420", "relation_id": 10564884, "area_id": 3610564884, "label": "37420", "display_name": "37420, Avoine", "job_dir": "ignore-me"}}',
                encoding='utf-8',
            )
            with mock.patch.object(prospect_pipeline, 'fetch_postcode_nominatim_results', side_effect=AssertionError('should not call nominatim')):
                config = prospect_pipeline.resolve_job_config('37420', tmpdir)

        self.assertEqual(config['postal_code'], '37420')
        self.assertEqual(config['relation_id'], 10564884)
        self.assertEqual(config['job_dir'], str(pathlib.Path(tmpdir) / '37420'))


class ContactEnrichmentTests(unittest.TestCase):
    def test_contact_enrichment_extracts_phone_from_relevant_search_result(self):
        record = {
            'name': 'Pharmacie Fraillon',
            'commune': 'Beaumont-en-Véron',
            'postal_code': '37420',
            'phone': '',
            'email': '',
        }
        results = [
            {
                'url': 'https://example.org/pharmacie-fraillon',
                'title': 'Pharmacie Fraillon à Beaumont-en-Véron',
                'snippet': 'Téléphone : 02 47 58 94 39. Adresse : 9 Beaumont-en-Véron 37420.'
            }
        ]

        prospect_pipeline.enrich_contact_from_search_results(record, results)

        self.assertEqual(record['phone'], '+33 2 47 58 94 39')

    def test_contact_enrichment_ignores_irrelevant_search_result(self):
        record = {
            'name': '3DG',
            'commune': 'Avoine',
            'postal_code': '37420',
            'phone': '',
            'email': '',
        }
        results = [
            {
                'url': 'https://example.org/unrelated',
                'title': 'Scratch - Imagine, Program, Share',
                'snippet': 'Contact : 05 63 40 19 42 pour un service sans rapport.'
            }
        ]

        prospect_pipeline.enrich_contact_from_search_results(record, results)

        self.assertEqual(record['phone'], '')


if __name__ == '__main__':
    unittest.main()
