import heapq
import math
import time
import requests
import numpy as np
import pandas as pd
import osmnx as ox
import folium
import streamlit as st
import streamlit.components.v1 as components
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score

# ==============================================================================
# CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(
    page_title="CadeiWaze",
    page_icon="♿",
    layout="wide"
)

CIDADES_CONFIG = {
    "Santo Amaro, Bahia, Brazil": {
        "origem_padrao": "Praça da Purificação, Santo Amaro, Bahia, Brazil",
        "destino_padrao": "CECULT UFRB, Santo Amaro, Bahia, Brazil",
        "coord_fallback_orig": (-12.5472, -38.7128),
        "coord_fallback_dest": (-12.5435, -38.7088),
        "prob_paralelepipedo": 0.45,
        "perfil_desc": "Centro histórico: alta incidência de paralelepípedo (sett) e calçadas estreitas."
    },
    "Feira de Santana, Bahia, Brazil": {
        "origem_padrao": "Terminal Central, Feira de Santana, Bahia, Brazil",
        "destino_padrao": "UEFS, Feira de Santana, Bahia, Brazil",
        "coord_fallback_orig": (-12.2575, -38.9675),
        "coord_fallback_dest": (-12.2015, -38.9715),
        "prob_paralelepipedo": 0.15,
        "perfil_desc": "Malha urbana ampla: predominância de asfalto com desníveis pontuais."
    },
    "Recife, Pernambuco, Brazil": {
        "origem_padrao": "Praça do Derby, Recife, Pernambuco, Brazil",
        "destino_padrao": "Universidade Católica de Pernambuco, Recife, Pernambuco, Brazil",
        "coord_fallback_orig": (-8.0556, -34.8981),
        "coord_fallback_dest": (-8.0558, -34.8878),
        "prob_paralelepipedo": 0.20,
        "perfil_desc": "Malha costeira densa: trechos planos alternados com pontes e rampas."
    }
}

SUPERFICIE_RMS_MAP = {
    "asphalt": (0.45, 0.12),
    "concrete": (0.50, 0.15),
    "paved": (0.65, 0.20),
    "paving_stones": (1.15, 0.25),
    "sett": (2.35, 0.45),
    "cobblestone": (2.95, 0.55),
    "compacted": (1.80, 0.35),
    "unpaved": (2.60, 0.50),
    "dirt": (3.10, 0.60),
    "gravel": (2.85, 0.55)
}

# ==============================================================================
# MÓDULO 1: GEOCODIFICAÇÃO E EXTRAÇÃO GEOESPACIAL REAL (OSM + ALTIMETRIA)
# ==============================================================================

@st.cache_data(show_spinner=False)
def geocodificar_endereco(endereco, fallback_coords):
    """Converte endereço digitado em (latitude, longitude) via OpenStreetMap."""
    try:
        lat, lon = ox.geocode(endereco)
        return (float(lat), float(lon)), True
    except Exception:
        return fallback_coords, False

def distancia_haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0  # Raio médio da Terra em metros (SI)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def adicionar_elevacao_real(G, seed_str):
    """Consulta altitude real (m) via Open-Elevation API com fallback offline."""
    nos = list(G.nodes(data=True))
    locations = [{"latitude": data["y"], "longitude": data["x"]} for _, data in nos]
    elevacoes = []
    fonte_dados = "Open-Elevation API (SRTM Real)"

    try:
        for i in range(0, len(locations), 150):
            lote = locations[i:i+150]
            resp = requests.post(
                "https://api.open-elevation.com/api/v1/lookup",
                json={"locations": lote},
                timeout=6
            )
            resp.raise_for_status()
            elevacoes.extend([r["elevation"] for r in resp.json()["results"]])
    except Exception:
        fonte_dados = "Modelo Topográfico Sintético (Fallback Offline)"
        rng = np.random.default_rng(sum(ord(c) for c in seed_str))
        for _, data in nos:
            lat, lon = data["y"], data["x"]
            h = 15.0 + 18.0 * math.sin(lat * 900.0) * math.cos(lon * 900.0) + rng.normal(0, 0.3)
            elevacoes.append(round(float(h), 2))

    for (node_id, _), elev in zip(nos, elevacoes):
        G.nodes[node_id]["elevation"] = float(elev)

    return fonte_dados

