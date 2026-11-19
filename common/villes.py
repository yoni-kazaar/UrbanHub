"""Les 8 villes du projet, leurs centres, et le rattachement d'une station à une ville (voir CONTRAT.md)."""
from math import asin, cos, radians, sin, sqrt

# Centre de chaque ville (latitude, longitude). Seule référence autorisée par le contrat.
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

RAYON_KM = 30


def distance_km(lat1, lon1, lat2, lon2):
    """Distance à vol d'oiseau (formule de haversine)."""
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * asin(sqrt(a))


def rattacher_ville(latitude, longitude):
    """Ville la plus proche à moins de 30 km de son centre, sinon None.

    Sur un DataFrame : df["ville"] = [rattacher_ville(la, lo) for la, lo in zip(df.latitude, df.longitude)]
    """
    ville, d = min(((v, distance_km(latitude, longitude, *c)) for v, c in VILLES.items()), key=lambda x: x[1])
    return ville if d <= RAYON_KM else None
