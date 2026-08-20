#!/usr/bin/env python3
"""
Descobridor de URLs de editais
==============================
Quando uma fonte falha com 404 (o site mudou de endereço), este script
rastreia o domínio raiz procurando páginas que pareçam listagens de
editais/chamadas, e mostra os melhores candidatos com uma nota de
confiança — para você colar em fontes.json.

Uso:
    python descobrir_urls.py                     # tenta todas as fontes que falharam
    python descobrir_urls.py "CNPq"              # uma fonte específica
    python descobrir_urls.py --url https://x.br  # um domínio qualquer
"""

import argparse
import json
import re
import sys
import time
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from classificador import Classificador, normalizar
from editais_scraper import (
    ARQ_FONTES,
    DADOS_DIR,
    buscar,
    carregar_config,
    carregar_fontes,
    carregar_json,
    extrair_por_varredura,
    limpar,
    montar_sessao,
    selecionar_fontes_por_nome,
)

# Termos que, no texto do link ou no caminho da URL, sugerem página de editais
PISTAS_LISTAGEM = [
    ("chamadas publicas", 10), ("chamada publica", 10),
    ("editais", 10), ("edital", 7),
    ("chamadas", 8), ("chamada", 6),
    ("oportunidades", 7), ("opportunities", 7),
    ("calls for proposals", 10), ("call for proposals", 10),
    ("calls", 6), ("appels a candidatures", 10), ("appels", 6),
    ("bolsas", 6), ("scholarships", 7), ("becas", 6),
    ("convocatorias", 8), ("financiamentos", 5),
    ("fomento", 5), ("programas", 3), ("noticias", 2), ("news", 2),
]

# Caminhos que quase sempre NÃO são o que queremos
ANTI_PISTAS = [
    "licitac", "contratos", "compras", "pregao", "dispensa", "concurso publico",
    "processo seletivo simplificado", "servidores", "folha de pagamento",
    "privacidade", "cookies", "acessibilidade", "mapa do site", "ouvidoria",
    "webmail", "intranet", "login", "wp-admin", "wp-login", "feed",
]

MAX_PAGINAS = 12          # quantas páginas rastrear por domínio
MAX_CANDIDATOS = 60       # limite de links a avaliar


def pontuar_url(texto_link, url):
    """Nota de 0 a ~30 de quão provável é ser uma listagem de editais."""
    t = normalizar(texto_link)
    caminho = normalizar(urlparse(url).path.replace("-", " ").replace("/", " "))
    alvo = f"{t} {caminho}"

    for anti in ANTI_PISTAS:
        if anti in alvo:
            return 0

    pontos = 0
    for pista, peso in PISTAS_LISTAGEM:
        if pista in caminho:
            pontos += peso           # no caminho da URL vale mais
        elif pista in t:
            pontos += int(peso * 0.7)

    # plural no caminho sugere listagem, não documento individual
    if re.search(r"/(editais|chamadas|oportunidades|calls|bolsas|scholarships)/?", url, re.I):
        pontos += 4
    # link para PDF é o edital em si, não a listagem
    if url.lower().endswith((".pdf", ".doc", ".docx", ".zip")):
        pontos -= 8
    # URL com número de edital é documento individual
    if re.search(r"\d{2,}[-_/]\d{4}", url):
        pontos -= 3

    return max(0, pontos)


def avaliar_pagina(sessao, url, cfg, clf):
    """Baixa a URL e conta quantos editais relevantes ela produziria."""
    html, erro = buscar(sessao, url, cfg)
    if html is None:
        return None, erro, 0

    soup = BeautifulSoup(html, "lxml")
    brutos = extrair_por_varredura(soup, url)
    relevantes = 0
    for item in brutos:
        if clf.classificar(item["titulo"], item["url"]) is not None:
            relevantes += 1
    return soup, None, relevantes


