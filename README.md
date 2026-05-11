# Prospection locale multi-code-postal

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
