#!/usr/bin/env python3
from datetime import date

from oportunidades import AnalisadorGlobalEd, avaliar_status_prazo

HOJE = date(2026, 8, 20)
A = AnalisadorGlobalEd()


def fonte(**extra):
    base = {
        "nome": "Teste",
        "fonte_curada_oportunidades": True,
        "fonte_curada_internacional": False,
    }
    base.update(extra)
    return base


def ok(cond, msg):
    if not cond:
        raise AssertionError(msg)


# 1. British Council: institutional research partnership + future deadline.
t = """
Researcher Challenges Grants 2026. Strengthen international research collaboration
and collaborative international research partnerships between UK higher education
institutions and partner institutions in Brazil. Funding up to GBP 40,000.
Apply by 17 September 2026.
"""
r = A.avaliar(t, fonte(fonte_curada_internacional=True), hoje=HOJE)
ok(r["relevante"] and r["ativo"], f"British Council should be active: {r}")
ok(r["prazo_final"] == "2026-09-17", r)
ok("cooperacao_pesquisa" in r["eixos"], r)

# 2. Fulbright page can still say open while the actual date is already past.
t = """
Doutorado sanduiche nos Estados Unidos com bolsa Fulbright/Capes.
Como foi a ultima inscricao. Inscricoes encerradas. Inscricoes abertas ate
02 de agosto de 2026.
"""
r = A.avaliar(t, fonte(fonte_curada_internacional=True), hoje=HOJE)
ok(r["status"] == "encerrado" and not r["ativo"], r)

# 3. CNPq/ERC: future deadline and real international research collaboration.
t = """
Chamada Publica CNPq/ERC No 21/2026. Conselho Europeu de Pesquisa.
Selecionar projetos de pesquisa com pesquisadores brasileiros doutores em
colaboracoes cientificas apoiadas pelo European Research Council.
Inscricoes: 03/08/2026 a 30/09/2026.
"""
r = A.avaliar(t, fonte(status_lista_confiavel="aberto"), hoje=HOJE)
ok(r["ativo"], r)
ok(r["prazo_final"] == "2026-09-30", r)

# 4. Generic local scholarship has no Global Ed axis or international component.
t = "Edital de bolsa de iniciacao cientifica para estudantes locais. Inscricoes ate 30/09/2026."
r = A.avaliar(t, fonte(), hoje=HOJE)
ok(not r["relevante"], r)

# 5. Incoming-only mobility to Brazil is not useful for the current outbound/partnership search.
t = """
International scholarship mobility programme for foreign students to study in Brazil.
Applications open until 30 September 2026. Funding available.
"""
r = A.avaliar(t, fonte(fonte_curada_internacional=True), hoje=HOJE)
ok(not r["relevante"] and r["inbound_only"], r)

# 6. A stale list label cannot beat a past deadline.
t = "Status: Em andamento. Data de Encerramento: 10/08/2026. Researcher mobility Brazil Europe grant."
r = avaliar_status_prazo(t, fonte(status_lista_confiavel="aberto"), hoje=HOJE)
ok(r["status"] == "encerrado", r)

# 7. Horizon Europe through FAPES is high-value collaborative research.
t = """
Chamada Horizon Europe. FAPES support for participation of Espirito Santo researchers
as co-PI in collaborative research and innovation projects in consortia with European partners.
Funding support. Inscricoes ate 31/12/2027.
"""
r = A.avaliar(t, fonte(), hoje=HOJE)
ok(r["ativo"] and r["aderencia"] >= 50, r)

# 8. DAAD Cotutelle maps directly to the co-supervision project.
t = """
Bi-nationally Supervised Doctoral Degrees / Cotutelle. DAAD grants for doctoral candidates.
Doctoral degree supervised by the home university and a university in Germany.
Application deadline 03.09.2026.
"""
r = A.avaliar(t, fonte(fonte_curada_internacional=True), hoje=HOJE)
ok(r["ativo"] and "cotutela_dupla_titulacao" in r["eixos"], r)

# 9. Opening date must not be mistaken for the application deadline.
t = """
As informacoes abaixo referem-se ao ultimo edital. Previsao para abertura das inscricoes:
01/06/2027. Como foi a ultima inscricao: inscricoes encerradas. Inscricoes abertas ate
02/08/2026.
"""
r = avaliar_status_prazo(t, fonte(), hoje=HOJE)
ok(r["status"] == "encerrado", r)
ok(r["prazo_final"] == "2026-08-02", r)

# 10. Cheap ranking must spend detail budget on strategic items first.
forte = A.pontuar_prequalificacao(
    "Cotutelle joint supervision international grant 2026 Germany application",
    fonte(fonte_curada_internacional=True),
)
fraco = A.pontuar_prequalificacao(
    "Programa de bolsas 2026",
    fonte(fonte_curada_oportunidades=True),
)
ok(forte > fraco, (forte, fraco))