@st.cache_resource(show_spinner="Construindo grafo viário, altimetria e superfícies...")
def construir_grafo_rota(orig_coords, dest_coords, prob_paralelepipedo, cidade_nome):
    ponto_medio = (
        (orig_coords[0] + dest_coords[0]) / 2.0,
        (orig_coords[1] + dest_coords[1]) / 2.0
    )
    dist_reta = distancia_haversine(orig_coords[0], orig_coords[1], dest_coords[0], dest_coords[1])
    # Define raio dinâmico com margem de segurança (mín. 700 m, máx. 3000 m para performance)
    raio_m = int(min(max(dist_reta * 0.75 + 350, 700), 3000))

    G = ox.graph_from_point(ponto_medio, dist=raio_m, network_type="walk")
    fonte_elev = adicionar_elevacao_real(G, cidade_nome)

    rng = np.random.default_rng(42)
    registros_arestas = []

    for u, v, k, data in G.edges(keys=True, data=True):
        d = max(float(data.get("length", 5.0)), 1.0)
        h_u = G.nodes[u].get("elevation", 0.0)
        h_v = G.nodes[v].get("elevation", 0.0)

        delta_h = abs(h_v - h_u)
        inclinacao_pct = (delta_h / d) * 100.0
        inclinacao_rad = math.atan(delta_h / d)

        raw_surface = data.get("surface", None)
        if isinstance(raw_surface, list):
            raw_surface = raw_surface[0]

        if raw_surface in SUPERFICIE_RMS_MAP:
            superficie = raw_surface
        else:
            superficie = "sett" if rng.random() < prob_paralelepipedo else "asphalt"

        media_rms, std_rms = SUPERFICIE_RMS_MAP[superficie]
        rms_az = max(0.15, float(rng.normal(media_rms, std_rms)))

        if inclinacao_pct > 12.0 or rms_az > 3.1:
            classe = 3  # Intransponível
        elif inclinacao_pct > 8.33:
            classe = 2  # Inclinação Crítica (> ABNT NBR 9050)
        elif rms_az > 1.5:
            classe = 1  # Trepidação Moderada / Piso Irregular
        else:
            classe = 0  # Via Acessível

        data["inclinacao_pct"] = round(inclinacao_pct, 2)
        data["inclinacao_rad"] = round(inclinacao_rad, 4)
        data["rms_az_ms2"] = round(rms_az, 4)
        data["superficie"] = superficie
        data["classe"] = classe

        registros_arestas.append({
            "comprimento_m": round(d, 2),
            "rms_az_ms2": round(rms_az, 4),
            "inclinacao_rad": round(inclinacao_rad, 4),
            "inclinacao_pct": round(inclinacao_pct, 2),
            "classe": classe
        })

    return G, pd.DataFrame(registros_arestas), fonte_elev

# ==============================================================================
# MÓDULO 2: ALGORITMOS II (A* vs DIJKSTRA COM MIN-HEAP)
# ==============================================================================

def atualizar_pesos_dinamicos(G, alpha, beta, bloqueio_coords=None):
    for u, v, k, data in G.edges(keys=True, data=True):
        d = data.get("length", 10.0)
        pen_inc = data["inclinacao_pct"] / 8.33
        pen_rug = data["rms_az_ms2"] / 1.5
        classe = data["classe"]

        if bloqueio_coords:
            lat_u, lon_u = G.nodes[u]["y"], G.nodes[u]["x"]
            if math.hypot(bloqueio_coords[0] - lat_u, bloqueio_coords[1] - lon_u) < 0.00035:
                classe = 3

        data["classe_efetiva"] = classe
        if classe == 3:
            data["peso_acessivel"] = d * 60.0
        else:
            data["peso_acessivel"] = d * (1.0 + alpha * pen_inc + beta * pen_rug)

def busca_min_heap(G, origem, destino, atributo_peso="peso_acessivel", usar_heuristica=True):
    t0 = time.perf_counter()
    fila = [(0.0, origem)]
    veio_de = {}
    custo_g = {no: float("inf") for no in G.nodes}
    custo_g[origem] = 0.0
    nos_expandidos = 0
    lat_dest, lon_dest = G.nodes[destino]["y"], G.nodes[destino]["x"]

    while fila:
        _, atual = heapq.heappop(fila)
        nos_expandidos += 1

        if atual == destino:
            caminho = []
            while atual in veio_de:
                caminho.append(atual)
                atual = veio_de[atual]
            caminho.append(origem)
            return caminho[::-1], custo_g[destino], nos_expandidos, (time.perf_counter() - t0) * 1000.0

        for vizinho in G.neighbors(atual):
            arestas = G.get_edge_data(atual, vizinho)
            peso_aresta = min(attr.get(atributo_peso, attr.get("length", 1.0)) for attr in arestas.values())
            tentativa_g = custo_g[atual] + peso_aresta

            if tentativa_g < custo_g[vizinho]:
                veio_de[vizinho] = atual
                custo_g[vizinho] = tentativa_g
                h = distancia_haversine(G.nodes[vizinho]["y"], G.nodes[vizinho]["x"], lat_dest, lon_dest) if usar_heuristica else 0.0
                heapq.heappush(fila, (tentativa_g + h, vizinho))

    return [], float("inf"), nos_expandidos, (time.perf_counter() - t0) * 1000.0

