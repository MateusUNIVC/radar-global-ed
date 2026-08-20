# Radar de Oportunidades Internacionais — UNIVC / Global Ed

## Atualização v4 — menos falso positivo, mais chamadas internacionais

Esta versão endurece a definição de **internacional** e amplia a descoberta em fontes oficiais.

### O que deixou de contar como internacional por si só

- `intercâmbio`, `exchange`, `mobilidade` ou `intercâmbio de conhecimento`;
- simples menções genéricas a cooperação ou compartilhamento de conhecimento;
- links de redes sociais e botões de compartilhamento.

Para uma fonte brasileira ampla, o item precisa ter **evidência internacional independente**: por exemplo `internacional`, `bilateral`, `no exterior`, `foreign institution`, `international partnership`, Horizon Europe/ERC, ou país/região estrangeira em contexto de chamada, pesquisa, parceria, bolsa ou mobilidade.

### Links sociais são descartados antes da classificação

O coletor ignora LinkedIn, Facebook, X/Twitter, Instagram, WhatsApp, YouTube e rotas típicas de `share`/`sharer`. Isso acontece antes de o link herdar o título do card, evitando entradas como **“Compartilhe no LinkedIn”**.

### Novas fontes internacionais ativas

- **EURAXESS LAC — chamadas com conexão Brasil**: lê notícias/chamadas recentes, mas exige menção explícita a Brasil/Brazil/FAPES/CONFAP/CNPq/CAPES, para não misturar editais exclusivos de Chile, Argentina etc.;
- **MSCA — Marie Skłodowska-Curie Actions**: monitora a página oficial de funding para Postdoctoral Fellowships, Doctoral Networks e chamadas futuras. Cards `forthcoming` não são tratados como abertos antes da abertura.

### Testes

`python testes_qualidade.py` executa **22 verificações**, incluindo:

- intercâmbio de conhecimento local não vira mobilidade internacional;
- mobilidade acadêmica internacional real continua entrando;
- `Compartilhe no LinkedIn`/Twitter são descartados;
- chamada Chile-only em agregador LAC é rejeitada e Brasil-Noruega é aceita;
- `forthcoming` não é confundido com `open`;
- deadline em JSON-LD também é lido.

Scraper local para identificar **oportunidades abertas e realmente aderentes aos projetos de internacionalização do UNIVC**, reduzindo dois problemas da versão anterior:

1. bolsas/editais que tinham palavras parecidas, mas pouca relação com o Global Ed;
2. páginas ainda indexadas como “abertas” mesmo depois do fim do prazo.

O resultado é um `painel.html` responsivo, que funciona offline e abre, por padrão, em **Recomendadas**: oportunidades abertas cujo alinhamento com o Global Ed ficou acima do corte estratégico.

---

## Painel redesenhado para decisão rápida

O frontend foi reorganizado para reduzir a quantidade de informação exibida de uma vez e destacar o que realmente exige ação:

- visão inicial **Recomendadas**;
- prazo final em posição de destaque, com alerta visual quando faltam até 14 dias;
- busca por título, agência, tema, eixo estratégico, público e restrições;
- ordenação por aderência, prazo ou data de descoberta;
- filtros avançados recolhidos para não poluir a tela;
- botão **Salvar** em cada oportunidade (persistido no navegador com `localStorage`);
- elegibilidade, score, anexos e observações ficam em uma área expansível;
- saúde das fontes e metodologia ficam no fim do painel, fora do fluxo principal;
- layout adaptado para celular e navegação por teclado.

## GitHub Pages + verificação diária

O projeto inclui `.github/workflows/atualizar-radar.yml`. Ele roda o scraper diariamente, preserva o histórico em `dados/` e publica o painel no GitHub Pages.

Guia completo: **`DEPLOY_GITHUB.md`**.

Resumo da configuração:

1. envie os arquivos para a raiz de um repositório com branch `main`;
2. em **Settings → Pages**, escolha **GitHub Actions** como fonte;
3. abra **Actions → Atualizar e publicar Radar Global Ed → Run workflow** para a primeira execução;
4. depois disso, a coleta roda automaticamente todos os dias às **06:17 (America/Sao_Paulo)**.

