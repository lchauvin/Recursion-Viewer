@echo off
rem Lance l'assistant de MJ et ouvre le navigateur.
rem Le coffre vient de la configuration, de ASSISTANT_COFFRE, ou de --coffre.
cd /d "%~dp0"
py -m assistant %*
