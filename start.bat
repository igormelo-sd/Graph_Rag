@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 goto failure
if not exist ".venv\Scripts\python.exe" (
    echo Ambiente Python nao encontrado. Siga a instalacao no README.md.
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
".venv\Scripts\python.exe" "main.py" --cli
if errorlevel 1 goto failure
endlocal
exit /b 0

:failure
echo.
echo Nao foi possivel iniciar ou concluir o RAG. Confira a mensagem acima.
pause
endlocal
exit /b 1
