"""
Exemplo: Saldo CAGED Mensal por Setor e Região
Fonte: Novo CAGED (MTP) via Base dos Dados (BigQuery)

Requisitos:
    pip install basedosdados pandas matplotlib

Nota: O Novo CAGED tem início em fev/2020. Para séries mais longas,
combinar com CAGED antigo (até jan/2020), aplicando tratamento da quebra.
"""

import basedosdados as bd
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

BILLING_PROJECT = "seu-projeto-gcp"  # ← alterar
ANO_INICIO = 2020
ANO_FIM = 2025

# ─────────────────────────────────────────────
# 1. COLETA
# ─────────────────────────────────────────────
QUERY = f"""
SELECT
    ano,
    mes,
    uf AS sigla_uf,
    secao AS cnae_secao,
    SUM(CASE WHEN categoria = 1 THEN quantidade ELSE 0 END)  AS admissoes,
    SUM(CASE WHEN categoria = 2 THEN quantidade ELSE 0 END)  AS desligamentos
FROM `basedosdados.br_me_caged.microdados_movimentacao`
WHERE ano BETWEEN {ANO_INICIO} AND {ANO_FIM}
GROUP BY 1, 2, 3, 4
"""

df = bd.read_sql(QUERY, billing_project_id=BILLING_PROJECT)
df["saldo"] = df["admissoes"] - df["desligamentos"]
df["data"] = pd.to_datetime(
    df[["ano", "mes"]].assign(day=1).rename(columns={"ano": "year", "mes": "month"})
)

# ─────────────────────────────────────────────
# 2. MAPEAMENTO SETORIAL
# ─────────────────────────────────────────────
MAP_SETOR = {
    'A': 'Agropecuária',
    'B': 'Ind. extrativa', 'C': 'Ind. transformação',
    'D': 'Utilities', 'E': 'Utilities',
    'F': 'Construção',
    'G': 'Comércio',
    'H': 'Transporte',
    'I': 'Alojamento/Alim.',
    'J': 'TIC', 'M': 'Serv. prof.', 'N': 'Serv. adm.',
    'K': 'Financeiro', 'L': 'Imobiliário',
    'O': 'Adm. pública', 'P': 'Educação', 'Q': 'Saúde',
    'R': 'Artes/Cultura', 'S': 'Outros serv.',
    'T': 'Serv. domésticos',
}
df["setor"] = df["cnae_secao"].map(MAP_SETOR).fillna("Não informado")

# ─────────────────────────────────────────────
# 3. SALDO MENSAL NACIONAL POR SETOR
# ─────────────────────────────────────────────
saldo_setor = (
    df.groupby(["data", "setor"])["saldo"]
    .sum()
    .reset_index()
    .pivot(index="data", columns="setor", values="saldo")
    .fillna(0)
    .sort_index()
)

# Saldo acumulado Brasil (total)
saldo_brasil = df.groupby("data")["saldo"].sum().reset_index().sort_values("data")

# ─────────────────────────────────────────────
# 4. ANÁLISE REGIONAL — TOP SETORES POR MACRORREGIÃO
# ─────────────────────────────────────────────
MAP_MACRO = {
    '11': 'Norte', '12': 'Norte', '13': 'Norte', '14': 'Norte',
    '15': 'Norte', '16': 'Norte', '17': 'Norte',
    '21': 'Nordeste', '22': 'Nordeste', '23': 'Nordeste', '24': 'Nordeste',
    '25': 'Nordeste', '26': 'Nordeste', '27': 'Nordeste', '28': 'Nordeste',
    '29': 'Nordeste',
    '31': 'Sudeste', '32': 'Sudeste', '33': 'Sudeste', '35': 'Sudeste',
    '41': 'Sul', '42': 'Sul', '43': 'Sul',
    '50': 'Centro-Oeste', '51': 'Centro-Oeste', '52': 'Centro-Oeste',
    '53': 'Centro-Oeste',
}
df["macrorregiao"] = df["sigla_uf"].astype(str).map(MAP_MACRO)

saldo_macro = (
    df.groupby(["macrorregiao", "setor"])["saldo"]
    .sum()
    .reset_index()
    .sort_values("saldo", ascending=False)
)

# ─────────────────────────────────────────────
# 5. VISUALIZAÇÃO
# ─────────────────────────────────────────────
fig, axes = plt.subplots(2, 1, figsize=(14, 10))
fig.suptitle("Saldo do Emprego Formal (Novo CAGED)", fontsize=14, fontweight="bold")

# Painel 1: saldo mensal Brasil com barras coloridas por sinal
ax1 = axes[0]
cores = ["#1A936F" if x >= 0 else "#C6541B" for x in saldo_brasil["saldo"]]
ax1.bar(saldo_brasil["data"], saldo_brasil["saldo"], color=cores, width=20)
ax1.axhline(0, color="black", linewidth=0.8)
ax1.set_title("Saldo Mensal — Brasil (admissões − desligamentos)")
ax1.set_ylabel("Saldo (mil postos)")
ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1000:,.0f}k"))
ax1.spines[["top", "right"]].set_visible(False)

# Painel 2: saldo acumulado por setor (top 10)
ax2 = axes[1]
top_setores = (
    df.groupby("setor")["saldo"].sum()
    .sort_values(ascending=True)
    .tail(10)
)
cores2 = ["#1A936F" if x >= 0 else "#C6541B" for x in top_setores.values]
ax2.barh(top_setores.index, top_setores.values / 1000, color=cores2)
ax2.axvline(0, color="black", linewidth=0.8)
ax2.set_title(f"Saldo Acumulado por Setor ({ANO_INICIO}–{ANO_FIM})")
ax2.set_xlabel("Saldo (mil postos)")
ax2.spines[["top", "right"]].set_visible(False)

fig.text(0, -0.01,
         "Fonte: Novo CAGED, MTP. Elaboração própria.\n"
         f"Período: fev/{ANO_INICIO} a dez/{ANO_FIM}.",
         fontsize=8, color="gray")

plt.tight_layout()
plt.savefig("saldo_caged_setor.png", dpi=150, bbox_inches="tight")
plt.show()
print("Gráfico salvo em saldo_caged_setor.png")
