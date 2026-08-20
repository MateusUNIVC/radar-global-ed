"""
Qualidade e novidade dos registros.

Este módulo existe por causa do que apareceu na primeira coleta real
(420 registros, 06-07/08/2026), onde só ~29 itens eram oportunidades
de fato. Os problemas encontrados, todos tratados aqui:

  - 140 páginas de navegação institucional passaram como se fossem editais
    ("Mobilidade para o exterior", "Câmara de Pesquisa", "Bolsas no exterior")
  - títulos com menu do site concatenado numa linha só
    ("GraduaçãoComo funciona PMAI-G/Ufes Registro da Mobilidade...")
  - prefixo de categoria e corpo do texto vazando no título
    ("em Cátedra Yale University Para professor ou pesquisador com...")
  - 48 edições de anos anteriores marcadas como abertas
    (Mobility Italy 2018, 2023, 2025 e 2026 lado a lado)
  - a mesma oportunidade contada 4 vezes por aparecer em fontes diferentes
  - código SVG vazando no texto do título
"""

import re
import unicodedata
from datetime import datetime

# --------------------------------------------------------------------------- #
# Limpeza de título
# --------------------------------------------------------------------------- #

# Prefixos de categoria que alguns sites colam antes do título real
PREFIXOS_CATEGORIA = [
    r"^em\s+(?:C[áa]tedra|Estudantes|Pesquisadores\s+e\s+Professores|Profissionais|"
    r"Professores|Alunos|Institui[çc][õo]es|Universidades|Escolas)\s+",
    r"^(?:Categoria|Tipo|Se[çc][ãa]o|Programa)\s*:\s*",
    r"^\s*[-–—•]\s+",
]

# Frases que marcam o início do CORPO do texto: o título termina antes delas.
# Aparecem quando o seletor pega o card inteiro em vez de só o cabeçalho.
INICIO_DE_CORPO = [
    r"\s+A\s+Comiss[ãa]o\s+[\w,\s]{0,40}?(?:oferece|receber|com\s+apoio)",
    r"\s+S[ãa]o\s+oferecidas?\s+",
    r"\s+(?:Destinad[ao]s?|Voltad[ao]s?|Dirigid[ao]s?)\s+a\s+",
    r"\s+(?:Bolsas?|Aux[íi]lios?)\s+para\s+(?:desenvolver|realizar|atuar|estudar)",
    r"\s+Por\s+meio\s+d[aeo]\s+",
    r"\s+Para\s+(?:atuar|desenvolver|realizar)\s+n[ao]\s+",
    r"\s+A\s+C[áa]tedra\s+(?:destina|se\s+destina)",
    r"\s+O\s+\w+\s+oferece\s+",
    r"\s+Este\s+(?:edital|programa|chamada)\s+",
    r"\s+Com\s+o\s+objetivo\s+de\s+",
    r"\s+Inscri[çc][õo]es\s+(?:abertas|at[ée]|encerram)",
    # "Professores e pesquisadores podem se candidatar..."
    r"\s+(?:Professores?|Pesquisadores?|Estudantes?|Candidatos?|Alunos?|Jovens)\s+"
    r"[\w,\s]{0,40}?(?:podem|poder[ãa]o|dever[ãa]o)\s+",
    # "Para professor ou pesquisador com experiência em..."
    r"\s+Para\s+(?:professor|pesquisador|estudante|aluno|profissional)e?s?\s+",
    r"\s+(?:Bolsa|Programa|Chamada)\s+(?:para|de)\s+\w+\s+\w+\s+(?:em|na|no|nos|nas)\s+",
]

# Títulos de edital reais raramente passam disto; acima daqui é corpo de texto
LIMITE_TITULO_REAL = 110

# Código SVG/CSS que vaza quando o texto do link inclui um ícone inline
LIXO_TECNICO = [
    r'<path[^>]*>', r'd="M[\d\s\.,\-A-Za-z]+"', r'viewBox="[^"]*"',
    r'xmlns="[^"]*"', r'<svg[^>]*>', r'</?\w+\s*/?>',
    r'\{[^}]{20,}\}',  # bloco CSS
]


def _sem_acento(texto):
    t = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in t if not unicodedata.combining(c))


