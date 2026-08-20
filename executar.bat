@echo off
REM ===================================================================
REM  Painel de Editais UNIVC - execucao automatica
REM  Aponte o Agendador de Tarefas do Windows para ESTE arquivo.
REM  Ele resolve sozinho o diretorio de trabalho, o que evita o erro
REM  de "modulo nao encontrado" quando o agendador roda de outra pasta.
REM ===================================================================

cd /d "%~dp0"

echo Executando verificacao de editais...
python editais_scraper.py

if errorlevel 1 (
    echo.
    echo ERRO na execucao. Verifique dados\execucao.log
    exit /b 1
)

echo.
echo Concluido. Abra painel.html
exit /b 0