# 11. CLI source selection accepts a unique short name after descriptive renames.
from editais_scraper import selecionar_fontes_por_nome
fs = [{"nome": "FAPES — Oportunidades abertas"}, {"nome": "DAAD Brasil"}]
ok(selecionar_fontes_por_nome(fs, "FAPES")[0]["nome"].startswith("FAPES"), fs)
ok(selecionar_fontes_por_nome(fs, "DAAD")[0]["nome"] == "DAAD Brasil", fs)

# 12. Mini integration: list -> detail -> strict deadline -> only the useful active call survives.
from editais_scraper import CONFIG_PADRAO, Orcamento, raspar_uma_pagina
from classificador import Classificador

class _Resp:
    def __init__(self, url, body, ctype="text/html; charset=utf-8"):
        self.url = url
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = {"Content-Type": ctype, "Content-Length": str(len(self._body))}
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"
        self.status_code = 200

    @property
    def text(self):
        return self._body.decode(self.encoding or "utf-8", errors="replace")

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

class _Sessao:
    def __init__(self, mapa):
        self.mapa = mapa

    def get(self, url, **kwargs):
        return self.mapa[url]

lista_url = "https://teste.invalid/abertas"
lista = """
<html><body>
<article><h3>Research Partnership Brazil UK 2026</h3><p>International collaborative research grant.</p><a href="/open">Ver chamada</a></article>
<article><h3>Research Partnership antiga 2026</h3><p>International collaborative research grant.</p><a href="/closed">Ver chamada</a></article>
<article><h3>Bolsa local 2026</h3><p>Bolsa de iniciacao cientifica local.</p><a href="/local">Ver chamada</a></article>
</body></html>
"""
mapa = {
    lista_url: _Resp(lista_url, lista),
    "https://teste.invalid/open": _Resp("https://teste.invalid/open", """
        International collaborative research partnership between a Brazilian higher education institution
        and a UK university. Grant funding. Application deadline 30 September 2026.
    """),
    "https://teste.invalid/closed": _Resp("https://teste.invalid/closed", """
        International collaborative research partnership. Grant funding.
        Application deadline 01 August 2026.
    """),
    "https://teste.invalid/local": _Resp("https://teste.invalid/local", """
        Bolsa de iniciacao cientifica local. Inscricoes ate 30 September 2026.
    """),
}
fonte_int = {
    "nome": "Teste Integracao",
    "regiao": "internacional",
    "seletor": "article",
    "seletor_titulo": "h3",
    "seletor_link": "a",
    "seletor_data": None,
    "agrupar_anexos": True,
    "sempre_internacional": True,
    "fonte_curada_oportunidades": True,
    "fonte_curada_internacional": True,
    "exigir_prazo_confirmado": True,
    "max_detalhes": 10,
}
cfg_int = dict(CONFIG_PADRAO)
cfg_int.update({"tentativas_por_url": 1, "modo_estrito_global_ed": True, "exigir_prazo_confirmado": True})
itens, n_brutos, _estr, erro, _soup = raspar_uma_pagina(
    _Sessao(mapa), fonte_int, cfg_int, Classificador(), A, lista_url, Orcamento(30)
)
ok(erro is None, erro)
ok(n_brutos >= 3, n_brutos)
ok(len(itens) == 1, itens)
ok(itens[0]["prazo_final"] == "2026-09-30", itens[0])
ok("Cooperacao internacional em pesquisa" in itens[0]["eixos_rotulos"], itens[0])

# 13. Accordion with several documents becomes one opportunity, not 3 noisy cards.
from bs4 import BeautifulSoup
from editais_scraper import extrair_por_seletor
html_group = """
<div class="accordion-item">
  <h3>CHAMADA CONFAP CDTI 2026</h3>
  <a href="/diretrizes.pdf">DIRETRIZES FAPES - CHAMADA CDTI 2026</a>
  <a href="/edital.pdf">EDITAL DA CHAMADA CONFAP - CDTI 2026-2027</a>
  <a href="/anexo.docx">ANEXO 1 - FORMULARIO</a>
</div>
"""
fonte_group = {
    "seletor": ".accordion-item", "seletor_titulo": "h3", "seletor_link": "a",
    "seletor_data": None, "agrupar_anexos": True,
}
g = extrair_por_seletor(BeautifulSoup(html_group, "lxml"), fonte_group, "https://x.test/lista")
ok(len(g) == 1, g)
ok(g[0]["titulo"] == "CHAMADA CONFAP CDTI 2026", g[0])
ok(len(g[0].get("anexos", [])) == 2, g[0])

print("OK - 13 quality checks passed")
