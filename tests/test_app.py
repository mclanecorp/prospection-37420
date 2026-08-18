#!/usr/bin/env python3
"""Tests de l'application de publication multi-réseaux."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# La configuration est lue à l'import : elle doit être posée avant.
_TMP = tempfile.mkdtemp(prefix='comite-tests-')
os.environ.update({
    'VAR_DIR': _TMP,
    'DB_PATH': str(Path(_TMP) / 'test.db'),
    'APP_PASSWORD': 'motdepasse',
    'SECRET_KEY': 'cle-de-test',
    'PUBLIC_BASE_URL': 'https://exemple.test',
    'DRY_RUN': '1',
})

from fastapi.testclient import TestClient  # noqa: E402

from app import charts, config, db, meta, publisher, stats  # noqa: E402
from app.main import app  # noqa: E402


def reset_database():
    db.init()
    with db.session() as conn:
        for table in ('snapshots', 'targets', 'media', 'group_shares',
                      'publications', 'fb_groups', 'accounts'):
            conn.execute(f'DELETE FROM {table}')
        # AUTOINCREMENT ne recycle pas les identifiants : on remet le compteur
        # à zéro pour que chaque test reparte de l'identifiant 1.
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN "
                     "('snapshots', 'targets', 'media', 'group_shares', "
                     "'publications', 'fb_groups', 'accounts')")


def add_account(platform='facebook', external_id='page-1', name='Page du comité'):
    with db.session() as conn:
        cursor = conn.execute(
            'INSERT INTO accounts (platform, external_id, name, access_token, '
            'connected_at) VALUES (?, ?, ?, ?, ?)',
            (platform, external_id, name, 'jeton', db.utcnow()))
        return cursor.lastrowid


class MetaErrorTest(unittest.TestCase):
    def test_message_utilisateur_prioritaire(self):
        payload = {'error': {'message': 'technique', 'error_user_msg': 'lisible',
                             'code': 190}}
        with self.assertRaises(meta.MetaError) as caught:
            meta._raise_for_payload(payload)
        self.assertEqual(str(caught.exception), 'lisible')
        self.assertEqual(caught.exception.code, 190)

    def test_reponse_sans_erreur_passe(self):
        self.assertIsNone(meta._raise_for_payload({'id': '123'}))


class ChartTest(unittest.TestCase):
    def test_courbe_vide_reste_lisible(self):
        html = charts.line_chart('Vues', [])
        self.assertIn('chart-empty', html)
        self.assertIn('Vues', html)

    def test_courbe_trace_une_ligne_et_une_legende(self):
        series = [
            {'name': 'Page', 'platform': 'facebook',
             'points': [('2026-08-01T10:00:00+00:00', 10),
                        ('2026-08-03T10:00:00+00:00', 90)]},
            {'name': 'Insta', 'platform': 'instagram',
             'points': [('2026-08-01T10:00:00+00:00', 4),
                        ('2026-08-03T10:00:00+00:00', 40)]},
        ]
        html = charts.line_chart('Vues', series)
        self.assertIn('<path class="line"', html)
        self.assertIn('var(--series-1)', html)   # Facebook
        self.assertIn('var(--series-2)', html)   # Instagram
        self.assertIn('legend', html)            # légende dès deux séries

    def test_serie_unique_sans_legende(self):
        html = charts.line_chart('Vues', [
            {'name': 'Page', 'platform': 'facebook',
             'points': [('2026-08-01T10:00:00+00:00', 10)]}])
        self.assertNotIn('class="legend"', html)

    def test_nom_de_serie_echappe(self):
        html = charts.line_chart('Vues', [
            {'name': '<script>alert(1)</script>', 'platform': 'facebook',
             'points': [('2026-08-01T10:00:00+00:00', 1),
                        ('2026-08-02T10:00:00+00:00', 2)]}])
        self.assertNotIn('<script>', html)

    def test_arrondi_de_l_axe(self):
        self.assertEqual(charts._nice_ceiling(3), 5)
        self.assertEqual(charts._nice_ceiling(1100), 1500)
        self.assertGreaterEqual(charts._nice_ceiling(870), 870)


class PublisherTest(unittest.TestCase):
    def setUp(self):
        reset_database()

    def test_url_des_medias_est_publique(self):
        with db.session() as conn:
            conn.execute('INSERT INTO publications (message, created_at) VALUES (?, ?)',
                         ('coucou', db.utcnow()))
            conn.execute('INSERT INTO media (publication_id, filename, mime, token) '
                         'VALUES (1, ?, ?, ?)', ('photo.jpg', 'image/jpeg', 'jeton123'))
            urls = publisher.media_urls(conn, 1)
        self.assertEqual(urls, ['https://exemple.test/media/jeton123.jpg'])

    def test_statut_global_selon_les_cibles(self):
        cas = [
            (['published', 'published'], 'published'),
            (['published', 'failed'], 'partial'),
            (['failed', 'failed'], 'failed'),
            (['pending', 'failed'], 'scheduled'),
        ]
        for statuts, attendu in cas:
            with self.subTest(statuts=statuts):
                reset_database()
                comptes = [add_account('facebook', f'p{i}', f'Page {i}')
                           for i in range(len(statuts))]
                with db.session() as conn:
                    conn.execute('INSERT INTO publications (message, created_at) '
                                 'VALUES (?, ?)', ('texte', db.utcnow()))
                    for account_id, statut in zip(comptes, statuts):
                        conn.execute('INSERT INTO targets (publication_id, account_id, '
                                     'status) VALUES (1, ?, ?)', (account_id, statut))
                    publisher._refresh_status(conn, 1, db.utcnow())
                    row = conn.execute(
                        'SELECT status FROM publications WHERE id = 1').fetchone()
                self.assertEqual(row['status'], attendu)


class StatsTest(unittest.TestCase):
    def setUp(self):
        reset_database()

    def test_metrique_inconnue_refusee(self):
        with db.session() as conn:
            with self.assertRaises(ValueError):
                stats.series(conn, 1, 'vues; DROP TABLE snapshots')

    def test_cumul_des_derniers_releves(self):
        account_id = add_account()
        with db.session() as conn:
            conn.execute('INSERT INTO publications (message, created_at) VALUES (?, ?)',
                         ('texte', db.utcnow()))
            conn.execute('INSERT INTO targets (publication_id, account_id, status) '
                         'VALUES (1, ?, ?)', (account_id, 'published'))
            for moment, vues in (('2026-08-01T00:00:00+00:00', 10),
                                 ('2026-08-02T00:00:00+00:00', 42)):
                conn.execute('INSERT INTO snapshots (target_id, captured_at, views, '
                             'likes, comments, shares) VALUES (1, ?, ?, 1, 1, 1)',
                             (moment, vues))
            totaux = stats.totals(conn, 1)
        # Seul le relevé le plus récent compte : les compteurs sont cumulatifs.
        self.assertEqual(totaux['views'], 42)

    def test_cumul_absent_sans_releve(self):
        with db.session() as conn:
            conn.execute('INSERT INTO publications (message, created_at) VALUES (?, ?)',
                         ('texte', db.utcnow()))
            self.assertIsNone(stats.totals(conn, 1))


class WebTest(unittest.TestCase):
    def setUp(self):
        reset_database()
        # PUBLIC_BASE_URL est en https, donc le cookie de session est marqué
        # Secure : le client de test doit parler https pour le conserver.
        self.client = TestClient(app, base_url='https://testserver')

    def connexion(self):
        response = self.client.post('/login', data={'password': 'motdepasse'},
                                    follow_redirects=False)
        self.assertEqual(response.status_code, 303)

    def test_acces_protege(self):
        response = self.client.get('/', follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], '/login')

    def test_mauvais_mot_de_passe(self):
        self.client.post('/login', data={'password': 'faux'}, follow_redirects=False)
        response = self.client.get('/', follow_redirects=False)
        self.assertEqual(response.status_code, 303)

    def test_publication_de_bout_en_bout(self):
        self.connexion()
        account_id = add_account()
        with db.session() as conn:
            conn.execute('INSERT INTO fb_groups (name, url) VALUES (?, ?)',
                         ('Groupe du village', 'https://facebook.com/groups/1'))

        response = self.client.post('/compose', data={
            'message': 'Brocante samedi', 'accounts': [str(account_id)],
            'action': 'publish'}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)

        with db.session() as conn:
            publication = conn.execute('SELECT * FROM publications').fetchone()
            target = conn.execute('SELECT * FROM targets').fetchone()
        self.assertEqual(publication['status'], 'published')
        self.assertEqual(target['status'], 'published')
        self.assertTrue(target['external_post_id'].startswith('dryrun_'))

        page = self.client.get(f'/publications/{publication["id"]}')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Brocante samedi', page.text)
        self.assertIn('Groupe du village', page.text)

    def test_publication_refusee_si_vide(self):
        self.connexion()
        account_id = add_account()
        response = self.client.post('/compose', data={
            'message': '  ', 'accounts': [str(account_id)], 'action': 'publish'},
            follow_redirects=False)
        self.assertEqual(response.headers['location'], '/compose')
        with db.session() as conn:
            self.assertEqual(
                conn.execute('SELECT COUNT(*) c FROM publications').fetchone()['c'], 0)

    def test_suivi_du_partage_en_groupe(self):
        self.connexion()
        account_id = add_account()
        with db.session() as conn:
            conn.execute('INSERT INTO fb_groups (name) VALUES (?)', ('Groupe A',))
        self.client.post('/compose', data={
            'message': 'Fête', 'accounts': [str(account_id)], 'action': 'draft'},
            follow_redirects=False)

        self.client.post('/publications/1/groups/1', data={'manual_views': '75'},
                         follow_redirects=False)
        with db.session() as conn:
            share = conn.execute('SELECT * FROM group_shares').fetchone()
        self.assertIsNotNone(share['shared_at'])
        self.assertEqual(share['manual_views'], 75)

        # Un second appui annule le partage : la case est une bascule.
        self.client.post('/publications/1/groups/1', data={'manual_views': '75'},
                         follow_redirects=False)
        with db.session() as conn:
            share = conn.execute('SELECT * FROM group_shares').fetchone()
        self.assertIsNone(share['shared_at'])

    def test_media_hors_dossier_refuse(self):
        response = self.client.get('/media/..%2F..%2Fapp%2Fconfig.py')
        self.assertEqual(response.status_code, 404)

    def test_healthz_public(self):
        self.assertEqual(self.client.get('/healthz').json(), {'status': 'ok'})

    def test_lien_de_groupe_dangereux_rejete(self):
        self.connexion()
        self.client.post('/groups', data={'name': 'Groupe piégé',
                                          'url': 'javascript:alert(1)'},
                         follow_redirects=False)
        with db.session() as conn:
            group = conn.execute('SELECT * FROM fb_groups').fetchone()
        self.assertEqual(group['name'], 'Groupe piégé')
        self.assertEqual(group['url'], '')

    def test_lien_de_groupe_valide_conserve(self):
        self.connexion()
        self.client.post('/groups', data={'name': 'Groupe',
                                          'url': 'https://facebook.com/groups/42'},
                         follow_redirects=False)
        with db.session() as conn:
            group = conn.execute('SELECT * FROM fb_groups').fetchone()
        self.assertEqual(group['url'], 'https://facebook.com/groups/42')


if __name__ == '__main__':
    unittest.main(verbosity=2)
