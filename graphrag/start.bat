@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 goto failure
rem Suporta venv local (graphrag\.venv) ou venv geral da raiz (..\.venv).
set "PY_LOCAL=.venv\Scripts\python.exe"
set "PY_ROOT=..\.venv\Scripts\python.exe"
set "PY="
if exist "%PY_LOCAL%" set "PY=%PY_LOCAL%"
if not defined PY if exist "%PY_ROOT%" set "PY=%PY_ROOT%"
if not defined PY (
    echo Ambiente Python nao encontrado nem em graphrag\.venv nem em ..\.venv. Siga a instalacao no README.md.
    goto failure
)
if not exist ".env" (
    echo Arquivo .env nao encontrado. Configure o provedor conforme README.md.
    goto failure
)
rem O bootstrap verifica o manifesto e o indice real, nao apenas a pasta.
rem Reutiliza embeddings existentes e sincroniza fontes novas ou alteradas.
set "RAG_INDEX_READ_ONLY=0"
set "RAG_INDEX_AUTO_DOWNLOAD=0"
echo Verificando o indice e preparando o chat RAG...
echo Na primeira execucao, os modelos locais podem precisar de download.
echo Usando Python: %PY%
"%PY%" --version
if errorlevel 1 goto failure
"%PY%" "main.py" --cli
if errorlevel 1 goto failure
endlocal
exit /b 0

:failure
echo.
echo Nao foi possivel iniciar ou concluir o RAG. Confira a mensagem acima.
pause
endlocal
exit /b 1
