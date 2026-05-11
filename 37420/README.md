# Prospection 37420

Collecte automatique des entreprises du code postal 37420 pour usage de prospection web.

## Fichiers
- `data/37420.json` : données complètes
- `data/37420.csv` : export tabulaire
- `data/37420_targets_without_clear_website.csv` : cibles prioritaires
- `reports/37420.html` : rapport HTML filtrable

## Méthode
- extraction des points business via OpenStreetMap / Overpass
- détection du site via tags OSM quand présents
- sinon recherche web légère pour classer `no`, `uncertain`, `likely_yes`

## Limites
- la couverture dépend des données OSM
- l'absence de site est une inférence, pas une preuve absolue
- certaines entreprises locales peuvent manquer si non cartographiées