---

## O que o filtro procura

O perfil foi construído a partir do documento institucional do Global Ed. A prioridade é:

1. **Cotutela / dupla titulação**;
2. **cooperação internacional em pesquisa** e projetos conjuntos;
3. **parcerias e internacionalização institucional**;
4. **mobilidade de docentes e pesquisadores**;
5. mobilidade estudantil internacional;
6. missões, visitas técnicas, eventos e workshops internacionais;
7. convidados, professores visitantes e conexões acadêmicas que possam alimentar o Global Talks.

O arquivo editável `perfil_global_ed.json` contém os eixos, palavras e pesos usados pelo algoritmo.

---

## Mudança principal: não classifica mais só pelo título

A versão antiga decidia principalmente por **título + URL**. Isso é insuficiente: prazo, elegibilidade e objetivo quase sempre aparecem apenas no corpo do edital.

Agora o fluxo é:

1. lê a página oficial de oportunidades;
2. remove navegação, menus e edições antigas antes de gastar requisições;
3. atribui um **pré-score estratégico** ao título/card;
4. abre primeiro os candidatos com maior chance de serem úteis;
5. lê a **página de detalhe ou o PDF**;
6. procura o **prazo final real** de inscrição/submissão;
7. exige componente internacional + pelo menos um eixo do Global Ed;
8. só então registra a oportunidade no painel.

Por padrão, `exigir_prazo_confirmado=true`: sem uma data final de candidatura detectável, o item **não entra em “Abertos confirmados”**. Isso sacrifica um pouco de cobertura para ganhar precisão.

---

## Como os prazos são tratados

O parser reconhece formatos como:

- `30/09/2026`, `30-09-2026`, `2026-09-30`;
- `17 de setembro de 2026`;
- `17 September 2026`, `September 17, 2026`;
- expressões próximas de `inscrições`, `submissão`, `deadline`, `apply by`, `closing date`, etc.

Datas de publicação, resultado, início do projeto, início do financiamento e **abertura das inscrições** recebem peso negativo para não serem confundidas com o encerramento.

Se a data final for anterior ao dia da execução, o item é descartado da lista ativa, ainda que o site tenha um rótulo desatualizado como “Inscrições abertas” ou “Em andamento”.

Além disso:

- uma oportunidade aberta que desaparece de uma listagem oficial que respondeu normalmente passa para **Verificar**;
- chamadas sem data explícita não podem permanecer abertas indefinidamente: `dias_sem_confirmacao` controla a validade da última confirmação.

---

## Fontes ativas por padrão

O arquivo `fontes.json` foi reduzido para privilegiar densidade e confiabilidade.

### Prioridade muito alta

- **FAPES — Oportunidades abertas**: página oficial de Chamadas Internacionais do Espírito Santo. É a fonte mais importante porque as diretrizes da FAPES determinam a participação local.
- **CONFAP — Em andamento**: chamadas multilaterais e bilaterais, mas o scraper não confia apenas no status “Em andamento”; exige a data real.
- **CNPq — Chamadas abertas**: usa a página oficial de chamadas abertas à submissão.

### Prioridade alta

- **CAPES — Editais e cooperação**: programas internacionais de pesquisa, mobilidade e cooperação acadêmica.
- **DAAD Brasil**: cotutela, doutorado sanduíche, estadias de pesquisa e mobilidade acadêmica; programas genéricos sem eixo Global Ed tendem a cair no filtro.
- **British Council — Ensino Superior**: chamadas de parceria e cooperação internacional de ensino superior/pesquisa.
- **Fulbright Brasil**: mantida para detectar novos ciclos, mas páginas com prazo vencido são descartadas mesmo quando o site conserva “Inscrições abertas”.

### Complementar

- **FAPES — Difusão internacional**: procura apenas oportunidades de eventos, visitas e difusão que tenham componente internacional explícito.

