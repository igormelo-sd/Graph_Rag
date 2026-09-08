---
name: Análise de Indicadores de Mercado de Trabalho
description: >
  Skill especializada em análise quantitativa e interpretação de indicadores
  do mercado de trabalho brasileiro. Cobre séries temporais, decomposição
  setorial e regional, sazonalidade, e integração de múltiplas fontes de
  microdados públicos: PNAD Contínua, RAIS, CAGED, PME, PNADC-Anual,
  Censo Demográfico, entre outras. Orienta o agente a estruturar análises
  econômicas rigorosas, produzir visualizações informativas e redigir
  interpretações alinhadas à literatura de economia do trabalho.
---

# Skill: Análise de Indicadores de Mercado de Trabalho

## Objetivo

Esta skill orienta a construção de análises completas do mercado de trabalho brasileiro, desde a coleta e limpeza de microdados até a interpretação econômica dos resultados. O foco está em:

- **Séries temporais** de indicadores agregados e desagregados
- **Diferenças setoriais** (subclasses CNAE, setor formal/informal, público/privado)
- **Diferenças regionais** (UF, Grande Região, RMSP e demais RMs, área rural/urbana)
- **Integração multifonte** com harmonização conceitual e temporal

---

## 1. Fontes de Dados e Seus Domínios

### 1.1 PNAD Contínua (PNADC) — IBGE