def analisar_rota(G, caminho):
    if len(caminho) < 2:
        return 0.0, 0.0, 0.0, []
    dist_total, soma_rms, max_inc = 0.0, 0.0, 0.0
    alertas = []
    trechos = 0

    for u, v in zip(caminho[:-1], caminho[1:]):
        melhor_aresta = min(G.get_edge_data(u, v).values(), key=lambda a: a.get("peso_acessivel", a.get("length", 1.0)))
        dist_total += melhor_aresta.get("length", 0.0)
        rms = melhor_aresta.get("rms_az_ms2", 0.0)
        inc = melhor_aresta.get("inclinacao_pct", 0.0)
        nome_rua = melhor_aresta.get("name", "Via sem nome")
        if isinstance(nome_rua, list):
            nome_rua = nome_rua[0]

        soma_rms += rms
        max_inc = max(max_inc, inc)
        trechos += 1

        if inc > 8.33 or rms > 2.2:
            motivo = f"Inclinação de {inc:.1f}% (> NBR 9050)" if inc > 8.33 else f"Piso irregular ({rms:.2f} m/s²)"
            alertas.append({
                "coord": (G.nodes[u]["y"], G.nodes[u]["x"]),
                "rua": nome_rua,
                "motivo": motivo
            })

    return dist_total, (soma_rms / max(trechos, 1)), max_inc, alertas

# ==============================================================================
# INTERFACE STREAMLIT (MVP)
# ==============================================================================

st.title("♿ CadeiWaze — Sistema Inteligente de Locomoção Open Source")
st.markdown(
    "Roteamento urbano acessível baseado em **altimetria real (SRTM)**, **pavimentação (OpenStreetMap)**, "
    "**norma ABNT NBR 9050** e **algoritmo A* com Min-Heap**."
)

with st.sidebar:
    st.header("1. Polo Urbano")
    cidade = st.selectbox("Cidade Base", list(CIDADES_CONFIG.keys()))
    cfg = CIDADES_CONFIG[cidade]
    st.caption(cfg["perfil_desc"])

    st.header("2. Definir Trajeto (Origem → Destino)")
    end_origem = st.text_input("Endereço de Origem", value=cfg["origem_padrao"])
    end_destino = st.text_input("Endereço de Destino", value=cfg["destino_padrao"])

    st.header("3. Perfil da Cadeira de Rodas")
    perfil = st.radio(
        "Tipo de Propulsão",
        ["Cadeira Manual (Penaliza rampas íngremes)", "Cadeira Motorizada (Penaliza trepidação)"]
    )
    alpha_def, beta_def = (3.5, 2.0) if "Manual" in perfil else (1.2, 3.5)
    alpha = st.slider("Peso Inclinação (α — NBR 9050)", 0.5, 5.0, alpha_def, 0.1)
    beta = st.slider("Peso Rugosidade (β — Vibração RMS)", 0.5, 5.0, beta_def, 0.1)

    st.header("4. Reporte Colaborativo")
    simular_barreira = st.checkbox("Simular bloqueio/obra temporária na rota curta", value=True)

# Geocodificação dos endereços digitados
orig_coords, ok_orig = geocodificar_endereco(end_origem, cfg["coord_fallback_orig"])
dest_coords, ok_dest = geocodificar_endereco(end_destino, cfg["coord_fallback_dest"])

if not ok_orig or not ok_dest:
    st.warning("Um dos endereços não foi localizado exatamente no OpenStreetMap; utilizando coordenada de referência do polo.")

G, df_arestas, fonte_elevacao = construir_grafo_rota(orig_coords, dest_coords, cfg["prob_paralelepipedo"], cidade)

# Classificador ML
X = df_arestas[["rms_az_ms2", "inclinacao_rad", "comprimento_m"]]
y = df_arestas["classe"]
clf = RandomForestClassifier(n_estimators=60, random_state=42)
acuracia_cv = cross_val_score(clf, X, y, cv=3).mean() * 100.0 if len(y.unique()) > 1 else 100.0
clf.fit(X, y)

no_origem = ox.distance.nearest_nodes(G, X=orig_coords[1], Y=orig_coords[0])
no_destino = ox.distance.nearest_nodes(G, X=dest_coords[1], Y=dest_coords[0])

# Rota convencional (menor distância)
rota_curta, _, _, _ = busca_min_heap(G, no_origem, no_destino, atributo_peso="length", usar_heuristica=True)

