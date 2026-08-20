"""Gera o painel.html — arquivo único, responsivo e sem dependências externas."""

import json
from copy import deepcopy
from datetime import datetime, timedelta, date

from relevancia import agrupar_equivalentes

CORES = {
    "indigo": ("#EEF0FF", "#3B3B8F", "#8E90D8"),
    "teal":   ("#E4F2F0", "#12615A", "#6FB3AA"),
    "roxo":   ("#F4EBFA", "#6B2E8F", "#B583D4"),
    "verde":  ("#E8F3E6", "#2C6323", "#84B87A"),
    "ambar":  ("#FBF0DC", "#8A5A11", "#D4A855"),
    "azul":   ("#E5EFFA", "#1B4F82", "#7BA8D1"),
    "laranja": ("#FCEBE1", "#8F4218", "#D9906B"),
    "rosa":   ("#FBE9F0", "#8A2551", "#D07E9E"),
    "ciano":  ("#E2F2F7", "#155E70", "#72B4C6"),
}

# A partir deste corte o painel trata a oportunidade como recomendada.
CORTE_PRIORITARIO = 30


def _atualizar_status_por_prazo(item, dias_sem_confirmacao=7):
    """Recalcula vencimento e envelhecimento da confirmação ao gerar o HTML."""
    prazo = item.get("prazo_final")
    if prazo:
        try:
            d = date.fromisoformat(prazo)
        except (ValueError, TypeError):
            d = None
        if d is not None:
            item["dias_restantes"] = (d - date.today()).days
            item["prazo_texto"] = d.strftime("%d/%m/%Y")
            if d < date.today() and item.get("status") == "aberto":
                item["status"] = "encerrado"
                item["motivo_status"] = "prazo encerrado em " + d.strftime("%d/%m/%Y")
            return

    if item.get("status") == "aberto" and dias_sem_confirmacao:
        try:
            visto = datetime.fromisoformat(item.get("visto_por_ultimo", ""))
        except (ValueError, TypeError):
            return
        if visto.date() < date.today() - timedelta(days=int(dias_sem_confirmacao)):
            item["status"] = "verificar"
            item["motivo_status"] = (
                f"sem confirmação recente há mais de {int(dias_sem_confirmacao)} dias"
            )


def _deduplicar(itens):
    """Mostra uma chamada uma única vez e preserva links/fontes alternativas."""
    grupos = agrupar_equivalentes(itens, lambda x: x.get("titulo", ""), limiar=0.72)
    saida = []
    for grupo in grupos:
        principal = max(
            grupo,
            key=lambda x: (
                1 if x.get("status") == "aberto" else 0,
                float(x.get("prioridade", 0) or 0),
                x.get("visto_por_ultimo", ""),
            ),
        )
        principal = deepcopy(principal)
        alternativas = []
        vistos = {(principal.get("fonte"), principal.get("url"))}
        for outro in grupo:
            chave = (outro.get("fonte"), outro.get("url"))
            if chave in vistos:
                continue
            vistos.add(chave)
            alternativas.append({
                "fonte": outro.get("fonte", ""),
                "url": outro.get("url", ""),
            })
        principal["tambem_em"] = alternativas
        saida.append(principal)
    return saida


def _json_script(valor):
    """Serializa JSON sem permitir que conteúdo externo encerre a tag <script>."""
    return json.dumps(valor, ensure_ascii=False).replace("</", "<\\/")


def renderizar(historico, diagnostico, agora, dias_novo, rotulos_temas, dias_sem_confirmacao=7):
    itens = [deepcopy(x) for x in historico.values()]
    for it in itens:
        _atualizar_status_por_prazo(it, dias_sem_confirmacao)
    itens = _deduplicar(itens)

    try:
        agora_dt = datetime.fromisoformat(agora)
    except (ValueError, TypeError):
        agora_dt = datetime.now()

    corte_novo = agora_dt - timedelta(days=dias_novo)
    for it in itens:
        try:
            primeiro = datetime.fromisoformat(it.get("visto_primeiro", agora))
        except (ValueError, TypeError):
            primeiro = agora_dt
        it["novo"] = primeiro >= corte_novo
        it["visto_em"] = primeiro.strftime("%d/%m/%Y")
        if it.get("prioridade") is None:
            it["prioridade"] = it.get("pontos", 0)

    # O JavaScript aplica a ordenação escolhida pelo usuário. Esta ordenação é
    # apenas um fallback útil quando o JS estiver desativado.
    itens.sort(
        key=lambda i: (
            1 if i.get("status") == "aberto" else 0,
            float(i.get("prioridade", 0) or 0),
            -(i.get("dias_restantes") if i.get("dias_restantes") is not None else 99999),
        ),
        reverse=True,
    )

    abertos = sum(1 for i in itens if i.get("status") == "aberto")
    recomendados = sum(
        1 for i in itens
        if i.get("status") == "aberto" and float(i.get("prioridade", 0) or 0) >= CORTE_PRIORITARIO
    )
    urgentes = sum(
        1 for i in itens
        if i.get("status") == "aberto"
        and i.get("dias_restantes") is not None
        and 0 <= int(i.get("dias_restantes")) <= 14
    )
    verificar = sum(1 for i in itens if i.get("status") == "verificar")
    novidades = sum(
        1 for i in itens
        if i.get("novidade") in ("novo", "atualizado", "nova_edicao")
    )

    fontes_ok = sum(1 for d in diagnostico if d.get("situacao") == "ok")
    fontes_total = len(diagnostico)

    css_temas = "\n".join(
        f'.t-{chave}{{background:{CORES.get(meta["cor"], CORES["azul"])[0]};'
        f'color:{CORES.get(meta["cor"], CORES["azul"])[1]};'
        f'border-color:{CORES.get(meta["cor"], CORES["azul"])[2]};}}'
        for chave, meta in rotulos_temas.items()
    )
    botoes_tema = "\n".join(
        f'<button type="button" class="chip f-tema t-{chave}" data-tema="{chave}" aria-pressed="false">{meta["rotulo"]}</button>'
        for chave, meta in sorted(rotulos_temas.items(), key=lambda kv: kv[1]["rotulo"])
    )

    return TEMPLATE.format(
        dados=_json_script(itens),
        rotulos=_json_script(rotulos_temas),
        diagnostico=_json_script(diagnostico),
        css_temas=css_temas,
        botoes_tema=botoes_tema,
        atualizado=agora_dt.strftime("%d/%m/%Y às %H:%M"),
        abertos=abertos,
        recomendados=recomendados,
        urgentes=urgentes,
        verificar=verificar,
        novidades=novidades,
        fontes_ok=fontes_ok,
        fontes_total=fontes_total,
        total=len(itens),
        corte=CORTE_PRIORITARIO,
    )


TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="description" content="Radar de oportunidades internacionais do Global Ed / UNIVC.">
<title>Radar Global Ed — Oportunidades Internacionais</title>
<style>
  :root {{
    --bg: #F4F7F5;
    --surface: #FFFFFF;
    --surface-soft: #F8FAF9;
    --ink: #14201D;
    --ink-2: #52605C;
    --ink-3: #7A8783;
    --line: #DDE5E1;
    --brand: #0B5D49;
    --brand-2: #074A3A;
    --brand-soft: #E7F3EF;
    --warning: #9A5B05;
    --warning-soft: #FFF4D9;
    --danger: #A23B2A;
    --danger-soft: #FDEDE9;
    --info: #2B5F91;
    --shadow: 0 1px 2px rgba(10,37,30,.04), 0 8px 24px rgba(10,37,30,.055);
    --r-sm: 8px;
    --r: 12px;
    --r-lg: 18px;
  }}
  * {{ box-sizing: border-box; }}
  html {{ -webkit-text-size-adjust: 100%; scroll-behavior: smooth; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 15px;
    line-height: 1.5;
  }}
  button, input, select {{ font: inherit; }}
  button, select {{ cursor: pointer; }}
  a {{ color: inherit; }}
  .shell {{ width: min(1180px, calc(100% - 40px)); margin: 0 auto; }}

  .site-header {{
    background: linear-gradient(135deg, #083E32 0%, #0B5D49 65%, #116B56 100%);
    color: #fff;
    padding: 28px 0 30px;
    border-bottom: 1px solid rgba(255,255,255,.14);
  }}
  .header-grid {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 30px; align-items: end; }}
  .eyebrow {{
    display: inline-flex; align-items: center; gap: 8px;
    margin-bottom: 8px; font-size: 11px; font-weight: 750; letter-spacing: .11em;
    text-transform: uppercase; color: #CFE6DE;
  }}
  .eyebrow::before {{ content: ""; width: 18px; height: 2px; border-radius: 2px; background: #B4DACC; }}
  h1 {{ margin: 0; font-size: clamp(27px, 4vw, 39px); line-height: 1.12; letter-spacing: -.035em; font-weight: 720; }}
  .subtitle {{ margin: 10px 0 0; max-width: 720px; color: #DCEDE7; font-size: 14px; }}
  .update-box {{
    min-width: 215px; padding: 11px 13px; border: 1px solid rgba(255,255,255,.18);
    border-radius: var(--r); background: rgba(255,255,255,.08); backdrop-filter: blur(5px);
  }}
  .update-label {{ font-size: 10px; text-transform: uppercase; letter-spacing: .09em; color: #BFDDD3; font-weight: 750; }}
  .update-time {{ margin-top: 2px; font-size: 13.5px; font-weight: 650; }}
  .health {{ margin-top: 6px; font-size: 12px; color: #DCEDE7; }}
  .health strong {{ color: #fff; }}

  main.shell {{ padding: 22px 0 80px; }}
  .summary-grid {{
    display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px;
  }}
  .summary-card {{
    background: var(--surface); border: 1px solid var(--line); border-radius: var(--r);
    padding: 15px 16px; box-shadow: var(--shadow); min-width: 0;
  }}
  .summary-card.primary {{ border-color: #B8D8CE; background: linear-gradient(180deg, #FFFFFF, #F4FAF8); }}
  .summary-kicker {{ font-size: 11px; color: var(--ink-3); font-weight: 650; }}
  .summary-value {{ margin-top: 3px; font-size: 25px; line-height: 1; font-weight: 750; letter-spacing: -.025em; }}
  .summary-card.primary .summary-value {{ color: var(--brand); }}
  .summary-card.urgent .summary-value {{ color: var(--danger); }}
  .summary-note {{ margin-top: 4px; font-size: 11.5px; color: var(--ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}

  .controls {{
    background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-lg);
    box-shadow: var(--shadow); margin-bottom: 18px; overflow: hidden;
  }}
  .search-area {{ padding: 16px; border-bottom: 1px solid var(--line); }}
  .search-label {{ display: block; margin-bottom: 7px; font-size: 11.5px; font-weight: 700; color: var(--ink-2); }}
  .search-row {{ display: flex; gap: 9px; }}
  .search-wrap {{ position: relative; flex: 1; }}
  .search-wrap svg {{ position: absolute; left: 12px; top: 50%; transform: translateY(-50%); width: 17px; height: 17px; color: var(--ink-3); pointer-events: none; }}
  .search {{
    width: 100%; height: 43px; padding: 0 13px 0 39px; border: 1px solid var(--line);
    border-radius: var(--r-sm); background: var(--surface-soft); color: var(--ink); outline: none;
  }}
  .search:focus {{ border-color: var(--brand); box-shadow: 0 0 0 3px rgba(11,93,73,.12); background: #fff; }}
  .search::placeholder {{ color: #95A09D; }}
  .btn-secondary {{
    height: 43px; padding: 0 14px; border: 1px solid var(--line); border-radius: var(--r-sm);
    background: #fff; color: var(--ink-2); font-weight: 650; font-size: 13px;
  }}
  .btn-secondary:hover {{ border-color: #B9C7C2; color: var(--ink); }}

  .view-tabs {{
    display: flex; gap: 6px; padding: 12px 16px; overflow-x: auto; scrollbar-width: thin;
    border-bottom: 1px solid var(--line);
  }}
  .view-tab {{
    flex: 0 0 auto; border: 1px solid transparent; background: transparent; color: var(--ink-2);
    border-radius: 999px; padding: 7px 11px; font-size: 12.5px; font-weight: 650;
  }}
  .view-tab:hover {{ background: var(--surface-soft); }}
  .view-tab.on {{ background: var(--brand-soft); color: var(--brand-2); border-color: #BFDBD2; }}
  .view-tab .count {{ margin-left: 4px; opacity: .72; font-variant-numeric: tabular-nums; }}

  .advanced {{ border-bottom: 1px solid var(--line); }}
  .advanced > summary {{
    list-style: none; display: flex; align-items: center; justify-content: space-between; gap: 14px;
    padding: 12px 16px; cursor: pointer; color: var(--ink-2); font-size: 12.5px; font-weight: 650;
  }}
  .advanced > summary::-webkit-details-marker {{ display: none; }}
  .advanced > summary:hover {{ background: var(--surface-soft); }}
  .advanced > summary .right {{ display: inline-flex; align-items: center; gap: 8px; color: var(--ink-3); }}
  .filter-count {{ display: none; min-width: 20px; height: 20px; align-items: center; justify-content: center; border-radius: 99px; background: var(--brand); color: #fff; font-size: 10px; }}
  .filter-count.show {{ display: inline-flex; }}
  .chev {{ transition: transform .18s; }}
  .advanced[open] .chev {{ transform: rotate(180deg); }}
  .advanced-body {{ padding: 4px 16px 16px; display: grid; gap: 15px; }}
  .filter-group {{ display: grid; gap: 7px; }}
  .filter-title {{ font-size: 10.5px; color: var(--ink-3); text-transform: uppercase; letter-spacing: .07em; font-weight: 750; }}
  .chips {{ display: flex; flex-wrap: wrap; gap: 7px; }}
  .chip {{
    border: 1px solid var(--line); background: var(--surface-soft); color: var(--ink-2);
    border-radius: 999px; padding: 6px 10px; font-size: 12px; font-weight: 600;
  }}
  .chip:hover {{ border-color: #B8C5C1; }}
  .chip.on {{ box-shadow: inset 0 0 0 1.5px currentColor; font-weight: 720; }}
  .f-regiao.on, .f-eleg.on {{ background: var(--ink); border-color: var(--ink); color: #fff; box-shadow: none; }}
  {css_temas}

  .toolbar {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; padding: 12px 16px; }}
  .result-count {{ margin: 0; color: var(--ink-3); font-size: 12.5px; }}
  .sort {{ display: inline-flex; align-items: center; gap: 7px; color: var(--ink-3); font-size: 12px; }}
  .sort select {{
    border: 1px solid var(--line); background: #fff; border-radius: 7px; color: var(--ink-2);
    height: 32px; padding: 0 28px 0 9px; font-size: 12px;
  }}

  .list {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 11px; }}
  .card {{
    background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-lg);
    box-shadow: var(--shadow); padding: 17px 18px; position: relative; overflow: hidden;
  }}
  .card.recommended {{ border-color: #BCD8CF; }}
  .card.recommended::before {{ content: ""; position: absolute; inset: 0 auto 0 0; width: 4px; background: var(--brand); }}
  .card.verificar::before {{ content: ""; position: absolute; inset: 0 auto 0 0; width: 4px; background: #C79030; }}
  .card-main {{ display: grid; grid-template-columns: minmax(0,1fr) 154px; gap: 18px; align-items: start; }}
  .source-row {{ display: flex; flex-wrap: wrap; gap: 6px 9px; align-items: center; margin-bottom: 6px; color: var(--ink-3); font-size: 11.5px; }}
  .source-name {{ color: var(--ink-2); font-weight: 700; }}
  .source-region {{ text-transform: uppercase; letter-spacing: .06em; font-size: 9.5px; font-weight: 760; }}
  .card-title-row {{ display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 10px; align-items: start; }}
  .card h2 {{ margin: 0; font-size: 17px; line-height: 1.35; letter-spacing: -.012em; font-weight: 680; }}
  .card h2 a {{ text-decoration: none; }}
  .card h2 a:hover {{ color: var(--brand); text-decoration: underline; text-underline-offset: 3px; }}
  .save-btn {{
    width: 34px; height: 34px; display: inline-grid; place-items: center; border-radius: 8px;
    border: 1px solid var(--line); background: #fff; color: var(--ink-3); padding: 0;
  }}
  .save-btn:hover {{ color: var(--brand); border-color: #B8D5CC; background: var(--brand-soft); }}
  .save-btn.saved {{ color: var(--brand); background: var(--brand-soft); border-color: #B8D5CC; }}
  .save-btn svg {{ width: 17px; height: 17px; }}
  .signal-row {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }}
  .badge {{
    display: inline-flex; align-items: center; border: 1px solid var(--line); border-radius: 999px;
    padding: 3px 8px; font-size: 10.5px; font-weight: 700; background: #F4F6F5; color: var(--ink-2);
  }}
  .badge.open {{ background: var(--brand-soft); color: var(--brand-2); border-color: #BDD9D0; }}
  .badge.verify {{ background: var(--warning-soft); color: #80500B; border-color: #E6CF96; }}
  .badge.closed {{ background: #F1F2F1; color: #6F7875; }}
  .badge.new {{ background: #EDF0FE; color: #42468F; border-color: #C9CBEA; }}
  .badge.updated {{ background: #FFF3DE; color: #8A5710; border-color: #E5C88D; }}
  .badge.fit-high {{ background: #E7F3EF; color: var(--brand-2); border-color: #BBD8CF; }}
  .badge.fit-mid {{ background: #EFF4FA; color: #315E83; border-color: #C9D8E5; }}

  .reason {{ margin: 11px 0 0; color: var(--ink-2); font-size: 13px; line-height: 1.5; }}
  .reason strong {{ color: var(--ink); }}
  .axes {{ display: flex; flex-wrap: wrap; gap: 5px; margin-top: 10px; }}
  .axis {{ background: #F2F7F5; border: 1px solid #D5E4DF; color: #315D52; border-radius: 6px; padding: 3px 7px; font-size: 10.5px; font-weight: 620; }}

  .deadline {{
    border: 1px solid var(--line); border-radius: var(--r); padding: 11px 12px; background: var(--surface-soft);
    min-height: 83px;
  }}
  .deadline.urgent {{ background: var(--danger-soft); border-color: #EBC1B9; }}
  .deadline.soon {{ background: var(--warning-soft); border-color: #E6CF96; }}
  .deadline-label {{ font-size: 9.5px; color: var(--ink-3); text-transform: uppercase; letter-spacing: .08em; font-weight: 760; }}
  .deadline strong {{ display: block; margin-top: 2px; font-size: 14px; color: var(--ink); }}
  .deadline .remaining {{ margin-top: 2px; font-size: 11.5px; color: var(--ink-2); }}
  .deadline.urgent .remaining {{ color: var(--danger); font-weight: 720; }}
  .deadline.soon .remaining {{ color: var(--warning); font-weight: 700; }}

  .card-footer {{
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
    margin-top: 14px; padding-top: 13px; border-top: 1px solid var(--line);
  }}
  .open-link {{
    display: inline-flex; align-items: center; gap: 6px; text-decoration: none; background: var(--brand);
    color: #fff; border: 1px solid var(--brand); border-radius: 8px; padding: 7px 11px; font-size: 12.5px; font-weight: 700;
  }}
  .open-link:hover {{ background: var(--brand-2); border-color: var(--brand-2); }}
  .details {{ flex: 1; min-width: 0; }}
  .details > summary {{
    list-style: none; cursor: pointer; color: var(--ink-2); font-size: 12px; font-weight: 650;
    text-align: right; user-select: none;
  }}
  .details > summary::-webkit-details-marker {{ display: none; }}
  .details > summary:hover {{ color: var(--brand); }}
  .details-content {{
    margin-top: 12px; padding: 12px; border-radius: var(--r); background: var(--surface-soft);
    border: 1px solid var(--line); font-size: 12.5px; color: var(--ink-2);
  }}
  .details-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px 18px; }}
  .detail-block h3 {{ margin: 0 0 5px; color: var(--ink); font-size: 11px; text-transform: uppercase; letter-spacing: .055em; }}
  .detail-block p {{ margin: 0; }}
  .restrictions {{ margin: 5px 0 0; padding-left: 17px; }}
  .restrictions li + li {{ margin-top: 4px; }}
  .warning {{ margin-top: 10px; padding: 8px 9px; border-radius: 7px; background: var(--warning-soft); border: 1px solid #E8D39D; color: #76500F; }}
  .changes {{ margin-top: 9px; font-weight: 650; color: #84540D; }}
  .attachments {{ margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--line); }}
  .attachments a, .alt-sources a {{ color: var(--brand); text-decoration: none; }}
  .attachments a:hover, .alt-sources a:hover {{ text-decoration: underline; }}
  .attachments ul {{ margin: 5px 0 0; padding-left: 17px; }}
  .alt-sources {{ margin-top: 8px; font-size: 11.5px; }}

  .empty {{
    display: none; text-align: center; padding: 54px 20px; background: var(--surface);
    border: 1px dashed #CAD6D2; border-radius: var(--r-lg); color: var(--ink-3);
  }}
  .empty strong {{ display: block; color: var(--ink); margin-bottom: 4px; font-size: 15px; }}
  .empty button {{ margin-top: 12px; }}

  .below {{ margin-top: 24px; display: grid; gap: 10px; }}
  .info-details {{ background: var(--surface); border: 1px solid var(--line); border-radius: var(--r); box-shadow: var(--shadow); }}
  .info-details > summary {{ list-style: none; cursor: pointer; padding: 13px 15px; font-size: 12.5px; font-weight: 680; color: var(--ink-2); }}
  .info-details > summary::-webkit-details-marker {{ display: none; }}
  .info-details > summary:hover {{ color: var(--brand); }}
  .info-content {{ padding: 0 15px 15px; color: var(--ink-2); font-size: 12.5px; }}
  .info-content p {{ margin: 0 0 9px; }}
  .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; }}
  table {{ width: 100%; min-width: 720px; border-collapse: collapse; background: #fff; }}
  th {{ text-align: left; color: var(--ink-3); font-size: 10px; text-transform: uppercase; letter-spacing: .06em; padding: 8px 9px; border-bottom: 1px solid var(--line); }}
  td {{ padding: 8px 9px; border-bottom: 1px solid var(--line); vertical-align: top; }}
  tr:last-child td {{ border-bottom: 0; }}
  td.url {{ max-width: 280px; word-break: break-all; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 10.5px; color: var(--ink-3); }}
  .ok {{ color: var(--brand); font-weight: 750; }}
  .failed {{ color: var(--danger); font-weight: 750; }}
  .method {{ margin: 0; padding-left: 18px; }}
  .method li + li {{ margin-top: 4px; }}
  .footer-note {{ margin-top: 18px; color: var(--ink-3); font-size: 11.5px; text-align: center; }}

  :focus-visible {{ outline: 3px solid rgba(11,93,73,.26); outline-offset: 2px; }}

  @media (max-width: 840px) {{
    .summary-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .card-main {{ grid-template-columns: minmax(0,1fr) 138px; }}
  }}
  @media (max-width: 640px) {{
    .shell {{ width: min(100% - 24px, 1180px); }}
    .site-header {{ padding: 22px 0 24px; }}
    .header-grid {{ grid-template-columns: 1fr; gap: 17px; }}
    .update-box {{ min-width: 0; width: 100%; }}
    main.shell {{ padding-top: 14px; }}
    .summary-grid {{ gap: 8px; margin-bottom: 12px; }}
    .summary-card {{ padding: 12px; }}
    .summary-value {{ font-size: 22px; }}
    .search-row {{ flex-direction: column; }}
    .btn-secondary {{ width: 100%; }}
    .toolbar {{ align-items: flex-start; flex-direction: column; }}
    .sort {{ width: 100%; justify-content: space-between; }}
    .sort select {{ flex: 1; max-width: 230px; }}
    .card {{ padding: 15px 14px; }}
    .card-main {{ grid-template-columns: 1fr; gap: 12px; }}
    .deadline {{ min-height: 0; display: grid; grid-template-columns: auto 1fr; column-gap: 10px; align-items: baseline; }}
    .deadline-label {{ grid-row: 1 / span 2; align-self: center; }}
    .deadline strong {{ margin: 0; }}
    .deadline .remaining {{ margin: 0; }}
    .card-footer {{ align-items: stretch; flex-direction: column; }}
    .open-link {{ justify-content: center; }}
    .details > summary {{ text-align: left; padding: 4px 0; }}
    .details-grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<header class="site-header">
  <div class="shell header-grid">
    <div>
      <div class="eyebrow">Global Ed · Relações Internacionais · UNIVC</div>
      <h1>Radar de oportunidades internacionais</h1>
      <p class="subtitle">Chamadas filtradas pela aderência aos projetos do Global Ed, com foco em cooperação, pesquisa, cotutela, mobilidade e internacionalização institucional.</p>
    </div>
    <div class="update-box" aria-label="Status da última coleta">
      <div class="update-label">Última verificação</div>
      <div class="update-time">{atualizado}</div>
      <div class="health"><strong>{fontes_ok}/{fontes_total}</strong> fontes responderam nesta coleta</div>
    </div>
  </div>
</header>

<main class="shell">
  <section class="summary-grid" aria-label="Resumo do radar">
    <article class="summary-card primary">
      <div class="summary-kicker">Recomendadas agora</div>
      <div class="summary-value">{recomendados}</div>
      <div class="summary-note">abertas e acima do corte de aderência</div>
    </article>
    <article class="summary-card">
      <div class="summary-kicker">Abertas confirmadas</div>
      <div class="summary-value">{abertos}</div>
      <div class="summary-note">com prazo validado pelo scraper</div>
    </article>
    <article class="summary-card urgent">
      <div class="summary-kicker">Prazo em até 14 dias</div>
      <div class="summary-value">{urgentes}</div>
      <div class="summary-note">merecem decisão rápida</div>
    </article>
    <article class="summary-card">
      <div class="summary-kicker">Precisam de conferência</div>
      <div class="summary-value">{verificar}</div>
      <div class="summary-note">status ou prazo ainda incerto</div>
    </article>
  </section>

  <section class="controls" aria-label="Busca e filtros">
    <div class="search-area">
      <label class="search-label" for="busca">Encontre uma oportunidade</label>
      <div class="search-row">
        <div class="search-wrap">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg>
          <input id="busca" class="search" type="search" autocomplete="off" placeholder="Busque por título, agência, país, tema ou eixo estratégico…">
        </div>
        <button type="button" class="btn-secondary" id="limpar">Limpar</button>
      </div>
    </div>

    <nav class="view-tabs" aria-label="Visões do radar">
      <button type="button" class="view-tab on" data-view="recomendadas" aria-pressed="true">Recomendadas <span class="count">{recomendados}</span></button>
      <button type="button" class="view-tab" data-view="abertas" aria-pressed="false">Todas abertas <span class="count">{abertos}</span></button>
      <button type="button" class="view-tab" data-view="novidades" aria-pressed="false">Novidades <span class="count">{novidades}</span></button>
      <button type="button" class="view-tab" data-view="verificar" aria-pressed="false">A verificar <span class="count">{verificar}</span></button>
      <button type="button" class="view-tab" data-view="salvos" aria-pressed="false">Salvos <span class="count" id="saved-count">0</span></button>
      <button type="button" class="view-tab" data-view="historico" aria-pressed="false">Histórico <span class="count">{total}</span></button>
    </nav>

    <details class="advanced" id="advanced">
      <summary>
        <span>Filtros avançados</span>
        <span class="right"><span class="filter-count" id="filter-count">0</span><span class="chev" aria-hidden="true">⌄</span></span>
      </summary>
      <div class="advanced-body">
        <div class="filter-group">
          <div class="filter-title">Origem da fonte</div>
          <div class="chips">
            <button type="button" class="chip f-regiao on" data-regiao="todas" aria-pressed="true">Todas</button>
            <button type="button" class="chip f-regiao" data-regiao="es" aria-pressed="false">Espírito Santo</button>
            <button type="button" class="chip f-regiao" data-regiao="nacional" aria-pressed="false">Brasil</button>
            <button type="button" class="chip f-regiao" data-regiao="internacional" aria-pressed="false">Exterior</button>
          </div>
        </div>
        <div class="filter-group">
          <div class="filter-title">Elegibilidade</div>
          <div class="chips">
            <button type="button" class="chip f-eleg on" data-eleg="todas" aria-pressed="true">Todas</button>
            <button type="button" class="chip f-eleg" data-eleg="individual" aria-pressed="false">Candidatura individual</button>
            <button type="button" class="chip f-eleg" data-eleg="sem_bloqueio" aria-pressed="false">Sem restrição conhecida</button>
          </div>
        </div>
        <div class="filter-group">
          <div class="filter-title">Temas</div>
          <div class="chips">{botoes_tema}</div>
        </div>
      </div>
    </details>

    <div class="toolbar">
      <p class="result-count" id="contagem" aria-live="polite"></p>
      <label class="sort" for="ordenacao">Ordenar por
        <select id="ordenacao">
          <option value="relevancia">Maior aderência</option>
          <option value="prazo">Prazo mais próximo</option>
          <option value="recentes">Mais recentes</option>
        </select>
      </label>
    </div>
  </section>

  <ul class="list" id="lista"></ul>
  <div class="empty" id="vazio">
    <strong>Nenhuma oportunidade encontrada</strong>
    Tente mudar a visão, retirar algum filtro ou ampliar a busca.
    <br><button type="button" class="btn-secondary" id="limpar-vazio">Limpar filtros</button>
  </div>

  <section class="below">
    <details class="info-details">
      <summary>Como o radar decide o que merece atenção</summary>
      <div class="info-content">
        <ol class="method">
          <li>prioriza oportunidades alinhadas aos eixos estratégicos do Global Ed;</li>
          <li>abre a página ou PDF do edital para validar contexto e prazo final;</li>
          <li>separa chamadas abertas confirmadas das que ainda precisam de conferência;</li>
          <li>ordena as recomendações pela aderência estratégica, sem esconder o histórico.</li>
        </ol>
      </div>
    </details>

    <details class="info-details">
      <summary>Saúde das fontes — {fontes_ok}/{fontes_total} responderam</summary>
      <div class="info-content">
        <p>Use esta seção para identificar rapidamente uma agência que deixou de responder ou mudou de endereço.</p>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Fonte</th><th>Origem</th><th>Situação</th><th>Relevantes</th><th>Tempo</th><th>URL usada</th></tr></thead>
            <tbody id="tbody-diag"></tbody>
          </table>
        </div>
      </div>
    </details>
  </section>

  <p class="footer-note">O radar é uma triagem automática. Confirme elegibilidade, contrapartidas e documentos na publicação oficial antes de candidatar.</p>
</main>

<script>
const DADOS = {dados};
const ROTULOS = {rotulos};
const DIAG = {diagnostico};
const CORTE = {corte};
const STORAGE_KEY = 'global-ed-favoritos-v1';

let fView = 'recomendadas';
let fRegiao = 'todas';
let fEleg = 'todas';
let fTemas = new Set();
let fBusca = '';
let fOrdenacao = 'relevancia';
let favoritos = carregarFavoritos();

const $lista = document.getElementById('lista');
const $vazio = document.getElementById('vazio');
const $contagem = document.getElementById('contagem');
const $savedCount = document.getElementById('saved-count');
const $filterCount = document.getElementById('filter-count');

function esc(s) {{
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
}}

function normalizar(s) {{
  return String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
}}

function carregarFavoritos() {{
  try {{ return new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')); }}
  catch (_) {{ return new Set(); }}
}}

function salvarFavoritos() {{
  try {{ localStorage.setItem(STORAGE_KEY, JSON.stringify([...favoritos])); }} catch (_) {{}}
  $savedCount.textContent = String(favoritos.size);
}}

const NOME_REGIAO = {{es:'Espírito Santo', nacional:'Brasil', internacional:'Exterior'}};
const NOME_STATUS = {{
  aberto:'Aberto confirmado', verificar:'Prazo a verificar', futuro:'Ainda não abriu',
  resultado:'Resultado', retificacao:'Retificação', encerrado:'Encerrado'
}};
const NOME_SIT = {{
  via_individual:'Candidatura individual', restricao_conhecida:'Restrição conhecida',
  verificar:'Verificar exigências', sem_catalogo:'Elegibilidade não catalogada'
}};
const NOME_NOVIDADE = {{novo:'Novo', atualizado:'Atualizado', nova_edicao:'Nova edição', inicial:'Acervo inicial'}};
const PESO_NOVIDADE = {{atualizado:4, nova_edicao:3, novo:2, inicial:1, conhecido:0}};

function prioridade(it) {{ return Number(it.prioridade != null ? it.prioridade : (it.pontos || 0)); }}
function recomendado(it) {{ return it.status === 'aberto' && prioridade(it) >= CORTE; }}

function rotuloAderencia(it) {{
  const p = prioridade(it);
  if (p >= 45) return ['Aderência muito alta', 'fit-high'];
  if (p >= CORTE) return ['Alta aderência', 'fit-high'];
  if (p >= 20) return ['Aderência média', 'fit-mid'];
  return ['Aderência complementar', ''];
}}

function prazoInfo(it) {{
  const rawDias = it.dias_restantes;
  const dias = rawDias !== null && rawDias !== undefined && rawDias !== '' && Number.isFinite(Number(rawDias))
    ? Number(rawDias) : null;
  const data = it.prazo_texto || 'Não identificado';
  let cls = '', restante = '';
  if (dias != null && it.status === 'aberto') {{
    if (dias === 0) {{ cls = 'urgent'; restante = 'Encerra hoje'; }}
    else if (dias === 1) {{ cls = 'urgent'; restante = 'Encerra amanhã'; }}
    else if (dias > 1 && dias <= 7) {{ cls = 'urgent'; restante = `Encerra em ${{dias}} dias`; }}
    else if (dias > 7 && dias <= 14) {{ cls = 'soon'; restante = `Encerra em ${{dias}} dias`; }}
    else if (dias > 14) restante = `${{dias}} dias restantes`;
  }} else if (it.status === 'verificar') restante = 'Confirme no edital oficial';
  else if (dias != null && dias < 0) restante = 'Prazo encerrado';
  return {{data, cls, restante}};
}}

function passa(it) {{
  if (fView === 'recomendadas' && !recomendado(it)) return false;
  if (fView === 'abertas' && it.status !== 'aberto') return false;
  if (fView === 'verificar' && it.status !== 'verificar') return false;
  if (fView === 'novidades') {{
    const nv = it.novidade;
    if (nv) {{ if (!['novo','atualizado','nova_edicao'].includes(nv)) return false; }}
    else if (!it.novo) return false;
  }}
  if (fView === 'salvos' && !favoritos.has(it.url)) return false;

  if (fRegiao !== 'todas' && it.regiao !== fRegiao) return false;
  if (fEleg === 'individual' && it.situacao_elegibilidade !== 'via_individual') return false;
  if (fEleg === 'sem_bloqueio' && it.situacao_elegibilidade === 'restricao_conhecida') return false;

  if (fTemas.size) {{
    const temas = it.temas || [];
    if (![...fTemas].some(t => temas.includes(t))) return false;
  }}

  if (fBusca) {{
    const temasTexto = (it.temas || []).map(t => ROTULOS[t] ? ROTULOS[t].rotulo : t);
    const restrTexto = (it.restricoes || []).map(r => `${{r.programa || ''}} ${{r.exige || ''}}`);
    const alvo = normalizar([
      it.titulo, it.fonte, it.regiao, it.motivo_relevancia,
      ...(it.eixos_rotulos || []), ...temasTexto, ...restrTexto,
      ...(it.publico_alvo || [])
    ].join(' '));
    if (!alvo.includes(fBusca)) return false;
  }}
  return true;
}}

function ordenar(itens) {{
  const copia = [...itens];
  copia.sort((a, b) => {{
    if (fOrdenacao === 'prazo') {{
      const da = a.status === 'aberto' && a.dias_restantes != null ? Number(a.dias_restantes) : 999999;
      const db = b.status === 'aberto' && b.dias_restantes != null ? Number(b.dias_restantes) : 999999;
      return da - db || prioridade(b) - prioridade(a);
    }}
    if (fOrdenacao === 'recentes') {{
      const ta = Date.parse(a.visto_primeiro || '') || 0;
      const tb = Date.parse(b.visto_primeiro || '') || 0;
      return tb - ta || (PESO_NOVIDADE[b.novidade] || 0) - (PESO_NOVIDADE[a.novidade] || 0);
    }}
    return prioridade(b) - prioridade(a)
      || (PESO_NOVIDADE[b.novidade] || 0) - (PESO_NOVIDADE[a.novidade] || 0)
      || ((a.dias_restantes == null ? 999999 : Number(a.dias_restantes)) - (b.dias_restantes == null ? 999999 : Number(b.dias_restantes)));
  }});
  return copia;
}}

function badgeStatus(it) {{
  const cls = it.status === 'aberto' ? 'open' : it.status === 'verificar' ? 'verify' : 'closed';
  return `<span class="badge ${{cls}}">${{esc(NOME_STATUS[it.status] || it.status)}}</span>`;
}}

function badgeNovidade(it) {{
  const nv = it.novidade;
  if (!nv || nv === 'conhecido' || (nv === 'inicial' && !it.novo)) return '';
  const cls = nv === 'atualizado' || nv === 'nova_edicao' ? 'updated' : 'new';
  return `<span class="badge ${{cls}}">${{esc(NOME_NOVIDADE[nv] || nv)}}</span>`;
}}

function montarCard(it) {{
  const p = prioridade(it);
  const [fitLabel, fitClass] = rotuloAderencia(it);
  const prazo = prazoInfo(it);
  const sit = it.situacao_elegibilidade || 'sem_catalogo';
  const restr = it.restricoes || [];
  const eixos = it.eixos_rotulos || [];
  const alertas = it.alertas_automaticos || [];
  const anexos = it.anexos || [];
  const alternativas = it.tambem_em || [];
  const salvo = favoritos.has(it.url);

  const li = document.createElement('li');
  li.className = 'card' + (recomendado(it) ? ' recommended' : '') + (it.status === 'verificar' ? ' verificar' : '');

  const eixosHtml = eixos.slice(0, 4).map(x => `<span class="axis">${{esc(x)}}</span>`).join('');
  const eixosExtra = eixos.length > 4 ? `<span class="axis">+${{eixos.length - 4}}</span>` : '';

  const restrHtml = restr.length
    ? `<ul class="restrictions">${{restr.map(x => `<li><strong>${{esc(x.programa || 'Regra detectada')}}:</strong> ${{esc(x.exige || '')}}</li>`).join('')}}</ul>`
    : `<p>Nenhuma restrição catalogada foi reconhecida automaticamente. Isso não substitui a leitura da elegibilidade no edital.</p>`;

  const alertaHtml = alertas.length ? `<div class="warning">${{esc(alertas.join(' · '))}}</div>` : '';
  const mudancas = (it.mudancas && it.mudancas.length)
    ? `<div class="changes">Atualização detectada: ${{esc(it.mudancas.join('; '))}}</div>` : '';
  const edicao = it.edicao_anterior_ano
    ? `<div class="changes">Nova edição — a anterior era de ${{esc(String(it.edicao_anterior_ano))}}.</div>` : '';

  const anexosHtml = anexos.length ? `
    <div class="attachments"><strong>Anexos:</strong>
      <ul>${{anexos.map(a => `<li><a href="${{esc(a.url)}}" target="_blank" rel="noopener">${{esc(a.rotulo || a.arquivo || 'Abrir anexo')}}</a></li>`).join('')}}</ul>
    </div>` : '';
  const altHtml = alternativas.length ? `
    <div class="alt-sources"><strong>Também encontrado em:</strong> ${{alternativas.map(a => `<a href="${{esc(a.url)}}" target="_blank" rel="noopener">${{esc(a.fonte || 'outra fonte')}}</a>`).join(' · ')}}</div>` : '';

  li.innerHTML = `
    <div class="card-main">
      <div>
        <div class="source-row">
          <span class="source-name">${{esc(it.fonte || 'Fonte não informada')}}</span>
          <span class="source-region">${{esc(NOME_REGIAO[it.regiao] || it.regiao || '')}}</span>
        </div>
        <div class="card-title-row">
          <h2><a href="${{esc(it.url)}}" target="_blank" rel="noopener">${{esc(it.titulo || 'Oportunidade sem título')}}</a></h2>
          <button type="button" class="save-btn${{salvo ? ' saved' : ''}}" data-save="${{esc(it.url)}}" aria-pressed="${{salvo ? 'true' : 'false'}}" aria-label="${{salvo ? 'Remover dos salvos' : 'Salvar oportunidade'}}" title="${{salvo ? 'Remover dos salvos' : 'Salvar oportunidade'}}">
            <svg viewBox="0 0 24 24" fill="${{salvo ? 'currentColor' : 'none'}}" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M6 3.8h12a1 1 0 0 1 1 1V21l-7-4-7 4V4.8a1 1 0 0 1 1-1Z"></path></svg>
          </button>
        </div>
        <div class="signal-row">
          ${{badgeStatus(it)}}
          <span class="badge ${{fitClass}}">${{esc(fitLabel)}}</span>
          ${{badgeNovidade(it)}}
          ${{sit === 'via_individual' ? '<span class="badge">Candidatura individual</span>' : ''}}
        </div>
        ${{it.motivo_relevancia ? `<p class="reason"><strong>Por que vale atenção:</strong> ${{esc(it.motivo_relevancia)}}</p>` : ''}}
        ${{eixosHtml || eixosExtra ? `<div class="axes">${{eixosHtml}}${{eixosExtra}}</div>` : ''}}
      </div>
      <aside class="deadline ${{prazo.cls}}" aria-label="Prazo">
        <div class="deadline-label">Prazo final</div>
        <strong>${{esc(prazo.data)}}</strong>
        <div class="remaining">${{esc(prazo.restante)}}</div>
      </aside>
    </div>

    <div class="card-footer">
      <a class="open-link" href="${{esc(it.url)}}" target="_blank" rel="noopener">Abrir edital oficial <span aria-hidden="true">↗</span></a>
      <details class="details">
        <summary>Elegibilidade e detalhes</summary>
        <div class="details-content">
          <div class="details-grid">
            <div class="detail-block">
              <h3>Elegibilidade</h3>
              <p><strong>${{esc(NOME_SIT[sit] || sit)}}</strong></p>
              ${{restrHtml}}
            </div>
            <div class="detail-block">
              <h3>Leitura do radar</h3>
              <p>Aderência: <strong>${{esc(fitLabel)}}</strong> (${{esc(String(p))}} pts).</p>
              <p>Status: <strong>${{esc(NOME_STATUS[it.status] || it.status)}}</strong>.</p>
              <p>Primeiro visto no radar: <strong>${{esc(it.visto_em || '—')}}</strong>.</p>
              ${{it.motivo_status ? `<p>Observação de status: ${{esc(it.motivo_status)}}</p>` : ''}}
            </div>
          </div>
          ${{alertaHtml}}${{mudancas}}${{edicao}}${{altHtml}}${{anexosHtml}}
        </div>
      </details>
    </div>`;
  return li;
}}

function atualizarFiltrosAtivos() {{
  let n = 0;
  if (fRegiao !== 'todas') n += 1;
  if (fEleg !== 'todas') n += 1;
  n += fTemas.size;
  $filterCount.textContent = String(n);
  $filterCount.classList.toggle('show', n > 0);
}}

function desenhar() {{
  const vis = ordenar(DADOS.filter(passa));
  $lista.innerHTML = '';
  $vazio.style.display = vis.length ? 'none' : 'block';
  const viewNames = {{recomendadas:'recomendadas', abertas:'abertas', novidades:'novidades', verificar:'a verificar', salvos:'salvas', historico:'no histórico'}};
  $contagem.textContent = vis.length === 1
    ? `1 oportunidade ${{viewNames[fView] || ''}}`
    : `${{vis.length}} oportunidades ${{viewNames[fView] || ''}}`;
  const frag = document.createDocumentFragment();
  for (const it of vis) frag.appendChild(montarCard(it));
  $lista.appendChild(frag);
  atualizarFiltrosAtivos();
  salvarFavoritos();
}}

function limparFiltros() {{
  fView = 'recomendadas'; fRegiao = 'todas'; fEleg = 'todas'; fTemas.clear(); fBusca = ''; fOrdenacao = 'relevancia';
  document.getElementById('busca').value = '';
  document.getElementById('ordenacao').value = 'relevancia';
  document.querySelectorAll('.view-tab').forEach(x => {{
    const on = x.dataset.view === 'recomendadas'; x.classList.toggle('on', on); x.setAttribute('aria-pressed', String(on));
  }});
  document.querySelectorAll('.f-regiao').forEach(x => {{
    const on = x.dataset.regiao === 'todas'; x.classList.toggle('on', on); x.setAttribute('aria-pressed', String(on));
  }});
  document.querySelectorAll('.f-eleg').forEach(x => {{
    const on = x.dataset.eleg === 'todas'; x.classList.toggle('on', on); x.setAttribute('aria-pressed', String(on));
  }});
  document.querySelectorAll('.f-tema').forEach(x => {{ x.classList.remove('on'); x.setAttribute('aria-pressed', 'false'); }});
  desenhar();
}}

document.querySelectorAll('.view-tab').forEach(b => b.addEventListener('click', () => {{
  document.querySelectorAll('.view-tab').forEach(x => {{ x.classList.remove('on'); x.setAttribute('aria-pressed', 'false'); }});
  b.classList.add('on'); b.setAttribute('aria-pressed', 'true'); fView = b.dataset.view; desenhar();
}}));

document.querySelectorAll('.f-regiao').forEach(b => b.addEventListener('click', () => {{
  document.querySelectorAll('.f-regiao').forEach(x => {{ x.classList.remove('on'); x.setAttribute('aria-pressed', 'false'); }});
  b.classList.add('on'); b.setAttribute('aria-pressed', 'true'); fRegiao = b.dataset.regiao; desenhar();
}}));

document.querySelectorAll('.f-eleg').forEach(b => b.addEventListener('click', () => {{
  document.querySelectorAll('.f-eleg').forEach(x => {{ x.classList.remove('on'); x.setAttribute('aria-pressed', 'false'); }});
  b.classList.add('on'); b.setAttribute('aria-pressed', 'true'); fEleg = b.dataset.eleg; desenhar();
}}));

document.querySelectorAll('.f-tema').forEach(b => b.addEventListener('click', () => {{
  const t = b.dataset.tema;
  const on = !fTemas.has(t);
  if (on) fTemas.add(t); else fTemas.delete(t);
  b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); desenhar();
}}));

document.getElementById('busca').addEventListener('input', e => {{ fBusca = normalizar(e.target.value.trim()); desenhar(); }});
document.getElementById('ordenacao').addEventListener('change', e => {{ fOrdenacao = e.target.value; desenhar(); }});
document.getElementById('limpar').addEventListener('click', limparFiltros);
document.getElementById('limpar-vazio').addEventListener('click', limparFiltros);

document.addEventListener('click', e => {{
  const btn = e.target.closest('[data-save]');
  if (!btn) return;
  const url = btn.dataset.save;
  if (favoritos.has(url)) favoritos.delete(url); else favoritos.add(url);
  desenhar();
}});

const $tb = document.getElementById('tbody-diag');
if (DIAG.length) {{
  $tb.innerHTML = DIAG.map(d => `
    <tr>
      <td><strong>${{esc(d.fonte)}}</strong></td>
      <td>${{esc(NOME_REGIAO[d.regiao] || d.regiao || '—')}}</td>
      <td class="${{d.situacao === 'ok' ? 'ok' : 'failed'}}">${{d.situacao === 'ok' ? 'ok' : 'falhou'}}</td>
      <td>${{esc(String(d.relevantes ?? 0))}}${{d.novos ? ` (+${{esc(String(d.novos))}} novo${{d.novos === 1 ? '' : 's'}})` : ''}}</td>
      <td>${{d.segundos != null ? esc(String(d.segundos)) + 's' : '—'}}</td>
      <td class="url">${{esc(d.url_usada) || '—'}}</td>
    </tr>`).join('');
}} else {{
  $tb.innerHTML = '<tr><td colspan="6" style="color:var(--ink-3)">Sem diagnóstico registrado.</td></tr>';
}}

salvarFavoritos();
desenhar();
</script>
</body>
</html>
"""
