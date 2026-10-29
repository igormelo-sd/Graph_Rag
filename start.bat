@echo off
rem Atalho para a aplicacao GraphRAG; a verificacao do ambiente fica em graphrag\start.bat.
call "%~dp0graphrag\start.bat"
exit /b %errorlevel%
