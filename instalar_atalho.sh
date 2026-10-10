#!/usr/bin/env sh
# Cria o atalho do aplicativo no menu do sistema (Linux).
#
#     ./instalar_atalho.sh              instala
#     ./instalar_atalho.sh --remover    desinstala
#
# É o equivalente Linux de ter o `Captura USB.bat` na área de trabalho: sem
# isto, abrir o programa exige um terminal. O atalho aponta para o `capturar.sh`
# nesta pasta, então mover o repositório depois exige rodar isto de novo.

PASTA="$(cd "$(dirname "$0")" && pwd)"
DESTINO="$HOME/.local/share/applications"
ARQUIVO="$DESTINO/captura-usb.desktop"

if [ "$1" = "--remover" ]; then
    rm -f "$ARQUIVO"
    [ -x "$(command -v update-desktop-database)" ] && update-desktop-database "$DESTINO" 2>/dev/null
    echo "Atalho removido."
    exit 0
fi

if [ ! -f "$PASTA/capturar.sh" ]; then
    echo "capturar.sh não encontrado em $PASTA — rode este script de dentro da pasta do projeto."
    exit 1
fi

chmod +x "$PASTA/capturar.sh"
mkdir -p "$DESTINO"

# Exec precisa de caminho absoluto: o menu não roda o programa a partir daqui.
# As aspas protegem um caminho com espaços, que é o caso comum de quem guarda o
# repositório num disco externo.
cat > "$ARQUIVO" <<FIM
[Desktop Entry]
Type=Application
Version=1.0
Name=Captura USB
GenericName=Gravador de captura
Comment=Visualizar e gravar placas de captura USB (HDMI→USB)
Exec="$PASTA/capturar.sh"
Path=$PASTA
Icon=camera-video
Terminal=false
Categories=AudioVideo;Video;Recorder;
Keywords=captura;gravar;HDMI;USB;video;
FIM

chmod +x "$ARQUIVO"
[ -x "$(command -v update-desktop-database)" ] && update-desktop-database "$DESTINO" 2>/dev/null

echo "Atalho criado: $ARQUIVO"
echo "Procure por «Captura USB» no menu de aplicativos."
