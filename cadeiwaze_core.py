import heapq
import math
import numpy as np
import pandas as pd
import osmnx as ox
import folium
from sklearn.ensemble import RandomForestClassifier

# ==============================================================================
# MÓDULO 1: PROCESSAMENTO DE TELEMETRIA INERCIAL (SENSOR LOGGER -> SI)
# ==============================================================================

def gerar_csv_exemplo(caminho="coleta_santo_amaro.csv"):
    """
    Gera um CSV no formato padrão do Sensor Logger para testes imediatos
    antes da coleta em campo nas 3 cidades.
    """
    np.random.seed(42)
    n = 300  # 6 segundos a 50 Hz
    tempo = np.linspace(0, 6, n)
    
    # Simula coordenadas em Santo Amaro - BA (Centro Histórico)
    lat = np.linspace(-12.5468, -12.5455, n)
    lon = np.linspace(-38.7122, -38.7108, n)
    
    # Trecho 1: calçada plana | Trecho 2: paralelepípedo | Trecho 3: rampa íngreme
    az = np.concatenate([
        np.random.normal(0.0, 0.35, 100),   # Baixa trepidação (m/s²)
        np.random.normal(0.0, 2.80, 100),   # Alta trepidação - paralelepípedo (m/s²)
        np.random.normal(0.0, 0.90, 100)    # Trepidação moderada na rampa (m/s²)
    ])
    pitch_rad = np.concatenate([
        np.random.normal(0.02, 0.005, 100), # ~2% inclinação (dentro da NBR 9050)
        np.random.normal(0.03, 0.010, 100), # ~3% inclinação
        np.random.normal(0.14, 0.015, 100)  # ~14% inclinação (crítica > 8.33%)
    ])
    
    df = pd.DataFrame({
        "seconds_elapsed": tempo,
        "latitude": lat,
        "longitude": lon,
        "accelerometer_z": az,        # m/s² (SI)
        "orientation_pitch": pitch_rad  # radianos (SI)
    })
    df.to_csv(caminho, index=False)
    return df

def extrair_metricas_si(df, janela=50):
    """
    Processa janelas temporais (ex: 50 amostras = 1 segundo a 50 Hz)
    e calcula rugosidade RMS (m/s²) e inclinação média (rad e %).
    """
    segmentos = []
    for i in range(0, len(df) - janela, janela):
        bloco = df.iloc[i:i+janela]
        
        # Raiz do Valor Quadrático Médio (RMS) da aceleração vertical (m/s²)
        rms_az = float(np.sqrt(np.mean(bloco["accelerometer_z"] ** 2)))
        
        # Inclinação média absoluta em radianos (SI) e percentual (ABNT NBR 9050)
        inclinacao_rad = float(np.mean(np.abs(bloco["orientation_pitch"])))
        inclinacao_pct = math.tan(inclinacao_rad) * 100.0
        
        # Rótulo heurístico inicial baseado na ABNT NBR 9050 (limite 8.33%)
        if inclinacao_pct > 12.0 or rms_az > 3.5:
            classe = 3  # Intransponível
        elif inclinacao_pct > 8.33:
            classe = 2  # Inclinação Crítica
        elif rms_az > 1.5:
            classe = 1  # Trepidação Moderada (Paralelepípedo/Irregular)
        else:
            classe = 0  # Via Acessível
            
        segmentos.append({
            "lat": bloco["latitude"].mean(),
            "lon": bloco["longitude"].mean(),
            "rms_az_ms2": round(rms_az, 4),
            "inclinacao_rad": round(inclinacao_rad, 4),
            "inclinacao_pct": round(inclinacao_pct, 2),
            "classe_acessibilidade": classe
        })
    return pd.DataFrame(segmentos)

def treinar_classificador_ml(df_segmentos):
    """
    Treina um Random Forest leve para classificar novos trechos
    a partir das assinaturas de vibração e inclinação.
    """
    X = df_segmentos[["rms_az_ms2", "inclinacao_rad"]]
    y = df_segmentos["classe_acessibilidade"]
    modelo = RandomForestClassifier(n_estimators=50, random_state=42)
    modelo.fit(X, y)
    return modelo


# ==============================================================================
# MÓDULO 2: ALGORITMOS II — GRAFO PONDERADO E BUSCA A* COM MIN-HEAP
# ==============================================================================

def distancia_haversine(lat1, lon1, lat2, lon2):
    """Calcula distância geodésica em metros (SI) para a heurística do A*."""
    R = 6371000.0  # Raio médio da Terra em metros (SI)
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def aplicar_pesos_acessibilidade(G, df_segmentos, alpha=2.5, beta=1.8):
    """
    Equação (1) do artigo:
    w(e) = d(e) * (1 + alpha * I(e) + beta * R(e))
    """
    for u, v, k, data in G.edges(keys=True, data=True):
        d = data.get("length", 10.0)  # distância em metros (SI)
        lat_u, lon_u = G.nodes[u]["y"], G.nodes[u]["x"]
        
        # Busca a telemetria coletada mais próxima da aresta (raio ~35 metros)
        dists = np.hypot(df_segmentos["lat"] - lat_u, df_segmentos["lon"] - lon_u)
        idx_min = dists.idxmin()
        
        if dists[idx_min] < 0.00035:
            amostra = df_segmentos.loc[idx_min]
            # Penalidade normalizada pela norma ABNT NBR 9050 (8.33%)
            penalidade_inclinacao = max(0.0, amostra["inclinacao_pct"] / 8.33)
            penalidade_rugosidade = amostra["rms_az_ms2"] / 1.5
            classe = int(amostra["classe_acessibilidade"])
        else:
            penalidade_inclinacao = 0.1
            penalidade_rugosidade = 0.1
            classe = 0
            
        data["classe"] = classe
        # Se a via for intransponível (classe 3), aplica custo proibitivo
        if classe == 3:
            data["peso_acessivel"] = d * 50.0
        else:
            data["peso_acessivel"] = d * (1.0 + alpha * penalidade_inclinacao + beta * penalidade_rugosidade)

