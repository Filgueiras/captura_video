"""Visualizador e gravador para placas de captura USB (UVC/UAC)."""

import os
import platform
from pathlib import Path

__version__ = "1.0.0"


# Caminhos onde as distribuicoes guardam a configuracao e os plugins do ALSA.
_ALSA_CONF = "/usr/share/alsa/alsa.conf"
_ALSA_PLUGINS = (
    "/usr/lib/{maquina}-linux-gnu/alsa-lib",  # Debian, Ubuntu, Zorin
    "/usr/lib64/alsa-lib",                    # Fedora, openSUSE
    "/usr/lib/alsa-lib",                      # Arch
)


def _reparar_alsa() -> None:
    """Aponta o alsa-lib embutido no PyAV para a configuracao do sistema.

    O wheel do PyAV traz a sua propria copia estatica do alsa-lib, compilada com
    o prefixo da maquina de build (`/tmp/vendor/share/alsa`). Esse caminho nao
    existe em lugar nenhum fora dali, entao a biblioteca sobe sem config: todo
    dispositivo vira "Unknown PCM" e a gravacao sai muda, sem erro visivel.

    Sem ALSA_PLUGIN_DIR o `default` tambem falha, porque nesta familia de
    distribuicoes ele e um atalho para o plugin do PipeWire/PulseAudio, que mora
    fora da copia embutida. Com as duas variaveis, `default` e `pulse` abrem
    normalmente — e e por ai que se captura qualquer fonte do sistema, ja que
    este wheel do PyAV nao tem o demuxer `pulse` proprio.

    Variaveis ja definidas pelo ambiente sao respeitadas: quem apontou para
    outro lugar tinha um motivo.
    """
    if platform.system() != "Linux":
        return

    if "ALSA_CONFIG_PATH" not in os.environ and Path(_ALSA_CONF).is_file():
        os.environ["ALSA_CONFIG_PATH"] = _ALSA_CONF

    if "ALSA_PLUGIN_DIR" in os.environ:
        return
    maquina = platform.machine()
    for molde in _ALSA_PLUGINS:
        pasta = Path(molde.format(maquina=maquina))
        if pasta.is_dir():
            os.environ["ALSA_PLUGIN_DIR"] = str(pasta)
            return


# Precisa acontecer antes de o PyAV carregar o alsa-lib, ou seja, antes de
# qualquer `av.open`. Importar o pacote e o unico ponto por onde todos os
# caminhos de entrada passam: a janela, a linha de comando e o executavel.
_reparar_alsa()
