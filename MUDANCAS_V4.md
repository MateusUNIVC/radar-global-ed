# Mudanças v4 — filtro internacional mais rigoroso

Esta revisão ataca três problemas observados na coleta real:

1. termos genéricos como "intercâmbio de conhecimento" não podem provar internacionalidade;
2. botões de compartilhamento (LinkedIn, Facebook, X/Twitter etc.) não podem virar oportunidades;
3. o radar precisa cobrir mais chamadas internacionais sem voltar a aumentar o ruído.

## Regras novas

- `intercâmbio`, `exchange`, `mobilidade` e `intercâmbio de conhecimento` deixaram de ser sinais suficientes;
- em fontes brasileiras amplas, é exigida evidência internacional independente;
- menção a país estrangeiro só conta quando aparece em contexto de pesquisa, parceria, chamada, financiamento ou mobilidade;
- agregadores regionais podem exigir conexão explícita com Brasil/FAPES/CONFAP/CNPq/CAPES;
- `forthcoming` é tratado como chamada futura, não como aberta;
- deadlines em JSON-LD/metadados podem ser recuperados;
- links de redes sociais e rotas de compartilhamento são descartados antes de herdarem títulos de cards.

## Fontes internacionais adicionadas

- EURAXESS LAC — chamadas com conexão Brasil;
- MSCA — Marie Skłodowska-Curie Actions.

## Verificação

Execute:

```bash
python testes_qualidade.py
python validar_fontes.py
```

A versão foi entregue com 22 verificações automatizadas de qualidade.
