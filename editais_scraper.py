#!/usr/bin/env python3
"""
Painel de Editais — UNIVC
=========================
Monitora agências de fomento do Espírito Santo, nacionais e internacionais,
capturando editais de pesquisa, mobilidade, cotutela, bolsas e cooperação
internacional. Gera um painel HTML local.

Uso:
    python editais_scraper.py                # execução normal
    python editais_scraper.py --so-painel    # só regera o painel do histórico
    python editais_scraper.py --fonte FAPES   # roda uma fonte só

Configuração de rede (rede institucional com proxy) fica em config.json.
"""

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from classificador import Classificador
from oportunidades import AnalisadorGlobalEd, texto_de_html, texto_de_pdf
from relevancia import (
    classificar_novidade,
    detectar_alteracao,
    edicao_encerrada,
    eh_navegacao,
    encontrar_edicao_anterior,
    identificar_restricoes,
    limpar_titulo,
    prioridade_final,
    rotulo_situacao,
)

BASE_DIR = Path(__file__).resolve().parent
DADOS_DIR = BASE_DIR / "dados"
DADOS_DIR.mkdir(exist_ok=True)

ARQ_FONTES = BASE_DIR / "fontes.json"
ARQ_CONFIG = BASE_DIR / "config.json"
ARQ_HISTORICO = DADOS_DIR / "historico.json"
ARQ_URLS_OK = DADOS_DIR / "urls_resolvidos.json"
ARQ_ESTADO = DADOS_DIR / "estado.json"
ARQ_LOG = DADOS_DIR / "execucao.log"
ARQ_PAINEL = BASE_DIR / "painel.html"

