# Outils du comité

Ce dépôt contient deux outils indépendants :

- **Publication multi-réseaux** (`app/`) — publier un post sur la Page Facebook
  et Instagram en une fois, suivre l'évolution des vues et des commentaires, et
  garder la trace des partages en groupes. Voir [GUIDE.md](GUIDE.md) pour
  l'installation pas à pas.
- **Prospection par code postal** (`src/`) — collecte d'entreprises locales,
  documentée ci-dessous.

---

## Publication multi-réseaux

Une application web à héberger, utilisable depuis un téléphone, protégée par un
mot de passe partagé entre les membres du comité.

Ce qu'elle fait :
- rédaction d'un post (texte + photos) publié d'un coup sur la **Page Facebook**
  et **Instagram**, tout de suite ou à une date programmée ;
- **tableau de bord** des vues, j'aime, commentaires et partages, avec une courbe
  d'évolution par publication (relevé toutes les six heures) ;
- **liste de partage** pour les groupes Facebook, à cocher au fur et à mesure.

Ce qu'elle ne fait pas, et ne peut pas faire : publier automatiquement dans les
groupes Facebook. Meta a supprimé l'API Groupes le 22 avril 2024 ; plus aucun
outil n'en est capable. L'app assiste le partage manuel à la place.

Démarrage rapide en mode simulation, sans aucune configuration Meta :

```bash
pip install -r requirements.txt
DRY_RUN=1 APP_PASSWORD=test uvicorn app.main:app --port 8000
```

Puis <http://localhost:8000>. Rien n'est publié pour de vrai et les
statistiques sont fictives : c'est fait pour prendre l'app en main.

Configuration réelle, hébergement et connexion des comptes Meta :
**[GUIDE.md](GUIDE.md)**.

Tests : `python3 -m unittest tests.test_app -v`

---

## Prospection locale multi-code-postal

Ce repo sert à collecter des entreprises locales par code postal pour de la prospection web.

Usage principal
- commande générique : python3 src/prospect_pipeline.py --postal-code 37420 --outdir-root .
- wrapper historique 37420 : python3 src/collect_37420.py

Structure des sorties
Chaque code postal écrit ses résultats dans un sous-dossier dédié.
Le repo ne doit pas contenir de doublons en racine dans `data/` ou `reports/`.
Le seul emplacement canonique des exports est `CODE_POSTAL/...`.

Exemple pour 37420 :
- 37420/data/37420.json
- 37420/data/37420.csv
- 37420/data/37420_targets_without_clear_website.csv
- 37420/data/37420_targets_without_clear_website.json
- 37420/reports/37420.html
- 37420/README.md

Paramètres utiles
- --postal-code : code postal à analyser
- --outdir-root : dossier racine dans lequel créer le sous-dossier du code postal
- --country : pays pour la résolution du code postal via Nominatim, par défaut France
- --sleep-seconds : pause entre recherches web ; mettre 0 pour aller plus vite

Exemple pour un autre code postal
- python3 src/prospect_pipeline.py --postal-code 37500 --outdir-root .

Ce que produit le pipeline
- extraction des points business via OpenStreetMap / Overpass
- détection du site via les tags OSM quand ils existent
- sinon recherche web légère pour classer les fiches en yes / likely_yes / uncertain / no
- enrichissement d'adresse/commune des cibles à partir du reverse geocoding Nominatim
- tentative d'enrichissement téléphone/email des cibles via extraction prudente depuis des résultats de recherche ciblés
- génération d'un HTML filtrable et de CSV/JSON pour la prospection

Cache
- `config/postal_codes.json` mémorise les relations de codes postaux déjà résolues pour éviter de solliciter Nominatim inutilement à chaque relance

Tests
- python3 -m unittest tests/test_pipeline.py -v

Limites
- la couverture dépend des données OpenStreetMap
- l'absence de site est une inférence, pas une preuve absolue
- certaines entreprises locales peuvent manquer si elles ne sont pas cartographiées
