# -*- mode: python ; coding: utf-8 -*-
"""Receita do PyInstaller.

    pyinstaller capturador.spec

Gera `dist/Captura USB/`, uma pasta com o executável e as bibliotecas ao lado
(modo "onedir"). O modo arquivo-único existe, mas descompacta ~230 MB de Qt e
FFmpeg num diretório temporário a cada abertura — em disco mecânico isso são
vários segundos de espera antes da janela aparecer.

O FFmpeg de linha de comando NÃO é embutido: ele continua sendo pré-requisito
do sistema no Windows, porque é o que enumera os formatos que a placa aceita.

Decisões registradas em docs/adr/0018-empacotar-com-pyinstaller-em-modo-pasta.md
Passo a passo e solução de problemas em docs/COMO_GERAR_EXECUTAVEL.md
"""

from PyInstaller.utils.hooks import collect_dynamic_libs

# As DLLs do FFmpeg que o PyAV carrega ficam em `av.libs`, fora do pacote. Sem
# recolhê-las explicitamente o executável abre e falha no primeiro `av.open`.
binarios = collect_dynamic_libs("av")

# Módulos que entram só porque alguma coisa os menciona, e pesam. O Qt em
# particular traz WebEngine e Quick inteiros se ninguém disser o contrário.
EXCLUIDOS = [
    "tkinter",
    "matplotlib",
    "PyQt5",
    "PyQt6",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQml",
    "PySide6.Qt3DCore",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtPdf",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
]

a = Analysis(
    ["principal.py"],
    pathex=[],
    binaries=binarios,
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUIDOS,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Captura USB",
    debug=False,
    strip=False,
    upx=False,          # UPX quebra a assinatura de DLLs do Qt e assusta antivírus
    # Sem console: é um aplicativo de janela. O efeito colateral é que erros de
    # inicialização não têm para onde ir — para depurar, troque para True.
    console=False,
    icon=None,          # troque por "recursos/icone.ico" quando houver um
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Captura USB",
)