def contar_grudados(texto):
    """
    Conta transições minúscula->maiúscula sem espaço. Sinal de menu de
    navegação raspado como texto único ('GraduaçãoComo funciona PMAI-G').

    Não uso isso para CORRIGIR o título: separar camelCase quebrava nomes
    próprios legítimos ('BiodivConnect' virava 'Biodiv Connect', 'ERAPerMed'
    virava 'ERAPer Med'). Serve só como indício de que o item é navegação e
    deve ser descartado inteiro.
    """
    return len(re.findall(r"[a-zà-ÿ][A-ZÀ-Þ]", texto or ""))


def limpar_titulo(titulo, limite=LIMITE_TITULO_REAL):
    """Normaliza o título para leitura humana e para comparação."""
    if not titulo:
        return ""
    t = titulo

    for padrao in LIXO_TECNICO:
        t = re.sub(padrao, " ", t)

    t = re.sub(r"\s+", " ", t).strip()

    for padrao in PREFIXOS_CATEGORIA:
        t = re.sub(padrao, "", t, flags=re.I).strip()

    # corta onde o corpo do texto começa
    for padrao in INICIO_DE_CORPO:
        m = re.search(padrao, t, flags=re.I)
        if m and m.start() >= 12:
            t = t[: m.start()].strip()
            break

    # corta em pontuação de fim de frase, se o título ficou longo
    if len(t) > limite:
        corte = t[:limite]
        for sep in (". ", " — ", " – ", " | ", "; "):
            pos = corte.rfind(sep)
            if pos > 40:
                corte = corte[:pos]
                break
        t = corte.strip()

    return t.rstrip(" .,;:-–—|")


# --------------------------------------------------------------------------- #
# Navegação institucional
# --------------------------------------------------------------------------- #

# Títulos que são página de menu/sistema, não oportunidade. Validado contra os
# 420 registros reais: estes padrões cobrem a maior parte das 140 páginas de
# navegação que passaram pelo filtro de palavras-chave.
PADROES_NAVEGACAO = [
    # seções de site
    r"^(?:apresenta[çc][ãa]o|hist[óo]rico|miss[ãa]o(?:\s+e\s+valores)?|quem\s+somos)$",
    r"^(?:in[íi]cio|home|p[áa]gina\s+inicial|portal)$",
    r"^(?:contato|fale\s+conosco|ouvidoria|imprensa|not[íi]cias)$",
    r"^(?:compartilh(?:e|ar|amento)|share)(?:\s+(?:no|na|on|via)\s+.*)?$",
    r"^(?:facebook|linkedin|twitter|instagram|whatsapp|youtube)$",
    r"^(?:transpar[êe]ncia|acesso\s+[àa]\s+informa[çc][ãa]o|carta\s+de\s+servi[çc]os)$",
    r"^(?:perguntas\s+frequentes|f\.?a\.?q\.?|d[úu]vidas)$",
    # estruturas de governança
    r"^(?:c[âa]mara|comiss[ãa]o|conselho|diretoria|pr[óo]-reitoria|secretaria)\b",
    r"^atas?\s+(?:da|do|de)\b",
    r"^(?:regimento|estatuto|portaria|resolu[çc][ãa]o|instru[çc][ãa]o\s+normativa)\b",
    r"^(?:organograma|equipe|servidores|administrador)$",
    r"^carreira\s+cient[íi]fica$",
    r"^difus[ãa]o\s+do\s+conhecimento$",
    r"^(?:conselho|c[âa]mara)\s+cient[íi]fico",
    r"^(?:in[íi]cio|sobre)\s+a\s+universidade",
    r"^(?:cursos?|unidades?|campi)$",
    # páginas-índice de bolsas e programas (menu, não edital)
    r"^(?:bolsas?|aux[íi]lios?|modalidades?)(?:\s+(?:no\s+)?(?:pa[íi]s|exterior|"
    r"nacionais?|internacionais?|vigentes?|dispon[íi]veis?))?$",
    r"^(?:outras?\s+)?(?:bolsas?|oportunidades?|op[çc][õo]es)"
    r"(?:\s+(?:nacionais?|internacionais?|de\s+mobilidade))?$",
    r"^(?:programas?|a[çc][õo]es|editais?|chamadas?)(?:\s+(?:e\s+\w+|vigentes?|"
    r"abertos?|anteriores?|encerrados?))?$",
    r"^(?:mobilidade|interc[âa]mbio|est[áa]gio)(?:\s+(?:virtual|para\s+o\s+exterior|"
    r"out|in|internacional))?$",
    r"^(?:gradua[çc][ãa]o|p[óo]s-?gradua[çc][ãa]o|mestrado|doutorado|"
    r"p[óo]s-?doutorado|extens[ãa]o|pesquisa|inova[çc][ãa]o)$",
    r"^(?:professor\s+visitante|t[ée]cnicos?-administrativos?|discentes?|docentes?)$",
    r"^registro\s+d[ao]\b",
    r"^como\s+funciona\b",
    r"^guide\s+for\b",
    # documentos administrativos e financeiros
    r"^(?:manual|tutorial|formul[áa]rios?|modelos?|planilhas?|tabelas?)\b",
    r"^(?:taxa|taxas|tjlp|tr\b|quadro\s+de\s+tarifa)",
    r"^(?:cr[ée]dito|financiamento|subven[çc][ãa]o|conv[êe]nios?)\b",
    r"^termo\s+de\s+(?:fomento|colabora[çc][ãa]o|coopera[çc][ãa]o)",
    r"^(?:obras\s+do\s+estado|licita[çc][õo]es)",
    r"^orienta[çc][õo]es\b",
    r"^acesso\s+\w+\s+via\s+vpn",
    r"^e-?mail\s+do\s+pesquisador$",
    r"^cart[ãa]o\s+(?:bolsista|pesquisa)",
    r"^di[áa]rias\s+para",
    r"^indicadores\s+de\s+pesquisa$",
    r"^grupos\s+de\s+pesquisa\s*-\s*censos$",
    # relatos históricos
    r"^missao\s+",
    r"^\s*(?:internacional|nacional)\s+\w+\s*$",  # "internacional Alemanha"
]

