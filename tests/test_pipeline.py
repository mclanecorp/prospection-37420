import importlib.util
import pathlib
import unittest

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


if __name__ == '__main__':
    unittest.main()
