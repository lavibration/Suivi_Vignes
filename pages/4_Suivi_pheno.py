import streamlit as st
import geemap.foliumap as geemap
import ee
import geopandas as gpd
import datetime
import pandas as pd
import json
import sys
import os
from typing import Dict, List, Tuple
import plotly.graph_objects as go
try:
    from scipy.signal import savgol_filter
except ImportError:
    savgol_filter = None

# ==============================================================================
# --- Initialisation des chemins et Imports (Adapté à votre structure) ---
# ==============================================================================
try:
    from mildiou_prevention import ConfigVignoble
except ImportError:
    st.error("❌ Erreur d'importation : Le fichier 'mildiou_prevention.py' n'est pas trouvé.")
    st.stop()

# ==============================================================================
# --- NOUVEAU : Tableau de Référence Phénologique (Basé sur votre image) ---
# ==============================================================================
# Clé = Mois (numérique)
REFERENCE_TABLE = {
    1: {'Stade': 'Repos hivernal', 'NDVI_min': 0.05, 'NDVI_moy': 0.10, 'NDMI_min': -0.05, 'NDMI_moy': 0.00},
    2: {'Stade': 'Bourgeon dans le coton', 'NDVI_min': 0.20, 'NDVI_moy': 0.25, 'NDMI_min': -0.05, 'NDMI_moy': 0.00},
    3: {'Stade': 'Pointe verte (Débourrement)', 'NDVI_min': 0.25, 'NDVI_moy': 0.28, 'NDMI_min': 0.00, 'NDMI_moy': 0.03},
    4: {'Stade': 'Feuilles étalées', 'NDVI_min': 0.30, 'NDVI_moy': 0.33, 'NDMI_min': 0.05, 'NDMI_moy': 0.06},
    5: {'Stade': 'Grappes visibles / Boutons', 'NDVI_min': 0.35, 'NDVI_moy': 0.38, 'NDMI_min': 0.08, 'NDMI_moy': 0.10},
    6: {'Stade': 'Floraison / Nouaison', 'NDVI_min': 0.38, 'NDVI_moy': 0.40, 'NDMI_min': 0.06, 'NDMI_moy': 0.08},
    7: {'Stade': 'Fermeture de grappe', 'NDVI_min': 0.32, 'NDVI_moy': 0.36, 'NDMI_min': 0.02, 'NDMI_moy': 0.05},
    8: {'Stade': 'Véraison', 'NDVI_min': 0.28, 'NDVI_moy': 0.33, 'NDMI_min': 0.00, 'NDMI_moy': 0.04},
    9: {'Stade': 'Maturité', 'NDVI_min': 0.25, 'NDVI_moy': 0.30, 'NDMI_min': -0.02, 'NDMI_moy': 0.03},
    10: {'Stade': 'Post-récolte', 'NDVI_min': 0.18, 'NDVI_moy': 0.25, 'NDMI_min': -0.03, 'NDMI_moy': 0.02},
    11: {'Stade': 'Chute des feuilles', 'NDVI_min': 0.10, 'NDVI_moy': 0.15, 'NDMI_min': -0.05, 'NDMI_moy': 0.00},
    12: {'Stade': 'Repos hivernal', 'NDVI_min': 0.05, 'NDVI_moy': 0.10, 'NDMI_min': -0.05, 'NDMI_moy': 0.00}
}

# ==============================================================================
# --- Earth Engine Setup and Helper Functions ---
# ==============================================================================

# ⚠️ REMPLACER CECI par votre ID de projet Google Cloud/Earth Engine
EE_PROJECT_ID = 'phenologie-477519'  # Mettez votre ID de projet ici


if "ee_initialized" not in st.session_state:
    try:
        # --- 1) Credentials Streamlit Cloud ---
        if "gcp_service_account" in st.secrets:
            service_account_info = dict(st.secrets["gcp_service_account"])

        # --- 2) Credentials locaux ---
        else:
            with open(".streamlit/service_account.json") as f:
                service_account_info = json.load(f)

        # Convertit en JSON string obligatoire pour Earth Engine
        key_json_str = json.dumps(service_account_info)

        credentials = ee.ServiceAccountCredentials(
            email=service_account_info["client_email"],
            key_data=key_json_str
        )

        ee.Initialize(credentials, project=EE_PROJECT_ID)

        st.session_state["ee_initialized"] = True
        st.success("✅ Earth Engine initialisé avec succès !")

    except Exception as e:
        st.error(f"❌ Erreur d'initialisation Earth Engine : {e}")
        st.stop()