# Marcas de que o título nomeia uma oportunidade concreta. Se alguma aparecer,
# as heurísticas frouxas (camelCase, comprimento) NÃO podem descartar o item.
# Necessário porque 'Chamada Transnacional Conjunta Biodiversa+ (BiodivConnect)'
# era descartada como menu por causa do camelCase em BiodivConnect.
MARCAS_DE_OPORTUNIDADE = re.compile(
    r"\b(chamada|edital|programa\s+\w|bolsas?\s+(?:de|para)|call\s+for|convocat|"
    r"appel|fellowship|grant|scholarship|pr[êe]mio|c[áa]tedra|auxílio\s+(?:a|para)|"
    r"sandu[íi]che|mobility|exchange|interc[âa]mbio\s+\w)\b",
    re.I,
)


def eh_navegacao(titulo):
    """True se o título é página de menu/sistema e não uma oportunidade."""
    t = re.sub(r"\s+", " ", _sem_acento(titulo or "")).strip().lower()
    if not t:
        return True

    # Título que nomeia uma oportunidade nunca é tratado como navegação pelas
    # heurísticas frouxas abaixo. Só os padrões explícitos podem descartá-lo.
    tem_marca = bool(MARCAS_DE_OPORTUNIDADE.search(titulo or ""))

    # menu concatenado: palavras grudadas e nenhuma numeração de edital
    if not tem_marca and len(t) > 55:
        if not re.search(r"\bn[ºo°]?\s*\d|\b\d{1,3}/\d{4}\b", t):
            if contar_grudados(titulo) >= 1:
                return True

    for padrao in PADROES_NAVEGACAO:
        if re.match(padrao, t, flags=re.I):
            return True
    return False


# --------------------------------------------------------------------------- #
# Edição antiga
# --------------------------------------------------------------------------- #

def detectar_ano(titulo, url=""):
    """
    Devolve o ano mais recente citado no título (ou na URL), ou None.
    Ignora números que claramente não são ano (ex: 21/2026 -> pega 2026).
    """
    anos = [int(a) for a in re.findall(r"\b(20[0-4]\d)\b", f"{titulo} {url}")]
    return max(anos) if anos else None


def edicao_encerrada(titulo, url="", ano_referencia=None):
    """
    True se o título indica edição de ano anterior.

    Motivo: no histórico real havia Mobility Italy 2018, 2023, 2025 e 2026
    todos marcados como 'aberto', porque o status vinha do texto e não da data.
    Só faz sentido para títulos que nomeiam uma chamada/edital/programa —
    um ano solto numa página institucional não significa nada.
    """
    if ano_referencia is None:
        ano_referencia = datetime.now().year
    if not re.search(r"chamada|edital|call|programa|convocat|appel|bolsa", titulo, re.I):
        return False, None
    ano = detectar_ano(titulo, url)
    if ano is None:
        return False, None
    return ano < ano_referencia, ano


