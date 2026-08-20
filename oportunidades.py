"""
Filtro estrategico de oportunidades para o Global Ed / UNIVC.

Diferenca em relacao ao classificador antigo:
- usa o texto do DETALHE do edital, nao so titulo/URL;
- valida prazo real e derruba chamadas vencidas;
- exige aderencia a um eixo concreto de internacionalizacao;
- detecta chamadas inbound-only e chamadas apenas para IES publicas;
- devolve explicacao curta para o painel.

As regras de aderencia ficam em perfil_global_ed.json para serem auditaveis.
"""

from __future__ import annotations

import io
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
PERFIL_FILE = BASE_DIR / "perfil_global_ed.json"


MESES = {
    "janeiro": 1, "jan": 1, "january": 1,
    "fevereiro": 2, "fev": 2, "february": 2, "feb": 2,
    "marco": 3, "mar": 3, "march": 3,
    "abril": 4, "abr": 4, "april": 4, "apr": 4,
    "maio": 5, "may": 5,
    "junho": 6, "jun": 6, "june": 6,
    "julho": 7, "jul": 7, "july": 7,
    "agosto": 8, "ago": 8, "august": 8, "aug": 8,
    "setembro": 9, "set": 9, "september": 9, "sep": 9, "sept": 9,
    "outubro": 10, "out": 10, "october": 10, "oct": 10,
    "novembro": 11, "nov": 11, "november": 11,
    "dezembro": 12, "dez": 12, "december": 12, "dec": 12,
    # espanhol / frances mais comuns em chamadas internacionais
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
    "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9,
    "octubre": 10, "noviembre": 11, "diciembre": 12,
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12,
}

PRAZO_CUES = [
    "prazo", "inscricoes", "inscricao", "submissao", "submissoes",
    "data limite", "data de encerramento", "encerramento", "candidaturas",
    "deadline", "apply by", "applications close", "application deadline",
    "closing date", "submission deadline", "submit by", "open until",
    "fecha limite", "cierre", "convocatoria hasta", "candidature jusqu",
]

DATA_NEGATIVA_CUES = [
    "publicado", "publicacao", "atualizado", "atualizacao", "lancamento",
    "inicio do projeto", "inicio dos projetos", "inicio da mobilidade",
    "funding starts", "start of funding", "selection decision", "resultado",
    "abertura das inscricoes", "previsao para abertura", "inscricoes abrem em",
    "applications open on", "opening date", "opens on",
]

ABERTO_CUES = [
    "inscricoes abertas", "submissoes abertas", "candidaturas abertas",
    "em andamento", "aberto para submissao", "prazo aberto", "apply now",
    "applications open", "open call", "call open", "status em andamento",
    "status: open", "status open", "open for applications",
]

FECHADO_CUES = [
    "inscricoes encerradas", "inscricoes fechadas", "candidaturas encerradas",
    "chamada encerrada", "edital encerrado", "status finalizado", "finalizado",
    "closed", "expired", "applications closed", "call closed", "deadline passed",
]

# Chamadas anunciadas, mas que ainda nao abriram. Uma data futura de deadline
# nao deve transformar automaticamente um card "forthcoming" em aberto.
FUTURO_CUES = [
    "status: forthcoming", "status forthcoming", "forthcoming call",
    "call forthcoming", "applications forthcoming", "opening soon",
    "abre em", "abrira em", "abertura prevista", "chamada futura",
]

RESULTADO_CUES = [
    "resultado final", "resultado preliminar", "lista de selecionados",
    "homologacao do resultado", "resultado da chamada",
]

PUBLICA_ONLY_PATTERNS = [
    r"somente\s+(?:as\s+)?(?:instituicoes|universidades|ies)\s+publicas",
    r"exclusiv\w*\s+para\s+(?:instituicoes|universidades|ies)\s+publicas",
    r"apenas\s+(?:instituicoes|universidades|ies)\s+publicas",
    r"public\s+universit(?:y|ies)\s+only",
]