| Aspecto | Detalhe |
|---|---|
| Cobertura | Todos os domicílios do Brasil (exceto área rural de RO, AC, AM, RR, PA, AP) |
| Frequência | Trimestral (divisa em 4 trimestres) e Anual (Visitas 1 e 5) |
| Período disponível | 1º trim/2012 até o presente |
| Unidade | Domicílios e pessoas de 14 anos ou mais |
| Acesso | [FTP IBGE](https://ftp.ibge.gov.br/Trabalho_e_Rendimento/Pesquisa_Nacional_por_Amostra_de_Domicilios_continua/) — arquivos `.zip` com `.txt` e dicionários `.xls`/`.pdf` |
| Pacote Python | `basedosdados` (tabela `br_ibge_pnad_continua`) ou leitura direta via `pandas` |
| Pacote R | `PNADcIBGE`, `survey` |

**Principais variáveis e conceitos:**

- **VD4002**: Condição de ocupação (ocupado / desocupado / fora da PEA)
- **VD4001**: Condição de atividade — define PEA e PNEA
- **VD4016 / VD4019**: Rendimento habitual / efetivo do trabalho principal
- **VD4020**: Rendimento habitual de todos os trabalhos
- **V4010 / V4013**: CNAE 2.0 da atividade principal (grupos e divisões)
- **V4012**: Posição na ocupação (empregado com/sem carteira, conta própria, empregador, etc.)
- **V2010**: Cor/raça | **V2007**: Sexo | **V2009**: Idade
- **UF**, **V1022**: Situação do domicílio (urbano/rural)
- **POSEST**: Pós-estratos para calibração do plano amostral

**Indicadores calculáveis:**

- Taxa de desocupação = desocupados / PEA × 100
- Taxa de informalidade = trabalhadores informais / ocupados × 100
  - Informal: empregados sem carteira + conta-própria sem CNPJ + trabalhadores domésticos sem carteira + trabalhadores familiares auxiliares
- Taxa de subutilização ampliada (TSD) = (desocupados + subocupados por insuficiência de horas + força de trabalho potencial) / força de trabalho ampliada
- Rendimento médio real: deflacionar pelo INPC (referência = data base escolhida)

**Plano amostral (obrigatório):**

```python
import pandas as pd
from svy import survey_design  # ou usar PNADcIBGE no R

# Sempre usar pesos amostrais (V1028 ou PESO_FINAL)
# e variâncias do plano complexo (estratos e UPAs)
```

---

### 1.2 RAIS — Relação Anual de Informações Sociais (MTE/MTP)

| Aspecto | Detalhe |
|---|---|
| Cobertura | Estabelecimentos com vínculos formais celetistas e estatutários |
| Frequência | Anual (referência 31/12 de cada ano) |
| Período disponível | 1985 – ano anterior ao corrente (defasagem ~12 meses) |
| Unidade | Vínculo empregatício (linha = 1 vínculo) |
| Acesso | [FTP MTP](ftp://ftp.mtps.gov.br/pdet/microdados/) ou via `basedosdados` |
| Pacote Python | `basedosdados`, leitura de `.txt` com `pandas` (separador `|`) |

**Principais variáveis:**

- **CNAE 2.0 Classe / Subclasse**: desagregação de até 5 dígitos do setor econômico
- **CBO 2002**: ocupação do trabalhador (6 dígitos)
- **Município de trabalho / IBGE**: localização do estabelecimento
- **Remuneração Média SM / Dezembro**: salário em reais e em salários mínimos
- **Tempo de emprego**: data admissão, data desligamento
- **Sexo, Raça/Cor, Escolaridade, Faixa Etária**
- **Causa do desligamento**: importante para turnover e rotatividade

**Indicadores calculáveis:**

- Salário médio por setor, ocupação, UF
- Rotatividade (turnover) = (admissões + desligamentos) / 2 / estoque médio × 100
- Distribuição salarial / Gini intra-setorial
- Participação do emprego formal por setor na UF

**Atenção:** RAIS **não capta** informais. Combinar com PNADC para análise de cobertura.

---

### 1.3 CAGED — Cadastro Geral de Empregados e Desempregados (MTE/MTP)

| Aspecto | Detalhe |
|---|---|
| Cobertura | Admissões e desligamentos no emprego formal CLT |
| Frequência | Mensal (publicação ~45 dias após referência) |
| Período — formato antigo | Jan/1999 – Jan/2020 (`.txt` por UF) |
| Período — Novo CAGED | Fev/2020 – presente (layouts `.txt` distintos, por tipo de movimentação) |
| Unidade | Movimentação (admissão ou desligamento) |
| Acesso | [FTP MTP](ftp://ftp.mtps.gov.br/pdet/microdados/NOVO%20CAGED/) |
| Pacote Python | `basedosdados`, leitura direta com `pandas` |

> ⚠️ **Quebra estrutural em fev/2020**: o Novo CAGED adotou eSocial como fonte
> administrativa. Comparações de longo prazo exigem tratamento da quebra.

**Principais variáveis (Novo CAGED):**

- **Competência**: AAAAMM da movimentação
- **Movimentação**: 10=admissão, 20=desligamento, 31=transferência
- **CNAE 2.0 Subclasse** (8 dígitos no Novo CAGED)
- **CBO 2002** (6 dígitos)
- **Município** (código IBGE 7 dígitos)
- **Salário (R$)**: salário mensal declarado
- **Sexo, Raça/Cor, Escolaridade, Faixa Etária**
- **Tipo de estabelecimento**: MEI, privado, público, etc.

**Indicadores calculáveis:**

- Saldo líquido mensal = admissões − desligamentos (por setor, UF, município)
- Salário médio de admissão por setor/UF
- Perfil do trabalhador formal admitido / demitido

---

### 1.4 Outras Fontes Complementares

| Fonte | Órgão | Frequência | Cobertura | Uso principal |
|---|---|---|---|---|
| **Censo Demográfico** | IBGE | Decenal | Todos os municípios | Diagnóstico territorial detalhado |
| **PNAD Anual** (até 2015) | IBGE | Anual | Nacional | Séries históricas comparáveis |
| **SIMT / SINE** | MTP | Mensal | Nacional | Intermediação de emprego |
| **CAT** | MTP | Mensal | Nacional | Acidentes de trabalho |
| **PPV / POF** | IBGE | Quinquenal | Nacional + domicílios | Pobreza, consumo, qualidade de vida |
| **Seguro-Desemprego** | MTP | Mensal | Requerentes formais | Fluxo de demissões sem justa causa |

---

## 2. Estrutura Padrão de Análise

### Passo 1 — Definição do Escopo

Antes de iniciar, responder:

1. **Qual indicador?** (desemprego, informalidade, rendimento, emprego formal, rotatividade...)
2. **Qual recorte temporal?** (curto prazo mensal, médio prazo trimestral, longo prazo anual)
3. **Qual desagregação?** (nacional, regional, setorial, por perfil demográfico)
4. **Qual fonte é mais adequada?** (ver tabela comparativa na Seção 1)
5. **Quais são os marcos institucionais/cíclicos relevantes?** (Reforma Trabalhista 2017, pandemia covid-19 2020, etc.)

### Passo 2 — Coleta e Estruturação

```python
# Exemplo: ler Novo CAGED via basedosdados
import basedosdados as bd
import pandas as pd

query = """
SELECT
  ano, mes, uf,
  secao AS cnae_secao,
  SUM(CASE WHEN categoria = 1 THEN quantidade ELSE 0 END) AS admissoes,
  SUM(CASE WHEN categoria = 2 THEN quantidade ELSE 0 END) AS desligamentos,
  SUM(CASE WHEN categoria = 1 THEN quantidade
           WHEN categoria = 2 THEN -quantidade
           ELSE 0 END) AS saldo
FROM `basedosdados.br_me_caged.microdados_movimentacao`
WHERE ano BETWEEN 2020 AND 2025
GROUP BY 1, 2, 3, 4
ORDER BY 1, 2, 3, 4
"""
df = bd.read_sql(query, billing_project_id="SEU_PROJETO_GCP")
df['data'] = pd.to_datetime(df[['ano','mes']].assign(day=1))
```

### Passo 3 — Tratamento de Séries Temporais

#### 3.1 Sazonalidade

- Usar **X-13ARIMA-SEATS** (via `statsmodels.tsa.x13`) ou decomposição STL
- Para PNADC trimestral: o IBGE já publica série dessazonalizada; prefira usar a oficial
- Para CAGED mensal: sazonalidade é pronunciada (dezembro = desligamentos, março = admissões)

```python
from statsmodels.tsa.seasonal import STL

stl = STL(serie_mensal, period=12, robust=True)
res = stl.fit()
tendencia = res.trend
sazonal   = res.seasonal
residuo   = res.resid
```

#### 3.2 Quebras Estruturais

- Identificar visualmente (Chow test ou `breakpoints` do R `strucchange`)
- Marcos obrigatórios a verificar:
  - Jan/2020: pandemia de covid-19 (queda abrupta)
  - Fev/2020: quebra metodológica CAGED → Novo CAGED
  - Nov/2017: Reforma Trabalhista (Lei 13.467/2017)
  - 2012–2014: pico do ciclo de crescimento
  - 2015–2016: recessão (Operação Lava Jato + ajuste fiscal)

#### 3.3 Comparações de Longo Prazo

- **PNAD Anual (pré-2012) → PNADC Anual (2012→)**: usar as pesquisas de compatibilidade publicadas pelo IBGE
- **CAGED antigo → Novo CAGED**: usar as notas técnicas do MTP e aplicar fator de ajuste quando disponível
- **PME → PNADC para RMs**: usar retropolação do IBGE ou método de encadeamento das taxas

### Passo 4 — Análise Setorial

```python
# Mapeamento de seções CNAE 2.0 para grupos analíticos
MAP_SETOR = {
    'A': 'Agropecuária',
    'B': 'Indústria extrativa',
    'C': 'Indústria de transformação',
    'D': 'Eletricidade e gás',
    'E': 'Água e saneamento',
    'F': 'Construção civil',
    'G': 'Comércio',
    'H': 'Transporte e armazenagem',
    'I': 'Alojamento e alimentação',
    'J': 'TIC',
    'K': 'Atividades financeiras',
    'L': 'Atividades imobiliárias',
    'M': 'Profissionais, científicas e técnicas',
    'N': 'Atividades administrativas',
    'O': 'Adm. pública e defesa',
    'P': 'Educação',
    'Q': 'Saúde e serviços sociais',
    'R': 'Artes e cultura',
    'S': 'Outras atividades de serviços',
    'T': 'Serviços domésticos',
}
```

**Técnicas de análise setorial:**

- **Participação relativa** (*share*) de cada setor no emprego total
- **Efeito deslocamento** (shift-share): decompor variação do emprego local em
  efeito nacional + efeito setorial + efeito competitivo
- **Matriz de transição setorial**: queda em setor X → absorção em setor Y?
- **Concentração industrial (HHI)** por UF ou município

### Passo 5 — Análise Regional

```python
# Codigos IBGE de grandes regiões
MACRORREGIAO = {
    '1': 'Norte',
    '2': 'Nordeste',
    '3': 'Sudeste',
    '4': 'Sul',
    '5': 'Centro-Oeste',
}
# Extrair a macrorregião do código do município:
df['macrorregiao'] = df['municipio'].astype(str).str[0].map(MACRORREGIAO)
```

**Técnicas de análise regional:**

- **Convergência/divergência** de taxas regionais ao longo do tempo (sigma-convergência)
- **Decomposição entre/dentro das regiões** (between/within Theil ou Gini)
- **Correlação espacial**: matriz de contiguidade + I de Moran (via `pysal`)
- **Painel de UFs**: efeitos fixos de UF e tempo para isolar heterogeneidade regional
- **Mapas coropléticos** com `geopandas` + malhas territoriais do IBGE (IBGE Geociências)

### Passo 6 — Integração Multifonte

| Pergunta analítica | Fontes recomendadas | Estratégia de integração |
|---|---|---|
| Evolução do desemprego | PNADC trimestral | Série única com dessazonalização |
| Abertura de postos formais | Novo CAGED mensal | Acumulado 12 meses (saldo) |
| Qualidade dos empregos criados | CAGED + RAIS | Comparar salário admissão (CAGED) com salário estoque (RAIS) |
| Informalidade | PNADC | Taxa de informalidade por setor/UF |
| Diagnóstico municipal | Censo + RAIS + CAGED | Quotient locational + shift-share |
| Evolução salarial real | RAIS anual + INPC | Deflacionar pela série do IBGE |
| Desigualdade de rendimentos | PNADC anual | Índice de Gini, percentis P10/P50/P90 |
| Impacto da Reforma Trabalhista | CAGED + RAIS pré/pós 11/2017 | DiD com grupo de controle |

---

## 3. Visualização

### Boas Práticas

- Sempre indicar **fonte**, **período** e **nota metodológica** no rodapé dos gráficos
- Para séries **longas** (>5 anos): usar gráfico de linhas com áreas sombreadas para recessões
- Para **comparações regionais**: mapas coropléticos ou *small multiples* (linhas por UF)
- Para **composição setorial**: gráfico de barras empilhadas (participação %) ou *treemap*
- Para **distribuições salariais**: densidade kernel ou violin plot (por demográfico ou período)

### Paleta de Cores Recomendada (contexto brasileiro)

```python
CORES_REGIAO = {
    'Norte':        '#2E86AB',
    'Nordeste':     '#A23B72',
    'Sudeste':      '#F18F01',
    'Sul':          '#C73E1D',
    'Centro-Oeste': '#3B1F2B',
}
CORES_FORMAL_INFORMAL = {
    'Formal':   '#1A936F',
    'Informal': '#C6541B',
}
```

### Exemplos de Código

```python
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

def plot_serie_temporal(df, coluna_data, coluna_valor, titulo, ylabel,
                        fonte, recessoes=None, ax=None):
    """Plota série temporal com marcação de recessões."""
    if ax is None:
        fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(df[coluna_data], df[coluna_valor], linewidth=2, color='#1F6EA2')
    if recessoes:
        for inicio, fim in recessoes:
            ax.axvspan(inicio, fim, alpha=0.15, color='gray', label='Recessão')
    ax.set_title(titulo, fontsize=14, fontweight='bold', pad=12)
    ax.set_ylabel(ylabel)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: f'{x:,.1f}'))
    ax.set_xlabel('')
    ax.annotate(f'Fonte: {fonte}', xy=(0, -0.12), xycoords='axes fraction',
                fontsize=8, color='gray')
    ax.spines[['top', 'right']].set_visible(False)
    return ax

# Uso:
RECESSOES_BR = [
    (pd.Timestamp('2014-10-01'), pd.Timestamp('2016-12-31')),
    (pd.Timestamp('2020-01-01'), pd.Timestamp('2020-06-30')),
]
plot_serie_temporal(df_pnadc, 'data', 'taxa_desocupacao',
                    'Taxa de Desocupação — Brasil',
                    'Taxa (%)', 'PNAD Contínua, IBGE',
                    recessoes=RECESSOES_BR)
```

---

## 4. Interpretação Econômica

<!--
  ATENÇÃO: as duas seções abaixo (Checklist de Interpretação e Glossário de
  Indicadores-Chave) são extraídas por rag_core/labor_market_skill.py e
  injetadas VERBATIM no prompt de síntese das engines RAG. Qualquer texto
  adicionado aqui vira instrução de produção — editar com cuidado e manter
  os títulos exatos das seções (o regex depende deles).
-->
<!-- rag-context:start -->
### Checklist de Interpretação

Ao redigir a análise, o agente **deve** responder:

1. **Nível e tendência**: O indicador está acima ou abaixo da média histórica? Qual é a tendência recente?
2. **Ciclo econômico**: A variação está associada a algum ciclo de crescimento ou recessão **que os documentos mencionem**?
3. **Heterogeneidade**: Quais setores/regiões/grupos demográficos se distanciam da média, **segundo as fontes**?
4. **Causalidade e mecanismos**: Quais mecanismos explicativos **as próprias fontes** apontam? Não especular além do que os documentos afirmam.

A análise **não** deve conter, salvo pedido explícito do usuário:

- ressalvas sobre limitações metodológicas das fontes (ex.: o que a PNADC ou o CAGED não captura);
- implicações ou recomendações de política pública (seguro-desemprego, requalificação, monitoramento etc.);
- seções acessórias como "Limitações da fonte" ou "Implicações de política".

### Glossário de Indicadores-Chave

| Indicador | Fórmula | Fonte principal |
|---|---|---|
| **Taxa de desocupação** | Desocupados / PEA × 100 | PNADC trimestral |
| **Taxa de informalidade** | Informais / Ocupados × 100 | PNADC trimestral |
| **Taxa de subutilização** | (D + S + FTP) / FTA × 100 | PNADC trimestral |
| **Saldo CAGED** | Admissões − Desligamentos | Novo CAGED mensal |
| **Rendimento médio real** | Salário nominal / INPC × 100 | PNADC / RAIS + IBGE |
| **Rotatividade** | (Admissões + Deslig.) / 2 / Estoque | RAIS anual |
| **Índice de Gini salarial** | Lorenz curve sobre distribuição de rendimentos | PNADC anual / RAIS |

*Legenda: D=desocupados; S=subocupados por insuf. horas; FTP=força de trabalho potencial; FTA=força de trabalho ampliada.*
<!-- rag-context:end -->

---

## 5. Referências e Literatura Recomendada

### Documentação Oficial

- **IBGE** — [Nota metodológica PNAD Contínua](https://www.ibge.gov.br/estatisticas/sociais/populacao/9171-pesquisa-nacional-por-amostra-de-domicilios-continua-mensal.html)
- **MTP** — [Manual do Novo CAGED](https://www.gov.br/trabalho-e-emprego/pt-br/servicos/empregador/caged)
- **MTP / PDET** — [Microdados RAIS](http://www.rais.gov.br/sitio/index.jsf)

### Literatura de Economia do Trabalho

- Corseuil & Foguel (2002) — *Uma sugestão de deflatores para rendimentos derivados de algumas pesquisas domiciliares do IBGE*
- Ramos & Ferreira (2006) — *Padrões espaciais da evolução do emprego formal no Brasil*
- Baltar et al. (2010) — *Trabalho no governo Lula: uma reflexão sobre a recente experiência brasileira*
- Saboia (2014) — *O salário mínimo e seu potencial para a melhoria da distribuição de renda no Brasil*
- Ulyssea (2018) — *Firms, Informality, and Development: Theory and Evidence from Brazil* (AER)
- Barbosa Filho & Moura (2015) — *Evolução recente do emprego e do desemprego no Brasil*
- Dix-Carneiro & Kovak (2017) — *Trade Liberalization and Regional Dynamics* (AER)

### Pacotes e Ferramentas

| Ferramenta | Linguagem | Finalidade |
|---|---|---|
| `basedosdados` | Python / R | Acesso a microdados via BigQuery |
| `PNADcIBGE` | R | Leitura e análise da PNADC com plano amostral |
| `survey` | R | Survey design e estimativas calibradas |
| `statsmodels` | Python | Séries temporais, ARIMA, decomposição STL |
| `pysal` + `libpysal` | Python | Análise espacial e I de Moran |
| `geopandas` | Python | Mapas coropléticos com malhas IBGE |
| `sidrar` | R | API do SIDRA/IBGE para tabelas agregadas |
| `ipeapy` | Python | Séries do IPEA Data (INPC, PIB, etc.) |

---

## 6. Fluxo de Trabalho Recomendado

```
1. Definir escopo (indicador + recorte + fonte)
        │
        ▼
2. Coletar microdados / tabelas agregadas
        │
        ▼
3. Limpar e padronizar (pesos amostrais, codificações)
        │
        ├── Série temporal ──► Dessazonalizar ──► Detectar quebras
        │
        ├── Análise setorial ──► Shift-share / participações
        │
        └── Análise regional ──► Mapas / I de Moran / painel
                │
                ▼
4. Visualizar (gráficos de linhas, mapas, barras)
                │
                ▼
5. Interpretar (nível, tendência, heterogeneidade, segundo as fontes)
                │
                ▼
6. Documentar fontes
```

---

## 7. Notas de Uso para o Agente

- **Sempre citar a fonte e data de referência** quando apresentar um número.
- **Nunca comparar diretamente** séries com quebras metodológicas sem tratamento explícito.
- **Apresentar intervalos de confiança** ao trabalhar com estimativas de amostras complexas (PNADC).
- **Contextualizar o ciclo econômico** antes de atribuir causalidade a políticas específicas.
- Ao gerar código, **priorizar reprodutibilidade**: fixar seeds, documentar versões de pacotes, salvar dados intermediários.
- Ao solicitar análise de um setor ou região específicos, **consultar os arquivos de referência** em `resources/` desta skill.
