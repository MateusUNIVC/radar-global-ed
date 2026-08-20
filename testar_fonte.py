#!/usr/bin/env python3
"""
Diagnostico de uma fonte usando EXATAMENTE o filtro quality-first do scraper.

Uso:
    python testar_fonte.py "FAPES — Oportunidades"
    python testar_fonte.py "CONFAP" --mostrar-descartados

O script abre a listagem, ordena os candidatos pelo sinal estrategico barato,
le paginas/PDFs de detalhe e mostra prazo + aderencia + motivo de descarte.
"""

import argparse
import sys

from bs4 import BeautifulSoup

from classificador import Classificador
from oportunidades import AnalisadorGlobalEd
from relevancia import edicao_encerrada, eh_navegacao, limpar_titulo
from editais_scraper import (
    Orcamento,
    buscar,
    buscar_texto_detalhe,
    carregar_config,
    carregar_fontes,
    extrair_por_seletor,
    extrair_por_varredura,
    montar_sessao,
    selecionar_fontes_por_nome,
)


def main():
    ap = argparse.ArgumentParser(description="Diagnostico quality-first de uma fonte")
    ap.add_argument("nome", help="nome completo ou trecho unico da fonte")
    ap.add_argument("--mostrar-descartados", action="store_true",
                    help="lista tambem os candidatos rejeitados e o motivo")
    ap.add_argument("--limite", type=int, default=25, help="quantos itens mostrar por grupo")
    args = ap.parse_args()

    cfg = carregar_config()
    fontes = carregar_fontes()
    matches = selecionar_fontes_por_nome(fontes, args.nome)
    if not matches:
        print(f"Fonte '{args.nome}' nao encontrada. Disponiveis:")
        for f in fontes:
            print(f"  - {f['nome']}  [{f['regiao']}]")
        sys.exit(1)
    if len(matches) > 1:
        print(f"O trecho '{args.nome}' seleciona mais de uma fonte. Seja mais especifico:")
        for f in matches:
            print("  -", f["nome"])
        sys.exit(1)
    fonte = matches[0]

    clf = Classificador()
    analisador = AnalisadorGlobalEd()
    sessao = montar_sessao(cfg)
    orcamento = Orcamento(float(fonte.get("tempo_max_segundos", cfg.get("tempo_max_por_fonte", 120))))

    print(f"\nFonte: {fonte['nome']}  [{fonte['regiao']}]")
    print(f"Dominio raiz: {fonte['dominio_raiz']}")
    print("Modo estrito:", "sim" if cfg.get("modo_estrito_global_ed", True) else "nao")
    print("Prazo final obrigatorio:", "sim" if fonte.get("exigir_prazo_confirmado", cfg.get("exigir_prazo_confirmado", True)) else "nao")

    html = None
    url_ok = None
    for url in fonte["urls_candidatos"]:
        print(f"\n  Tentando {url}")
        html, erro = buscar(sessao, url, cfg, orcamento)
        if html is not None:
            print(f"    OK — {len(html):,} bytes")
            url_ok = url
            break
        print(f"    FALHOU — {erro}")

    if html is None:
        print("\nNenhum URL candidato respondeu.")
        print(f"Rode: python descobrir_urls.py \"{args.nome}\"")
        sys.exit(1)

    soup = BeautifulSoup(html, "lxml")
    por_seletor = extrair_por_seletor(soup, fonte, url_ok)
    por_varredura = extrair_por_varredura(soup, url_ok)
    brutos = por_seletor if len(por_seletor) >= 3 else por_varredura
    usada = "seletor" if brutos is por_seletor else "varredura"
    if len(por_varredura) > len(brutos):
        brutos, usada = por_varredura, "varredura"

    print(f"  Extracao: {usada}; {len(brutos)} link(s) bruto(s)")

    candidatos = []
    descartados = []
    for pos, item in enumerate(brutos):
        titulo = limpar_titulo(item.get("titulo", ""))
        if eh_navegacao(titulo):
            descartados.append((titulo, "navegacao", None))
            continue
        antiga, _ano = edicao_encerrada(titulo, item.get("url", ""))
        if antiga:
            descartados.append((titulo, "edicao de ano anterior", None))
            continue
        texto_pre = " ".join([
            titulo,
            item.get("data_texto", ""),
            item.get("contexto_texto", ""),
            item.get("url", ""),
        ])
        if not analisador.prequalificar(texto_pre, fonte):
            descartados.append((titulo, "sem sinal estrategico no card/titulo", None))
            continue
        pre = analisador.pontuar_prequalificacao(texto_pre, fonte)
        candidatos.append((pre, -pos, item, titulo, texto_pre))

    candidatos.sort(reverse=True, key=lambda x: (x[0], x[1]))
    max_detalhes = min(
        int(fonte.get("max_detalhes", cfg.get("max_detalhes_por_fonte", 35))),
        max(20, args.limite * 2),
    )

    aceitos = []
    for idx, (pre, _ordem, item, titulo, texto_pre) in enumerate(candidatos):
        detalhe = ""
        tipo = ""
        if idx < max_detalhes:
            detalhe, tipo = buscar_texto_detalhe(sessao, item["url"], cfg, orcamento)
        texto = " ".join([texto_pre, detalhe])[:180000]
        av = analisador.avaliar(texto, fonte)

        exige_data = fonte.get("exigir_prazo_confirmado", cfg.get("exigir_prazo_confirmado", True))
        motivo = None
        if not av["relevante"]:
            motivo = "baixa aderencia / sem eixo Global Ed"
        elif cfg.get("modo_estrito_global_ed", True) and av["status"] != "aberto":
            motivo = av.get("motivo_status") or f"status {av['status']}"
        elif cfg.get("modo_estrito_global_ed", True) and exige_data and not av.get("prazo_final"):
            motivo = "prazo final nao confirmado"

        if motivo:
            descartados.append((titulo, motivo, av))
            continue

        r = clf.classificar(
            titulo, item["url"], fonte.get("sempre_internacional", False),
            texto_extra=texto, permitir_sem_tema=True,
        ) or {"temas": []}
        aceitos.append((titulo, pre, av, tipo, r.get("temas", [])))

    aceitos.sort(key=lambda x: (x[2].get("aderencia", 0), x[1]), reverse=True)

    print("\n" + "=" * 100)
    print(f"ACEITOS COMO ABERTOS CONFIRMADOS: {len(aceitos)}")
    print("=" * 100)
    print(f"{'FIT':>3} {'PRE':>3} {'PRAZO':<10} {'TIPO':<5} TITULO")
    print("-" * 100)
    for titulo, pre, av, tipo, _temas in aceitos[:args.limite]:
        print(f"{av.get('aderencia',0):>3} {pre:>3} {av.get('prazo_texto','-') or '-':<10} {tipo[:5]:<5} {titulo[:70]}")
        if av.get("motivo_relevancia"):
            print(" " * 8 + "-> " + av["motivo_relevancia"][:86])

    print(f"\nDESCARTADOS: {len(descartados)}")
    if args.mostrar_descartados:
        print("-" * 100)
        for titulo, motivo, av in descartados[:args.limite]:
            fit = av.get("aderencia", 0) if av else 0
            prazo = av.get("prazo_texto", "") if av else ""
            print(f"x fit={fit:>3} prazo={prazo or '-':<10} {titulo[:58]:<58} | {motivo}")
        if len(descartados) > args.limite:
            print(f"... e mais {len(descartados) - args.limite}")

    print("\nEsse diagnostico usa o mesmo criterio do painel: detalhe/PDF + prazo + eixo Global Ed.\n")


if __name__ == "__main__":
    main()
