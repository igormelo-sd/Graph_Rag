"""
Exemplo: Taxa de Desocupação Trimestral — Brasil e Grandes Regiões
Fonte: PNAD Contínua (IBGE) via Base dos Dados (BigQuery)

Requisitos:
    pip install basedosdados pandas matplotlib statsmodels

Configurar o projeto GCP em ~/.basedosdados/config.toml ou via variável de ambiente.
"""

import basedosdados as bd
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from statsmodels.tsa.seasonal import STL

# ─────────────────────────────────────────────
# 1. COLETA DE DADOS
# ─────────────────────────────────────────────
BILLING_PROJECT = "seu-projeto-gcp"  # ← alterar

QUERY = """
SELECT
    ano,
    trimestre,
    regiao,
    SUM(pessoas_desocupadas)   AS desocupados,
    SUM(pessoas_na_pea)        AS pea
FROM `basedosdados.br_ibge_pnad_continua.brasil`
WHERE ano >= 2012
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3
"""

df = bd.read_sql(QUERY, billing_project_id=BILLING_PROJECT)

# Construir coluna de data (primeiro mês do trimestre)
MES_TRIM = {1: 1, 2: 4, 3: 7, 4: 10}
df["mes"] = df["trimestre"].map(MES_TRIM)
df["data"] = pd.to_datetime(
    df[["ano", "mes"]].assign(day=1).rename(columns={"ano": "year", "mes": "month"})
)

# ─────────────────────────────────────────────
# 2. CÁLCULO DOS INDICADORES
# ─────────────────────────────────────────────
df["taxa_desocupacao"] = df["desocupados"] / df["pea"] * 100

# Série nacional
brasil = (
    df.groupby("data")[["desocupados", "pea"]]
    .sum()
    .assign(taxa=lambda x: x["desocupados"] / x["pea"] * 100)
    .reset_index()
    .sort_values("data")
)

# ─────────────────────────────────────────────
# 3. DESSAZONALIZAÇÃO (série nacional)
# ─────────────────────────────────────────────
serie = brasil.set_index("data")["taxa"]
stl = STL(serie, period=4, robust=True)
res = stl.fit()

brasil["taxa_dessaz"] = res.trend + res.resid  # componente sem sazonalidade

# ─────────────────────────────────────────────
# 4. VISUALIZAÇÃO
# ─────────────────────────────────────────────
RECESSOES = [
    (pd.Timestamp("2014-10-01"), pd.Timestamp("2016-12-31")),
    (pd.Timestamp("2020-01-01"), pd.Timestamp("2020-06-30")),
]

fig, axes = plt.subplots(1, 2, figsize=(16, 5))
fig.suptitle("Taxa de Desocupação — Brasil", fontsize=14, fontweight="bold")

# Painel esquerdo: série bruta + dessazonalizada
ax = axes[0]
ax.plot(brasil["data"], brasil["taxa"], color="#9ECAE1", linewidth=1.5,
        label="série bruta", alpha=0.8)
ax.plot(brasil["data"], brasil["taxa_dessaz"], color="#1F6EA2", linewidth=2.2,
        label="dessazonalizada (STL)")
for ini, fim in RECESSOES:
    ax.axvspan(ini, fim, color="gray", alpha=0.12)
ax.set_ylabel("Taxa (%)")
ax.set_title("Brasil — bruta e dessazonalizada")
ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
ax.legend()
ax.spines[["top", "right"]].set_visible(False)

# Painel direito: por região (série bruta)
CORES = {"Norte": "#2E86AB", "Nordeste": "#A23B72", "Sudeste": "#F18F01",
         "Sul": "#C73E1D", "Centro-Oeste": "#3B1F2B"}

ax = axes[1]
for regiao, grupo in df.groupby("regiao"):
    grupo = grupo.sort_values("data")
    ax.plot(grupo["data"], grupo["taxa_desocupacao"],
            color=CORES.get(regiao, "gray"), linewidth=1.8, label=regiao)
for ini, fim in RECESSOES:
    ax.axvspan(ini, fim, color="gray", alpha=0.12)
ax.set_title("Por Grande Região")
ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
ax.legend(fontsize=8)
ax.spines[["top", "right"]].set_visible(False)

fig.text(0, -0.02,
         "Fonte: PNAD Contínua, IBGE. Elaboração própria.\n"
         "Áreas cinzas = recessões identificadas.",
         fontsize=8, color="gray")

plt.tight_layout()
plt.savefig("taxa_desocupacao_pnadc.png", dpi=150, bbox_inches="tight")
plt.show()
print("Gráfico salvo em taxa_desocupacao_pnadc.png")
