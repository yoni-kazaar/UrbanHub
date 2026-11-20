"""Aides Streamlit partagées par les pages : chargement en cache des tables Gold et filtres."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # pour importer common/ depuis app/
from common.lake import lire_croise, lire_gold  # noqa: E402

TZ = "Europe/Paris"


@st.cache_data(ttl=600)
def charger(source):
    """Table Gold avec une colonne heure_locale (Europe/Paris) pour l'affichage, ou None."""
    df = lire_gold(source)
    if df is not None:
        df["heure"] = pd.to_datetime(df["heure"], utc=True)
        df["heure_locale"] = df["heure"].dt.tz_convert(TZ)
    return df


@st.cache_data(ttl=600)
def charger_croise():
    """Scores et métriques du modèle de la Partie 4, ou (None, None)."""
    return lire_croise()


def exiger(source):
    df = charger(source)
    if df is None:
        st.warning(f"Table Gold `{source}` pas encore publiée. Pour tester : `python -m common.fake_gold` puis `URBANHUB_FAKE=1`.")
        st.stop()
    return df


def filtres(df):
    """Filtres de la barre latérale : villes et période."""
    villes = sorted(df["ville"].dropna().unique())
    choix = st.sidebar.multiselect("Villes", villes, default=villes)
    debut, fin = df["heure_locale"].min().date(), df["heure_locale"].max().date()
    periode = st.sidebar.date_input("Période", (debut, fin), min_value=debut, max_value=fin)
    if len(periode) == 2:
        d = df["heure_locale"].dt.date
        df = df[(d >= periode[0]) & (d <= periode[1])]
    return df[df["ville"].isin(choix)]
