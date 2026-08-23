@echo off
chcp 65001 >nul
title Ai-Girlfriend 打包构建脚本
color 0B

echo.
echo =========================================
echo    Ai-Girlfriend 打包构建脚本
echo =========================================
echo.

REM 检查 PyInstaller
where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [信息] 安装 PyInstaller...
    pip install -q pyinstaller
    if errorlevel 1 (
        echo [错误] PyInstaller 安装失败
        pause
        exit /b 1
    )
)

REM 检查 Inno Setup
where iscc >nul 2>&1
if errorlevel 1 (
    echo [警告] 未检测到 Inno Setup，将仅生成可执行文件，不生成安装包
    echo [信息] 可从 https://jrsoftware.org/isdl.php 下载 Inno Setup
    set HAS_INNO=0
) else (
    set HAS_INNO=1
)

REM 清理旧构建
echo [信息] 清理旧构建文件...
if exist build rmdir /s /q build 2>nul
if exist dist rmdir /s /q dist 2>nul
if exist build del /q build 2>nul
if exist dist del /q dist 2>nul

REM 运行 PyInstaller
echo [信息] 运行 PyInstaller 打包...
pyinstaller --clean --noconfirm ai_girlfriend.spec
if errorlevel 1 (
    echo [错误] PyInstaller 打包失败
    pause
    exit /b 1
)

echo [信息] 可执行文件已生成: dist\AiGirlfriend.exe

if %HAS_INNO%==1 (
    echo [信息] 编译 Inno Setup 安装包...
    iscc AiGirlfriend.iss
    if errorlevel 1 (
        echo [错误] Inno Setup 编译失败
        pause
        exit /b 1
    )
    echo [信息] 安装包已生成: dist\AiGirlfriend_Setup_v1.0.0.exe
) else (
    echo [信息] 跳过安装包生成（未安装 Inno Setup）
    echo [信息] 可直接使用 dist\AiGirlfriend.exe
)

echo.
echo =========================================
echo    构建完成！
echo =========================================
echo 可执行文件: dist\AiGirlfriend.exe
if %HAS_INNO%==1 echo 安装包: dist\AiGirlfriend_Setup_v1.0.0.exe
echo.
pause