def a_estrela_min_heap(G, origem, destino, atributo_peso="peso_acessivel"):
    """
    Implementação explícita do algoritmo A* usando Fila de Prioridade (Min-Heap).
    Complexidade de tempo: O((|V| + |E|) log |V|)
    """
    fila_prioridade = []
    heapq.heappush(fila_prioridade, (0.0, origem))
    
    veio_de = {}
    custo_g = {no: float("inf") for no in G.nodes}
    custo_g[origem] = 0.0
    
    lat_dest, lon_dest = G.nodes[destino]["y"], G.nodes[destino]["x"]
    
    while fila_prioridade:
        _, atual = heapq.heappop(fila_prioridade)
        
        if atual == destino:
            # Reconstrói o caminho ótimo
            caminho = []
            while atual in veio_de:
                caminho.append(atual)
                atual = veio_de[atual]
            caminho.append(origem)
            return caminho[::-1], custo_g[destino]
        
        for vizinho in G.neighbors(atual):
            # Pega a melhor aresta paralela entre atual e vizinho
            arestas = G.get_edge_data(atual, vizinho)
            peso_aresta = min(attr.get(atributo_peso, attr.get("length", 1.0)) for attr in arestas.values())
            
            tentativa_g = custo_g[atual] + peso_aresta
            if tentativa_g < custo_g[vizinho]:
                veio_de[vizinho] = atual
                custo_g[vizinho] = tentativa_g
                h = distancia_haversine(G.nodes[vizinho]["y"], G.nodes[vizinho]["x"], lat_dest, lon_dest)
                f = tentativa_g + h
                heapq.heappush(fila_prioridade, (f, vizinho))
                
    return [], float("inf")


# ==============================================================================
# MÓDULO 3: EXECUÇÃO COMPARATIVA E GERAÇÃO DO MAPA MVP
# ==============================================================================

if __name__ == "__main__":
    print("1. Processando telemetria inercial (SI)...")
    df_raw = gerar_csv_exemplo("coleta_santo_amaro.csv")
    df_metricas = extrair_metricas_si(df_raw)
    modelo_ml = treinar_classificador_ml(df_metricas)
    
    print("\n--- Resumo Estatístico para Tabela 1 do Artigo (SI) ---")
    print(df_metricas[["rms_az_ms2", "inclinacao_rad", "inclinacao_pct"]].describe().loc[["mean", "max"]])
    
    print("\n2. Baixando grafo viário de Santo Amaro - BA via OpenStreetMap...")
    # Pode trocar por "Feira de Santana, Bahia, Brazil" ou "Recife, Pernambuco, Brazil"
    G = ox.graph_from_place("Santo Amaro, Bahia, Brazil", network_type="walk")
    aplicar_pesos_acessibilidade(G, df_metricas)
    
    # Define origem e destino próximos à área de coleta
    no_origem = ox.distance.nearest_nodes(G, X=-38.7122, Y=-12.5468)
    no_destino = ox.distance.nearest_nodes(G, X=-38.7095, Y=-12.5445)
    
    # Compara Rota Padrão (apenas distância) vs. Rota CadeiWaze (acessível)
    rota_curta, dist_curta = a_estrela_min_heap(G, no_origem, no_destino, atributo_peso="length")
    rota_acessivel, custo_acessivel = a_estrela_min_heap(G, no_origem, no_destino, atributo_peso="peso_acessivel")
    
    # Calcula distância física real da rota acessível em metros
    dist_real_acessivel = sum(
        min(d["length"] for d in G.get_edge_data(u, v).values())
        for u, v in zip(rota_acessivel[:-1], rota_acessivel[1:])
    )
    
    print(f"\n3. Comparativo de Roteamento:")
    print(f"   - Rota Convencional (Menor Distância): {dist_curta:.2f} m")
    print(f"   - Rota CadeiWaze (Mais Acessível):    {dist_real_acessivel:.2f} m (Custo Ponderado: {custo_acessivel:.2f})")
    
    # Gera mapa interativo HTML para a apresentação e figura do artigo
    mapa = folium.Map(location=[-12.5460, -38.7110], zoom_start=16)
    
    coords_curta = [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in rota_curta]
    coords_acessivel = [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in rota_acessivel]
    
    folium.PolyLine(coords_curta, color="red", weight=4, opacity=0.7, tooltip="Rota Padrão (Mais Curta)").add_to(mapa)
    folium.PolyLine(coords_acessivel, color="green", weight=5, opacity=0.9, tooltip="Rota CadeiWaze (Acessível)").add_to(mapa)
    
    mapa.save("mapa_comparativo_cadeiwaze.html")
    print("\nMapa salvo com sucesso em 'mapa_comparativo_cadeiwaze.html'!")