# --------------------------------------------------------------------------- #
# Assinatura para deduplicação entre fontes
# --------------------------------------------------------------------------- #

PALAVRAS_VAZIAS = {
    "de", "da", "do", "das", "dos", "e", "o", "a", "os", "as", "em", "para",
    "com", "no", "na", "nos", "nas", "por", "ao", "aos", "the", "of", "and",
    "for", "in", "publicacao", "chamada", "edital", "programa", "diretrizes",
    "aviso", "call", "n", "no", "alteracao", "retificacao",
}


def assinatura(titulo):
    """
    Chave que identifica a MESMA oportunidade em fontes diferentes.

    No histórico real, o Mobility CONFAP Italy 2026 aparecia 4 vezes, como
    'CHAMADA MOBILITY CONFAP ITALY 2026', 'PUBLICAÇÃO CONFAP - CHAMADA
    MOBILITY CONFAP ITALY 2026', 'DIRETRIZES FAPES MOBILITY ITALY 2026' e
    'Chamada MCI – MOBILITY CONFAP ITALY 2026'. Removendo palavras genéricas
    e acentos, as quatro convergem para a mesma chave.

    O ANO É PRESERVADO de propósito: a edição 2026 e a 2025 são oportunidades
    diferentes e não devem ser fundidas. Já os números curtos (o '15' de
    'Edital 15/2026') são descartados, porque variam de fonte para fonte.
    """
    bruto = titulo or ""
    # Número de edital explícito (Nº 02/2026, 15/2026) entra na chave: editais
    # numerados diferentes são oportunidades diferentes, mesmo com tema igual
    # ('Edital 02/2026 IFA Inglês' e 'Edital 13/2026 IFA Inglês' coexistem).
    numeros = re.findall(r"\b(\d{1,3})\s*/\s*20[0-4]\d\b", bruto)
    marcador = ("num" + "-".join(sorted(numeros))) if numeros else ""

    t = _sem_acento(bruto).lower()
    t = re.sub(r"[^\w\s]", " ", t)
    tokens = []
    if marcador:
        tokens.append(marcador)
    for p in t.split():
        if p in PALAVRAS_VAZIAS:
            continue
        if p.isdigit():
            if len(p) == 4 and p.startswith("20"):
                tokens.append(p)      # ano: identifica a edição
            continue                   # número de edital: descarta
        if len(p) > 2:
            tokens.append(p)
    if not tokens:
        return ""
    # ordena para que a ordem das palavras não importe
    return " ".join(sorted(set(tokens)))


def assinatura_sem_ano(titulo):
    """Como assinatura(), mas também sem o ano — para casar edições diferentes
    da mesma chamada recorrente (Mobility Italy 2026 vs 2027)."""
    t = re.sub(r"\b20[0-4]\d\b", " ", titulo or "")
    return assinatura(t)


def tokens_assinatura(titulo):
    """Conjunto de tokens da assinatura, para comparar por similaridade."""
    a = assinatura(titulo)
    return set(a.split()) if a else set()


def similaridade(tokens_a, tokens_b):
    """Jaccard entre dois conjuntos de tokens (0 a 1)."""
    if not tokens_a or not tokens_b:
        return 0.0
    inter = len(tokens_a & tokens_b)
    uniao = len(tokens_a | tokens_b)
    return inter / uniao if uniao else 0.0