@st.cache_data
def get_reference_df(year=2025):
    """Crée un DataFrame de référence pour l'année, avec une date au 15 de chaque mois."""

    # --- CORRECTION ICI ---
    # Remplacer datetime.date par pd.Timestamp pour correspondre au type
    # des données satellite (pd.to_datetime)
    dates = [pd.Timestamp(year, month, 15) for month in range(1, 13)]
    data = [REFERENCE_TABLE[month] for month in range(1, 13)]
    df = pd.DataFrame(data, index=dates)

    # --- CORRECTION ICI AUSSI ---
    # Assurer que le point de départ utilise aussi pd.Timestamp
    df_start = pd.DataFrame([REFERENCE_TABLE[1]], index=[pd.Timestamp(year, 1, 1)])

    df = pd.concat([df_start, df])
    return df


@st.cache_data
def load_and_prepare_data():
    """Charge le GeoJSON local et fusionne avec les données de ConfigVignoble."""
    try:
        config = ConfigVignoble()
        df_config = pd.DataFrame(config.parcelles)
    except Exception as e:
        st.error(f"Erreur de chargement ConfigVignoble : {e}")
        return None, None, None

    current_dir = os.path.dirname(os.path.abspath(__file__))
    geojson_path = os.path.join(current_dir, '..', 'map.geojson')

    if not os.path.exists(geojson_path):
        st.error(f"❌ Fichier GeoJSON non trouvé au chemin calculé : {geojson_path}. Vérifiez l'emplacement.")
        return None, None, None

    try:
        gdf = gpd.read_file(geojson_path)
        gdf = gdf.to_crs(epsg=4326)

        if 'name' in gdf.columns and 'Nom' not in gdf.columns:
            gdf.rename(columns={'name': 'Nom'}, inplace=True)
        elif 'Nom' not in gdf.columns:
            gdf['Nom'] = gdf.iloc[:, 0].astype(str)
            st.warning("⚠️ Colonne 'Nom' ou 'name' non trouvée. La première colonne du GeoJSON est utilisée comme nom.")

        geom_types = gdf.geometry.geom_type.unique()
        if not all(gtype in ['Polygon', 'MultiPolygon'] for gtype in geom_types):
            st.error(f"❌ Erreur de Géométrie : Votre GeoJSON contient des types non-valides ({geom_types}).")
            return None, None, None

        gdf_merged = gdf.merge(df_config[['nom', 'stade_actuel']],
                               left_on='Nom', right_on='nom', how='left').drop(columns=['nom']).rename(
            columns={'stade_actuel': 'Stade'})

        gdf_merged['Stade'] = gdf_merged['Stade'].fillna('repos')

        ee_features = []
        for index, row in gdf_merged.iterrows():
            geom = ee.Geometry(row.geometry.__geo_interface__)
            ee_features.append(ee.Feature(geom, {'Nom': row['Nom'], 'Stade': row['Stade']}))

        ee_feature_collection = ee.FeatureCollection(ee_features)
        geom_envelope = ee_feature_collection.geometry().bounds()

        return gdf_merged, ee_feature_collection, geom_envelope

    except Exception as e:
        st.error(f"Erreur lors du traitement du GeoJSON ou de la fusion : {e}")
        st.exception(e)
        return None, None, None


def mask_s2_clouds(image):
    """Masquage des nuages via la bande SCL (Scene Classification Layer) et mise à l'échelle."""
    # SCL est la bande de classification de scène fournie avec Sentinel-2 L2A.
    scl = image.select('SCL')

    # On garde les pixels de type : 4 (végétation), 5 (sols nus), 6 (eau), 7 (non classé).
    # On exclut : 3 (ombres), 8-9-10 (nuages), 11 (neige).
    mask = scl.gte(4).And(scl.lte(7))

    # Appliquer le masque et diviser par 10000 pour obtenir des réflectances entre 0 et 1.
    return image.updateMask(mask).divide(10000).copyProperties(image, ["system:time_start", "date"])