Fontes muito ruidosas, internas a outra IES, dependentes de JavaScript ou pouco aderentes permanecem no JSON com `"desativada": true`, para consulta e reativação manual quando necessário.

---

## Instalação

Requer Python 3.10 ou superior.

```bash
python -m pip install -r requirements.txt
```

Dependências:

- `requests`
- `beautifulsoup4`
- `lxml`
- `pypdf` — necessário para ler o conteúdo dos PDFs dos editais

---

## Uso

Validar a configuração sem usar internet:

```bash
python validar_fontes.py
```

Rodar a coleta completa:

```bash
python editais_scraper.py
```

Rodar uma fonte específica — o nome pode ser um trecho; se o trecho casar com várias fontes, todas serão executadas:

```bash
python editais_scraper.py --fonte FAPES
python editais_scraper.py --fonte CONFAP
python editais_scraper.py --fonte DAAD
```

Regerar apenas o HTML a partir do histórico salvo:

```bash
python editais_scraper.py --so-painel
```

Depois, abra `painel.html` no navegador.

---

## Testes de qualidade

Antes de usar ou depois de alterar regras:

```bash
python testes_qualidade.py
```

Os testes cobrem, entre outros casos:

- parceria Brasil–Reino Unido com prazo futuro;
- Fulbright com texto “aberto”, mas prazo já vencido;
- CNPq/ERC;
- bolsa local genérica sem internacionalização;
- mobilidade apenas de entrada de estrangeiros para o Brasil;
- status “Em andamento” com deadline vencido;
- Horizon Europe;
- DAAD Cotutelle.

Também vale rodar:

```bash
python -m py_compile *.py
python validar_fontes.py
```

---

## Diagnosticar uma fonte

O `testar_fonte.py` agora usa o **mesmo filtro quality-first do scraper**, inclusive leitura de detalhe/PDF.

```bash
python testar_fonte.py "FAPES — Oportunidades"
python testar_fonte.py "CONFAP" --mostrar-descartados
```

Ele mostra:

- pré-score;
- aderência Global Ed;
- prazo encontrado;
- tipo do detalhe (`html`/`pdf`);
- motivo de relevância;
- motivo de descarte.

Isso é mais útil do que simplesmente contar palavras-chave no título.

---

## Quando o endereço de uma fonte mudar

```bash
python descobrir_urls.py "CNPq"
python descobrir_urls.py "CAPES"
python descobrir_urls.py --url https://exemplo.org
```

O descobridor procura páginas que pareçam listas de editais. Ele é uma ferramenta de manutenção; uma URL descoberta deve ser conferida antes de virar fonte principal.

---

## Configurações que controlam precisão

No `config.json`:

```json
{
  "modo_estrito_global_ed": true,
  "exigir_prazo_confirmado": true,
  "aceitar_prazo_desconhecido": false,
  "max_detalhes_por_fonte": 35,
  "max_paginas_pdf": 12,
  "dias_sem_confirmacao": 7
}
```

### `modo_estrito_global_ed`

Quando `true`, só aceita item com avaliação final `aberto`.

### `exigir_prazo_confirmado`

Quando `true`, “a página diz que está aberta” não basta: é necessária uma data final extraída do card, detalhe ou PDF.

Pode ser sobrescrito em uma fonte específica por:

```json
"exigir_prazo_confirmado": false
```

Use isso apenas em uma fonte oficial muito confiável que publique chamadas abertas sem deadline convencional.

### `max_detalhes_por_fonte`

Controla quantas páginas/PDFs podem ser abertas por fonte. Os candidatos são ordenados por pré-score, então o orçamento é gasto primeiro nas oportunidades mais promissoras.

### `max_paginas_pdf`

Limita quantas páginas de cada PDF serão lidas. Editais muito longos costumam trazer objetivo, elegibilidade e cronograma nas páginas iniciais.

### `dias_sem_confirmacao`

Evita deixar “aberto” indefinidamente um item sem deadline quando a fonte para de confirmar sua existência.

---

## Perfil estratégico do Global Ed

Edite `perfil_global_ed.json` para mudar o que é considerado relevante sem alterar Python.