def agrupar_equivalentes(registros, obter_titulo, limiar=0.70):
    """
    Agrupa registros que são a MESMA oportunidade, tolerando variação de
    redação entre fontes.

    A igualdade exata de assinatura não bastava: 'CHAMADA MOBILITY CONFAP
    ITALY 2026' e 'Chamada MCI – MOBILITY CONFAP ITALY 2026' diferem por uma
    sigla e não casavam. Com similaridade de Jaccard elas se juntam.

    Exige ano compatível: duas edições da mesma chamada em anos diferentes
    nunca são fundidas, mesmo com texto quase idêntico.

    Devolve lista de listas.
    """
    itens = []
    for r in registros:
        titulo = obter_titulo(r)
        tk = tokens_assinatura(titulo)
        itens.append({
            "reg": r,
            "tokens": tk,
            "ano": detectar_ano(titulo),
            # marcador de numeração de edital: se dois itens têm numeração e ela
            # difere, são editais distintos e não podem ser fundidos, mesmo com
            # texto quase igual ('Edital 02/2026 IFA Inglês' vs '13/2026').
            "num": next((x for x in tk if x.startswith("num")), None),
        })

    grupos = []
    usados = set()
    for i, a in enumerate(itens):
        if i in usados or not a["tokens"]:
            if i not in usados and not a["tokens"]:
                grupos.append([a["reg"]])
                usados.add(i)
            continue
        grupo = [a["reg"]]
        usados.add(i)
        for j in range(i + 1, len(itens)):
            if j in usados:
                continue
            b = itens[j]
            if a["ano"] != b["ano"]:      # edições diferentes não se misturam
                continue
            if a["num"] and b["num"] and a["num"] != b["num"]:
                continue                   # editais numerados distintos
            if similaridade(a["tokens"], b["tokens"]) >= limiar:
                grupo.append(b["reg"])
                usados.add(j)
        grupos.append(grupo)
    return grupos


# --------------------------------------------------------------------------- #
# Novidade
# --------------------------------------------------------------------------- #

def classificar_novidade(registro, execucao_atual, primeira_execucao=False):
    """
    Diz em que sentido um item é "novo". O critério antigo — visto nos últimos
    N dias — marcava os 420 itens da primeira coleta como novos, o que não
    informa nada. Aqui a novidade é relativa às EXECUÇÕES, não ao calendário.

    Devolve um dos rótulos:
      "inicial"     — apareceu na primeira coleta; é acervo, não novidade
      "novo"        — apareceu depois da primeira coleta (novidade de verdade)
      "atualizado"  — já existia, mas título ou situação mudaram
      "nova_edicao" — é a edição nova de uma chamada recorrente já conhecida
      "conhecido"   — já estava lá e nada mudou
    """
    visto_em = registro.get("execucao_primeira")

    # Ordem importa: uma alteração publicada agora é mais informativa que a
    # origem do registro. Um edital do acervo inicial que acabou de receber
    # retificação deve aparecer como "atualizado", não como "inicial".
    if registro.get("alterado_na_execucao") == execucao_atual:
        return "atualizado"
    if registro.get("nova_edicao_de"):
        return "nova_edicao"
    if visto_em is None:
        return "inicial" if primeira_execucao else "novo"
    if visto_em == execucao_atual:
        return "inicial" if primeira_execucao else "novo"
    if visto_em == 1 and execucao_atual > 1:
        return "inicial"
    return "conhecido"


def detectar_alteracao(registro, titulo_novo, status_novo):
    """
    Detecta que um item já conhecido mudou. Uma retificação publicada ou uma
    mudança de situação costuma ser mais urgente que um edital novo: significa
    que algo mudou num processo que já estava em curso.

    Devolve lista de descrições das mudanças, ou lista vazia.
    """
    mudancas = []
    antigo_titulo = registro.get("titulo", "")
    antigo_status = registro.get("status", "")

    if antigo_titulo and titulo_novo and antigo_titulo != titulo_novo:
        if assinatura(antigo_titulo) != assinatura(titulo_novo):
            mudancas.append("título alterado")
    if antigo_status and status_novo and antigo_status != status_novo:
        mudancas.append(f"situação: {antigo_status} para {status_novo}")
    return mudancas


def encontrar_edicao_anterior(titulo, historico, url_atual):
    """
    Procura no histórico uma edição anterior da mesma chamada recorrente.

    Serve para o caso mais valioso do painel: 'Mobility CONFAP Italy 2027'
    aparecer marcado como nova edição de uma chamada que a instituição já
    conhece, em vez de surgir como um item qualquer no meio de centenas.

    Devolve (url_anterior, ano_anterior) ou (None, None).
    """
    ano_atual = detectar_ano(titulo)
    if ano_atual is None:
        return None, None
    familia = assinatura_sem_ano(titulo)
    if not familia:
        return None, None
    tokens_atual = set(familia.split())

    melhor = (None, None, 0.0)
    for url, reg in historico.items():
        if url == url_atual:
            continue
        titulo_antigo = reg.get("titulo", "")
        ano_antigo = detectar_ano(titulo_antigo)
        if ano_antigo is None or ano_antigo >= ano_atual:
            continue
        tokens_antigo = set(assinatura_sem_ano(titulo_antigo).split())
        sim = similaridade(tokens_atual, tokens_antigo)
        if sim >= 0.75 and sim > melhor[2]:
            melhor = (url, ano_antigo, sim)
    return melhor[0], melhor[1]


