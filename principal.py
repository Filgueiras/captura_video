"""Ponto de entrada para o executável empacotado.

O `capturador/__main__.py` usa imports relativos (`from . import dispositivos`),
que só funcionam quando o módulo é carregado como parte do pacote. O PyInstaller
carrega o script de entrada como `__main__`, sem pacote, então apontar a receita
direto para `__main__.py` quebraria esses imports. Este arquivo importa o pacote
pelo nome e só depois chama a função.
"""

import sys

from capturador.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