def add_indices(image):
    """Calcul des indices NDVI et NDMI."""
    ndvi = image.normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndmi = image.normalizedDifference(["B8A", "B11"]).rename("NDMI")
    return image.addBands([ndvi, ndmi]).set("date", image.date().format("YYYY-MM-dd"))


def get_mean_value_zonal(image, ee_feature_collection):
    mean_stats = image.reduceRegions(
        collection=ee_feature_collection,
        reducer=ee.Reducer.mean(),
        scale=10
    )
    return mean_stats.map(lambda f: f.set('date', image.get('date')))

def smooth_series(df, column, window_length=5, polyorder=2):
    """Lissage de la série temporelle."""
    if df.empty or column not in df.columns:
        return pd.Series(dtype=float)

    if savgol_filter and len(df) >= window_length:
        try:
            # Savgol filter returns a numpy array
            return savgol_filter(df[column], window_length=window_length, polyorder=polyorder)
        except:
            return df[column].rolling(window=3, center=True, min_periods=1).mean()
    else:
        return df[column].rolling(window=3, center=True, min_periods=1).mean()

def flag_grass_noise(df):
    """Identifie les points potentiellement bruités par l'enherbement inter-rang."""
    if df.empty:
        return df
    # Mois de dormance : Nov, Dec, Jan, Fev
    dormancy_months = [11, 12, 1, 2]
    # Si on est en dormance et que le NDVI est élevé, c'est probablement de l'herbe
    # On utilise un seuil empirique de 0.18 pour la vigne en dormance
    df['grass_noise'] = (df.index.month.isin(dormancy_months)) & (df['NDVI'] > 0.18)
    return df


# ==============================================================================
# --- APPLICATION STREAMLIT PRINCIPALE ---
# ==============================================================================

st.title("🛰️ Suivi NDVI/NDMI et Alertes Vigueur des Parcelles Viticoles")
st.markdown("---")

# Tentative de chargement des données
gdf_merged, ee_feature_collection, geom_envelope = load_and_prepare_data()

if gdf_merged is None:
    st.info("💡 Veuillez vous assurer que le fichier 'map.geojson' et 'config_vignoble.json' existent et sont valides.")
    st.stop()

st.success(f"✅ Configuration chargée. {len(gdf_merged)} parcelles détectées.")

# --- 2️⃣ Sélection de la période et Lancement ---
st.markdown("---")
col_date1, col_date2 = st.columns(2)
with col_date1:
    start_date = st.date_input("📆 Date de début", datetime.date(2025, 1, 1), key='start_date_sat')
with col_date2:
    end_date = st.date_input("📆 Date de fin", datetime.date.today(), key='end_date_sat')

if st.button("🚀 Lancer l'Analyse Satellite (Sentinel-2)", type="primary"):
    st.session_state['analyse_lancee'] = True

    # Stocker les dates pour les re-runs
    st.session_state['start_date_sat_run'] = start_date
    st.session_state['end_date_sat_run'] = end_date

    with st.spinner("⏳ Récupération et traitement des images Sentinel-2..."):

        try:
            # Calcul de la date de fin inclusive (+1 jour)
            end_date_plus_1 = end_date + datetime.timedelta(days=1)

            s2 = (
                ee.ImageCollection("COPERNICUS/S2_SR")
                .filterBounds(geom_envelope)
                .filterDate(str(start_date), str(end_date_plus_1))
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 80))
                .sort("system:time_start")
            )

            if s2.size().getInfo() == 0:
                st.error("❌ Aucune image Sentinel-2 exploitable trouvée sur cette période (trop de nuages).")
                st.session_state['analyse_lancee'] = False
                st.stop()

            # Application du masque de nuages et calcul des indices
            s2_indices = s2.map(mask_s2_clouds).map(add_indices)

            results_dict = s2_indices.map(
                lambda img: get_mean_value_zonal(img, ee_feature_collection)
            ).flatten().getInfo()

            if results_dict and 'features' in results_dict:

                actual_feature_list = results_dict['features']
                df_ee = pd.DataFrame([f['properties'] for f in actual_feature_list])
                df_ee['date'] = pd.to_datetime(df_ee['date'])

                st.session_state['df_series'] = df_ee.dropna(subset=['NDVI', 'NDMI']).drop_duplicates(
                    subset=['Nom', 'date'])
                st.session_state['analyse_complete'] = True
                st.success("✅ Analyse complétée. Données des séries temporelles extraites.")

            else:
                st.error("❌ Erreur : Les résultats d'Earth Engine sont vides ou mal formés.")
                st.session_state['analyse_complete'] = False

        except ee.EEException as e:
            st.error(f"❌ Erreur Earth Engine lors du traitement : {e}")
        except Exception as e:
            st.error(f"❌ Erreur inattendue : {e}")
            st.exception(e)