INBOUND_PATTERNS = [
    r"estudantes?\s+internacionais?.{0,100}(?:estudar|cursar|pos-graduacao).{0,80}no\s+brasil",
    r"estrangeiros?.{0,100}(?:estudar|cursar).{0,80}no\s+brasil",
    r"foreign\s+students?.{0,100}(?:study|degree).{0,80}(?:in|at)\s+brazil",
    r"incoming\s+(?:mobility|students?).{0,100}brazil",
]

OUTBOUND_OR_PARTNERSHIP_CUES = [
    "do brasil para", "brasil para", "pesquisadores do brasil", "no exterior",
    "abroad", "outgoing", "from brazil", "brasil e", "brazil and", "brazil-",
    "parceria", "partnership", "cooperacao", "collaboration", "consorcio",
]

BRAZIL_CUES = [
    "brasil", "brazil", "brasileir", "brazilian", "espirito santo",
    "fapes", "confap", "cnpq", "capes",
]

# Termos que, sozinhos, NAO provam internacionalidade. Este conjunto existe
# justamente para evitar falsos positivos como "intercambio de conhecimento".
TERMOS_MOBILIDADE_GENERICOS = [
    "intercambio", "exchange", "mobilidade", "mobility",
    "intercambio de conhecimento", "knowledge exchange",
]


@dataclass(frozen=True)
class DataCandidata:
    valor: date
    inicio: int
    fim: int
    contexto: str
    score: int


def normalizar(texto: str) -> str:
    if not texto:
        return ""
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _tem_algum(texto_norm: str, termos: Iterable[str]) -> bool:
    return any(normalizar(t) in texto_norm for t in termos if t)


def _limpar_ano_quebrado(texto: str) -> str:
    # Alguns CMS exibem "202 6". Corrige so esse caso para nao alterar outros numeros.
    return re.sub(r"\b(20[0-4])\s+([0-9])\b", r"\1\2", texto)


def _date_safe(ano: int, mes: int, dia: int) -> Optional[date]:
    try:
        if 2000 <= ano <= 2049:
            return date(ano, mes, dia)
    except ValueError:
        return None
    return None


