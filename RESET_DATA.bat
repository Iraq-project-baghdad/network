@echo off
cd /d "%~dp0"
echo This will delete all local accounts, chats, captions, and secure rooms.
pause
if exist data\app.db del /f /q data\app.db
if exist data\server_secret.key del /f /q data\server_secret.key
echo Data reset completed.
pause
