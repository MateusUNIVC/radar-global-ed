# Publicar o Radar Global Ed no GitHub Pages

## Ponto mais importante

O GitHub só reconhece workflows se o arquivo estiver **na raiz do repositório** neste caminho exato:

`.github/workflows/atualizar-radar.yml`

Se aparecer como `radar_global_ed_final/.github/workflows/atualizar-radar.yml`, o GitHub **não vai reconhecer** o workflow.

## Forma recomendada de enviar os arquivos

1. Descompacte `radar_global_ed_UNIVC_v3_1_repo_pronto.zip`.
2. Abra a pasta extraída.
3. Envie **todos os arquivos e pastas que estão dentro dela** para a raiz do repositório.
4. No GitHub, confirme que você vê `.github` na página inicial do repositório.
5. Abra `.github/workflows/atualizar-radar.yml` e confirme que o arquivo existe.

A estrutura correta começa assim:

```
.github/
  workflows/
    atualizar-radar.yml
dados/
editais_scraper.py
editais_painel.py
requirements.txt
...
```

## Se o workflow não aparecer na aba Actions

Você pode criar o arquivo diretamente pelo GitHub:

1. Abra o repositório.
2. Clique em **Add file > Create new file**.
3. No nome do arquivo, digite exatamente:
   `.github/workflows/atualizar-radar.yml`
4. Cole o conteúdo do arquivo incluído neste projeto.
5. Clique em **Commit changes** e salve no branch padrão.

Depois disso, abra **Actions**. O workflow deve aparecer com o nome:

**Atualizar e publicar Radar Global Ed**

## GitHub Pages

1. Vá em **Settings > Pages**.
2. Em **Build and deployment > Source**, selecione **GitHub Actions**.
3. Volte para **Actions**.
4. Abra **Atualizar e publicar Radar Global Ed**.
5. Clique em **Run workflow** para a primeira execução.

## Execução diária

O workflow está programado para rodar todos os dias às **06:17 no horário de Brasília**, além de permitir execução manual por **Run workflow**.

## Histórico

A pasta `dados/` é atualizada automaticamente pelo workflow para preservar o estado entre execuções. Para isso, o workflow solicita `contents: write`.

Se houver erro de permissão ao salvar o histórico, verifique em:

**Settings > Actions > General > Workflow permissions**

que o repositório permite escrita pelo `GITHUB_TOKEN`, se a política da conta/organização permitir.

## Branch padrão

Esta versão não presume que o branch se chama `main`: ela usa automaticamente o branch padrão do repositório ao salvar o histórico.