def _coletar_datas(texto: str) -> list[tuple[date, int, int]]:
    texto = _limpar_ano_quebrado(texto or "")
    out: list[tuple[date, int, int]] = []

    # dd/mm/yyyy, dd-mm-yyyy, dd.mm.yyyy
    for m in re.finditer(r"(?<!\d)(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(20[0-4]\d)(?!\d)", texto):
        d = _date_safe(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if d:
            out.append((d, m.start(), m.end()))

    # yyyy-mm-dd
    for m in re.finditer(r"(?<!\d)(20[0-4]\d)\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{1,2})(?!\d)", texto):
        d = _date_safe(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            out.append((d, m.start(), m.end()))

    # 17 de setembro de 2026 / 17 September 2026 / September 17, 2026
    nomes = "|".join(sorted((re.escape(x) for x in MESES), key=len, reverse=True))
    norm = normalizar(texto)

    for m in re.finditer(rf"(?<!\d)(\d{{1,2}})\s+(?:de\s+)?({nomes})\s+(?:de\s+)?(20[0-4]\d)", norm, re.I):
        d = _date_safe(int(m.group(3)), MESES[m.group(2).lower()], int(m.group(1)))
        if d:
            out.append((d, m.start(), m.end()))

    for m in re.finditer(rf"\b({nomes})\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*(20[0-4]\d)\b", norm, re.I):
        d = _date_safe(int(m.group(3)), MESES[m.group(1).lower()], int(m.group(2)))
        if d:
            out.append((d, m.start(), m.end()))

    # remove duplicatas do mesmo valor/span aproximado
    vistos = set()
    unicos = []
    for d, ini, fim in sorted(out, key=lambda x: (x[1], x[0])):
        chave = (d.isoformat(), ini // 4)
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append((d, ini, fim))
    return unicos


def _pontuar_contexto_data(texto_norm: str, ini: int, fim: int) -> tuple[int, str]:
    janela = texto_norm[max(0, ini - 150): min(len(texto_norm), fim + 150)]
    antes = texto_norm[max(0, ini - 90):ini]
    colada = texto_norm[max(0, ini - 55): min(len(texto_norm), fim + 55)]
    score = 0
    if _tem_algum(janela, PRAZO_CUES):
        score += 8
    if re.search(r"\b(?:ate|until|by)\b", janela):
        score += 3
    if _tem_algum(janela, DATA_NEGATIVA_CUES):
        score -= 4
    # Se a data esta colada a "prazo"/"deadline", aumenta a confianca.
    if _tem_algum(colada, PRAZO_CUES):
        score += 5

    # Uma data imediatamente precedida por "abertura/opens on" e data de INICIO,
    # nao deadline. A penalizacao precisa ser forte porque a mesma frase contem
    # "inscricoes/applications", que por si so e um sinal positivo de prazo.
    if _tem_algum(antes, [
        "previsao para abertura", "abertura das inscricoes", "inscricoes abrem em",
        "applications open on", "opening date", "opens on",
    ]):
        score -= 20

    # Sinais de fechamento imediatamente antes da data sao os mais confiaveis.
    if re.search(r"(?:\bate\b|deadline|encerramento|closing date|close(?:s|d)?(?: on)?|apply by|submission deadline).{0,35}$", antes):
        score += 8
    return score, janela


def extrair_prazo_final(texto: str) -> tuple[Optional[date], str, int]:
    """Retorna (data, trecho_contexto, confianca_0_100)."""
    if not texto:
        return None, "", 0
    norm = normalizar(_limpar_ano_quebrado(texto))
    candidatos: list[DataCandidata] = []
    for d, ini, fim in _coletar_datas(texto):
        score, contexto = _pontuar_contexto_data(norm, ini, fim)
        if score > 0:
            candidatos.append(DataCandidata(d, ini, fim, contexto, score))
    if not candidatos:
        return None, "", 0

    # Em intervalo de inscricoes, a segunda data tende a ser o fechamento.
    # Entre empates de score, escolhe a data mais tardia.
    melhor = max(candidatos, key=lambda c: (c.score, c.valor, c.inicio))
    confianca = min(100, 45 + melhor.score * 5)
    return melhor.valor, melhor.contexto, confianca


def avaliar_status_prazo(texto: str, fonte: dict, hoje: Optional[date] = None) -> dict:
    hoje = hoje or date.today()
    norm = normalizar(texto)

    prazo, trecho, confianca = extrair_prazo_final(texto)
    fechado_explicito = _tem_algum(norm, FECHADO_CUES)
    aberto_explicito = _tem_algum(norm, ABERTO_CUES)
    futuro_explicito = _tem_algum(norm, FUTURO_CUES)
    resultado_explicito = _tem_algum(norm, RESULTADO_CUES)

    if prazo is not None:
        if prazo < hoje:
            status = "encerrado"
            motivo = f"prazo encerrado em {prazo.strftime('%d/%m/%Y')}"
        else:
            # Se o proprio texto diz claramente que fechou ou ainda nao abriu,
            # nao confiar apenas em uma data futura possivelmente de outra fase.
            if fechado_explicito and not aberto_explicito:
                status = "encerrado"
                motivo = "pagina informa inscricoes encerradas"
            elif futuro_explicito and not aberto_explicito:
                status = "futuro"
                motivo = "chamada anunciada, mas ainda nao aberta"
            else:
                status = "aberto"
                motivo = f"prazo confirmado ate {prazo.strftime('%d/%m/%Y')}"
        dias = (prazo - hoje).days
        return {
            "status": status,
            "prazo_final": prazo.isoformat(),
            "prazo_texto": prazo.strftime("%d/%m/%Y"),
            "dias_restantes": dias,
            "confianca_prazo": confianca,
            "motivo_status": motivo,
            "trecho_prazo": trecho[:360],
        }

    if resultado_explicito or fechado_explicito:
        return {
            "status": "encerrado", "prazo_final": "", "prazo_texto": "",
            "dias_restantes": None, "confianca_prazo": 80,
            "motivo_status": "pagina indica resultado/encerramento", "trecho_prazo": "",
        }

    if futuro_explicito and not aberto_explicito:
        return {
            "status": "futuro", "prazo_final": "", "prazo_texto": "",
            "dias_restantes": None, "confianca_prazo": 65,
            "motivo_status": "pagina indica chamada futura/ainda nao aberta", "trecho_prazo": "",
        }

    if aberto_explicito:
        return {
            "status": "aberto", "prazo_final": "", "prazo_texto": "",
            "dias_restantes": None, "confianca_prazo": 65,
            "motivo_status": "pagina indica chamada aberta", "trecho_prazo": "",
        }

    if fonte.get("status_lista_confiavel") == "aberto":
        return {
            "status": "aberto", "prazo_final": "", "prazo_texto": "",
            "dias_restantes": None, "confianca_prazo": 55,
            "motivo_status": "fonte oficial lista a oportunidade como aberta", "trecho_prazo": "",
        }

    return {
        "status": "verificar", "prazo_final": "", "prazo_texto": "",
        "dias_restantes": None, "confianca_prazo": 0,
        "motivo_status": "prazo nao confirmado automaticamente", "trecho_prazo": "",
    }


def texto_de_html(html: str, limite: int = 120000) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")

    # Alguns portais guardam o prazo apenas em JSON-LD/metadados. Extraimos
    # somente campos semanticamente ligados a fechamento para nao confundir
    # data de publicacao com deadline.
    extras = []
    chaves_prazo = {
        "applicationdeadline", "submissiondeadline", "deadline",
        "closingdate", "validthrough", "enddate",
    }

    def caminhar_json(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                nk = re.sub(r"[^a-z]", "", str(k).lower())
                if nk in chaves_prazo and isinstance(v, (str, int, float)):
                    extras.append(f"application deadline {v}")
                else:
                    caminhar_json(v)
        elif isinstance(obj, list):
            for v in obj:
                caminhar_json(v)

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        bruto = script.string or script.get_text() or ""
        try:
            caminhar_json(json.loads(bruto))
        except Exception:
            pass

    for meta in soup.find_all("meta"):
        chave = normalizar(meta.get("name") or meta.get("property") or "")
        if any(cue in chave for cue in ("deadline", "closing date", "valid through", "end date")):
            valor = meta.get("content") or ""
            if valor:
                extras.append(f"application deadline {valor}")

    for no in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        no.decompose()
    # Titulos e corpo, mantendo espacos para o parser de datas.
    texto = " ".join(soup.stripped_strings)
    if extras:
        texto = texto + " " + " ".join(extras)
    return re.sub(r"\s+", " ", texto)[:limite]


def texto_de_pdf(conteudo: bytes, max_paginas: int = 12, limite: int = 120000) -> str:
    if not conteudo:
        return ""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(io.BytesIO(conteudo))
        partes = []
        for pagina in reader.pages[:max_paginas]:
            partes.append(pagina.extract_text() or "")
        return re.sub(r"\s+", " ", " ".join(partes))[:limite]
    except Exception:
        return ""


class AnalisadorGlobalEd:
    def __init__(self, caminho: Optional[Path] = None):
        caminho = Path(caminho) if caminho else PERFIL_FILE
        with open(caminho, "r", encoding="utf-8") as f:
            self.cfg = json.load(f)
        self.eixos = self.cfg["eixos"]
        self.limiar = float(self.cfg.get("limiar_aderencia", 30))

    def _eixos_encontrados(self, texto_norm: str) -> list[dict]:
        encontrados = []
        for chave, meta in self.eixos.items():
            if chave.startswith("_"):
                continue
            termos = [normalizar(x) for x in meta.get("termos", [])]
            hits = [t for t in termos if t and t in texto_norm]
            if hits:
                encontrados.append({
                    "chave": chave,
                    "rotulo": meta["rotulo"],
                    "peso": int(meta.get("peso", 0)),
                    "hits": hits[:5],
                    "temas": list(meta.get("temas", [])),
                })
        return sorted(encontrados, key=lambda x: x["peso"], reverse=True)

    def _evidencia_internacional(self, texto_norm: str, fonte: dict) -> tuple[bool, str]:
        """Exige evidencia internacional independente do tema de mobilidade.

        "Intercambio", "exchange" e "mobilidade" nunca bastam sozinhos.
        Em fontes brasileiras amplas, a oportunidade precisa dizer explicitamente
        internacional/exterior/bilateral/etc., ou citar um pais/bloco estrangeiro
        perto de sinais de cooperacao, pesquisa, chamada ou financiamento.
        """
        if fonte.get("fonte_curada_internacional"):
            return True, "fonte internacional curada"

        fortes = [normalizar(x) for x in self.cfg.get("sinais_internacionais_fortes", [])]
        fortes = [x for x in fortes if x]
        for termo in fortes:
            if termo in texto_norm:
                return True, f"sinal internacional explicito: {termo}"

        geograficos = [normalizar(x) for x in self.cfg.get("sinais_geograficos", [])]
        ancora = [
            "parceria", "partnership", "cooperacao", "collaboration",
            "joint research", "research collaboration", "pesquisa", "research",
            "grant", "funding", "bolsa", "fellowship", "chamada", "call for",
            "edital", "university", "universidade", "higher education institution",
            "researcher mobility", "student mobility", "study abroad",
        ]
        for termo in geograficos:
            if not termo:
                continue
            inicio = 0
            while True:
                pos = texto_norm.find(termo, inicio)
                if pos < 0:
                    break
                janela = texto_norm[max(0, pos - 450): min(len(texto_norm), pos + len(termo) + 450)]
                if _tem_algum(janela, ancora):
                    return True, f"pais/regiao estrangeira em contexto de oportunidade: {termo}"
                inicio = pos + len(termo)

        return False, "sem evidencia internacional independente"

    def _conexao_brasil(self, texto_norm: str) -> bool:
        return _tem_algum(texto_norm, BRAZIL_CUES)

    def pontuar_prequalificacao(self, texto: str, fonte: dict) -> int:
        """Pontua o candidato usando apenas titulo/card/URL.

        O valor e usado para ordenar os candidatos ANTES de gastar requisicoes
        de detalhe. Assim, quando uma fonte tem centenas de links, cotutela,
        cooperacao internacional e mobilidade de pesquisadores sao abertas
        primeiro; links genericos de programas ficam por ultimo.
        """
        norm = normalizar(texto)
        if len(norm) < 8:
            return -100

        eixos = self._eixos_encontrados(norm)
        score = 0
        if eixos:
            score += min(50, eixos[0]["peso"])
            score += min(8, 3 * max(0, len(eixos) - 1))
        if _tem_algum(norm, self.cfg.get("sinais_internacionais", [])):
            score += 18
        elif fonte.get("fonte_curada_internacional"):
            score += 12
        if _tem_algum(norm, self.cfg.get("sinais_fomento", [])):
            score += 10
        if _tem_algum(norm, self.cfg.get("sinais_oportunidade", [])):
            score += 8
        if _tem_algum(norm, self.cfg.get("paises_prioritarios", [])):
            score += 5
        if _tem_algum(norm, FECHADO_CUES) or _tem_algum(norm, RESULTADO_CUES):
            score -= 35

        # Listas oficiais podem ter titulos opacos (ex.: "Edital 21/2026").
        # Eles continuam elegiveis para leitura, mas atras de candidatos que
        # ja mostram aderencia no card.
        if fonte.get("fonte_curada_oportunidades") and re.search(r"\b20(?:26|27|28)\b", norm):
            score += 3
        return score

    def prequalificar(self, texto: str, fonte: dict) -> bool:
        """Filtro barato antes de baixar cada pagina de detalhe."""
        norm = normalizar(texto)
        score = self.pontuar_prequalificacao(texto, fonte)
        if score >= 8:
            return True
        if self._eixos_encontrados(norm):
            return True
        # Ultimo recurso para listas oficiais: aceita titulos opacos com ano
        # corrente/proximo, mas o ranking os deixa depois dos candidatos fortes.
        if fonte.get("fonte_curada_oportunidades"):
            return bool(re.search(r"\b20(?:26|27|28)\b", norm))
        return False

    def avaliar(self, texto: str, fonte: dict, hoje: Optional[date] = None) -> dict:
        hoje = hoje or date.today()
        norm = normalizar(texto)
        eixos = self._eixos_encontrados(norm)

        intl, motivo_intl = self._evidencia_internacional(norm, fonte)
        conexao_brasil = self._conexao_brasil(norm)
        fomento = _tem_algum(norm, self.cfg.get("sinais_fomento", []))
        oportunidade = _tem_algum(norm, self.cfg.get("sinais_oportunidade", []))

        status = avaliar_status_prazo(texto, fonte, hoje=hoje)
        if status["prazo_final"]:
            oportunidade = True

        inbound = any(re.search(p, norm, re.I | re.S) for p in INBOUND_PATTERNS)
        tem_saida_ou_parceria = _tem_algum(norm, OUTBOUND_OR_PARTNERSHIP_CUES)
        apenas_publica = any(re.search(p, norm, re.I | re.S) for p in PUBLICA_ONLY_PATTERNS)

        score = 0
        if eixos:
            score += eixos[0]["peso"]
            score += min(10, 5 * max(0, len(eixos) - 1))
        if intl:
            score += 12
        if fomento:
            score += 8
        if oportunidade:
            score += 5
        if _tem_algum(norm, self.cfg.get("paises_prioritarios", [])):
            score += 4
        if _tem_algum(norm, self.cfg.get("areas_prioritarias", [])):
            score += 2
        if inbound and not tem_saida_ou_parceria:
            score -= 45
        if apenas_publica:
            score -= 18
        score = max(0, min(100, score))

        motivos = []
        if eixos:
            motivos.append(" / ".join(x["rotulo"] for x in eixos[:2]))
        if intl:
            motivos.append("componente internacional")
        if fomento:
            motivos.append("financiamento/bolsa")
        if status["prazo_texto"]:
            motivos.append("prazo " + status["prazo_texto"])

        alertas = []
        if inbound and not tem_saida_ou_parceria:
            alertas.append("aparenta ser mobilidade de entrada para o Brasil")
        if apenas_publica:
            alertas.append("texto indica restricao a instituicoes publicas")
        if status["status"] == "verificar":
            alertas.append("prazo nao confirmado")

        relevante = bool(eixos and intl and oportunidade and score >= self.limiar)
        if inbound and not tem_saida_ou_parceria:
            relevante = False
        if fonte.get("exigir_conexao_brasil") and not conexao_brasil:
            relevante = False
            alertas.append("fonte regional: oportunidade sem conexao explicita com o Brasil")

        # Em modo estrito, vencido nunca entra como oportunidade ativa. O registro
        # pode continuar no historico, mas o painel o esconde por padrao.
        ativo = relevante and status["status"] == "aberto"

        temas_sugeridos = []
        for eixo in eixos:
            for t in eixo.get("temas", []):
                if t not in temas_sugeridos:
                    temas_sugeridos.append(t)
        if intl and "internacional" not in temas_sugeridos:
            temas_sugeridos.insert(0, "internacional")
        if fomento and "bolsas" not in temas_sugeridos:
            temas_sugeridos.append("bolsas")

        publico = []
        publico_map = self.cfg.get("publicos", {})
        for chave, termos in publico_map.items():
            if _tem_algum(norm, termos):
                publico.append(chave)

        return {
            **status,
            "relevante": relevante,
            "ativo": ativo,
            "aderencia": score,
            "eixos": [x["chave"] for x in eixos],
            "eixos_rotulos": [x["rotulo"] for x in eixos],
            "temas_sugeridos": temas_sugeridos,
            "publico_alvo": publico,
            "alertas_automaticos": alertas,
            "motivo_relevancia": " | ".join(motivos[:4]),
            "sinal_internacional": intl,
            "motivo_internacional": motivo_intl,
            "conexao_brasil": conexao_brasil,
            "sinal_fomento": fomento,
            "sinal_oportunidade": oportunidade,
            "inbound_only": inbound and not tem_saida_ou_parceria,
            "apenas_instituicao_publica": apenas_publica,
        }