Cada eixo tem:

- `peso` — importância na aderência;
- `termos` — expressões indicativas;
- `temas` — tags do painel.

Exemplo simplificado:

```json
"cotutela_dupla_titulacao": {
  "peso": 46,
  "termos": ["cotutela", "cotutelle", "joint supervision", "dual degree"]
}
```

O filtro exige pelo menos um eixo detectado, além de sinal internacional e sinal de oportunidade/chamada.

---

## Elegibilidade

`restricoes.json` funciona como uma camada de triagem, não como parecer jurídico ou acadêmico.

Ele reconhece programas conhecidos e acrescenta alertas, por exemplo:

- exigência de vínculo com doutorado/PPG;
- necessidade de consórcio internacional;
- participação via FAP estadual;
- oportunidades de candidatura individual de docente/pesquisador.

O conteúdo do edital continua sendo a fonte definitiva.

---

## Rede institucional / proxy

Se aparecer `ProxyError`, `Tunnel connection failed`, `SSL` ou timeouts em sites estrangeiros, configure a rede em `config.json`:

```json
"proxy_http": "http://servidor:porta",
"proxy_https": "http://servidor:porta"
```

Se o proxy institucional inspeciona HTTPS e substitui certificados, `"verificar_ssl": false` pode contornar o erro **somente em rede institucional confiável**. O ideal é pedir ao TI a cadeia de certificados/proxy correta.

O scraper também tem orçamento máximo de tempo por fonte, para impedir que um único site trave a execução inteira.

---

## Limitações conhecidas

### Sites carregados só por JavaScript

`requests` não executa JavaScript. Por isso fontes SPA podem aparecer como vazias. Elas ficam desativadas por padrão quando não oferecem uma listagem HTML estável.

### PDFs escaneados como imagem

`pypdf` extrai texto digital. Um PDF totalmente escaneado pode não produzir texto e, com prazo obrigatório, será descartado em vez de ser falsamente classificado como aberto. Essa é uma escolha de precisão.

### Prazo muito distante no documento

O limite padrão lê as 12 primeiras páginas do PDF. Se uma agência colocar o cronograma apenas no fim de editais longos, aumente `max_paginas_pdf`.

### Nenhum scraper substitui leitura do edital

O painel é uma **triagem de oportunidades**. Ele reduz ruído e prioriza chamadas, mas requisitos institucionais, contrapartidas e documentos devem ser confirmados na publicação oficial.

---

## Agendamento diário no Windows

O arquivo `executar.bat` já muda para a pasta correta e roda o scraper.

No Agendador de Tarefas do Windows:

1. Criar Tarefa Básica;
2. frequência diária;
3. ação **Iniciar um programa**;
4. selecione o caminho completo de `executar.bat`.

O histórico fica em `dados/` e o painel é atualizado em `painel.html`.

---

## Estrutura dos arquivos

- `editais_scraper.py` — coleta, detalhe/PDF, histórico e orquestração;
- `oportunidades.py` — prazo, aderência e filtro Global Ed;
- `perfil_global_ed.json` — estratégia e pesos auditáveis;
- `fontes.json` — fontes ativas/desativadas;
- `classificador.py` — temas auxiliares;
- `relevancia.py` — limpeza, deduplicação, restrições e prioridade;
- `restricoes.json` — catálogo de alertas de elegibilidade;
- `editais_painel.py` — HTML offline;
- `testes_qualidade.py` — testes do filtro;
- `testar_fonte.py` — diagnóstico de uma fonte com o filtro real;
- `validar_fontes.py` — validação do JSON de fontes;
- `descobrir_urls.py` — manutenção quando páginas mudam;
- `executar.bat` — execução automatizada no Windows.

---

## Filosofia desta versão

Para o Global Ed, é melhor mostrar **10 oportunidades fortes, abertas e explicáveis** do que 150 itens vagamente relacionados.

Por isso a versão atual privilegia **precisão, prazo confirmado e aderência aos projetos institucionais**, mantendo itens duvidosos fora do filtro padrão.