@echo off
rem Atalho para a aplicacao GraphRAG; a verificacao do ambiente fica em graph_rag\start.bat.
call "%~dp0graph_rag\start.bat"
exit /b %errorlevel%