ponto_bloqueio = None
if simular_barreira and len(rota_curta) > 2:
    no_meio = rota_curta[len(rota_curta) // 2]
    ponto_bloqueio = (G.nodes[no_meio]["y"], G.nodes[no_meio]["x"])

# Rota CadeiWaze (A* vs Dijkstra)
atualizar_pesos_dinamicos(G, alpha, beta, bloqueio_coords=ponto_bloqueio)
rota_astar, custo_astar, nos_astar, tempo_astar = busca_min_heap(G, no_origem, no_destino, "peso_acessivel", usar_heuristica=True)
rota_dijk, custo_dijk, nos_dijk, tempo_dijk = busca_min_heap(G, no_origem, no_destino, "peso_acessivel", usar_heuristica=False)

dist_curta, rms_curta, inc_curta, _ = analisar_rota(G, rota_curta)
dist_acess, rms_acess, inc_acess, alertas_rota = analisar_rota(G, rota_astar)

st.caption(f"**Fonte Altimétrica:** {fonte_elevacao} | **Grafo:** $|V| = {G.number_of_nodes()}$ vértices, $|E| = {G.number_of_edges()}$ arestas")

# Indicadores Principais
c1, c2, c3, c4 = st.columns(4)
c1.metric("Distância Rota Acessível", f"{dist_acess:.0f} m", f"+{max(0.0, dist_acess - dist_curta):.0f} m vs. curta")
c2.metric("Vibração Média (RMS)", f"{rms_acess:.2f} m/s²", f"{rms_acess - rms_curta:.2f} m/s²")
c3.metric("Inclinação Máx. na Rota", f"{inc_acess:.1f} %", f"Padrão: {inc_curta:.1f} %")
c4.metric("Eficiência A* vs. Dijkstra", f"{nos_astar} nós", f"Dijkstra visitou {nos_dijk} nós")

col_mapa, col_dados = st.columns([1.35, 1.0])

with col_mapa:
    st.subheader("Mapa de Navegação e Alertas")
    if not rota_astar:
        st.error("Não foi possível encontrar um caminho contínuo entre os pontos dentro do raio do grafo. Tente endereços mais próximos.")
    else:
        centro = [(orig_coords[0] + dest_coords[0]) / 2, (orig_coords[1] + dest_coords[1]) / 2]
        mapa = folium.Map(location=centro, zoom_start=15)

        coords_curta = [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in rota_curta]
        coords_acess = [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in rota_astar]

        folium.PolyLine(coords_curta, color="#d9534f", weight=4, opacity=0.7, tooltip="Rota Convencional (Menor Distância)").add_to(mapa)
        folium.PolyLine(coords_acess, color="#28a745", weight=6, opacity=0.9, tooltip="Rota CadeiWaze (Mais Acessível)").add_to(mapa)

        folium.Marker(orig_coords, tooltip=f"Origem: {end_origem}", icon=folium.Icon(color="blue", icon="play")).add_to(mapa)
        folium.Marker(dest_coords, tooltip=f"Destino: {end_destino}", icon=folium.Icon(color="green", icon="flag")).add_to(mapa)

        if ponto_bloqueio:
            folium.Marker(ponto_bloqueio, tooltip="Barreira Temporária Reportada", icon=folium.Icon(color="red", icon="ban-circle")).add_to(mapa)

        for al in alertas_rota[:5]:
            folium.CircleMarker(
                location=al["coord"],
                radius=6,
                color="orange",
                fill=True,
                tooltip=f"Atenção ({al['rua']}): {al['motivo']}"
            ).add_to(mapa)

        components.html(mapa._repr_html_(), height=460)

with col_dados:
    st.subheader("Alertas ao Longo do Percurso")
    if alertas_rota:
        for al in alertas_rota[:4]:
            st.warning(f"**{al['rua']}**: {al['motivo']}")
    else:
        st.success("Nenhum trecho crítico encontrado na rota acessível selecionada.")

    st.subheader("Benchmark: Algoritmos II (Min-Heap)")
    df_bench = pd.DataFrame([
        {"Algoritmo": "A* (Heurística Haversine)", "Nós Expandidos": nos_astar, "Tempo (ms)": round(tempo_astar, 3), "Custo Ótimo": round(custo_astar, 1)},
        {"Algoritmo": "Dijkstra Clássico", "Nós Expandidos": nos_dijk, "Tempo (ms)": round(tempo_dijk, 3), "Custo Ótimo": round(custo_dijk, 1)}
    ])
    st.table(df_bench)

    st.subheader("Métricas da Malha Urbana (SI)")
    df_resumo_si = pd.DataFrame({
        "Parâmetro (SI)": ["Rugosidade RMS (m/s²)", "Inclinação (rad)", "Inclinação (%)"],
        "Média": [
            round(df_arestas["rms_az_ms2"].mean(), 3),
            round(df_arestas["inclinacao_rad"].mean(), 4),
            round(df_arestas["inclinacao_pct"].mean(), 2)
        ],
        "Máximo": [
            round(df_arestas["rms_az_ms2"].max(), 3),
            round(df_arestas["inclinacao_rad"].max(), 4),
            round(df_arestas["inclinacao_pct"].max(), 2)
        ]
    })
    st.table(df_resumo_si)