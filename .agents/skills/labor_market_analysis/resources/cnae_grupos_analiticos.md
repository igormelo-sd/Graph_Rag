# CNAE 2.0 — Grupos Analíticos para Mercado de Trabalho

Este arquivo mapeia as **seções da CNAE 2.0** a agrupamentos analíticos comuns
na literatura de mercado de trabalho brasileiro. Use como referência ao construir
variáveis de setor nas bases PNADC, RAIS e CAGED.

---

## Agrupamento Padrão (4 Macrossetores)

| Macrossetor | Seções CNAE 2.0 | Descrição |
|---|---|---|
| **Agropecuária** | A | Agricultura, pecuária, pesca, silvicultura |
| **Indústria** | B, C, D, E | Extr. mineral, transformação, eletricidade, água/saneamento |
| **Construção** | F | Construção civil |
| **Serviços** | G–U | Todos os demais |

---

## Agrupamento Detalhado (10 Grupos)

| Grupo | Seções CNAE | Nomenclatura |
|---|---|---|
| Agropecuária | A | Agropecuária |
| Indústria de transformação | C | Manufatura |
| Indústria extrativa + utilidades | B, D, E | Indústria extrativa e utilities |
| Construção civil | F | Construção |
| Comércio | G | Comércio, reparação de veículos |
| Transporte e logística | H | Transporte, armazenagem e correios |
| Serviços de alojamento e aliment. | I | Turismo e hotelaria |
| Serviços financeiros e imobiliários | K, L | Finanças, seguros, imóveis |
| Serviços de alta qualificação | J, M, N | TIC, P&D, serviços profissionais |
| Serviços públicos e sociais | O, P, Q | Adm. pública, educação, saúde |
| Outros serviços | R, S, T, U | Cultura, domésticos, org. internac. |

---

## Mapeamento para Código Python

```python
MAP_CNAE_MACROSSETOR = {
    'A': 'Agropecuária',
    'B': 'Indústria', 'C': 'Indústria', 'D': 'Indústria', 'E': 'Indústria',
    'F': 'Construção',
}
# Seções G–U → 'Serviços'
for s in 'GHIJKLMNOPQRSTU':
    MAP_CNAE_MACROSSETOR[s] = 'Serviços'

MAP_CNAE_GRUPO10 = {
    'A': 'Agropecuária',
    'B': 'Ind. extrativa e utilities', 'D': 'Ind. extrativa e utilities',
    'E': 'Ind. extrativa e utilities',
    'C': 'Ind. de transformação',
    'F': 'Construção civil',
    'G': 'Comércio',
    'H': 'Transporte e logística',
    'I': 'Alojamento e alimentação',
    'J': 'Serv. alta qualificação', 'M': 'Serv. alta qualificação',
    'N': 'Serv. alta qualificação',
    'K': 'Serv. financeiros e imob.', 'L': 'Serv. financeiros e imob.',
    'O': 'Serv. públicos e sociais', 'P': 'Serv. públicos e sociais',
    'Q': 'Serv. públicos e sociais',
    'R': 'Outros serviços', 'S': 'Outros serviços',
    'T': 'Outros serviços', 'U': 'Outros serviços',
}
```

---

## Notas

- **Seção na PNADC**: variável `V4010` (código de 5 dígitos do grupo CNAE);
  extrair a letra da seção requer tabela de correspondência do IBGE disponível
  em [CNAE 2.0 — Notas explicativas](https://cnae.ibge.gov.br/).
- **Seção no CAGED/RAIS**: campo `secao` (1 letra) já disponível no BigQuery
  via `basedosdados`.
- Agrupamentos mais finos (divisão, grupo, classe, subclasse) são viáveis no
  RAIS e Novo CAGED, mas podem gerar células pequenas — avaliar tamanho amostral.
