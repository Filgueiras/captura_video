#!/usr/bin/env sh
# Abre o aplicativo. Torne executável uma vez com:  chmod +x capturar.sh
cd "$(dirname "$0")" || exit 1

# O ambiente virtual mora fora da pasta do projeto de propósito: o repositório
# costuma ficar num disco externo NTFS/exFAT, que não suporta os links
# simbólicos que o venv cria. VENV_CAPTURA sobrescreve, se preferir outro lugar.
VENV="${VENV_CAPTURA:-$HOME/.venvs/captura_video}"

# Um .venv dentro da pasta tem prioridade — quem criou um ali quis usá-lo.
if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python -m capturador "$@"
fi

if [ -x "$VENV/bin/python" ]; then
    exec "$VENV/bin/python" -m capturador "$@"
fi

# Sem ambiente virtual: só serve se as dependências estiverem no Python do
# sistema. No Ubuntu 24.04 e derivados (Zorin 18) o pip recusa instalar aí
# (PEP 668), então na prática este caminho é para quem montou tudo à mão.
if command -v python3 >/dev/null 2>&1 && python3 -c "import PySide6" 2>/dev/null; then
    exec python3 -m capturador "$@"
fi

echo "Ambiente virtual não encontrado em: $VENV"
echo
echo "Crie-o uma vez com:"
echo "  sudo apt install python3-venv v4l-utils libasound2-plugins"
echo "  python3 -m venv \"$VENV\""
echo "  \"$VENV/bin/pip\" install -r requisitos.txt"
exit 1
