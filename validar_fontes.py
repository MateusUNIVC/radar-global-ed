#!/usr/bin/env python3
"""
Validador do fontes.json
========================
Checa o arquivo de fontes SEM acessar a internet, pegando os erros que
quebrariam a execução antes mesmo da primeira requisição.

Uso:
    python validar_fontes.py            # só relata
    python validar_fontes.py --corrigir  # aplica as correções seguras
"""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
ARQ_FONTES = BASE_DIR / "fontes.json"

REGIOES_VALIDAS = {"es", "nacional", "internacional"}
TIPOS_PAGINACAO = {"auto", "query", "template"}

# Parâmetros de busca que costumam significar "só o que já fechou"
VALORES_SUSPEITOS = {
    "filtro": ["encerrada", "encerradas", "fechada", "fechadas", "closed", "expirado"],
    "status": ["encerrada", "encerradas", "fechada", "closed", "3", "9"],
}


def host_de(url):
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return urlparse(url).netloc.lower().replace("www.", "")


def validar(fontes):
    """Devolve (erros, avisos, correcoes) — correcoes é dict com o que dá para arrumar."""
    erros, avisos, correcoes = [], [], {}
    nomes = set()

    for indice, f in enumerate(fontes):
        nome = f.get("nome") or f"[fonte sem nome, posição {indice}]"
        rot = f"{nome}"

        # --- campos obrigatórios ---
        for campo in ("nome", "regiao", "urls_candidatos"):
            if not f.get(campo):
                erros.append(f"{rot}: campo obrigatório ausente ou vazio: '{campo}'")

        if nome in nomes:
            erros.append(f"{rot}: nome duplicado — o histórico usa o nome como rótulo")
        nomes.add(nome)

        if f.get("regiao") and f["regiao"] not in REGIOES_VALIDAS:
            erros.append(
                f"{rot}: regiao '{f['regiao']}' inválida "
                f"(use: {', '.join(sorted(REGIOES_VALIDAS))})"
            )

        # --- URLs candidatos ---
        candidatos = f.get("urls_candidatos") or []
        if isinstance(candidatos, str):
            erros.append(f"{rot}: urls_candidatos deve ser uma lista, não texto")
            candidatos = [candidatos]

        hosts = set()
        for pos, u in enumerate(candidatos):
            if not isinstance(u, str) or not u.strip():
                erros.append(f"{rot}: URL vazia na posição {pos}")
                continue

            if not u.startswith(("http://", "https://")):
                erros.append(
                    f"{rot}: URL sem 'https://' — requests lança MissingSchema: {u}"
                )
                correcoes.setdefault(nome, {}).setdefault("urls", {})[pos] = "https://" + u
                hosts.add(host_de(u))
                continue

            partes = urlparse(u)
            hosts.add(partes.netloc.lower().replace("www.", ""))

            # query grudada no caminho, sem '?'
            if "=" in partes.path and not partes.query:
                avisos.append(
                    f"{rot}: parece haver filtro no caminho sem '?' — "
                    f"confira se não deveria ser '?': ...{partes.path}"
                )

            # parâmetro repetido
            if partes.query:
                q = parse_qs(partes.query, keep_blank_values=True)
                for chave, valores in q.items():
                    if len(valores) <= 1:
                        continue
                    # Repetição com valores numéricos distintos = quase sempre
                    # acidente de paginação (?pg=1&...&pg=2, gerado ao clicar
                    # na página 2 e copiar da barra de endereço).
                    # Repetição com valores de texto = filtro multi-valor
                    # intencional (?category=A&category=B), que é legítimo e
                    # preservado pela paginação.
                    if all(v.isdigit() for v in valores):
                        avisos.append(
                            f"{rot}: parâmetro '{chave}' repetido com números "
                            f"{valores} — parece URL copiada após clicar numa página. "
                            f"O scraper normaliza para um valor só."
                        )
                    else:
                        avisos.append(
                            f"{rot}: '{chave}' tem {len(valores)} valores "
                            f"(filtro multi-valor) — preservado na paginação, "
                            f"só confirme que são os filtros que você quer."
                        )
                # filtro que pode estar excluindo o que interessa
                for chave, ruins in VALORES_SUSPEITOS.items():
                    for valor in q.get(chave, []):
                        if valor.lower() in ruins:
                            avisos.append(
                                f"{rot}: a URL filtra '{chave}={valor}' — isso pode "
                                f"trazer só editais encerrados. Confira se não quer o "
                                f"filtro de abertos/em andamento."
                            )

        # --- domínio raiz ---
        dr = f.get("dominio_raiz", "")
        if not dr:
            avisos.append(f"{rot}: sem dominio_raiz — descobrir_urls.py não funcionará")
        else:
            if not dr.startswith(("http://", "https://")):
                erros.append(f"{rot}: dominio_raiz sem esquema: {dr}")
                correcoes.setdefault(nome, {})["dominio_raiz"] = "https://" + dr
            h_dr = host_de(dr)
            if hosts and h_dr and h_dr not in hosts:
                sugestao = sorted(hosts)[0]
                erros.append(
                    f"{rot}: dominio_raiz ({h_dr}) não bate com os candidatos "
                    f"({', '.join(sorted(hosts))}) — descobrir_urls.py rastrearia "
                    f"o site errado"
                )
                correcoes.setdefault(nome, {})["dominio_raiz"] = f"https://{sugestao}"

        # --- seletores ---
        if not f.get("seletor"):
            avisos.append(f"{rot}: sem seletor — usará sempre a varredura de links")

        # --- paginação ---
        pag = f.get("paginacao")
        if pag:
            tipo = pag.get("tipo", "auto")
            if tipo not in TIPOS_PAGINACAO:
                erros.append(
                    f"{rot}: paginacao.tipo '{tipo}' inválido "
                    f"(use: {', '.join(sorted(TIPOS_PAGINACAO))})"
                )
            if tipo == "template":
                if not any("{pagina}" in u for u in candidatos):
                    erros.append(
                        f"{rot}: paginacao tipo 'template' exige o marcador "
                        f"{{pagina}} em pelo menos um urls_candidatos"
                    )
            if tipo == "query" and not pag.get("parametro"):
                erros.append(f"{rot}: paginacao tipo 'query' exige 'parametro'")
            teto = int(pag.get("max_paginas", 5))
            if teto > 25:
                avisos.append(
                    f"{rot}: max_paginas={teto} é alto — cada página é uma "
                    f"requisição. A parada automática já protege; 5 a 10 basta."
                )

    return erros, avisos, correcoes


