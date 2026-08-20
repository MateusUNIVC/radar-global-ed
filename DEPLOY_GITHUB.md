# Publicar o Radar Global Ed no GitHub Pages

O projeto já vem preparado para duas coisas diferentes:

1. **GitHub Actions** executa o Python todos os dias, acessa as fontes e atualiza o histórico.
2. **GitHub Pages** publica o `painel.html` gerado como um site estático.

O Pages sozinho não executa Python. A verificação diária acontece no runner do GitHub Actions e o resultado é enviado ao Pages depois da coleta.

## Configuração inicial

### 1. Crie o repositório

No GitHub, crie um repositório, por exemplo:

`radar-global-ed`

Para a configuração mais simples, use a branch padrão `main`.

### 2. Envie os arquivos deste projeto

A raiz do repositório deve conter diretamente:

- `editais_scraper.py`
- `editais_painel.py`
- `requirements.txt`
- os arquivos `.json`
- a pasta `.github/workflows/`

Evite colocar tudo dentro de uma segunda pasta no repositório.

### 3. Ative o GitHub Pages por Actions

No repositório:

**Settings → Pages → Build and deployment → Source → GitHub Actions**

Não selecione “Deploy from a branch”. Este projeto já possui o workflow de publicação.

### 4. Rode a primeira coleta manualmente

Abra:

**Actions → Atualizar e publicar Radar Global Ed → Run workflow**

A primeira execução instala o Python, roda os testes, faz a coleta, gera o painel e publica o site.

Depois disso o endereço costuma seguir o formato:

`https://SEU-USUARIO.github.io/radar-global-ed/`

O endereço exato aparece no próprio job de deploy e em **Settings → Pages**.

## Atualização automática diária

O arquivo `.github/workflows/atualizar-radar.yml` está configurado para rodar **todos os dias às 06:17 no horário de Brasília**:

```yaml
schedule:
  - cron: "17 6 * * *"
    timezone: "America/Sao_Paulo"
```

Para mudar o horário, altere apenas esses campos. Exemplo: 08:30 todos os dias:

```yaml
schedule:
  - cron: "30 8 * * *"
    timezone: "America/Sao_Paulo"
```

O workflow também aceita execução manual pela aba **Actions** e roda quando há `push` na branch `main`.

## Por que o workflow salva a pasta `dados/`

Os runners do GitHub são temporários. Se nada fosse salvo, cada execução começaria do zero e o radar perderia a noção de:

- oportunidades já conhecidas;
- novas edições;
- alterações detectadas;
- última confirmação de uma chamada;
- URLs de fontes que funcionaram anteriormente.

Por isso o bot faz commit dos JSONs em `dados/` após a coleta. O arquivo de log não é versionado.

## Permissões necessárias

O workflow usa:

- `contents: write` para preservar os JSONs do histórico;
- `pages: write` para publicar o site;
- `id-token: write` para o deploy do GitHub Pages.

Se a branch `main` tiver proteção que bloqueie commits do `github-actions[bot]`, permita esse bot ou adapte a política da branch. Sem conseguir salvar `dados/`, o site ainda poderia ser gerado, mas o histórico não seria confiável entre execuções.

## Como confirmar que está funcionando

Na aba **Actions**, a execução deve concluir estas etapas:

1. Rodar testes de qualidade
2. Verificar bolsas e gerar painel
3. Salvar histórico da coleta
4. Enviar site para Pages
5. Publicar GitHub Pages

No painel publicado, confira o bloco **Última verificação** e a seção **Saúde das fontes**.

## Observações importantes

- Sites de agências podem bloquear IPs de datacenter ou mudar HTML/URL. Isso aparecerá em “Saúde das fontes”.
- O GitHub pode atrasar workflows agendados em horários de pico; por isso o exemplo usa minuto `17`, não o início da hora.
- Em repositórios públicos, workflows agendados podem ser desativados pelo GitHub após longos períodos sem atividade. Como este projeto normalmente grava estado diariamente, isso tende a não ocorrer enquanto as coletas estiverem funcionando.
- GitHub Pages publica conteúdo na web. Não coloque senhas, tokens, dados pessoais ou configurações de proxy com credenciais nos arquivos do repositório.
