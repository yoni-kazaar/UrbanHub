"""
Référentiel commun des 8 villes UrbanHub (CONTRAT.md).

Un seul fichier de coordonnées pour tout le projet : personne n'utilise
d'autres centres de villes. Fonction commune : rattacher_ville().
"""

from math import asin, cos, radians, sin, sqrt

# Centre de chaque ville (latitude, longitude) en degrés décimaux
VILLES = {
    "Paris": (48.8566, 2.3522),
    "Lyon": (45.7640, 4.8357),
    "Marseille": (43.2965, 5.3698),
    "Toulouse": (43.6047, 1.4442),
    "Lille": (50.6292, 3.0573),
    "Bordeaux": (44.8378, -0.5792),
    "Nantes": (47.2184, -1.5536),
    "Strasbourg": (48.5734, 7.7521),
}

RAYON_KM = 30  # règle du contrat


def distance_km(lat1, lon1, lat2, lon2):
    """Distance à vol d'oiseau entre deux points (formule de haversine)."""
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * asin(sqrt(a))


def rattacher_ville(latitude, longitude, rayon_km=RAYON_KM):
    """
    Renvoie la ville du contrat la plus proche si elle est à moins de rayon_km,
    sinon None (qui deviendra null dans les fichiers Parquet).
    """
    if latitude is None or longitude is None:
        return None
    meilleure, d_min = None, None
    for ville, (lat_c, lon_c) in VILLES.items():
        d = distance_km(latitude, longitude, lat_c, lon_c)
        if d <= rayon_km and (d_min is None or d < d_min):
            meilleure, d_min = ville, d
    return meilleure
