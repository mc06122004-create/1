@echo off
pip install pyinstaller
pyinstaller --noconfirm --onedir --windowed --name StackBot stackbot/main.py
echo Сборка завершена! Проверьте папку dist/StackBot/
pause
