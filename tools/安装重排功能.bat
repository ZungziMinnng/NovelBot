@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
echo ============================================================
echo   可选功能：本地重排
echo.
echo   给检索结果加一层精排，长篇写作时找参考资料更准。
echo   代价：约 4.6GB 磁盘，建议有 NVIDIA 显卡再装。
echo   不装也能正常用，只是少这一层。
echo ============================================================
echo.
set /p yes=要继续吗？(Y/N):
if /i not "%yes%"=="Y" goto :eof

echo.
echo [1/3] 安装 PyTorch（走官方索引，这一步清华源没有）...
"..\runtime\python.exe" -m pip install torch --index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 goto failed

echo.
echo [2/3] 安装 sentence-transformers（走清华源）...
"..\runtime\python.exe" -m pip install -r requirements-rerank.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 goto failed

echo.
echo [3/3] 下载重排模型（走 hf-mirror 镜像）...
set HF_ENDPOINT=https://hf-mirror.com
"..\runtime\python.exe" -m huggingface_hub.commands.huggingface_cli download BAAI/bge-reranker-v2-m3
if errorlevel 1 goto failed

echo.
echo 完成。重启 NovelBot 后，在小说的上下文设置里打开重排开关即可生效。
pause
goto :eof

:failed
echo.
echo 安装失败。重排是可选功能，装不上不影响 NovelBot 正常使用。
pause
