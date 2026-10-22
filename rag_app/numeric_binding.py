"""Vínculo conservador por ocorrência narrativa, com contexto literal do parágrafo."""
import re
from domain_ontology import fold, facets, MONTHS

_PLACES='acre|alagoas|amapa|amazonas|bahia|ceara|distrito federal|espirito santo|goias|maranhao|mato grosso do sul|mato grosso|minas gerais|paraiba|parana|para|pernambuco|piaui|rio de janeiro|rio grande do norte|rio grande do sul|rondonia|roraima|santa catarina|sao paulo|sergipe|tocantins|brasil'
_GEO=re.compile(r'\b(?:(estado|municipio|cidade)\s+(?:d[aeo]\s+)?)?('+_PLACES+r')\b')
_MONTH=re.compile(r'\b('+'|'.join(MONTHS)+r')\s+(?:de\s+)?((?:19|20)\d{2})\b')
_PERCENT=re.compile(r'[-−]?\d+(?:,\d+)?\s*%')
_BOUNDARY=re.compile(r'[!?;]|(?<!p)\.(?=\s+[A-ZÀ-Ú]|$)')
_NEGATIVE={'queda','recuo','recuou','retracao','contracao','caiu','reduziu','diminuiu'}
_MOVEMENT=re.compile(r'\b(?:queda|recuo|recuou|retracao|contracao|caiu|reduziu|diminuiu|avanco|avancou|alta|crescimento|cresceu|aumento|aumentou|subiu|expandiu)\b')


def _dates(text):
    found=[]
    for m in _MONTH.finditer(fold(text)):
        if re.search(r'publica|edicao|atualiz',fold(text)[max(0,m.start()-35):m.start()]): continue
        found.append((m.start(),f'{m[2]}-{MONTHS.index(m[1])+1:02d}'))
    return found


def _basis(text):
    text=fold(text)
    values=set()
    if re.search(r'sem ajuste sazonal|nao ajustad[ao]|sem dessazonal',text): values.add('nao_sazonal')
    elif re.search(r'ajuste sazonal|livre de influencias sazonais|dessazonal',text): values.add('sazonal')
    if re.search(r'mesmo mes do ano anterior|comparacao (?:interanual|anual)|frente a .*20\d{2}.*20\d{2}',text): values.add('interanual')
    if re.search(r'mes (?:imediatamente )?anterior|comparacao com (?:'+ '|'.join(MONTHS)+r')',text): values.add('mensal')
    return values


def _binding(text,position,number_end):
    starts=[m.end() for m in _BOUNDARY.finditer(text) if m.end()<=position]
    ends=[m.start() for m in _BOUNDARY.finditer(text) if m.start()>=number_end]
    start=starts[-1] if starts else 0; end=ends[0] if ends else len(text)
    sentence=text[start:end]
    paragraph_start=0
    for m in re.finditer(r'\n\s*\n',text[:start]): paragraph_start=m.end()
    prefix=text[max(paragraph_start,start-2200):start]
    left=text[start:position]; right=text[number_end:end]
    next_rate=_PERCENT.search(right)
    if next_rate: right=right[:next_rate.start()]
    previous_rates=list(_PERCENT.finditer(left))
    value_left=left[previous_rates[-1].end():] if previous_rates else left
    geos=list(_GEO.finditer(fold(left)))
    if not geos:
        trailing=_GEO.search(fold(right))
        geos=[trailing] if trailing else []
    place=None
    if geos:
        g=geos[-1]; place=('municipio:' if g[1] in {'municipio','cidade'} else '')+g[2]
        # São Paulo sem qualificação continua exigindo revisão.
        if g[2]=='sao paulo' and not g[1]: place=None
    local_dates=_dates(right)
    previous_dates=_dates(text[max(paragraph_start,start-2200):position])
    period=local_dates[0][1] if local_dates else previous_dates[-1][1] if previous_dates else None
    if re.search(r'mes anterior',fold(right)) and not local_dates and period:
        year,month=map(int,period.split('-')); month-=1
        if not month: year-=1; month=12
        period=f'{year}-{month:02d}'
    context=prefix+' '+sentence
    explicit=facets(sentence)['indicator']
    indicators=explicit or facets(prefix)['indicator']
    sectors=facets(sentence)['sector'] or facets(prefix)['sector']
    own_basis=_basis(sentence)
    inherited=_basis(prefix)
    basis=own_basis | (inherited-{'interanual','mensal'} if own_basis & {'interanual','mensal'} else inherited)
    movement=_MOVEMENT.findall(fold(value_left))
    if not movement: movement=_MOVEMENT.findall(fold(right))[:1]
    direction=('negativa' if movement[-1] in _NEGATIVE else 'positiva') if movement else None
    return {'place':place,'period':period,'indicators':indicators,'sectors':sectors,'basis':basis,'direction':direction,'excerpt':context.strip()}


def bound_support(claim_text, claim_start, claim_end, source_text, source_start, source_end):
    wanted=_binding(claim_text,claim_start,claim_end)
    found=_binding(source_text,source_start,source_end)
    issues=[]
    for name in ['place','period']:
        if not wanted[name] or wanted[name]!=found[name]: issues.append(name+': vínculo local ausente ou divergente')
    if wanted['indicators']:
        if not found['indicators'] or wanted['indicators']!=found['indicators']: issues.append('indicator: divergente')
    elif not wanted['sectors'] or wanted['sectors']!=found['sectors'] or not found['indicators']:
        issues.append('indicator: assunto insuficientemente identificado')
    if wanted['basis']-found['basis'] or ({'mensal','interanual'} & found['basis']-wanted['basis']): issues.append('basis: comparação divergente')
    if wanted['direction'] and found['direction'] and wanted['direction']!=found['direction']: issues.append('direction: movimento divergente')
    claim_qualifiers=facets(claim_text)
    source_qualifiers=facets(found['excerpt'])
    for dimension in ('sector','scale','source','coverage'):
        if claim_qualifiers[dimension] and claim_qualifiers[dimension]!=source_qualifiers[dimension]:
            issues.append(dimension+': qualificador divergente')
    return not issues,issues,found['excerpt'][:1800],wanted['period']