# ==============================================================================
# --- 5️⃣ Visualisation et Alertes (MODIFIÉ) ---
# ==============================================================================

if st.session_state.get('analyse_complete', False) and 'df_series' in st.session_state:

    df_chart = st.session_state['df_series']

    st.markdown("---")
    st.subheader("📈 Analyse de Tendance vs Références Phénologiques")

    parcelle_select = st.selectbox(
        "📍 Sélectionnez la parcelle à visualiser",
        df_chart['Nom'].unique(),
        key='select_parcelle_chart'
    )

    # Filtrer par parcelle
    df_parcelle = df_chart[df_chart['Nom'] == parcelle_select].set_index('date').sort_index()

    if df_parcelle.empty:
        st.warning(f"Aucune donnée satellite trouvée pour la parcelle '{parcelle_select}' après filtrage.")
    else:
        # --- NOUVEAU : Traitement des données ---
        df_parcelle = flag_grass_noise(df_parcelle)
        df_parcelle['NDVI_smooth'] = smooth_series(df_parcelle, 'NDVI')
        df_parcelle['NDMI_smooth'] = smooth_series(df_parcelle, 'NDMI')

        # Récupérer l'année de l'analyse pour la courbe de référence
        analysis_year = df_parcelle.index[0].year
        ref_df = get_reference_df(analysis_year)

        last_date = df_parcelle.index[-1]
        last_month = last_date.month

        # --- FONCTION DE VISUALISATION PLOTLY ---
        def create_index_chart(df, ref_df, index_name, title, color_map, y_min, y_max):
            fig = go.Figure()
            # Zones de dormance
            years = df.index.year.unique()
            for year in years:
                fig.add_vrect(
                    x0=pd.Timestamp(year, 11, 1), x1=pd.Timestamp(year, 12, 31),
                    fillcolor="rgba(200, 200, 200, 0.3)", layer="below", line_width=0
                )
                fig.add_vrect(
                    x0=pd.Timestamp(year, 1, 1), x1=pd.Timestamp(year, 2, 28),
                    fillcolor="rgba(200, 200, 200, 0.3)", layer="below", line_width=0
                )
            # Références
            fig.add_trace(go.Scatter(x=ref_df.index, y=ref_df[f'{index_name}_moy'],
                                     name='Réf. Moyenne', line=dict(color='#ffa500', dash='dash')))
            fig.add_trace(go.Scatter(x=ref_df.index, y=ref_df[f'{index_name}_min'],
                                     name='Réf. Minimum', line=dict(color='#ff0000', dash='dot')))
            # Brut
            fig.add_trace(go.Scatter(x=df.index, y=df[index_name],
                                     name='Mesuré (Brut)', mode='markers',
                                     marker=dict(color=color_map['raw'], size=5, opacity=0.4)))
            # Lissé
            fig.add_trace(go.Scatter(x=df.index, y=df[f'{index_name}_smooth'],
                                     name='Mesuré (Lissé)', line=dict(color=color_map['smooth'], width=3)))
            # Bruit herbe
            grass_df = df[df['grass_noise']]
            if not grass_df.empty:
                fig.add_trace(go.Scatter(x=grass_df.index, y=grass_df[index_name],
                                         name='Bruit Enherbement', mode='markers',
                                         marker=dict(color='purple', size=8, symbol='x')))
            fig.update_layout(
                title=title, xaxis_title="Date", yaxis_title=index_name,
                yaxis=dict(range=[y_min, y_max]),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=0, r=0, t=40, b=0), height=350
            )
            return fig

        # --- ALERTE ET GRAPHIQUE NDVI ---
        col_g1, col_g2 = st.columns(2)

        with col_g1:
            fig_ndvi = create_index_chart(
                df_parcelle, ref_df, 'NDVI', "Vigueur (NDVI)",
                {'raw': '#1f77b4', 'smooth': '#00008b'}, 0, 0.6
            )
            st.plotly_chart(fig_ndvi, use_container_width=True)

            # Logique d'alerte basée sur la dernière mesure vs le min du mois
            last_ndvi = df_parcelle['NDVI_smooth'].iloc[-1]
            ref_min_ndvi = REFERENCE_TABLE[last_month]['NDVI_min']

            if last_ndvi < ref_min_ndvi and REFERENCE_TABLE[last_month]['Stade'] != 'dormance':
                st.error(
                    f"🚨 ALERTE VIGUEUR : NDVI récent ({last_ndvi:.2f}) est **sous la normale** ({ref_min_ndvi}) pour ce mois-ci ({REFERENCE_TABLE[last_month]['Stade']}).")
            else:
                st.success(f"✅ Vigueur (NDVI : {last_ndvi:.2f}) conforme pour ce mois-ci.")

        # --- ALERTE ET GRAPHIQUE NDMI ---
        with col_g2:
            fig_ndmi = create_index_chart(
                df_parcelle, ref_df, 'NDMI', "Humidité Foliaire (NDMI)",
                {'raw': '#ff7f0e', 'smooth': '#d62728'}, -0.1, 0.2
            )
            st.plotly_chart(fig_ndmi, use_container_width=True)

            # Logique d'alerte
            last_ndmi = df_parcelle['NDMI_smooth'].iloc[-1]
            ref_min_ndmi = REFERENCE_TABLE[last_month]['NDMI_min']

            if last_ndmi < ref_min_ndmi and REFERENCE_TABLE[last_month]['Stade'] != 'dormance':
                st.warning(
                    f"💧 ALERTE SÉCHERESSE : NDMI récent ({last_ndmi:.2f}) est **sous le seuil de stress** ({ref_min_ndmi}) pour ce mois-ci.")
            else:
                st.success(f"✅ NDMI ({last_ndmi:.2f}) indique une hydratation adéquate.")

        # --- 6️⃣ Carte de Synthèse (Image Médiane) ---
        st.markdown("---")
        st.subheader("🗺️ Carte de Synthèse (Image Médiane)")

        col_map1, col_map2 = st.columns([1, 4])

        with col_map1:
            index_type = st.radio(
                "📊 Indice à visualiser :",
                ["NDVI", "NDMI"],
                horizontal=False,
                key='map_index'
            )

        run_start_date = st.session_state.get('start_date_sat_run', start_date)
        run_end_date = st.session_state.get('end_date_sat_run', end_date)

        # Calcul de la date de fin inclusive (+1 jour)
        run_end_date_plus_1 = run_end_date + datetime.timedelta(days=1)

        s2_collection = (
            ee.ImageCollection("COPERNICUS/S2_SR")
            .filterBounds(geom_envelope)
            .filterDate(str(run_start_date), str(run_end_date_plus_1))
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 80))
            .map(mask_s2_clouds)
            .map(add_indices)
        )

        median_image = s2_collection.median()

        m = geemap.Map(center=[gdf_merged.centroid.y.mean(), gdf_merged.centroid.x.mean()], zoom=13)

        if index_type == "NDVI":
            vis_params = {"bands": ["NDVI"], "min": 0, "max": 0.8, "palette": ["brown", "yellow", "green"]}
            legend_title = "NDVI Médian"
            legend_dict = {'0.1': 'brown', '0.3': 'yellow', '0.6': 'green', '0.8': 'green'}
        else:
            vis_params = {"bands": ["NDMI"], "min": -0.5, "max": 0.4, "palette": ["red", "yellow", "#00441b"]}
            legend_title = "NDMI Médian (Humidité)"
            legend_dict = {'-0.4': 'red', '0.0': 'yellow', '0.4': '#00441b'}

        m.addLayer(median_image.select(index_type), vis_params, f'Image Médiane ({index_type})')
        m.add_legend(title=legend_title, legend_dict=legend_dict)
        m.add_gdf(gdf_merged, layer_name="Parcelles Viticoles")

        with col_map2:
            m.to_streamlit(height=600)