def aplicar(fontes, correcoes):
    n = 0
    for f in fontes:
        c = correcoes.get(f.get("nome"))
        if not c:
            continue
        if "dominio_raiz" in c:
            print(f"  {f['nome']}: dominio_raiz -> {c['dominio_raiz']}")
            f["dominio_raiz"] = c["dominio_raiz"]
            n += 1
        for pos, nova in (c.get("urls") or {}).items():
            print(f"  {f['nome']}: URL[{pos}] -> {nova}")
            f["urls_candidatos"][pos] = nova
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description="Valida o fontes.json")
    ap.add_argument("--corrigir", action="store_true",
                    help="aplica as correções seguras e salva o arquivo")
    args = ap.parse_args()

    dados = json.load(open(ARQ_FONTES, encoding="utf-8"))
    fontes = dados["fontes"]

    erros, avisos, correcoes = validar(fontes)

    print(f"\n{len(fontes)} fonte(s) verificada(s)")

    if erros:
        print(f"\nERROS ({len(erros)}) — impedem ou atrapalham a execução:")
        for e in erros:
            print(f"  x {e}")
    if avisos:
        print(f"\nAVISOS ({len(avisos)}) — vale conferir:")
        for a in avisos:
            print(f"  ! {a}")
    if not erros and not avisos:
        print("\nNenhum problema encontrado.")

    if correcoes:
        if args.corrigir:
            print(f"\nAplicando correções:")
            n = aplicar(fontes, correcoes)
            backup = ARQ_FONTES.with_suffix(".json.bak")
            backup.write_text(
                json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            with open(ARQ_FONTES, "w", encoding="utf-8") as fh:
                json.dump(dados, fh, ensure_ascii=False, indent=2)
            print(f"\n{n} correção(ões) aplicada(s). Backup em {backup.name}")
        else:
            print(f"\n{sum(1 + len(c.get('urls', {})) for c in correcoes.values())} "
                  f"item(ns) podem ser corrigidos automaticamente.")
            print("Rode:  python validar_fontes.py --corrigir")

    sys.exit(1 if erros else 0)


if __name__ == "__main__":
    main()