def rastrear(sessao, dominio_raiz, cfg, clf):
    """
    Explora o domínio a partir da home, procurando páginas de listagem.
    Devolve lista de (url, pontos_heuristica, editais_encontrados).
    """
    print(f"\nRastreando {dominio_raiz} ...")
    soup, erro, _ = avaliar_pagina(sessao, dominio_raiz, cfg, clf)
    if soup is None:
        print(f"  Não foi possível abrir o domínio raiz: {erro}")
        print("  Verifique se o endereço está certo e se a rede permite o acesso.")
        return []

    # 1) coleta e pontua todos os links da home
    candidatos = OrderedDict()
    base_netloc = urlparse(dominio_raiz).netloc
    raiz = ".".join(base_netloc.split(".")[-2:])

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urljoin(dominio_raiz, href).split("#")[0].rstrip("/")
        if raiz not in urlparse(url).netloc:
            continue
        nota = pontuar_url(limpar(a.get_text()), url)
        if nota <= 0:
            continue
        if url not in candidatos or nota > candidatos[url][0]:
            candidatos[url] = (nota, limpar(a.get_text()))

    if not candidatos:
        print("  Nenhum link promissor encontrado na home.")
        return []

    ordenados = sorted(candidatos.items(), key=lambda kv: kv[1][0], reverse=True)
    ordenados = ordenados[:MAX_CANDIDATOS]
    print(f"  {len(ordenados)} link(s) promissor(es); testando os {min(MAX_PAGINAS, len(ordenados))} melhores...")

    # 2) abre os melhores e conta editais de verdade
    resultados = []
    for url, (nota, texto) in ordenados[:MAX_PAGINAS]:
        _, erro, achados = avaliar_pagina(sessao, url, cfg, clf)
        marca = "!" if achados >= 5 else ("+" if achados > 0 else " ")
        estado = f"{achados} edital(is)" if erro is None else f"falhou ({erro})"
        print(f"   {marca} [heur {nota:>2}] {estado:<22} {url}")
        if erro is None:
            resultados.append({"url": url, "heuristica": nota,
                               "editais": achados, "texto_link": texto})
        time.sleep(0.7)

    resultados.sort(key=lambda r: (r["editais"], r["heuristica"]), reverse=True)
    return resultados


def imprimir_sugestao(nome, resultados):
    uteis = [r for r in resultados if r["editais"] > 0]
    if not uteis:
        print(f"\n  Nenhuma página com editais relevantes encontrada para {nome}.")
        print("  Possibilidades: o site carrega a lista por JavaScript, exige login,")
        print("  ou a rede está bloqueando. Abra o site no navegador, vá até a página")
        print("  de editais e cole o endereço manualmente em fontes.json.")
        return

    print(f"\n  {'='*60}")
    print(f"  SUGESTÃO para \"{nome}\" — cole em fontes.json:")
    print(f"  {'='*60}")
    urls = [r["url"] for r in uteis[:4]]
    bloco = json.dumps({"urls_candidatos": urls}, ensure_ascii=False, indent=6)
    print("\n".join("  " + l for l in bloco.splitlines()))
    print()


def main():
    ap = argparse.ArgumentParser(description="Descobre URLs de editais")
    ap.add_argument("nome", nargs="?", help="nome da fonte em fontes.json")
    ap.add_argument("--url", help="rastreia um domínio arbitrário")
    args = ap.parse_args()

    cfg = carregar_config()
    sessao = montar_sessao(cfg)
    clf = Classificador()

    if args.url:
        resultados = rastrear(sessao, args.url.rstrip("/"), cfg, clf)
        imprimir_sugestao(args.url, resultados)
        return

    fontes = carregar_fontes()

    if args.nome:
        alvo = selecionar_fontes_por_nome(fontes, args.nome)
        if not alvo:
            print(f"Fonte '{args.nome}' nao encontrada. Disponiveis:")
            for f in fontes:
                print("  -", f["nome"])
            sys.exit(1)
    else:
        # sem argumento: só as que falharam na última execução
        diag = carregar_json(DADOS_DIR / "diagnostico.json", {"fontes": []})
        falharam = {d["fonte"] for d in diag.get("fontes", []) if d.get("situacao") != "ok"}
        if not falharam:
            print("Nenhuma fonte falhou na última execução (ou nunca houve execução).")
            print("Para rastrear uma fonte específica: python descobrir_urls.py \"CNPq\"")
            return
        alvo = [f for f in fontes if f["nome"] in falharam]
        print(f"Fontes que falharam na última execução: {', '.join(sorted(falharam))}")

    for fonte in alvo:
        resultados = rastrear(sessao, fonte["dominio_raiz"].rstrip("/"), cfg, clf)
        imprimir_sugestao(fonte["nome"], resultados)


if __name__ == "__main__":
    main()