# --------------------------------------------------------------------------- #
# Restrições conhecidas e peso por fonte
# --------------------------------------------------------------------------- #
# Substitui o julgamento de elegibilidade que antes vinha da API. A abordagem é
# deliberadamente diferente: testei regex genérico de restrição contra os 420
# registros reais e as exigências de elegibilidade praticamente não aparecem no
# título (2 casos em 420). Detectar por padrão livre daria falso positivo. Então
# o que existe aqui é casamento com um catálogo curado de programas conhecidos,
# em restricoes.json — editável, revisável, e explicitamente incompleto.

import json as _json
from pathlib import Path as _Path

_ARQ_RESTRICOES = _Path(__file__).resolve().parent / "restricoes.json"
_CACHE = {"restricoes": None, "pesos": None}


def _carregar():
    if _CACHE["restricoes"] is None:
        if _ARQ_RESTRICOES.exists():
            dados = _json.load(open(_ARQ_RESTRICOES, encoding="utf-8"))
            lista = []
            for item in dados.get("restricoes", []):
                try:
                    lista.append({
                        "programa": item["programa"],
                        "regex": re.compile(item["padrao"], re.I),
                        "exige": item.get("exige", ""),
                        "impacto": item.get("impacto", "atencao"),
                    })
                except re.error:
                    continue
            _CACHE["restricoes"] = lista
            _CACHE["pesos"] = {
                k: v for k, v in (dados.get("peso_por_fonte") or {}).items()
                if not k.startswith("_")
            }
        else:
            _CACHE["restricoes"] = []
            _CACHE["pesos"] = {}
    return _CACHE["restricoes"], _CACHE["pesos"]


def identificar_restricoes(titulo, url=""):
    """
    Casa o título com o catálogo de programas conhecidos.

    Devolve lista de dicts {programa, exige, impacto}. Vazia significa
    "nenhum programa catalogado reconhecido" — NÃO significa "sem restrição".
    Essa distinção é importante e o painel a preserva.
    """
    restricoes, _ = _carregar()
    alvo = _sem_acento(f"{titulo} {url}").lower()
    achados = []
    vistos = set()
    for r in restricoes:
        if r["regex"].search(alvo) and r["programa"] not in vistos:
            vistos.add(r["programa"])
            achados.append({
                "programa": r["programa"],
                "exige": r["exige"],
                "impacto": r["impacto"],
            })
    return achados


def peso_da_fonte(nome_fonte):
    """Multiplicador de pontuação por fonte (agência do próprio estado pesa mais)."""
    _, pesos = _carregar()
    return float(pesos.get(nome_fonte, 1.0))


def prioridade_final(pontos, nome_fonte, restricoes_achadas, status):
    """
    Pontuação final em Python puro, sem IA.

    Combina: pontuação temática do classificador, peso da fonte, e o impacto
    das restrições conhecidas. É o que ordena o painel agora.
    """
    valor = float(pontos) * peso_da_fonte(nome_fonte)

    impactos = {r["impacto"] for r in restricoes_achadas}
    if "bloqueia" in impactos:
        valor *= 0.2      # não zera: pode haver via que o título não revela
    elif "favoravel" in impactos:
        valor *= 1.4
    elif "atencao" in impactos:
        valor *= 0.85

    if status == "encerrado":
        valor *= 0.15
    elif status == "resultado":
        valor *= 0.4
    elif status == "retificacao":
        valor *= 0.8

    return round(valor, 1)


def rotulo_situacao(restricoes_achadas):
    """
    Rótulo curto e honesto para o painel.

    'sem_catalogo' é diferente de 'sem restrição': quer dizer que nenhum
    programa conhecido foi reconhecido, e não que a instituição é elegível.
    """
    if not restricoes_achadas:
        return "sem_catalogo"
    impactos = {r["impacto"] for r in restricoes_achadas}
    if "bloqueia" in impactos:
        return "restricao_conhecida"
    if "favoravel" in impactos:
        return "via_individual"
    return "verificar"
