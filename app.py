import heapq
import math
import os
import time
import requests
import numpy as np
import pandas as pd
import networkx as nx
import osmnx as ox
import folium
import streamlit as st
import streamlit.components.v1 as components

# ==============================================================================
# CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(
    page_title="CadeiWaze | Roteamento Acessível Open Source",
    layout="wide"
)

OVERPASS_MIRRORS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

CIDADES_CONFIG = {
    "Santo Amaro, Bahia, Brazil": {
        "centro": (-12.5455, -38.7110),
        "raio_m": 1200,
        "prob_paralelepipedo": 0.45,
        "perfil_desc": "Centro histórico: alta incidência de paralelepípedo (sett) e calçadas estreitas.",
        "locais_sugeridos": {
            "Praça da Purificação, Santo Amaro, BA": (-12.5472, -38.7128),
            "CECULT / UFRB, Santo Amaro, BA": (-12.5435, -38.7088),
            "Terminal Rodoviário de Santo Amaro, BA": (-12.5495, -38.7145),
            "Mercado Municipal de Santo Amaro, BA": (-12.5463, -38.7102),
            "Santa Casa de Misericórdia, Santo Amaro, BA": (-12.5441, -38.7132),
        }
    },
    "Feira de Santana, Bahia, Brazil": {
        "centro": (-12.2555, -38.9645),
        "raio_m": 1300,
        "prob_paralelepipedo": 0.15,
        "perfil_desc": "Malha urbana ampla: predominância de asfalto com desníveis pontuais.",
        "locais_sugeridos": {
            "Terminal Central, Feira de Santana, BA": (-12.2575, -38.9675),
            "Prefeitura Municipal, Feira de Santana, BA": (-12.2552, -38.9631),
            "Praça da Matriz, Feira de Santana, BA": (-12.2588, -38.9658),
            "Hospital Geral Clériston Andrade, Feira de Santana, BA": (-12.2485, -38.9580),
            "Estação Rodoviária de Feira de Santana, BA": (-12.2512, -38.9555),
        }
    },
    "Recife, Pernambuco, Brazil": {
        "centro": (-8.0565, -34.8920),
        "raio_m": 1300,
        "prob_paralelepipedo": 0.20,
        "perfil_desc": "Malha costeira densa: trechos planos alternados com pontes e rampas.",
        "locais_sugeridos": {
            "Praça do Derby, Recife, PE": (-8.0556, -34.8981),
            "Universidade Católica de Pernambuco (UNICAP), Recife, PE": (-8.0558, -34.8878),
            "Parque Treze de Maio, Recife, PE": (-8.0582, -34.8815),
            "Hospital da Restauração, Recife, PE": (-8.0542, -34.8965),
            "Mercado da Boa Vista, Recife, PE": (-8.0628, -34.8889),
        }
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
# MÓDULO 1: EXTRAÇÃO GEOESPACIAL E MODELAGEM FÍSICA (SISTEMA INTERNACIONAL)
# ==============================================================================

def distancia_haversine(lat1, lon1, lat2, lon2):
    """Calcula a distância geodésica em metros (SI) entre duas coordenadas."""
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

@st.cache_data(show_spinner=False)
def geocodificar_endereco(endereco, fallback_coords):
    """Converte endereço textual em coordenadas geográficas via OpenStreetMap."""
    try:
        lat, lon = ox.geocode(endereco)
        return (float(lat), float(lon)), True
    except Exception:
        return fallback_coords, False

def _gerar_malha_fallback(centro, seed_str):
    """Gera malha viária regular georreferenciada caso as APIs externas estejam indisponíveis."""
    G_grid = nx.MultiDiGraph(crs="epsg:4326")
    lat0, lon0 = centro
    passo = 0.0009
    n = 8
    rng = np.random.default_rng(sum(ord(c) for c in seed_str))

    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            nid = (i + n) * (2 * n + 1) + (j + n)
            G_grid.add_node(nid, y=lat0 + i * passo, x=lon0 + j * passo)

    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            u = (i + n) * (2 * n + 1) + (j + n)
            for di, dj in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                ni, nj = i + di, j + dj
                if -n <= ni <= n and -n <= nj <= n:
                    v = (ni + n) * (2 * n + 1) + (nj + n)
                    dist = distancia_haversine(
                        G_grid.nodes[u]["y"], G_grid.nodes[u]["x"],
                        G_grid.nodes[v]["y"], G_grid.nodes[v]["x"]
                    )
                    rua = f"Rua Setor {abs(i)+1}" if di == 0 else f"Avenida Transversal {abs(j)+1}"
                    if rng.random() > 0.08:
                        G_grid.add_edge(u, v, key=0, length=dist, name=rua)
    return G_grid

def adicionar_elevacao_real(G, seed_str):
    """Consulta a altitude (m) dos nós do grafo via modelo digital de elevação SRTM."""
    nos = list(G.nodes(data=True))
    locations = [{"latitude": data["y"], "longitude": data["x"]} for _, data in nos]
    elevacoes = []
    fonte_dados = "Open-Elevation API (SRTM)"

    try:
        for i in range(0, len(locations), 200):
            lote = locations[i:i+200]
            resp = requests.post(
                "https://api.open-elevation.com/api/v1/lookup",
                json={"locations": lote},
                timeout=5
            )
            resp.raise_for_status()
            elevacoes.extend([r["elevation"] for r in resp.json()["results"]])
        if len(elevacoes) != len(nos):
            raise ValueError("Inconsistência no total de pontos altimétricos")
    except Exception:
        fonte_dados = "Modelo Topográfico Parametrizado"
        rng = np.random.default_rng(sum(ord(c) for c in seed_str))
        elevacoes = [
            round(float(15.0 + 18.0 * math.sin(d["y"] * 900.0) * math.cos(d["x"] * 900.0) + rng.normal(0, 0.3)), 2)
            for _, d in nos
        ]

    for (node_id, _), elev in zip(nos, elevacoes):
        G.nodes[node_id]["elevation"] = float(elev)

    return fonte_dados

@st.cache_resource(show_spinner="Carregando malha viária da cidade...")
def carregar_grafo_cidade(cidade_nome):
    """Constrói e enriquece o multigrafo direcionado da malha viária do município."""
    cfg = CIDADES_CONFIG[cidade_nome]
    os.makedirs("cache_mapas", exist_ok=True)
    slug = "".join(c if c.isalnum() else "_" for c in cidade_nome.lower())[:25]
    arquivo_cache = os.path.join("cache_mapas", f"{slug}.graphml")

    G = None
    fonte_osm = ""

    if os.path.exists(arquivo_cache):
        G = ox.load_graphml(arquivo_cache)
        fonte_osm = "OpenStreetMap (Cache Local)"
    else:
        for mirror in OVERPASS_MIRRORS:
            try:
                ox.settings.overpass_url = mirror
                ox.settings.requests_timeout = 12
                G = ox.graph_from_point(cfg["centro"], dist=cfg["raio_m"], network_type="walk")
                ox.save_graphml(G, arquivo_cache)
                fonte_osm = f"OpenStreetMap ({mirror.split('/')[2]})"
                break
            except Exception:
                continue

    if G is None:
        G = _gerar_malha_fallback(cfg["centro"], cidade_nome)
        fonte_osm = "Malha Urbana Parametrizada"

    fonte_elev = adicionar_elevacao_real(G, cidade_nome)
    rng = np.random.default_rng(42)
    registros = []

    for u, v, k, data in G.edges(keys=True, data=True):
        d = max(float(data.get("length", 5.0)), 1.0)
        delta_h = abs(G.nodes[v].get("elevation", 0.0) - G.nodes[u].get("elevation", 0.0))
        inclinacao_pct = min((delta_h / max(d, 20.0)) * 100.0, 25.0)
        inclinacao_rad = math.atan(inclinacao_pct / 100.0)

        raw_surface = data.get("surface")
        if isinstance(raw_surface, list):
            raw_surface = raw_surface[0]

        if raw_surface in SUPERFICIE_RMS_MAP:
            superficie = raw_surface
        else:
            superficie = "sett" if rng.random() < cfg["prob_paralelepipedo"] else "asphalt"

        media_rms, std_rms = SUPERFICIE_RMS_MAP[superficie]
        rms_az = max(0.15, float(rng.normal(media_rms, std_rms)))

        if inclinacao_pct > 12.0 or rms_az > 3.1:
            classe = 3
        elif inclinacao_pct > 8.33:
            classe = 2
        elif rms_az > 1.5:
            classe = 1
        else:
            classe = 0

        data["inclinacao_pct"] = round(inclinacao_pct, 2)
        data["inclinacao_rad"] = round(inclinacao_rad, 4)
        data["rms_az_ms2"] = round(rms_az, 4)
        data["superficie"] = superficie
        data["classe"] = classe

        registros.append({
            "comprimento_m": round(d, 2),
            "rms_az_ms2": round(rms_az, 4),
            "inclinacao_rad": round(inclinacao_rad, 4),
            "inclinacao_pct": round(inclinacao_pct, 2),
            "classe": classe
        })

    return G, pd.DataFrame(registros), f"{fonte_osm} + {fonte_elev}"

# ==============================================================================
# MÓDULO 2: ALGORITMOS EM GRAFOS (A* E DIJKSTRA COM MIN-HEAP)
# ==============================================================================

def atualizar_pesos_dinamicos(G, alpha, beta, bloqueio_coords=None):
    """Aplica a função de custo multiobjetivo w(e) e bloqueios dinâmicos às arestas."""
    for u, v, k, data in G.edges(keys=True, data=True):
        d = float(data.get("length", 10.0))
        pen_inc = data["inclinacao_pct"] / 8.33
        pen_rug = data["rms_az_ms2"] / 1.5
        classe = data["classe"]

        bloqueada = False
        if bloqueio_coords:
            lat_u, lon_u = G.nodes[u]["y"], G.nodes[u]["x"]
            lat_v, lon_v = G.nodes[v]["y"], G.nodes[v]["x"]
            dist_u = distancia_haversine(bloqueio_coords[0], bloqueio_coords[1], lat_u, lon_u)
            dist_v = distancia_haversine(bloqueio_coords[0], bloqueio_coords[1], lat_v, lon_v)
            if min(dist_u, dist_v) <= 35.0:
                bloqueada = True

        data["bloqueada"] = bloqueada
        if bloqueada:
            data["peso_acessivel"] = float("inf")
        elif classe == 3:
            data["peso_acessivel"] = d * 60.0
        else:
            data["peso_acessivel"] = d * (1.0 + alpha * pen_inc + beta * pen_rug)

def busca_min_heap(G, origem, destino, atributo_peso="peso_acessivel", usar_heuristica=True):
    """Executa busca A* ou Dijkstra utilizando fila de prioridade binária (Min-Heap)."""
    t0 = time.perf_counter()
    fila = [(0.0, origem)]
    veio_de = {}
    custo_g = {no: float("inf") for no in G.nodes}
    custo_g[origem] = 0.0
    fechados = set()
    nos_expandidos = 0
    lat_dest, lon_dest = G.nodes[destino]["y"], G.nodes[destino]["x"]

    while fila:
        _, atual = heapq.heappop(fila)
        if atual in fechados:
            continue
        fechados.add(atual)
        nos_expandidos += 1

        if atual == destino:
            caminho = []
            while atual in veio_de:
                caminho.append(atual)
                atual = veio_de[atual]
            caminho.append(origem)
            return caminho[::-1], custo_g[destino], nos_expandidos, (time.perf_counter() - t0) * 1000.0

        for vizinho in G.neighbors(atual):
            if vizinho in fechados:
                continue
            arestas = G.get_edge_data(atual, vizinho)
            peso_aresta = min(float(attr.get(atributo_peso, attr.get("length", 1.0))) for attr in arestas.values())
            if math.isinf(peso_aresta):
                continue

            tentativa_g = custo_g[atual] + peso_aresta
            if tentativa_g < custo_g[vizinho]:
                veio_de[vizinho] = atual
                custo_g[vizinho] = tentativa_g
                h = distancia_haversine(G.nodes[vizinho]["y"], G.nodes[vizinho]["x"], lat_dest, lon_dest) if usar_heuristica else 0.0
                heapq.heappush(fila, (tentativa_g + h, vizinho))

    return [], float("inf"), nos_expandidos, (time.perf_counter() - t0) * 1000.0

def analisar_rota(G, caminho, atributo_selecao="peso_acessivel"):
    """Extrai métricas físicas (SI), alertas normativos e perfil longitudinal da rota."""
    if len(caminho) < 2:
        return 0.0, 0.0, 0.0, [], [], {}
    dist_total, soma_rms, max_inc = 0.0, 0.0, 0.0
    alertas = []
    perfil_trechos = []
    pontos_bloqueaveis = {}
    dist_acumulada = 0.0

    for idx, (u, v) in enumerate(zip(caminho[:-1], caminho[1:]), start=1):
        melhor_aresta = min(
            G.get_edge_data(u, v).values(),
            key=lambda a: float(a.get(atributo_selecao, a.get("length", 1.0)))
        )
        comp = float(melhor_aresta.get("length", 0.0))
        rms = float(melhor_aresta.get("rms_az_ms2", 0.0))
        inc = float(melhor_aresta.get("inclinacao_pct", 0.0))
        nome_rua = melhor_aresta.get("name", "Via sem nome")
        if isinstance(nome_rua, list):
            nome_rua = nome_rua[0]

        dist_total += comp
        dist_acumulada += comp
        soma_rms += rms * comp
        max_inc = max(max_inc, inc)

        if 1 < idx < len(caminho) - 1:
            rotulo_ponto = f"Trecho {idx}: {nome_rua} ({round(dist_acumulada)} m)"
            pontos_bloqueaveis[rotulo_ponto] = (G.nodes[u]["y"], G.nodes[u]["x"])

        perfil_trechos.append({
            "Distância (m)": round(dist_acumulada, 0),
            "Inclinação (%)": inc,
            "Rugosidade (m/s²)": rms
        })

        if inc > 8.33 or rms > 2.2:
            motivo = f"Inclinação de {inc:.1f}% (> NBR 9050)" if inc > 8.33 else f"Piso irregular ({rms:.2f} m/s²)"
            alertas.append({
                "coord": (G.nodes[u]["y"], G.nodes[u]["x"]),
                "rua": nome_rua,
                "motivo": motivo
            })

    rms_medio = soma_rms / dist_total if dist_total > 0 else 0.0
    return dist_total, rms_medio, max_inc, alertas, perfil_trechos, pontos_bloqueaveis

# ==============================================================================
# INTERFACE DE NAVEGAÇÃO E ANÁLISE (STREAMLIT)
# ==============================================================================

st.title("CadeiWaze — Sistema Inteligente de Locomoção Open Source")
st.markdown(
    "Roteamento urbano acessível baseado em **altimetria (SRTM)**, **pavimentação (OpenStreetMap)**, "
    "**norma ABNT NBR 9050** e **algoritmo A* com Min-Heap**."
)

with st.sidebar:
    st.header("1. Polo Urbano")
    cidade = st.selectbox("Cidade Base", list(CIDADES_CONFIG.keys()))
    cfg = CIDADES_CONFIG[cidade]
    st.caption(cfg["perfil_desc"])

    with st.form("form_trajeto"):
        st.header("2. Definir Trajeto (Origem para Destino)")
        nomes_locais = list(cfg["locais_sugeridos"].keys()) + ["Outro endereço (digitar)..."]

        sel_orig = st.selectbox("Ponto de Origem (Sugestões)", nomes_locais, index=0)
        txt_orig = st.text_input("Ou digite o endereço de origem", placeholder="Ex: Rua da Matriz, Santo Amaro, BA")

        sel_dest = st.selectbox("Ponto de Destino (Sugestões)", nomes_locais, index=1)
        txt_dest = st.text_input("Ou digite o endereço de destino", placeholder="Ex: Praça da Purificação, Santo Amaro, BA")

        st.header("3. Perfil da Cadeira de Rodas")
        perfil = st.radio(
            "Tipo de Propulsão",
            ["Cadeira Manual (Penaliza rampas íngremes)", "Cadeira Motorizada (Penaliza trepidação)"]
        )
        alpha_def, beta_def = (3.5, 2.0) if "Manual" in perfil else (1.2, 3.5)
        alpha = st.slider("Peso Inclinação (alpha — NBR 9050)", 0.5, 5.0, alpha_def, 0.1)
        beta = st.slider("Peso Rugosidade (beta — Vibração RMS)", 0.5, 5.0, beta_def, 0.1)
        limite_desvio_pct = st.slider("Alerta de desvio máximo (%)", 10, 100, 35, 5)

        st.form_submit_button("Pesquisar Trajeto", use_container_width=True)

G, df_arestas, fonte_dados = carregar_grafo_cidade(cidade)

if sel_orig == "Outro endereço (digitar)..." and txt_orig.strip():
    end_origem_label = txt_orig.strip()
    orig_coords, ok_orig = geocodificar_endereco(end_origem_label, cfg["centro"])
else:
    end_origem_label = sel_orig if sel_orig != "Outro endereço (digitar)..." else nomes_locais[0]
    orig_coords = cfg["locais_sugeridos"][end_origem_label]
    ok_orig = True

if sel_dest == "Outro endereço (digitar)..." and txt_dest.strip():
    end_destino_label = txt_dest.strip()
    dest_coords, ok_dest = geocodificar_endereco(end_destino_label, cfg["centro"])
else:
    end_destino_label = sel_dest if sel_dest != "Outro endereço (digitar)..." else nomes_locais[1]
    dest_coords = cfg["locais_sugeridos"][end_destino_label]
    ok_dest = True

if not ok_orig or not ok_dest:
    st.warning("Endereço digitado não encontrado com precisão no OpenStreetMap; usando referência próxima do polo.")

no_origem = ox.distance.nearest_nodes(G, X=orig_coords[1], Y=orig_coords[0])
no_destino = ox.distance.nearest_nodes(G, X=dest_coords[1], Y=dest_coords[0])

rota_curta, _, _, _ = busca_min_heap(G, no_origem, no_destino, atributo_peso="length", usar_heuristica=True)
dist_curta, rms_curta, inc_curta, _, perfil_curta, pontos_rota_curta = analisar_rota(G, rota_curta, "length")

with st.sidebar:
    st.divider()
    st.header("4. Reporte Colaborativo")
    opcoes_bloqueio = ["Nenhum obstáculo reportado"] + list(pontos_rota_curta.keys())
    local_bloqueado = st.selectbox(
        "Sinalizar obra ou bloqueio em um ponto da via:",
        opcoes_bloqueio,
        help="Selecione um trecho específico para interditar a via e recalcular a rota."
    )

ponto_bloqueio = pontos_rota_curta.get(local_bloqueado)

atualizar_pesos_dinamicos(G, alpha, beta, bloqueio_coords=ponto_bloqueio)
rota_astar, custo_astar, nos_astar, tempo_astar = busca_min_heap(G, no_origem, no_destino, "peso_acessivel", usar_heuristica=True)
rota_dijk, custo_dijk, nos_dijk, tempo_dijk = busca_min_heap(G, no_origem, no_destino, "peso_acessivel", usar_heuristica=False)

dist_acess, rms_acess, inc_acess, alertas_rota, perfil_acess, _ = analisar_rota(G, rota_astar, "peso_acessivel")

st.caption(f"**Base Cartográfica:** {fonte_dados} | **Grafo:** |V| = {G.number_of_nodes()} vértices, |E| = {G.number_of_edges()} arestas")

if dist_curta > 0 and dist_acess > 0:
    acrescimo_pct = ((dist_acess - dist_curta) / dist_curta) * 100.0
    if acrescimo_pct > limite_desvio_pct:
        st.warning(
            f"**Aviso de Trade-off (Distância vs. Acessibilidade):** A rota mais acessível é **{acrescimo_pct:.1f}% mais longa** "
            f"({dist_acess:.0f} m contra {dist_curta:.0f} m da rota curta). Avalie se a autonomia da bateria ou o esforço físico "
            f"comporta o desvio, ou reduza os pesos alpha e beta para uma rota intermediária."
        )

c1, c2, c3, c4 = st.columns(4)
c1.metric("Distância Rota Acessível", f"{dist_acess:.0f} m", f"+{max(0.0, dist_acess - dist_curta):.0f} m vs. curta")
c2.metric("Vibração Média (RMS)", f"{rms_acess:.2f} m/s²", f"{rms_acess - rms_curta:.2f} m/s²")
c3.metric("Inclinação Máx. na Rota", f"{inc_acess:.1f} %", f"Padrão: {inc_curta:.1f} %")
c4.metric("Eficiência A* vs. Dijkstra", f"{nos_astar} nós", f"Dijkstra visitou {nos_dijk} nós")

col_mapa, col_dados = st.columns([1.35, 1.0])

with col_mapa:
    st.subheader("Mapa de Navegação e Alertas")
    if not rota_astar:
        st.error("Não foi possível encontrar um caminho contínuo sem atravessar o ponto bloqueado. Selecione outro trecho ou remova o bloqueio.")
    else:
        centro = [(orig_coords[0] + dest_coords[0]) / 2, (orig_coords[1] + dest_coords[1]) / 2]
        mapa = folium.Map(location=centro, zoom_start=15)

        coords_curta = [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in rota_curta]
        coords_acess = [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in rota_astar]

        folium.PolyLine(coords_curta, color="#E63946", weight=4, opacity=0.75, tooltip="Rota Convencional (Menor Distância)").add_to(mapa)
        folium.PolyLine(coords_acess, color="#2A9D8F", weight=6, opacity=0.95, tooltip="Rota CadeiWaze (Mais Acessível)").add_to(mapa)

        folium.Marker(orig_coords, tooltip=f"Origem: {end_origem_label}", icon=folium.Icon(color="blue", icon="play")).add_to(mapa)
        folium.Marker(dest_coords, tooltip=f"Destino: {end_destino_label}", icon=folium.Icon(color="green", icon="flag")).add_to(mapa)

        if ponto_bloqueio:
            folium.Marker(
                ponto_bloqueio,
                tooltip=f"Bloqueio Reportado: {local_bloqueado}",
                icon=folium.Icon(color="red", icon="ban-circle")
            ).add_to(mapa)

        for al in alertas_rota[:5]:
            folium.CircleMarker(
                location=al["coord"],
                radius=6,
                color="orange",
                fill=True,
                tooltip=f"Atenção ({al['rua']}): {al['motivo']}"
            ).add_to(mapa)

        components.html(mapa._repr_html_(), height=480)

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

# ==============================================================================
# SEÇÃO DE GRÁFICOS COMPARATIVOS (EMPILHADOS VERTICALMENTE E COM ALTO CONTRASTE)
# ==============================================================================
st.divider()
st.subheader("Análise Visual: Rota Convencional vs. Rota CadeiWaze")

st.markdown("**1. Comparativo Geral de Esforço e Distância (Barras Agrupadas)**")
df_comp = pd.DataFrame({
    "Métrica": ["Distância (m)", "Vibração Média (x100 m/s²)", "Inclinação Máx. (x10 %)"],
    "Rota Convencional (Curta)": [round(dist_curta, 1), round(rms_curta * 100, 1), round(inc_curta * 10, 1)],
    "Rota CadeiWaze (Acessível)": [round(dist_acess, 1), round(rms_acess * 100, 1), round(inc_acess * 10, 1)]
}).set_index("Métrica")
st.bar_chart(
    df_comp,
    stack=False,
    color=["#E63946", "#2A9D8F"],
    height=340
)

st.markdown("**2. Perfil de Inclinação (%) e Rugosidade (m/s²) ao Longo da Rota Acessível**")
if perfil_acess:
    df_perfil = pd.DataFrame(perfil_acess).set_index("Distância (m)")
    st.line_chart(
        df_perfil[["Inclinação (%)", "Rugosidade (m/s²)"]],
        color=["#F4A261", "#9B5DE5"],
        height=340
    )