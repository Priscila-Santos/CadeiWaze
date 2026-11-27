
# CadeiWaze — Sistema Inteligente de Rotas Acessíveis

O **CadeiWaze** é um protótipo de aplicativo web gratuito e de código aberto desenvolvido para a disciplina de **Projeto de Algoritmos II** do curso de **Bacharelado em Sistemas de Informação** (UFRB). O objetivo do projeto é ajudar pessoas que utilizam cadeira de rodas a encontrar caminhos mais seguros e confortáveis nas cidades, evitando ladeiras muito íngremes, buracos, calçamentos irregulares (como paralelepípedos) e obstáculos temporários.

> *Link da aplicação:* [https://cadeiwaze.streamlit.app/](https://cadeiwaze.streamlit.app/)

## Como o Projeto Funciona

Aplicativos tradicionais de mapas (como Google Maps ou Waze) costumam indicar o caminho mais curto ou mais rápido para carros e pedestres, mas não avaliam se a rua é adequada para uma cadeira de rodas. O CadeiWaze resolve esse problema combinando quatro etapas:

1. **Leitura do Mapa e do Relevo:** O sistema busca as ruas reais de uma cidade por meio do **OpenStreetMap** (uma plataforma colaborativa e gratuita de mapas), armazena a malha viária em cache local para consultas instantâneas e consulta a altitude das ruas para descobrir onde existem subidas e descidas.
2. **Avaliação de Acessibilidade (Norma ABNT NBR 9050):** A NBR 9050 é a norma brasileira que define as regras de acessibilidade no país. Ela determina, por exemplo, que rampas acessíveis não devem ultrapassar uma inclinação de **8,33%**. O sistema identifica ruas que passam desse limite ou que possuem piso muito irregular (como paralelepípedos, que causam forte trepidação).
3. **Adaptação ao Tipo de Cadeira:** O usuário pode escolher entre **Cadeira Manual** (o sistema evita principalmente ladeiras íngremes, para reduzir o esforço físico nos braços) ou **Cadeira Motorizada** (o sistema evita principalmente pisos esburacados ou irregulares, para garantir estabilidade e evitar trepidação excessiva).
4. **Cálculo da Melhor Rota (Algoritmos de Busca):** O mapa da cidade é transformado em um **Grafo** (uma estrutura matemática em que cada esquina é um "ponto" e cada trecho de rua é uma "ligação" com um nível de dificuldade). Para encontrar o melhor caminho entre a origem e o destino, o programa utiliza dois métodos clássicos da computação:
   - **Algoritmo A\* (A-Estrela):** Um método de busca inteligente que calcula a rota mais segura olhando sempre na direção do destino final, economizando tempo e processamento.
   - **Algoritmo de Dijkstra:** Um método tradicional que explora todos os caminhos possíveis ao redor até garantir a melhor rota. O aplicativo exibe os dois lado a lado para provar que o A\* chega ao mesmo resultado seguro visitando menos ruas.


## O Que Você Precisa Ter Instalado no Computador

Antes de baixar e rodar o projeto, certifique-se de ter dois programas gratuitos instalados:

- **Python (versão 3.10 ou superior):** É a linguagem de programação usada para construir toda a lógica e a tela do aplicativo.
- **Git:** É a ferramenta usada para baixar o código do projeto diretamente do GitHub para o seu computador.


## Passo a Passo para Instalar e Executar

Siga as instruções abaixo no terminal do seu computador (como o Prompt de Comando, PowerShell ou o terminal integrado do VS Code):

### 1. Baixar o projeto para o seu computador

Abra o terminal, vá até a pasta onde deseja salvar o projeto e execute o comando abaixo para copiar os arquivos do repositório:

```bash
git clone [https://github.com/Priscila-Santos/CadeiWaze.git](https://github.com/Priscila-Santos/CadeiWaze.git)
cd CadeiWaze

```

### 2. Criar um Ambiente Virtual (`venv`)

Um **ambiente virtual** é uma pasta isolada criada dentro do projeto para guardar apenas as ferramentas que o CadeiWaze precisa, evitando conflitos com outros programas do seu computador.

**No Windows:**

```bash
python -m venv venv
.\venv\Scripts\activate

```

**No Linux ou macOS:**

```bash
python3 -m venv venv
source venv/bin/activate

```

Quando o ambiente estiver ativado, aparecerá a palavra `(venv)` no início da linha do seu terminal.

### 3. Instalar as Bibliotecas Necessárias

As **bibliotecas** são pacotes de código prontos que ajudam o Python a desenhar mapas, fazer cálculos matemáticos e montar a página web. Todas elas estão listadas no arquivo `requirements.txt`. Para instalá-las de uma só vez, digite:

```bash
pip install --upgrade pip
pip install -r requirements.txt

```

### 4. Iniciar o Aplicativo

Com tudo instalado, execute o comando abaixo para ligar o servidor local do **Streamlit** (a ferramenta que transforma o código Python em uma página interativa no navegador):

```bash
streamlit run app.py

```

Após alguns segundos, o seu navegador abrirá automaticamente a tela do **CadeiWaze** (geralmente no endereço `http://localhost:8501`).


## Como Usar e Testar a Aplicação

Na tela principal do aplicativo, utilize o menu lateral esquerdo para simular diferentes situações:

1. **Escolher a Cidade Base:** Selecione entre **Santo Amaro (BA)**, **Feira de Santana (BA)** ou **Recife (PE)**. Cada cidade representa um cenário urbano diferente (centro histórico com paralelepípedos, cidade ampla com desníveis pontuais ou malha urbana costeira densa).
2. **Definir Origem e Destino:** Escolha entre os pontos sugeridos da cidade ou selecione *"Outro endereço (digitar)..."* para informar ruas, praças e instituições reais, clicando em **Pesquisar Trajeto**.
3. **Ajustar o Perfil da Cadeira e o Limite de Desvio:** Alterne entre *Cadeira Manual* e *Cadeira Motorizada*, deslize os controles de peso ($\alpha$ e $\beta$) e defina o percentual máximo de desvio aceitável para receber alertas de custo-benefício (distância versus acessibilidade).
4. **Reporte Colaborativo por Trecho:** Selecione um trecho específico do trajeto para sinalizar uma obra, buraco ou bloqueio temporário na via e observar o recálculo automático de desvio.
5. **Comparar Resultados no Mapa, Tabelas e Gráficos:**
* **Linha Vermelha:** Mostra o caminho mais curto convencional (que pode conter ladeiras íngremes ou pisos irregulares).
* **Linha Verde:** Mostra a rota acessível recomendada pelo CadeiWaze, acompanhada de alertas normativos, tabelas de desempenho (A* vs. Dijkstra e métricas no Sistema Internacional) e gráficos comparativos de esforço e perfil longitudinal.



## Estrutura dos Arquivos do Repositório

```text
CadeiWaze/
├── cache_mapas/        # Malhas viárias (.graphml) salvas localmente para carregamento rápido
├── app.py              # Arquivo principal com os cálculos de rota, regras de acessibilidade e interface visual
├── requirements.txt    # Lista das bibliotecas Python necessárias para execução
├── .gitignore          # Lista de arquivos temporários ignorados pelo controle de versão
└── README.md           # Guia de explicação, instalação e uso do projeto

```


## Equipe de Desenvolvimento

* **Arthur Campos** — Universidade Federal do Recôncavo da Bahia (Feira de Santana – BA)
* **Guilherme Dias** — Universidade Federal do Recôncavo da Bahia (Feira de Santana – BA)
* **Priscila Silva dos Santos** — Universidade Federal do Recôncavo da Bahia (Santo Amaro – BA)


## Licença

Este projeto é distribuído sob a licença **MIT**. Isso significa que qualquer pessoa, estudante ou instituição pública pode copiar, estudar, adaptar e utilizar o código gratuitamente, desde que mantenha os créditos aos autores originais.