CONFIG_PADRAO = {
    "timeout_conexao": 10,
    "timeout_leitura": 25,
    "tempo_max_por_fonte": 120,
    "timeout_segundos": 25,
    "tentativas_por_url": 2,
    "pausa_entre_fontes": 1.5,
    "pausa_entre_paginas": 1.0,
    "dias_badge_novo": 10,
    "verificar_ssl": True,
    "proxy_http": "",
    "proxy_https": "",
    "analisar_detalhes": True,
    "max_detalhes_por_fonte": 35,
    "max_bytes_detalhe": 6000000,
    "max_paginas_pdf": 12,
    "timeout_detalhe": 16,
    "aceitar_prazo_desconhecido": False,
    "modo_estrito_global_ed": True,
    "exigir_prazo_confirmado": True,
    "dias_sem_confirmacao": 7,
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(ARQ_LOG, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("editais")


# --------------------------------------------------------------------------- #
# Configuração e estado
# --------------------------------------------------------------------------- #

def carregar_config():
    cfg = dict(CONFIG_PADRAO)
    if ARQ_CONFIG.exists():
        with open(ARQ_CONFIG, "r", encoding="utf-8") as f:
            usuario = json.load(f)
        cfg.update({k: v for k, v in usuario.items() if not k.startswith("_")})
    return cfg


def carregar_fontes():
    with open(ARQ_FONTES, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return [f for f in cfg["fontes"] if not f.get("desativada")]


def selecionar_fontes_por_nome(fontes, consulta):
    """Aceita nome completo ou trecho; um trecho pode selecionar varias fontes."""
    if not consulta:
        return list(fontes)
    q = consulta.strip().casefold()
    exatas = [f for f in fontes if f.get("nome", "").casefold() == q]
    if exatas:
        return exatas
    parciais = [f for f in fontes if q in f.get("nome", "").casefold()]
    return parciais


def carregar_json(caminho, padrao):
    if caminho.exists():
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            log.warning("Arquivo %s corrompido; recomeçando do zero.", caminho.name)
    return padrao


def salvar_json(caminho, dados):
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    tmp.replace(caminho)  # gravação atômica: não corrompe se cair no meio


# --------------------------------------------------------------------------- #
# Rede
# --------------------------------------------------------------------------- #

def montar_sessao(cfg):
    sessao = requests.Session()
    sessao.headers.update({
        "User-Agent": cfg["user_agent"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    })
    proxies = {}
    if cfg.get("proxy_http"):
        proxies["http"] = cfg["proxy_http"]
    if cfg.get("proxy_https"):
        proxies["https"] = cfg["proxy_https"]
    if proxies:
        sessao.proxies.update(proxies)
        log.info("Usando proxy configurado: %s", proxies)
    if not cfg.get("verificar_ssl", True):
        sessao.verify = False
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        log.warning("Verificação SSL DESATIVADA (verificar_ssl=false no config.json).")
    return sessao


class Orcamento:
    """
    Limite de tempo total para uma fonte.

    Existe porque o timeout do requests é entre-bytes: um servidor que goteja
    dados, ou que aceita a conexão e responde muito devagar, pode manter o
    script preso muito além do timeout nominal. Este é o corte de verdade.
    """

    def __init__(self, limite_segundos):
        self.limite = float(limite_segundos)
        self.inicio = time.monotonic()

    def decorrido(self):
        return time.monotonic() - self.inicio

    def restante(self):
        return max(0.0, self.limite - self.decorrido())

    def estourou(self):
        return self.decorrido() >= self.limite


def buscar(sessao, url, cfg, orcamento=None):
    """
    Tenta baixar uma URL, com retry. Devolve (html, erro).

    Sobre o timeout: o do `requests` é uma tupla (conexão, leitura) e a parte de
    LEITURA é o tempo máximo ENTRE BYTES, não o tempo total. Um servidor que
    responde devagar, gotejando dados, nunca dispara esse timeout — foi o que
    deixou a execução pendurada no Chevening. Por isso existe também o
    'orcamento': um limite de tempo total para a fonte, checado aqui antes de
    cada tentativa e usado como corte real.
    """
    tempo_conexao = float(cfg.get("timeout_conexao", 10))
    tempo_leitura = float(cfg.get("timeout_leitura", cfg.get("timeout_segundos", 25)))

    ultimo_erro = None
    for tentativa in range(1, int(cfg.get("tentativas_por_url", 2)) + 1):
        if orcamento is not None and orcamento.estourou():
            return None, f"orçamento de tempo da fonte esgotado ({orcamento.limite:.0f}s)"

        restante = orcamento.restante() if orcamento is not None else None
        leitura_efetiva = tempo_leitura
        if restante is not None:
            leitura_efetiva = max(3.0, min(tempo_leitura, restante))

        log.info(
            "      GET %s  (conexão %.0fs, leitura %.0fs%s)",
            url[:95] + ("…" if len(url) > 95 else ""),
            tempo_conexao, leitura_efetiva,
            f", resta {restante:.0f}s da fonte" if restante is not None else "",
        )

        inicio = time.monotonic()
        try:
            resp = sessao.get(
                url,
                timeout=(tempo_conexao, leitura_efetiva),
                allow_redirects=True,
                stream=False,
            )
            resp.raise_for_status()
            if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"
            texto = resp.text
            log.info(
                "      -> %d, %s bytes em %.1fs",
                resp.status_code, f"{len(texto):,}".replace(",", "."),
                time.monotonic() - inicio,
            )
            return texto, None

        except requests.HTTPError as exc:
            codigo = exc.response.status_code if exc.response is not None else "?"
            ultimo_erro = f"HTTP {codigo}"
            log.info("      -> %s em %.1fs", ultimo_erro, time.monotonic() - inicio)
            if codigo in (404, 403, 410, 401):
                break  # não insiste em URL que não existe ou é proibida

        except requests.exceptions.ReadTimeout:
            ultimo_erro = f"leitura excedeu {leitura_efetiva:.0f}s"
            log.info("      -> %s", ultimo_erro)

        except requests.exceptions.ConnectTimeout:
            ultimo_erro = f"conexão excedeu {tempo_conexao:.0f}s"
            log.info("      -> %s", ultimo_erro)

        except requests.exceptions.SSLError as exc:
            ultimo_erro = "erro de SSL (proxy inspecionando tráfego?)"
            log.info("      -> %s: %s", ultimo_erro, str(exc)[:110])
            break  # retry não resolve certificado

        except requests.exceptions.ProxyError:
            ultimo_erro = "proxy recusou (rede bloqueando este domínio?)"
            log.info("      -> %s", ultimo_erro)
            break  # retry não vence bloqueio de rede

        except requests.RequestException as exc:
            ultimo_erro = type(exc).__name__
            log.info("      -> %s em %.1fs", ultimo_erro, time.monotonic() - inicio)

        if tentativa < int(cfg.get("tentativas_por_url", 2)):
            espera = 1.5 * tentativa
            if orcamento is not None and orcamento.restante() < espera + 3:
                break
            time.sleep(espera)

    return None, ultimo_erro


# --------------------------------------------------------------------------- #
# Extração
# --------------------------------------------------------------------------- #


CACHE_DETALHES = {}

def buscar_texto_detalhe(sessao, url, cfg, orcamento=None):
    """Baixa e extrai texto de uma pagina de detalhe HTML/PDF.

    O scraper antigo julgava o edital so pelo titulo. Este passo e a principal
    mudanca de qualidade: prazo, elegibilidade e objetivo normalmente so
    aparecem na pagina/PDF do edital.
    """
    if not cfg.get("analisar_detalhes", True):
        return "", "desativado"
    if not url.startswith(("http://", "https://")):
        return "", "url-invalida"
    if url in CACHE_DETALHES:
        return CACHE_DETALHES[url]

    tipo = tipo_de_arquivo(url)
    if tipo and tipo != "PDF":
        CACHE_DETALHES[url] = ("", tipo.lower())
        return CACHE_DETALHES[url]

    if orcamento is not None and orcamento.estourou():
        return "", "orcamento-esgotado"

    timeout_conexao = min(float(cfg.get("timeout_conexao", 10)), 10.0)
    timeout_leitura = float(cfg.get("timeout_detalhe", 16))
    if orcamento is not None:
        timeout_leitura = max(3.0, min(timeout_leitura, orcamento.restante()))
    limite = int(cfg.get("max_bytes_detalhe", 6000000))

    try:
        resp = sessao.get(
            url,
            timeout=(timeout_conexao, timeout_leitura),
            allow_redirects=True,
            stream=True,
        )
        resp.raise_for_status()
        tamanho = resp.headers.get("Content-Length")
        if tamanho and int(tamanho) > limite:
            CACHE_DETALHES[url] = ("", "grande-demais")
            return CACHE_DETALHES[url]

        partes = []
        total = 0
        for bloco in resp.iter_content(chunk_size=65536):
            if not bloco:
                continue
            total += len(bloco)
            if total > limite:
                CACHE_DETALHES[url] = ("", "grande-demais")
                return CACHE_DETALHES[url]
            partes.append(bloco)
        conteudo = b"".join(partes)
        ctype = (resp.headers.get("Content-Type") or "").lower()
        url_final = (resp.url or url).lower()

        if "pdf" in ctype or url_final.endswith(".pdf") or tipo == "PDF":
            texto = texto_de_pdf(
                conteudo, max_paginas=int(cfg.get("max_paginas_pdf", 12))
            )
            resultado = (texto, "pdf")
        elif "html" in ctype or not ctype or ctype.startswith("text/"):
            enc = resp.encoding or resp.apparent_encoding or "utf-8"
            html = conteudo.decode(enc, errors="replace")
            resultado = (texto_de_html(html), "html")
        else:
            resultado = ("", ctype.split(";")[0] or "binario")
        CACHE_DETALHES[url] = resultado
        return resultado
    except (requests.RequestException, ValueError, OSError) as exc:
        resultado = ("", type(exc).__name__)
        CACHE_DETALHES[url] = resultado
        return resultado

def limpar(texto):
    return re.sub(r"\s+", " ", texto or "").strip()


# Textos de link que não identificam nada por si — precisam herdar o título
# do bloco onde estão. É o caso dos dropdowns de anexo da FAPES: o link diz
# só "Baixar", e o nome do edital está no cabeçalho do accordion.
TEXTOS_GENERICOS = [
    "baixar", "download", "download aqui", "clique aqui", "clique",
    "acesse", "acesso", "abrir", "ver", "veja", "visualizar", "consultar",
    "leia mais", "saiba mais", "mais informacoes", "mais informações",
    "anexo", "anexos", "arquivo", "arquivos", "documento", "documentos",
    "edital", "edital completo", "íntegra", "integra", "texto integral",
    "pdf", "doc", "docx", "xls", "xlsx", "zip", "planilha", "formulario",
    "formulário", "resultado", "aqui", "link", "detalhes", "mais",
    "inscricao", "inscrição", "inscreva-se", "acesse o edital",
]

# Rótulos que indicam o documento PRINCIPAL de um bloco (peso alto na escolha
# do representante do grupo) e os que indicam documento SECUNDÁRIO.
ROTULOS_PRINCIPAIS = [
    "edital completo", "texto integral", "integra", "edital", "chamada",
    "baixar", "download", "documento", "pdf", "arquivo", "aviso",
]
ROTULOS_SECUNDARIOS = [
    "anexo", "retificacao", "errata", "adendo", "aditamento", "resultado",
    "formulario", "cronograma", "planilha", "modelo", "manual", "tabela",
    "faq", "perguntas", "apresentacao", "slide", "relatorio", "termo",
]
# Rótulos puramente de navegação: não são anexo de nada
ROTULOS_NAVEGACAO = [
    "clique aqui", "saiba mais", "leia mais", "veja mais", "ver mais",
    "acesse", "acesso", "mais informacoes", "faq", "perguntas frequentes",
    "voltar", "inicio", "home", "contato", "fale conosco",
]

EXTENSOES_ARQUIVO = {
    ".pdf": "PDF", ".doc": "DOC", ".docx": "DOC", ".xls": "XLS",
    ".xlsx": "XLS", ".zip": "ZIP", ".rar": "ZIP", ".odt": "DOC",
    ".ods": "XLS", ".ppt": "PPT", ".pptx": "PPT",
}

# Onde procurar o título de um bloco/accordion, em ordem de preferência
SELETORES_TITULO_BLOCO = [
    "summary", ".accordion-header", ".accordion-button", ".card-header",
    ".panel-heading", "h1", "h2", "h3", "h4", "h5",
    ".titulo", ".title", ".field--name-title", "strong", "b",
]


def tipo_de_arquivo(url):
    """Devolve 'PDF', 'DOC', etc. se a URL aponta para um arquivo, senão ''."""
    caminho = urlparse(url).path.lower()
    for ext, rotulo in EXTENSOES_ARQUIVO.items():
        if caminho.endswith(ext):
            return rotulo
    return ""


def texto_e_generico(texto):
    """True se o texto do link não identifica o edital por si mesmo."""
    t = normalizar_simples(texto)
    if not t or len(t) < 12:
        return True
    if t in TEXTOS_GENERICOS:
        return True
    # "baixar edital", "clique aqui para acessar", "anexo i", "edital 2026.pdf"
    for g in TEXTOS_GENERICOS:
        if t.startswith(g) and len(t) <= len(g) + 20:
            return True
    return False


def normalizar_simples(texto):
    """Minúsculas sem acento — versão leve, só para comparar rótulos de link."""
    import unicodedata
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()
    

# Dominios e rotas de compartilhamento nunca sao oportunidades. Este filtro
# roda ANTES de herdar o titulo do card; assim um botao "Compartilhe no
# LinkedIn" nao vira acidentalmente um edital com o titulo do bloco.
DOMINIOS_SOCIAIS_RUIDO = {
    "linkedin.com", "www.linkedin.com", "facebook.com", "www.facebook.com",
    "twitter.com", "www.twitter.com", "x.com", "www.x.com",
    "instagram.com", "www.instagram.com", "youtube.com", "www.youtube.com",
    "youtu.be", "wa.me", "api.whatsapp.com", "t.me", "telegram.me",
    "pinterest.com", "www.pinterest.com", "addthis.com", "sharethis.com",
}

PADROES_URL_COMPARTILHAMENTO = [
    r"/sharing/", r"/sharer", r"/intent/tweet",
    r"sharearticle", r"share-offsite", r"[?&](?:share|sharing)=",
    r"whatsapp://", r"mailto:",
]

PADROES_TEXTO_COMPARTILHAMENTO = [
    r"^compartilh(?:e|ar|amento)", r"^share(?: this| on| via|$)",
    r"^(?:facebook|linkedin|twitter|instagram|whatsapp|youtube)$",
    r"^(?:compartilhe|share).*(?:facebook|linkedin|twitter|instagram|whatsapp)",
]


def link_e_ruido(href, url_completa, ancora=None):
    """True para redes sociais, botoes de share e links utilitarios."""
    href_l = (href or "").strip().lower()
    url_l = (url_completa or "").strip().lower()
    if href_l.startswith(("#", "mailto:", "tel:", "javascript:", "whatsapp:")):
        return True

    host = (urlparse(url_l).netloc or "").split(":")[0]
    if any(host == d or host.endswith("." + d) for d in DOMINIOS_SOCIAIS_RUIDO):
        return True
    if any(re.search(p, url_l, re.I) for p in PADROES_URL_COMPARTILHAMENTO):
        return True

    if ancora is not None:
        partes = [
            limpar(ancora.get_text(" ", strip=True)),
            limpar(ancora.get("title") or ""),
            limpar(ancora.get("aria-label") or ""),
            " ".join(ancora.get("class", []) or []),
        ]
        texto = normalizar_simples(" ".join(partes))
        if any(re.search(p, texto, re.I) for p in PADROES_TEXTO_COMPARTILHAMENTO):
            return True
        # Classes comuns de widgets sociais, mesmo quando o icone nao tem texto.
        if re.search(r"\b(?:social|share|sharing|linkedin|facebook|twitter|whatsapp)\b", texto):
            return True
    return False


def titulo_do_bloco(no, seletor_titulo=None):
    """Acha o título de um bloco/accordion, para os anexos herdarem."""
    tentativas = []
    if seletor_titulo:
        tentativas.append(seletor_titulo)
    tentativas.extend(SELETORES_TITULO_BLOCO)

    for sel in tentativas:
        try:
            el = no.select_one(sel)
        except Exception:
            continue
        if el is None:
            continue
        texto = limpar(el.get_text())
        if texto and len(texto) >= 12 and not texto_e_generico(texto):
            return texto

    # último recurso: primeira linha de texto do bloco
    bruto = limpar(no.get_text())
    if bruto:
        primeira = bruto.split("  ")[0][:160]
        if len(primeira) >= 12:
            return primeira
    return ""


def extrair_links_do_bloco(no, url_base, fonte):
    """
    Extrai TODOS os links de um bloco, não só o primeiro.

    Isso é o que resolve os dropdowns de anexo: um bloco cujo cabeçalho é
    "Edital 15/2026 - Bolsas de Mobilidade" pode conter 6 links de download.
    Antes só o primeiro era capturado; agora todos são, e cada um herda o
    título do cabeçalho quando o próprio texto do link é genérico
    ("Baixar", "Anexo I", "PDF").
    """
    itens = []
    cabecalho = titulo_do_bloco(no, fonte.get("seletor_titulo"))

    el_data = no.select_one(fonte["seletor_data"]) if fonte.get("seletor_data") else None
    data_texto = limpar(el_data.get_text()) if el_data else ""
    contexto_texto = limpar(no.get_text(" ", strip=True))[:6000]

    # todos os links do bloco, mais o próprio nó se ele for um <a>
    ancoras = list(no.select("a[href]"))
    if no.name == "a" and no.get("href"):
        ancoras.insert(0, no)

    vistos = set()
    for a in ancoras:
        href = a.get("href", "")
        if not href:
            continue
        url = urljoin(url_base, href)
        if link_e_ruido(href, url, a):
            continue
        if url in vistos:
            continue
        vistos.add(url)

        texto_link = limpar(a.get_text())
        # o title/aria-label às vezes carrega o nome real do arquivo
        if texto_e_generico(texto_link):
            for atributo in ("title", "aria-label"):
                alternativo = limpar(a.get(atributo) or "")
                if alternativo and not texto_e_generico(alternativo):
                    texto_link = alternativo
                    break

        arquivo = tipo_de_arquivo(url)

        classes = " ".join(no.get("class", []) if hasattr(no, "get") else [])
        eh_container_grupo = bool(cabecalho) and (
            getattr(no, "name", "") == "details"
            or re.search(r"(?:accordion-item|panel|collapse|card)", classes, re.I)
        )
        herdou = texto_e_generico(texto_link) and bool(cabecalho)
        if herdou:
            titulo = cabecalho
            rotulo = texto_link if texto_link and len(texto_link) >= 3 else ""
        else:
            titulo = texto_link or cabecalho
            # Em accordions/panels, o texto do link ajuda a escolher o documento
            # principal, mas todos os arquivos pertencem ao mesmo edital.
            rotulo = texto_link if eh_container_grupo else ""

        if not titulo:
            continue

        itens.append({
            "titulo": titulo,
            "url": url,
            "data_texto": data_texto,
            "arquivo": arquivo,
            "contexto_texto": contexto_texto,
            # campos internos, usados só pelo agrupamento
            "_cabecalho": cabecalho if (herdou or eh_container_grupo) else "",
            "_rotulo": rotulo,
        })

    return itens


def agrupar_por_cabecalho(itens, ativo=True):
    """
    Junta os vários anexos de um mesmo edital numa entrada só.

    Um dropdown com "Edital 15/2026" no cabeçalho e 5 links de download
    geraria 5 entradas com o mesmo título — ruído no painel. Aqui fica uma
    entrada (a de rótulo mais informativo, preferindo PDF), e os demais
    links viram 'anexos' dentro dela: nada se perde, nada se repete.

    Agrupa pelo cabeçalho herdado, que é a parte antes do ' — '.
    """
    if not ativo:
        return itens

    grupos = {}
    ordem = []
    for item in itens:
        cabecalho = item.get("_cabecalho", "")
        # só agrupa itens que herdaram cabeçalho; os de título próprio ficam sós
        if cabecalho and len(normalizar_simples(cabecalho)) >= 12:
            chave = "cab:" + normalizar_simples(cabecalho)
        else:
            chave = "uni:" + item["url"]
        if chave not in grupos:
            grupos[chave] = []
            ordem.append(chave)
        grupos[chave].append(item)

    def limpo(item):
        saida = {k: v for k, v in item.items() if not k.startswith("_")}
        return saida

    saida = []
    for chave in ordem:
        grupo = grupos[chave]
        if len(grupo) == 1:
            saida.append(limpo(grupo[0]))
            continue

        # Representante do grupo: deve ser o documento PRINCIPAL, não um anexo
        # nem a retificação. Sem isso, um bloco com "Baixar" + "Retificação"
        # escolheria a retificação (rótulo mais longo) e o edital seria
        # classificado como documento retificador, perdendo pontuação.
        def peso(it):
            rot = normalizar_simples(it.get("_rotulo") or "")
            nota = 0
            if any(rot.startswith(x) for x in ROTULOS_SECUNDARIOS):
                nota -= 10
            if any(x in rot for x in ROTULOS_PRINCIPAIS):
                nota += 10
            if it.get("arquivo") == "PDF":
                nota += 3
            elif it.get("arquivo"):
                nota += 1
            return (nota, -len(rot))

        principal_original = max(grupo, key=peso)
        principal = limpo(principal_original)
        cabecalho_grupo = principal_original.get("_cabecalho", "")
        if cabecalho_grupo:
            principal["titulo"] = cabecalho_grupo

        anexos = []
        for it in grupo:
            if it["url"] == principal["url"]:
                continue
            rot = normalizar_simples(it.get("_rotulo") or "")
            # link de navegação sem arquivo não é anexo do edital
            if not it.get("arquivo") and any(
                rot.startswith(x) or rot == x for x in ROTULOS_NAVEGACAO
            ):
                continue
            anexos.append({
                "url": it["url"],
                "rotulo": it.get("_rotulo") or "anexo",
                "arquivo": it.get("arquivo", ""),
            })
        principal["anexos"] = anexos
        saida.append(principal)
    return saida


def extrair_por_seletor(soup, fonte, url_base):
    """
    Estratégia 1: usa os seletores CSS configurados para a fonte.
    Captura todos os links de cada bloco (ver extrair_links_do_bloco).
    """
    itens = []
    seletor = fonte.get("seletor")
    if not seletor:
        return itens

    vistos = set()
    try:
        nos = soup.select(seletor)
    except Exception as exc:
        log.warning("    seletor inválido (%s): %s", seletor, exc)
        return itens

    for no in nos:
        for item in extrair_links_do_bloco(no, url_base, fonte):
            if item["url"] in vistos:
                continue
            vistos.add(item["url"])
            itens.append(item)

    return agrupar_por_cabecalho(itens, fonte.get("agrupar_anexos", True))


def extrair_por_varredura(soup, url_base):
    """
    Estratégia 2 (fallback): varre TODOS os links da página.
    Não filtra por palavra-chave aqui — o classificador faz esse trabalho
    depois, com regras muito melhores. Isso evita perder editais cujo
    título não contém a palavra 'edital'.
    """
    itens = []
    vistos = set()
    dominio_base = urlparse(url_base).netloc

    for a in soup.find_all("a", href=True):
        href = a["href"]
        url_completa = urljoin(url_base, href)
        if link_e_ruido(href, url_completa, a):
            continue
        if url_completa in vistos:
            continue
        vistos.add(url_completa)

        # descarta links para domínios de terceiros (redes sociais etc.),
        # mas mantém PDFs e subdomínios da própria instituição
        destino = urlparse(url_completa).netloc
        if destino and dominio_base:
            raiz_base = ".".join(dominio_base.split(".")[-2:])
            if raiz_base not in destino and not url_completa.lower().endswith(".pdf"):
                continue

        texto = limpar(a.get_text())

        # Se o rótulo do link não diz nada ("Baixar", "PDF", "Anexo I"),
        # sobe na árvore procurando um cabeçalho que o identifique. É o
        # mesmo problema dos dropdowns de anexo, mas fora de um bloco
        # reconhecido por seletor.
        if texto_e_generico(texto):
            contexto = ""
            ancestral = a
            for _ in range(4):
                ancestral = ancestral.parent
                if ancestral is None or ancestral.name in ("body", "html"):
                    break
                contexto = titulo_do_bloco(ancestral)
                if contexto and not texto_e_generico(contexto):
                    break
                contexto = ""
            if contexto:
                cab = contexto
                rot = texto
                texto = contexto
            else:
                cab, rot = "", ""
        else:
            cab, rot = "", ""

        contexto_texto = ""
        ancestral_ctx = a
        for _ in range(4):
            ancestral_ctx = ancestral_ctx.parent
            if ancestral_ctx is None or ancestral_ctx.name in ("body", "html"):
                break
            candidato_ctx = limpar(ancestral_ctx.get_text(" ", strip=True))
            if 20 <= len(candidato_ctx) <= 5000:
                contexto_texto = candidato_ctx
                if len(candidato_ctx) >= 60:
                    break

        itens.append({
            "titulo": texto,
            "url": url_completa,
            "data_texto": "",
            "arquivo": tipo_de_arquivo(url_completa),
            "contexto_texto": contexto_texto[:5000],
            "_cabecalho": cab,
            "_rotulo": rot,
        })
    return agrupar_por_cabecalho(itens, True)


TEXTOS_PROXIMA = [
    "proxima", "próxima", "proximo", "próximo", "proximos", "próximos",
    "next", "seguinte", "seguintes", "avancar", "avançar",
    "mais resultados", "ver mais", "load more", "carregar mais", "show more",
]

# Símbolos: casam só por igualdade exata, senão ">" pegaria qualquer coisa
SIMBOLOS_PROXIMA = ["»", "›", ">>", ">", "→", "▶"]

TEXTOS_ULTIMA = ["ultima", "última", "ultimo", "último", "last", "fim", "final", "end"]

CONTAINERS_PAGINACAO = [
    ".pagination", ".pager", ".page-numbers", ".paginacao", ".paginator",
    ".listingBar", ".listing-bar",          # Plone — usado nos sites gov.br
    ".nav-links", ".wp-pagenavi",            # WordPress
    "nav[aria-label*='pag']", "nav[role='navigation']",
    ".pages", ".paging", ".page-nav",
    "[class*='pagination']", "[class*='paginacao']", "[class*='pager']",
]


def texto_indica_proxima(texto, titulo="", rotulo=""):
    """True se o rótulo do link significa 'ir para a próxima página'."""
    combinado = f"{texto} {titulo} {rotulo}".strip().lower()
    if not combinado:
        return False
    # "última" pula páginas — não serve para avançar de uma em uma
    if any(t in combinado for t in TEXTOS_ULTIMA):
        return False
    if any(t in combinado for t in TEXTOS_PROXIMA):
        return True
    if texto.strip() in SIMBOLOS_PROXIMA:
        return True
    return False


def achar_proxima_pagina(soup, url_atual, pagina_atual):
    """
    Descobre a URL da próxima página lendo a própria página, sem precisar
    saber o parâmetro de paginação do site.

    Ordem de tentativa (da mais confiável para a menos):
      1. rel="next" — padrão HTML, é o sinal mais forte que existe
      2. link cujo texto é exatamente o número da próxima página
      3. link com texto de avanço ("próxima", "next", "»") num container
         de paginação
      4. link com texto de avanço em qualquer lugar da página

    Devolve a URL absoluta, ou None se não achar.
    """
    host_atual = urlparse(url_atual).netloc

    def valida(href):
        """Aceita só link interno, diferente da página atual."""
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            return None
        completa = urljoin(url_atual, href).split("#")[0]
        if urlparse(completa).netloc != host_atual:
            return None
        if completa.rstrip("/") == url_atual.rstrip("/"):
            return None
        return completa

    # 1. rel="next" (em <a> ou <link>)
    for tag in soup.find_all(["a", "link"], rel=True):
        rel = tag.get("rel")
        rel = [rel] if isinstance(rel, str) else (rel or [])
        if any("next" in r.lower() for r in rel):
            url = valida(tag.get("href"))
            if url:
                return url

    # 2. link cujo texto é o número da próxima página
    alvo = str(pagina_atual + 1)
    for a in soup.find_all("a", href=True):
        if limpar(a.get_text()) == alvo:
            url = valida(a["href"])
            if url:
                return url

    # 3. texto de avanço dentro de um container de paginação
    for seletor in CONTAINERS_PAGINACAO:
        try:
            containers = soup.select(seletor)
        except Exception:
            continue
        for cont in containers:
            for a in cont.find_all("a", href=True):
                if texto_indica_proxima(
                    limpar(a.get_text()),
                    a.get("title") or "",
                    a.get("aria-label") or "",
                ):
                    url = valida(a["href"])
                    if url:
                        return url

    # 4. último recurso: texto de avanço em qualquer link da página
    for a in soup.find_all("a", href=True):
        texto = limpar(a.get_text())
        if not texto or len(texto) > 30:
            continue
        if texto_indica_proxima(texto, a.get("title") or "", a.get("aria-label") or ""):
            url = valida(a["href"])
            if url:
                return url

    return None


def montar_url_pagina(url_base, cfg_pag, numero):
    """
    Devolve a URL da página 'numero'.

    Dois modos:
      tipo="query"    -> troca/insere um parâmetro na query string.
                         Ex: ...&pg=1  ->  ...&pg=3
                         Parâmetros duplicados são normalizados para um só,
                         então uma URL copiada com "&pg=1&pg=2" é corrigida.
      tipo="template" -> substitui o marcador {pagina} na própria URL.
                         Ex: https://site.br/editais/page/{pagina}/
    """
    if not cfg_pag:
        return url_base

    tipo = cfg_pag.get("tipo", "query")

    if tipo == "template":
        return url_base.replace("{pagina}", str(numero))

    parametro = cfg_pag.get("parametro", "page")
    partes = urlparse(url_base)
    query = parse_qs(partes.query, keep_blank_values=True)
    query[parametro] = [str(numero)]   # lista de 1 item = elimina duplicatas
    nova_query = urlencode(query, doseq=True)
    return urlunparse(partes._replace(query=nova_query))


def provavel_javascript(soup):
    """
    Heurística para páginas que montam o conteúdo por JavaScript.

    Sinal característico: muito código de script e pouquíssimo conteúdo em
    HTML, frequentemente com um contêiner de montagem vazio (<div id="root">,
    <div id="app">, [data-reactroot]). Nesse caso o `requests` recebe o
    esqueleto da página, não a lista — e não há o que extrair.
    """
    scripts = soup.find_all("script")
    tamanho_scripts = sum(len(s.get_text() or "") for s in scripts)
    for src in ("src",):
        tamanho_scripts += sum(200 for s in scripts if s.get(src))

    texto_visivel = len(limpar(soup.get_text()))
    links = len(soup.find_all("a", href=True))

    ancora_vazia = False
    for seletor in ("#root", "#app", "#__next", "[data-reactroot]", "#application"):
        try:
            el = soup.select_one(seletor)
        except Exception:
            continue
        if el is not None and len(limpar(el.get_text())) < 50:
            ancora_vazia = True
            break

    if ancora_vazia:
        return True
    if links <= 5 and tamanho_scripts > max(2000, texto_visivel * 2):
        return True
    return False


def raspar_uma_pagina(sessao, fonte, cfg, clf, analisador, url, orcamento=None):
    """Baixa uma listagem e devolve somente oportunidades Global Ed ativas.

    A listagem serve apenas para descobrir candidatos. A decisao final usa o
    texto do card + a pagina/PDF de detalhe e valida o prazo.
    """
    html, erro = buscar(sessao, url, cfg, orcamento)
    if html is None:
        return [], 0, "", erro, None

    soup = BeautifulSoup(html, "lxml")

    brutos = extrair_por_seletor(soup, fonte, url)
    estrategia = "seletor"
    if len(brutos) < 3:
        por_varredura = extrair_por_varredura(soup, url)
        if len(por_varredura) > len(brutos):
            brutos, estrategia = por_varredura, "varredura"

    relevantes = []
    descartados_navegacao = 0
    descartados_pre = 0
    descartados_prazo = 0
    descartados_fit = 0
    detalhes_ok = 0

    limite_detalhes = int(
        fonte.get("max_detalhes", cfg.get("max_detalhes_por_fonte", 35))
    )
    detalhes_usados = int(fonte.get("_detalhes_usados", 0))

    # Ordena antes de baixar detalhes. Em fontes grandes, isso impede que links
    # genericos consumam o orcamento antes de cotutela/cooperacao/mobilidade.
    candidatos = []
    for posicao, item in enumerate(brutos):
        titulo = limpar_titulo(item["titulo"])
        if eh_navegacao(titulo):
            descartados_navegacao += 1
            continue

        encerrada_ano, ano = edicao_encerrada(titulo, item["url"])
        if encerrada_ano:
            descartados_prazo += 1
            continue

        contexto = item.get("contexto_texto", "")
        texto_pre = " ".join([titulo, item.get("data_texto", ""), contexto, item["url"]])
        if not analisador.prequalificar(texto_pre, fonte):
            descartados_pre += 1
            continue
        pre_score = analisador.pontuar_prequalificacao(texto_pre, fonte)
        candidatos.append((pre_score, -posicao, item, titulo, ano, texto_pre))

    candidatos.sort(reverse=True, key=lambda x: (x[0], x[1]))

    for _pre_score, _ordem, item, titulo, ano, texto_pre in candidatos:
        texto_detalhe = ""
        detalhe_tipo = ""
        if detalhes_usados < limite_detalhes:
            texto_detalhe, detalhe_tipo = buscar_texto_detalhe(
                sessao, item["url"], cfg, orcamento
            )
            detalhes_usados += 1
            if texto_detalhe:
                detalhes_ok += 1

        texto_completo = " ".join([texto_pre, texto_detalhe])[:180000]
        avaliacao = analisador.avaliar(texto_completo, fonte)

        if not avaliacao["relevante"]:
            descartados_fit += 1
            continue

        # O modo estrito e a resposta direta ao problema relatado: se o prazo
        # venceu ou nao pode ser confirmado, a oportunidade nao entra no painel.
        if cfg.get("modo_estrito_global_ed", True):
            if avaliacao["status"] != "aberto":
                descartados_prazo += 1
                continue
            exigir_data = fonte.get(
                "exigir_prazo_confirmado", cfg.get("exigir_prazo_confirmado", True)
            )
            if exigir_data and not avaliacao.get("prazo_final"):
                descartados_prazo += 1
                continue
        elif (
            avaliacao["status"] == "verificar"
            and not cfg.get("aceitar_prazo_desconhecido", False)
        ):
            descartados_prazo += 1
            continue

        resultado = clf.classificar(
            titulo,
            item["url"],
            fonte.get("sempre_internacional", False),
            texto_extra=texto_completo,
            permitir_sem_tema=True,
        )
        if resultado is None:
            descartados_fit += 1
            continue

        for tema in avaliacao.get("temas_sugeridos", []):
            if tema in clf.temas and tema not in resultado["temas"]:
                resultado["temas"].append(tema)
        resultado["temas"] = sorted(
            set(resultado["temas"]),
            key=lambda c: clf.temas.get(c, {}).get("prioridade", 3),
        )
        resultado["status"] = avaliacao["status"]
        resultado["pontos"] = avaliacao["aderencia"]

        # O catalogo agora recebe o detalhe, nao apenas o titulo.
        achadas = identificar_restricoes(texto_completo[:70000], item["url"])
        if avaliacao.get("apenas_instituicao_publica"):
            achadas.append({
                "programa": "Restricao detectada no edital",
                "exige": "o texto aparenta limitar a chamada a instituicoes publicas; confirmar no edital",
                "impacto": "bloqueia",
            })
        resultado["restricoes"] = achadas
        resultado["situacao_elegibilidade"] = rotulo_situacao(achadas)
        resultado["prioridade"] = prioridade_final(
            resultado["pontos"], fonte["nome"], achadas, resultado["status"]
        )

        item = {**item, **resultado}
        item["titulo"] = titulo
        item["ano_edicao"] = ano
        item["prazo_final"] = avaliacao.get("prazo_final", "")
        item["prazo_texto"] = avaliacao.get("prazo_texto", "")
        item["dias_restantes"] = avaliacao.get("dias_restantes")
        item["confianca_prazo"] = avaliacao.get("confianca_prazo", 0)
        item["motivo_status"] = avaliacao.get("motivo_status", "")
        item["aderencia"] = avaliacao.get("aderencia", 0)
        item["eixos"] = avaliacao.get("eixos", [])
        item["eixos_rotulos"] = avaliacao.get("eixos_rotulos", [])
        item["publico_alvo"] = avaliacao.get("publico_alvo", [])
        item["alertas_automaticos"] = avaliacao.get("alertas_automaticos", [])
        item["motivo_relevancia"] = avaliacao.get("motivo_relevancia", "")
        item["detalhe_lido"] = bool(texto_detalhe)
        item["detalhe_tipo"] = detalhe_tipo
        relevantes.append(item)

    fonte["_detalhes_usados"] = detalhes_usados

    if descartados_navegacao:
        log.info("      %d link(s) descartado(s) como navegacao", descartados_navegacao)
    log.info(
        "      filtro Global Ed: %d pre-filtro, %d baixa aderencia, %d prazo/status, %d detalhe(s) lido(s)",
        descartados_pre, descartados_fit, descartados_prazo, detalhes_ok,
    )

    return relevantes, len(brutos), estrategia, None, soup

def percorrer_paginas(sessao, fonte, cfg, clf, analisador, url_base, tentativas_log, orcamento=None):
    """
    Percorre as páginas de uma fonte paginada, acumulando resultados.

    Três modos, definidos em fonte["paginacao"]["tipo"]:
      "auto"     — lê o link de "próxima página" da própria página (padrão).
                   Não precisa saber o parâmetro do site.
      "query"    — troca um parâmetro da URL (?pg=1 -> ?pg=2).
      "template" — substitui {pagina} na URL.

    Para quando: a página falha, vem vazia, não traz nenhuma URL nova,
    não há próxima página, ou o teto max_paginas é atingido.

    A parada por "nada novo" é essencial: muitos sites devolvem a última
    página repetidamente quando o número pedido passa do fim, e sem esse
    teste o laço rodaria até o teto coletando repetições.
    """
    cfg_pag = fonte["paginacao"]
    tipo = cfg_pag.get("tipo", "auto")
    inicio = int(cfg_pag.get("inicio", 1))
    limite = int(cfg_pag.get("max_paginas", 5))

    acumulado = []
    vistos_itens = set()
    urls_visitadas = set()
    estrategia_final = ""
    numero = inicio
    url = url_base if tipo == "auto" else montar_url_pagina(url_base, cfg_pag, inicio)

    for indice in range(limite):
        if url in urls_visitadas:
            log.info("      pág %d: URL repetida — fim da paginação", numero)
            break
        urls_visitadas.add(url)

        if orcamento is not None and orcamento.estourou():
            log.warning(
                "      tempo da fonte esgotado (%.0fs) — parando com %d pág lidas",
                orcamento.limite, indice,
            )
            break

        relevantes, n_brutos, estrategia, erro, soup = raspar_uma_pagina(
            sessao, fonte, cfg, clf, analisador, url, orcamento
        )

        if erro is not None:
            if indice == 0:
                tentativas_log.append(f"{url} -> {erro}")
                return [], None, ""
            log.info("      pág %d: %s — encerrando paginação", numero, erro)
            break

        if indice == 0:
            estrategia_final = estrategia
            if not relevantes:
                tentativas_log.append(
                    f"{url} -> OK, {n_brutos} links, 0 relevantes ({estrategia})"
                )
                log.info(
                    "      pág %d respondeu, mas sem oportunidade ativa; continuando a paginação",
                    numero,
                )

        novos = [r for r in relevantes if r["url"] not in vistos_itens]
        if indice > 0 and not novos:
            log.info("      pág %d: nada novo — fim da paginação", numero)
            break

        acumulado.extend(novos)
        vistos_itens.update(r["url"] for r in novos)
        log.info("      pág %d: %d bruto(s), %d novo(s)", numero, n_brutos, len(novos))

        if n_brutos == 0:
            log.info("      pág %d: página vazia — fim da paginação", numero)
            break

        # descobre para onde ir
        if tipo == "auto":
            proxima = achar_proxima_pagina(soup, url, numero)
            if not proxima:
                log.info("      sem link de próxima página — fim (%d pág lidas)", indice + 1)
                break
            url = proxima
        else:
            url = montar_url_pagina(url_base, cfg_pag, numero + 1)

        numero += 1
        time.sleep(cfg.get("pausa_entre_paginas", 1.0))
    else:
        log.info("      teto de %d páginas atingido", limite)

    tentativas_log.append(
        f"{url_base} -> OK, {len(acumulado)} relevantes em "
        f"{len(urls_visitadas)} página(s) ({estrategia_final})"
    )
    return acumulado, url_base, estrategia_final


def resolver_e_raspar(sessao, fonte, cfg, urls_ok, clf, analisador, orcamento=None):
    """
    Percorre os URLs candidatos da fonte até um deles produzir editais
    relevantes. Devolve (itens_classificados, url_usada, diagnostico).
    """
    nome = fonte["nome"]
    fonte["_detalhes_usados"] = 0
    candidatos = list(fonte.get("urls_candidatos", []))

    # o URL que funcionou na última vez vai para o começo da fila
    url_memorizada = urls_ok.get(nome)
    if url_memorizada and url_memorizada in candidatos:
        candidatos.remove(url_memorizada)
        candidatos.insert(0, url_memorizada)
    elif url_memorizada:
        candidatos.insert(0, url_memorizada)

    tentativas_log = []
    tem_paginacao = bool(fonte.get("paginacao"))
    ler_todas = bool(fonte.get("ler_todas_urls"))

    # Modo acumulativo: os urls_candidatos são SEÇÕES DIFERENTES da mesma fonte
    # (ex: FAPES tem páginas separadas para internacionais, pesquisa, extensão,
    # inovação), não alternativas da mesma página. Lê todas e junta.
    if ler_todas:
        acumulado = []
        vistos = set()
        urls_ok_lista = []
        for url in candidatos:
            if orcamento is not None and orcamento.estourou():
                log.warning("    tempo da fonte esgotado — %d seção(ões) não lida(s)",
                            len(candidatos) - candidatos.index(url))
                break
            if tem_paginacao:
                itens, url_res, _ = percorrer_paginas(
                    sessao, fonte, cfg, clf, analisador, url, tentativas_log, orcamento
                )
            else:
                itens, n_br, estrat, erro, soup = raspar_uma_pagina(
                    sessao, fonte, cfg, clf, analisador, url, orcamento
                )
                if erro is not None:
                    tentativas_log.append(f"{url} -> {erro}")
                    log.info("    seção %s -> %s", url, erro)
                    continue
                tentativas_log.append(
                    f"{url} -> OK, {n_br} links, {len(itens)} relevantes ({estrat})"
                )
                url_res = url

            novos = [i for i in itens if i["url"] not in vistos]
            acumulado.extend(novos)
            vistos.update(i["url"] for i in novos)
            if url_res:
                urls_ok_lista.append(url_res)
            log.info("    seção lida: %s -> %d novo(s)", url, len(novos))
            time.sleep(cfg.get("pausa_entre_paginas", 1.0))

        if acumulado:
            log.info(
                "    TOTAL da fonte: %d edital(is) de %d seção(ões)",
                len(acumulado), len(urls_ok_lista),
            )
        return acumulado, (urls_ok_lista[0] if urls_ok_lista else None), tentativas_log

    # Modo alternativas (padrão): para na primeira URL que der resultado.
    primeiro_ok = None
    for url in candidatos:
        if tem_paginacao:
            relevantes, url_ok, _ = percorrer_paginas(
                sessao, fonte, cfg, clf, analisador, url, tentativas_log, orcamento
            )
            if url_ok and primeiro_ok is None:
                primeiro_ok = url_ok
            if relevantes:
                return relevantes, url_ok, tentativas_log
            continue

        if orcamento is not None and orcamento.estourou():
            log.warning("    tempo da fonte esgotado — candidatos restantes não testados")
            break

        relevantes, n_brutos, estrategia, erro, soup = raspar_uma_pagina(
            sessao, fonte, cfg, clf, analisador, url, orcamento
        )
        if erro is not None:
            tentativas_log.append(f"{url} -> {erro}")
            log.info("    tentou %s -> %s", url, erro)
            continue

        if primeiro_ok is None:
            primeiro_ok = url
        tentativas_log.append(
            f"{url} -> OK, {n_brutos} links, {len(relevantes)} relevantes ({estrategia})"
        )
        log.info(
            "    %s -> %d link(s) brutos, %d relevante(s) via %s",
            url, n_brutos, len(relevantes), estrategia,
        )

        if n_brutos <= 3 and soup is not None and provavel_javascript(soup):
            log.warning(
                "    ATENÇÃO: a página respondeu mas quase não tem links — "
                "provavelmente monta a lista por JavaScript. Ver LEIA-ME, "
                "seção 'Fontes que exigem navegador'."
            )
            tentativas_log.append(f"{url} -> suspeita de conteúdo carregado por JavaScript")

        if relevantes:
            return relevantes, url, tentativas_log
        # página respondeu mas não tinha nada relevante: tenta o próximo candidato

    return [], primeiro_ok, tentativas_log


# --------------------------------------------------------------------------- #
# Execução
# --------------------------------------------------------------------------- #

def executar(filtro_fonte=None):
    cfg = carregar_config()
    fontes = carregar_fontes()
    if filtro_fonte:
        selecionadas = selecionar_fontes_por_nome(fontes, filtro_fonte)
        if not selecionadas:
            log.error(
                "Fonte '%s' não encontrada. Disponíveis: %s",
                filtro_fonte, ", ".join(f["nome"] for f in fontes),
            )
            return None
        fontes = selecionadas

    clf = Classificador()
    analisador = AnalisadorGlobalEd()
    sessao = montar_sessao(cfg)
    historico = carregar_json(ARQ_HISTORICO, {})
    urls_ok = carregar_json(ARQ_URLS_OK, {})
    estado = carregar_json(ARQ_ESTADO, {"execucao": 0, "execucoes": []})
    agora = datetime.now().isoformat(timespec="seconds")

    # Número da execução. É o que permite distinguir "novidade de verdade" de
    # "estava no acervo desde a primeira coleta" — sem isso, a primeira
    # execução marca tudo como novo e o rótulo perde sentido.
    estado["execucao"] = int(estado.get("execucao", 0)) + 1
    execucao_atual = estado["execucao"]
    primeira_execucao = execucao_atual == 1
    log.info("Execução nº %d%s", execucao_atual,
             " (primeira: tudo será marcado como acervo inicial)" if primeira_execucao else "")

    diagnostico = []
    novos_total = 0
    fontes_ok = 0
    interrompido = False

    for fonte in fontes:
        nome = fonte["nome"]
        log.info("Fonte: %s [%s]", nome, fonte["regiao"])

        # Orçamento de tempo por fonte: o corte real contra páginas que penduram.
        # Pode ser sobrescrito por fonte com "tempo_max_segundos".
        limite = float(fonte.get("tempo_max_segundos",
                                cfg.get("tempo_max_por_fonte", 120)))
        orcamento = Orcamento(limite)

        try:
            itens, url_usada, tentativas = resolver_e_raspar(
                sessao, fonte, cfg, urls_ok, clf, analisador, orcamento
            )
        except KeyboardInterrupt:
            log.warning(
                "\nInterrompido pelo usuário durante '%s'. "
                "Salvando o que já foi coletado...", nome
            )
            interrompido = True
            itens, url_usada, tentativas = [], None, ["interrompido pelo usuário"]

        if url_usada:
            urls_ok[nome] = url_usada
            fontes_ok += 1
            situacao = "ok"
        else:
            situacao = "falhou"
            log.warning("  -> nenhum candidato funcionou para %s", nome)

        novos_da_fonte = 0
        atualizados_da_fonte = 0
        for item in itens:
            chave = item["url"]
            titulo_novo = item.get("titulo") or item["titulo_limpo"]

            if chave in historico:
                registro = historico[chave]
                mudancas = detectar_alteracao(registro, titulo_novo, item["status"])
                if mudancas:
                    registro["alterado_na_execucao"] = execucao_atual
                    registro["mudancas"] = mudancas
                    atualizados_da_fonte += 1
                    log.info("      alterado: %s (%s)",
                             titulo_novo[:60], "; ".join(mudancas))
                registro["titulo"] = titulo_novo or registro["titulo"]
                registro["temas"] = item["temas"]
                registro["status"] = item["status"]
                registro["pontos"] = item["pontos"]
                registro["prioridade"] = item.get("prioridade", item["pontos"])
                registro["restricoes"] = item.get("restricoes", [])
                registro["situacao_elegibilidade"] = item.get("situacao_elegibilidade", "sem_catalogo")
                for campo in (
                    "prazo_final", "prazo_texto", "dias_restantes",
                    "confianca_prazo", "motivo_status", "aderencia",
                    "eixos", "eixos_rotulos", "publico_alvo",
                    "alertas_automaticos", "motivo_relevancia",
                    "detalhe_lido", "detalhe_tipo",
                ):
                    if campo in item:
                        registro[campo] = item[campo]
                registro["arquivo"] = item.get("arquivo", registro.get("arquivo", ""))
                if item.get("anexos"):
                    registro["anexos"] = item["anexos"]
                registro["visto_por_ultimo"] = agora
                registro["execucao_ultima"] = execucao_atual
            else:
                # é a edição nova de uma chamada recorrente já conhecida?
                url_anterior, ano_anterior = encontrar_edicao_anterior(
                    titulo_novo, historico, chave
                )
                historico[chave] = {
                    "titulo": titulo_novo,
                    "url": item["url"],
                    "data_texto": item["data_texto"],
                    "arquivo": item.get("arquivo", ""),
                    "anexos": item.get("anexos", []),
                    "fonte": nome,
                    "regiao": fonte["regiao"],
                    "temas": item["temas"],
                    "status": item["status"],
                    "pontos": item["pontos"],
                    "prioridade": item.get("prioridade", item["pontos"]),
                    "restricoes": item.get("restricoes", []),
                    "situacao_elegibilidade": item.get("situacao_elegibilidade", "sem_catalogo"),
                    "prazo_final": item.get("prazo_final", ""),
                    "prazo_texto": item.get("prazo_texto", ""),
                    "dias_restantes": item.get("dias_restantes"),
                    "confianca_prazo": item.get("confianca_prazo", 0),
                    "motivo_status": item.get("motivo_status", ""),
                    "aderencia": item.get("aderencia", item.get("pontos", 0)),
                    "eixos": item.get("eixos", []),
                    "eixos_rotulos": item.get("eixos_rotulos", []),
                    "publico_alvo": item.get("publico_alvo", []),
                    "alertas_automaticos": item.get("alertas_automaticos", []),
                    "motivo_relevancia": item.get("motivo_relevancia", ""),
                    "detalhe_lido": item.get("detalhe_lido", False),
                    "detalhe_tipo": item.get("detalhe_tipo", ""),
                    "ano_edicao": item.get("ano_edicao"),
                    "visto_primeiro": agora,
                    "visto_por_ultimo": agora,
                    "execucao_primeira": execucao_atual,
                    "execucao_ultima": execucao_atual,
                }
                if url_anterior:
                    historico[chave]["nova_edicao_de"] = url_anterior
                    historico[chave]["edicao_anterior_ano"] = ano_anterior
                    log.info("      nova edição de chamada conhecida (%s): %s",
                             ano_anterior, titulo_novo[:56])
                novos_da_fonte += 1

        # Se a listagem oficial respondeu normalmente, mas uma oportunidade que
        # antes estava aberta nao apareceu nesta coleta, ela deixa de ser
        # tratada como "aberta confirmada". Isto evita perpetuar chamadas
        # retiradas/encerradas sem prazo parseavel no historico.
        if situacao == "ok":
            for registro in historico.values():
                if registro.get("fonte") != nome:
                    continue
                if registro.get("execucao_ultima") == execucao_atual:
                    continue
                if registro.get("status") != "aberto":
                    continue
                registro["status"] = "verificar"
                registro["motivo_status"] = (
                    "nao localizado na listagem oficial na ultima coleta; confirmar antes de usar"
                )
                alertas = list(registro.get("alertas_automaticos") or [])
                if "nao localizado na ultima coleta" not in alertas:
                    alertas.append("nao localizado na ultima coleta")
                registro["alertas_automaticos"] = alertas
                registro["alterado_na_execucao"] = execucao_atual
                mudancas = list(registro.get("mudancas") or [])
                if "aberto -> verificar (nao localizado)" not in mudancas:
                    mudancas.append("aberto -> verificar (nao localizado)")
                registro["mudancas"] = mudancas[-6:]
                atualizados_da_fonte += 1

        novos_total += novos_da_fonte
        log.info(
            "  -> %d relevante(s), %d novo(s), %d atualizado(s) — %.0fs",
            len(itens), novos_da_fonte, atualizados_da_fonte, orcamento.decorrido(),
        )

        diagnostico.append({
            "fonte": nome,
            "regiao": fonte["regiao"],
            "situacao": situacao,
            "url_usada": url_usada or "",
            "relevantes": len(itens),
            "novos": novos_da_fonte,
            "atualizados": atualizados_da_fonte,
            "segundos": round(orcamento.decorrido(), 1),
            "tentativas": tentativas,
        })

        # Salva a cada fonte: se travar ou for interrompido, não perde o anterior.
        salvar_json(ARQ_HISTORICO, historico)
        salvar_json(ARQ_URLS_OK, urls_ok)

        if interrompido:
            break

        try:
            time.sleep(cfg["pausa_entre_fontes"])
        except KeyboardInterrupt:
            log.warning("\nInterrompido pelo usuário. Salvando...")
            interrompido = True
            break

    # rótulo de novidade em todos os registros
    for registro in historico.values():
        registro["novidade"] = classificar_novidade(
            registro, execucao_atual, primeira_execucao
        )

    estado["execucoes"].append({
        "numero": execucao_atual, "quando": agora,
        "novos": novos_total, "total": len(historico),
    })
    estado["execucoes"] = estado["execucoes"][-30:]

    salvar_json(ARQ_HISTORICO, historico)
    salvar_json(ARQ_URLS_OK, urls_ok)
    salvar_json(ARQ_ESTADO, estado)
    salvar_json(DADOS_DIR / "diagnostico.json",
                {"execucao": agora, "numero": execucao_atual, "fontes": diagnostico})

    log.info(
        "FIM%s: %d/%d fonte(s) com resultado, %d edital(is) novo(s), %d no histórico.",
        " (INTERROMPIDO)" if interrompido else "",
        fontes_ok, len(diagnostico), novos_total, len(historico),
    )

    lentas = [d for d in diagnostico if d.get("segundos", 0) >= 60]
    if lentas:
        log.warning("Fontes lentas (>=60s): %s", ", ".join(
            f"{d['fonte']} {d['segundos']:.0f}s" for d in lentas))

    gerar_painel(historico, diagnostico, agora, cfg, clf)
    return {"fontes_ok": fontes_ok, "fontes_total": len(diagnostico),
            "novos": novos_total, "historico": len(historico),
            "interrompido": interrompido, "lentas": lentas}


def gerar_painel(historico, diagnostico, agora, cfg, clf):
    from editais_painel import renderizar
    html = renderizar(
        historico, diagnostico, agora, cfg["dias_badge_novo"], clf.rotulos(),
        cfg.get("dias_sem_confirmacao", 7),
    )
    ARQ_PAINEL.write_text(html, encoding="utf-8")
    log.info("Painel gravado em %s", ARQ_PAINEL)


def main():
    ap = argparse.ArgumentParser(description="Painel de Editais UNIVC")
    ap.add_argument("--fonte", help="roda apenas a fonte com este nome")
    ap.add_argument("--so-painel", action="store_true",
                    help="não acessa a internet; só regera o painel a partir do histórico")
    args = ap.parse_args()

    if args.so_painel:
        cfg = carregar_config()
        historico = carregar_json(ARQ_HISTORICO, {})
        diag = carregar_json(DADOS_DIR / "diagnostico.json", {"fontes": []})
        gerar_painel(historico, diag.get("fontes", []),
                     datetime.now().isoformat(timespec="seconds"), cfg, Classificador())
        print(f"Painel regerado com {len(historico)} edital(is). Abra painel.html")
        return

    try:
        stats = executar(args.fonte)
    except KeyboardInterrupt:
        print("\nInterrompido. O histórico já salvo foi preservado.")
        print("Rode  python editais_scraper.py --so-painel  para gerar o painel.")
        return

    if stats:
        print(f"\n{'='*64}")
        if stats.get("interrompido"):
            print("  EXECUÇÃO INTERROMPIDA — o que foi coletado está salvo")
        print(f"  {stats['fontes_ok']}/{stats['fontes_total']} fontes retornaram resultado")
        print(f"  {stats['novos']} edital(is) novo(s) nesta execução")
        print(f"  {stats['historico']} edital(is) no histórico total")
        print(f"{'='*64}")
        print("  Abra painel.html para ver.")
        if stats.get("lentas"):
            print("\n  Fontes lentas nesta execução:")
            for d in stats["lentas"]:
                print(f"    {d['fonte']}: {d['segundos']:.0f}s")
            print("    Para pular uma delas, adicione  \"desativada\": true")
            print("    no bloco da fonte em fontes.json.")
        print("  Fontes que falharam: rode  python descobrir_urls.py \"NOME\"\n")


if __name__ == "__main__":
    main()
