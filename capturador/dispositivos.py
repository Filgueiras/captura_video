"""Enumeracao de dispositivos de captura, independente de plataforma.

Windows -> DirectShow (dshow), via `ffmpeg -list_devices/-list_options`.
Linux   -> V4L2 para video (v4l2-ctl quando disponivel) e PulseAudio/ALSA para audio.

O resto do programa so conhece as dataclasses daqui; nada de codigo especifico
de sistema operacional vaza para o motor de captura ou para a interface.
"""

from __future__ import annotations

import glob
import os
import platform
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

# Codecs comprimidos que valem a pena priorizar: entregam resolucao cheia com
# taxa de quadros alta dentro do orcamento de banda do USB.
CODECS_COMPRIMIDOS = ("mjpeg", "h264", "hevc", "mjpg")

WINDOWS = platform.system() == "Windows"

# Impede que uma janela de console pisque na tela a cada chamada do ffmpeg.
_SEM_JANELA = subprocess.CREATE_NO_WINDOW if WINDOWS else 0


@dataclass(frozen=True)
class ModoVideo:
    """Uma combinacao de codec/resolucao/taxa que o dispositivo aceita."""

    codec: str
    largura: int
    altura: int
    fps: float

    @property
    def comprimido(self) -> bool:
        return self.codec.lower() in CODECS_COMPRIMIDOS

    @property
    def pixels(self) -> int:
        return self.largura * self.altura

    @property
    def rotulo(self) -> str:
        marca = "" if self.comprimido else "  (nao comprimido)"
        return f"{self.largura}x{self.altura}  {self.fps:g} fps  [{self.codec}]{marca}"

    def opcoes_ffmpeg(self) -> dict[str, str]:
        """Opcoes de entrada que fixam este modo, sem deixar nada por negociar."""
        opcoes = {
            "video_size": f"{self.largura}x{self.altura}",
            "framerate": f"{self.fps:g}",
        }
        if WINDOWS:
            # dshow separa codec comprimido de formato de pixel cru.
            if self.comprimido:
                opcoes["vcodec"] = self.codec
            else:
                opcoes["pixel_format"] = self.codec
        else:
            # v4l2 usa input_format para os dois casos.
            opcoes["input_format"] = self.codec
        return opcoes


TIPO_PLACA = "placa"
TIPO_TELA = "tela"
TIPO_JANELA = "janela"

# Taxas oferecidas para captura de tela. A placa dita as dela; a tela nao tem
# taxa propria, entao o usuario escolhe.
TAXAS_TELA = (60.0, 30.0, 24.0, 15.0)


@dataclass
class DispositivoVideo:
    nome: str
    caminho: str  # o que vai para av.open()
    modos: list[ModoVideo] = field(default_factory=list)
    # Caminho da entrada de audio do MESMO aparelho fisico, quando existir.
    # Placas de captura expoem video e audio como funcoes separadas; parear as
    # duas evita que o usuario grave o microfone do PC sem perceber.
    audio_associado: str | None = None

    tipo: str = TIPO_PLACA
    indice: int = 0                 # saida de video, para telas
    origem: tuple[int, int] = (0, 0)  # canto superior esquerdo, para telas

    @property
    def permite_copia(self) -> bool:
        """Se faz sentido gravar sem recomprimir.

        Tela e janela chegam como quadros crus: 1080p60 em BGRA sao 500 MB/s.
        Copiar isso para o disco nao e "sem perda", e inviavel.
        """
        return self.tipo == TIPO_PLACA

    def entrada(self, modo: ModoVideo, cursor: bool = True
                ) -> tuple[str, str, dict[str, str]]:
        """Devolve (caminho, formato, opcoes) prontos para o `av.open`.

        Cada tipo de fonte usa um demuxer diferente e distribui a configuracao
        entre caminho e opcoes de um jeito proprio — o ddagrab, por exemplo,
        recebe tudo dentro da string do filtro. Concentrar isso aqui evita que
        o motor de captura precise saber de qualquer um desses detalhes.
        """
        if self.tipo == TIPO_TELA:
            return self._entrada_tela(modo, cursor)
        if self.tipo == TIPO_JANELA:
            return self._entrada_janela(modo, cursor)
        return self.caminho, formato_entrada_video(), modo.opcoes_ffmpeg()

    def _entrada_tela(self, modo: ModoVideo, cursor: bool):
        if WINDOWS:
            if self.caminho == "ddagrab":
                # Desktop Duplication API: a mesma via que o OBS usa. Entra
                # como filtro do lavfi, e nao como dispositivo, por isso a
                # configuracao inteira mora na string.
                filtro = (f"ddagrab=output_idx={self.indice}"
                          f":framerate={modo.fps:g}"
                          f":draw_mouse={1 if cursor else 0}"
                          f",hwdownload,format=bgra")
                return filtro, "lavfi", {}
            x, y = self.origem
            return "desktop", "gdigrab", {
                "framerate": f"{modo.fps:g}",
                "draw_mouse": "1" if cursor else "0",
                "offset_x": str(x), "offset_y": str(y),
                "video_size": f"{modo.largura}x{modo.altura}",
            }
        x, y = self.origem
        return f"{os.environ.get('DISPLAY', ':0.0')}+{x},{y}", "x11grab", {
            "framerate": f"{modo.fps:g}",
            "draw_mouse": "1" if cursor else "0",
            "video_size": f"{modo.largura}x{modo.altura}",
        }

    def _entrada_janela(self, modo: ModoVideo, cursor: bool):
        if WINDOWS:
            # O gdigrab e o unico caminho para uma janela especifica: o ddagrab
            # so sabe duplicar saidas de video inteiras.
            return f"title={self.caminho}", "gdigrab", {
                "framerate": f"{modo.fps:g}",
                "draw_mouse": "1" if cursor else "0",
            }
        x, y = self.origem
        return f"{os.environ.get('DISPLAY', ':0.0')}+{x},{y}", "x11grab", {
            "framerate": f"{modo.fps:g}",
            "video_size": f"{modo.largura}x{modo.altura}",
        }

    def melhor_modo(self) -> ModoVideo | None:
        """Maior resolucao, preferindo formatos comprimidos e mais quadros.

        Essa ordenacao e exatamente o que players genericos erram: eles pegam o
        primeiro formato oferecido (geralmente cru) e ficam presos a 5 fps.
        """
        if not self.modos:
            return None
        return max(self.modos, key=lambda m: (m.comprimido, m.pixels, m.fps))


# De onde as amostras vem. O padrao e um demuxer do FFmpeg (dshow, pulse,
# alsa), aberto pelo PyAV como qualquer outra entrada. O WASAPI e o caminho
# nativo do Windows para a saida de audio, que o FFmpeg nao alcanca.
BACKEND_DEMUXER = ""
BACKEND_WASAPI = "wasapi"


@dataclass
class DispositivoAudio:
    nome: str
    caminho: str
    taxas: list[int] = field(default_factory=list)
    canais: list[int] = field(default_factory=list)
    # Se este dispositivo entrega o que SAI pelas caixas em vez de uma entrada
    # fisica. Gravando a tela e quase sempre o que se quer; gravando uma placa
    # e quase sempre o que NAO se quer.
    loopback: bool = False
    backend: str = BACKEND_DEMUXER

    def melhor_taxa(self) -> int:
        # 48 kHz quando existir: e o que placas HDMI entregam de fato e evita
        # reamostragem desnecessaria. Senao, a maior disponivel.
        if 48000 in self.taxas:
            return 48000
        return max(self.taxas) if self.taxas else 48000

    def melhor_canais(self) -> int:
        return 2 if 2 in self.canais else (max(self.canais) if self.canais else 2)


@dataclass
class Dispositivos:
    video: list[DispositivoVideo] = field(default_factory=list)
    audio: list[DispositivoAudio] = field(default_factory=list)
    aviso: str = ""


# --------------------------------------------------------------------------
# Audio do computador (loopback)
# --------------------------------------------------------------------------
#
# O Windows nao expoe a saida de audio como dispositivo de captura, e o FFmpeg
# nao tem loopback WASAPI. Gravar "o som do PC" depende de algum dispositivo
# instalado que faca essa ponte e apareca como entrada DirectShow. A ordem
# abaixo e de preferencia, e nao alfabetica:
#
# 1. virtual-audio-capturer grava a saida padrao sem alterar nada no sistema —
#    o usuario continua ouvindo normalmente. E a unica que funciona em
#    qualquer maquina, desde que instalada.
# 2. Cabos virtuais (VB-Cable, VoiceMeeter) so carregam som depois de virarem
#    o dispositivo de reproducao padrao; funciona, mas o usuario deixa de
#    ouvir pelas caixas enquanto grava.
# 3. Mixagem estereo depende de o driver da placa expor a funcao e de ela
#    estar habilitada. A maioria das maquinas atuais nao tem.
_LOOPBACK_WINDOWS = (
    "virtual-audio-capturer",
    "cable output",
    "voicemeeter output",
    "stereo mix",
    "mixagem estéreo",
    "mixagem estereo",
    "what u hear",
    "wave out mix",
)

DICA_LOOPBACK_WINDOWS = (
    "O caminho normal para gravar o som que sai pelas caixas é o WASAPI em modo "
    "loopback, que não precisa de instalação nenhuma. Ele não respondeu nesta "
    "máquina — verifique se o pacote `soundcard` está instalado "
    "(pip install -r requisitos.txt) e se o serviço de áudio do Windows está "
    "em pé.\n\n"
    "Não havendo jeito, resta instalar um dispositivo que faça a ponte por "
    "DirectShow:\n\n"
    "1. Mixagem estéreo — botão direito no ícone de som ▸ Configurações de som "
    "▸ Mais configurações de som ▸ aba Gravação ▸ botão direito na lista ▸ "
    "Mostrar dispositivos desabilitados ▸ habilitar «Mixagem estéreo». Não "
    "custa nada tentar, mas só existe se o driver da placa oferecer.\n\n"
    "2. VB-Cable (vb-audio.com/Cable) — funciona, mas só carrega som depois de "
    "virar o dispositivo de reprodução padrão; enquanto grava, você deixa de "
    "ouvir pelas caixas.\n\n"
    "Depois de habilitar, clique em «Procurar dispositivos»."
)

DICA_LOOPBACK_LINUX = (
    "Gravar o som do computador aqui depende do PulseAudio/PipeWire: a fonte "
    "«.monitor» da saída em uso é o que captura o que sai pelas caixas. Ela não "
    "apareceu, o que normalmente significa que o servidor de som não está "
    "rodando ou que o PyAV desta máquina foi compilado sem o demuxer `pulse` — "
    "nesse caso só há entradas ALSA, e ALSA não tem monitor da saída.\n\n"
    "Depois de resolver, clique em «Procurar dispositivos»."
)


def dica_loopback() -> str:
    """Como habilitar a captura do audio do computador nesta plataforma."""
    return DICA_LOOPBACK_WINDOWS if WINDOWS else DICA_LOOPBACK_LINUX


def _e_loopback_windows(nome: str) -> bool:
    baixo = nome.casefold()
    return any(marca in baixo for marca in _LOOPBACK_WINDOWS)


def escolher_loopback(dispositivos: list[DispositivoAudio]) -> DispositivoAudio | None:
    """A melhor fonte de "audio do computador" entre as enumeradas, se houver.

    Quando ha mais de uma — nao e raro: quem tem a Mixagem estereo ligada
    tambem tem o loopback WASAPI da mesma placa — a escolha nao pode ser a
    primeira da lista. O WASAPI vem sempre na frente: nao pede instalacao, nao
    depende do driver expor nada e nao obriga o usuario a trocar o dispositivo
    de reproducao padrao. Entre os de DirectShow vale a ordem de
    `_LOOPBACK_WINDOWS`.
    """
    candidatos = [d for d in dispositivos if d.loopback]
    if not candidatos:
        return None
    if not WINDOWS:
        return candidatos[0]

    def posicao(dispositivo: DispositivoAudio) -> tuple[int, int]:
        if dispositivo.backend == BACKEND_WASAPI:
            # Todos empatados: `min` devolve o primeiro, e a enumeracao ja
            # entrega a saida padrao na frente.
            return (0, 0)
        baixo = dispositivo.nome.casefold()
        for indice, marca in enumerate(_LOOPBACK_WINDOWS):
            if marca in baixo:
                return (1, indice)
        return (1, len(_LOOPBACK_WINDOWS))

    return min(candidatos, key=posicao)


def _loopback_wasapi() -> list[DispositivoAudio]:
    """Saidas do Windows abertas em modo loopback, sem driver de terceiros.

    O FFmpeg nao tem loopback WASAPI e o Windows nao expoe a saida como
    dispositivo de captura, entao esta e a unica via que nao exige instalar um
    filtro DirectShow de terceiros. A `soundcard` fala COM direto, sem compilar
    nada — o que importa porque wheels compilados costumam demorar a
    acompanhar versoes novas do Python.

    Qualquer tropeco aqui devolve lista vazia em vez de propagar: sem loopback
    o programa continua util, com a lista de entradas de sempre.
    """
    if not WINDOWS:
        return []
    try:
        import soundcard
    except Exception:
        return []

    try:
        saidas = [m for m in soundcard.all_microphones(include_loopback=True)
                  if m.isloopback]
    except Exception:
        return []
    try:
        padrao = str(soundcard.default_speaker().name)
    except Exception:
        padrao = ""

    dispositivos = []
    for saida in saidas:
        nome = str(saida.name)
        dispositivos.append(DispositivoAudio(
            nome=f"{nome} — saída padrão" if nome == padrao else nome,
            caminho=str(saida.id),
            # O WASAPI reamostra para a taxa pedida; estas sao as que fazem
            # sentido guardar num arquivo.
            taxas=[48000, 44100],
            canais=[2],
            loopback=True,
            backend=BACKEND_WASAPI,
        ))
    # A saida padrao primeiro: e a que esta tocando quando o usuario pensa "o
    # som do computador".
    dispositivos.sort(key=lambda d: d.nome.endswith("— saída padrão"), reverse=True)
    return dispositivos


# --------------------------------------------------------------------------
# Utilitarios
# --------------------------------------------------------------------------

def formato_entrada_video() -> str:
    return "dshow" if WINDOWS else "v4l2"


def formato_entrada_audio() -> str:
    """Backend de audio, limitado ao que o FFmpeg embutido no PyAV realmente tem.

    Nem todo wheel do PyAV e compilado com libpulse, entao nao basta o `pactl`
    existir no sistema: o demuxer precisa estar presente tambem, senao a
    abertura falha com "Unknown input format".
    """
    if WINDOWS:
        return "dshow"

    import av  # importado aqui para o modulo continuar util sem o PyAV

    if _tem("pactl") and "pulse" in av.formats_available:
        return "pulse"
    return "alsa"


def _tem(programa: str) -> bool:
    return shutil.which(programa) is not None


def _rodar(argumentos: list[str], tempo_limite: int = 20) -> str:
    """Executa um comando e devolve stdout+stderr como texto.

    O ffmpeg escreve as listagens em stderr e termina com codigo de erro; isso
    e esperado, entao o codigo de saida e ignorado de proposito.
    """
    try:
        proc = subprocess.run(
            argumentos,
            capture_output=True,
            timeout=tempo_limite,
            creationflags=_SEM_JANELA,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    bruto = (proc.stdout or b"") + (proc.stderr or b"")
    return bruto.decode("utf-8", errors="replace")


def _dedup_modos(modos: list[ModoVideo]) -> list[ModoVideo]:
    """Remove duplicatas e mantem, por codec+resolucao, so a maior taxa."""
    melhor: dict[tuple[str, int, int], ModoVideo] = {}
    for m in modos:
        chave = (m.codec, m.largura, m.altura)
        atual = melhor.get(chave)
        if atual is None or m.fps > atual.fps:
            melhor[chave] = m
    return sorted(
        melhor.values(),
        key=lambda m: (m.comprimido, m.pixels, m.fps),
        reverse=True,
    )


# --------------------------------------------------------------------------
# Windows / DirectShow
# --------------------------------------------------------------------------

_RE_DISPOSITIVO = re.compile(r'"([^"]+)"\s+\((video|audio|video,\s*audio)\)')
_RE_MODO_VIDEO = re.compile(
    r"(?:vcodec|pixel_format)=(\S+)\s+min\s+s=(\d+)x(\d+)\s+fps=([\d.]+)"
    r"\s+max\s+s=(\d+)x(\d+)\s+fps=([\d.]+)"
)
_RE_MODO_AUDIO = re.compile(r"ch=\s*(\d+),\s*bits=\s*(\d+),\s*rate=\s*(\d+)")


def _listar_windows() -> Dispositivos:
    if not _tem("ffmpeg"):
        return Dispositivos(
            aviso=(
                "ffmpeg nao foi encontrado no PATH. Ele e necessario para "
                "descobrir os formatos que a placa aceita.\n"
                "Instale com:  winget install Gyan.FFmpeg"
            )
        )

    saida = _rodar(["ffmpeg", "-hide_banner", "-f", "dshow",
                    "-list_devices", "true", "-i", "dummy"])

    nomes_video, nomes_audio = [], []
    for linha in saida.splitlines():
        achado = _RE_DISPOSITIVO.search(linha)
        if not achado:
            continue
        nome, tipo = achado.group(1), achado.group(2)
        (nomes_video if tipo.startswith("video") else nomes_audio).append(nome)

    # Cada sondagem gasta um a dois segundos esperando o dshow responder. Como
    # sao dispositivos distintos, elas nao competem entre si e podem ir juntas.
    with ThreadPoolExecutor(max_workers=6) as pool:
        modos = {n: pool.submit(_modos_video_windows, n) for n in nomes_video}
        formatos = {n: pool.submit(_modos_audio_windows, n) for n in nomes_audio}

        resultado = Dispositivos()
        for nome in nomes_video:
            resultado.video.append(DispositivoVideo(
                nome=nome, caminho=f"video={nome}", modos=modos[nome].result()))
        for nome in nomes_audio:
            taxas, canais = formatos[nome].result()
            resultado.audio.append(DispositivoAudio(
                nome=nome, caminho=f"audio={nome}", taxas=taxas, canais=canais,
                loopback=_e_loopback_windows(nome)))

    resultado.audio.extend(_loopback_wasapi())
    return resultado


def _modos_video_windows(nome: str) -> list[ModoVideo]:
    saida = _rodar(["ffmpeg", "-hide_banner", "-f", "dshow",
                    "-list_options", "true", "-i", f"video={nome}"])
    modos = []
    for achado in _RE_MODO_VIDEO.finditer(saida):
        codec = achado.group(1)
        # Usa sempre o extremo superior do intervalo anunciado.
        largura, altura = int(achado.group(5)), int(achado.group(6))
        fps = float(achado.group(7))
        modos.append(ModoVideo(codec=codec, largura=largura,
                               altura=altura, fps=round(fps, 3)))
    return _dedup_modos(modos)


def _modos_audio_windows(nome: str) -> tuple[list[int], list[int]]:
    saida = _rodar(["ffmpeg", "-hide_banner", "-f", "dshow",
                    "-list_options", "true", "-i", f"audio={nome}"])
    taxas, canais = set(), set()
    for achado in _RE_MODO_AUDIO.finditer(saida):
        canal, bits, taxa = int(achado.group(1)), int(achado.group(2)), int(achado.group(3))
        if bits != 16:  # 8 bits nunca vale a pena aqui.
            continue
        canais.add(canal)
        taxas.add(taxa)
    return sorted(taxas), sorted(canais)


# --------------------------------------------------------------------------
# Captura de tela e de janela
# --------------------------------------------------------------------------

def _modos_tela(largura: int, altura: int) -> list[ModoVideo]:
    return [ModoVideo("bgra", largura, altura, fps) for fps in TAXAS_TELA]


def _telas_windows() -> list[DispositivoVideo]:
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    try:
        # Sem isto o Windows mente sobre as dimensoes em telas com escala
        # diferente de 100%, e a captura sai cortada ou esticada.
        user32.SetProcessDPIAware()
    except Exception:
        pass

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT),
                    ("rcWork", wt.RECT), ("dwFlags", wt.DWORD),
                    ("szDevice", wt.WCHAR * 32)]

    proc = ctypes.WINFUNCTYPE(ctypes.c_int, wt.HMONITOR, wt.HDC,
                              ctypes.POINTER(wt.RECT), wt.LPARAM)
    achados: list[tuple[int, int, int, int, bool]] = []

    def _coletar(hmon, hdc, lprc, dados):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            achados.append((r.left, r.top, r.right - r.left, r.bottom - r.top,
                            bool(info.dwFlags & 1)))
        return 1

    user32.EnumDisplayMonitors(0, None, proc(_coletar), 0)

    # A ordem do EnumDisplayMonitors NAO e a do `output_idx` do ddagrab, que
    # segue a enumeracao do DXGI. Ordenar pela posicao horizontal parece
    # natural e esta errado: foi verificado nesta maquina que `output_idx=0`
    # e o monitor PRINCIPAL, mesmo ele estando a direita do outro. Com a
    # ordenacao por coordenada o usuario escolheria um ecra e gravaria o outro.
    # O DXGI lista a saida principal primeiro, entao e essa a ordem usada.
    achados.sort(key=lambda m: (not m[4], m[0], m[1]))

    telas: list[DispositivoVideo] = []
    usar_dda = "lavfi" in _formatos_disponiveis()

    for indice, (x, y, largura, altura, primario) in enumerate(achados):
        marca = " (principal)" if primario else ""
        telas.append(DispositivoVideo(
            nome=f"Ecrã {indice + 1}{marca} — {largura}x{altura}",
            caminho="ddagrab" if usar_dda else "desktop",
            modos=_modos_tela(largura, altura),
            tipo=TIPO_TELA, indice=indice, origem=(x, y),
        ))

    if len(achados) > 1:
        # Area virtual: util para quem quer os dois monitores num arquivo so,
        # mas custa o dobro de pixels. Sempre via gdigrab, porque o ddagrab
        # duplica uma saida de cada vez.
        esquerda = min(m[0] for m in achados)
        topo = min(m[1] for m in achados)
        largura = max(m[0] + m[2] for m in achados) - esquerda
        altura = max(m[1] + m[3] for m in achados) - topo
        telas.append(DispositivoVideo(
            nome=f"Todos os ecrãs — {largura}x{altura}",
            caminho="desktop", modos=_modos_tela(largura, altura),
            tipo=TIPO_TELA, origem=(esquerda, topo),
        ))

    return telas


_RE_XRANDR = re.compile(r"^\s*\d+:\s+\S*\s*(\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)\s+(\S+)",
                        re.MULTILINE)


def _telas_linux() -> list[DispositivoVideo]:
    if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        # Sob Wayland puro o x11grab nao enxerga a tela; devolver uma opcao que
        # so produz preto seria pior que nao oferecer nada.
        return []

    telas: list[DispositivoVideo] = []
    saida = _rodar(["xrandr", "--listmonitors"]) if _tem("xrandr") else ""
    for achado in _RE_XRANDR.finditer(saida):
        largura, altura = int(achado.group(1)), int(achado.group(2))
        x, y = int(achado.group(3)), int(achado.group(4))
        telas.append(DispositivoVideo(
            nome=f"Ecrã {achado.group(5)} — {largura}x{altura}",
            caminho="x11grab", modos=_modos_tela(largura, altura),
            tipo=TIPO_TELA, indice=len(telas), origem=(x, y),
        ))

    if not telas:
        telas.append(DispositivoVideo(
            nome="Ecrã inteiro", caminho="x11grab",
            modos=_modos_tela(1920, 1080), tipo=TIPO_TELA,
        ))
    return telas


def _formatos_disponiveis() -> set[str]:
    try:
        import av

        return set(av.formats_available)
    except Exception:
        return set()


def listar_telas() -> list[DispositivoVideo]:
    """Monitores disponiveis para captura."""
    try:
        return _telas_windows() if WINDOWS else _telas_linux()
    except Exception:
        return []


# Janelas menores que isto sao quase sempre elementos invisiveis do sistema.
_MINIMO_JANELA = (140, 90)

# Titulos de janelas tecnicas que aparecem na enumeracao mas nao interessam.
_JANELAS_IGNORADAS = (
    "Program Manager", "Microsoft Text Input Application",
    "Windows Input Experience", "Configurações", "Definições",
)


def _janelas_windows() -> list[DispositivoVideo]:
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    achadas: list[DispositivoVideo] = []
    vistos: set[str] = set()

    def _coletar(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        tamanho = user32.GetWindowTextLengthW(hwnd)
        if tamanho == 0:
            return True
        buffer = ctypes.create_unicode_buffer(tamanho + 1)
        user32.GetWindowTextW(hwnd, buffer, tamanho + 1)
        titulo = buffer.value.strip()
        if not titulo or titulo in vistos or titulo in _JANELAS_IGNORADAS:
            return True

        r = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        largura, altura = r.right - r.left, r.bottom - r.top
        if largura < _MINIMO_JANELA[0] or altura < _MINIMO_JANELA[1]:
            return True

        vistos.add(titulo)
        achadas.append(DispositivoVideo(
            nome=f"{titulo}  ({largura}x{altura})",
            caminho=titulo,  # o gdigrab localiza a janela pelo titulo
            modos=_modos_tela(largura, altura),
            tipo=TIPO_JANELA, origem=(r.left, r.top),
        ))
        return True

    user32.EnumWindows(proc(_coletar), 0)
    return achadas


_RE_WMCTRL = re.compile(r"^(0x\w+)\s+\S+\s+\S+\s+(.+)$", re.MULTILINE)


def _janelas_linux() -> list[DispositivoVideo]:
    if not _tem("wmctrl") or not _tem("xdotool"):
        return []

    achadas: list[DispositivoVideo] = []
    for achado in _RE_WMCTRL.finditer(_rodar(["wmctrl", "-l"])):
        identificador, titulo = achado.group(1), achado.group(2).strip()
        geometria = _rodar(["xdotool", "getwindowgeometry", "--shell", identificador])
        valores = dict(
            linha.split("=", 1) for linha in geometria.splitlines() if "=" in linha
        )
        try:
            x, y = int(valores["X"]), int(valores["Y"])
            largura, altura = int(valores["WIDTH"]), int(valores["HEIGHT"])
        except (KeyError, ValueError):
            continue
        if largura < _MINIMO_JANELA[0] or altura < _MINIMO_JANELA[1]:
            continue
        achadas.append(DispositivoVideo(
            nome=f"{titulo}  ({largura}x{altura})",
            caminho=identificador,
            modos=_modos_tela(largura, altura),
            tipo=TIPO_JANELA, origem=(x, y),
        ))
    return achadas


def listar_janelas() -> list[DispositivoVideo]:
    """Janelas abertas que podem ser capturadas isoladamente."""
    try:
        return _janelas_windows() if WINDOWS else _janelas_linux()
    except Exception:
        return []


# --------------------------------------------------------------------------
# Pareamento video <-> audio (Windows)
# --------------------------------------------------------------------------

# Container nulo: o Windows joga nele tudo que nao pertence a um aparelho
# fisico identificavel. Agrupar por ele juntaria placa-mae, GPU e webcam.
_CONTAINER_NULO = "{00000000-0000-0000-FFFF-FFFFFFFFFFFF}"

_PS_CONTAINERS = r"""
# Sem isto o PowerShell escreve na codepage do console (cp850/cp1252) e nomes
# com acento chegam corrompidos, o que faz o pareamento por nome falhar.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
# Só as classes cujos nomes aparecem no DirectShow. Incluir 'MEDIA' triplicaria
# a quantidade de dispositivos consultados sem acrescentar nenhum par possível.
foreach ($cls in 'Camera','Image','AudioEndpoint') {
  foreach ($d in (Get-PnpDevice -PresentOnly -Class $cls -ErrorAction SilentlyContinue)) {
    try {
      $c = (Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName 'DEVPKEY_Device_ContainerId' -ErrorAction Stop).Data
    } catch { $c = $null }
    if ($c -and $d.FriendlyName) { "$c`t$($d.FriendlyName)" }
  }
}
"""


def _containers_windows() -> dict[str, str]:
    """Mapeia nome amigavel -> ContainerId.

    O ContainerId e o identificador que o Windows da ao aparelho fisico: todas
    as interfaces do mesmo dongle (video, audio, HID) compartilham o mesmo
    valor, o que resolve o pareamento sem depender de nomes parecidos.
    """
    saida = _rodar(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_CONTAINERS],
        tempo_limite=25,
    )
    mapa: dict[str, str] = {}
    for linha in saida.splitlines():
        if "\t" not in linha:
            continue
        container, nome = linha.split("\t", 1)
        container, nome = container.strip(), nome.strip()
        if container and container != _CONTAINER_NULO:
            mapa[nome] = container
    return mapa


def _aplicar_containers(resultado: Dispositivos, mapa: dict[str, str]) -> None:
    if not mapa or not resultado.video or not resultado.audio:
        return

    for dispositivo in resultado.video:
        container = mapa.get(dispositivo.nome)
        if not container:
            continue
        for audio in resultado.audio:
            if mapa.get(audio.nome) == container:
                dispositivo.audio_associado = audio.caminho
                break


# --------------------------------------------------------------------------
# Pareamento video <-> audio (Linux)
# --------------------------------------------------------------------------

def _card_alsa_do_video(caminho_video: str) -> int | None:
    """Descobre o indice da placa ALSA que vem do mesmo aparelho USB.

    O sysfs guarda a topologia: o no de video aponta para a interface USB
    (`1-4:1.0`); subindo um nivel chega-se ao aparelho (`1-4`), e as outras
    interfaces dele ficam lado a lado — inclusive a de audio, que registra um
    `sound/cardN`.
    """
    no = Path("/sys/class/video4linux") / Path(caminho_video).name / "device"
    try:
        interface = no.resolve(strict=True)
    except OSError:
        return None

    aparelho = interface.parent
    for candidato in sorted(aparelho.glob("*/sound/card*")):
        sufixo = candidato.name.removeprefix("card")
        if sufixo.isdigit():
            return int(sufixo)
    return None


_RE_PACTL_NOME = re.compile(r"^\s*Name:\s*(\S+)", re.MULTILINE)
_RE_PACTL_CARD = re.compile(r'alsa\.card\s*=\s*"(\d+)"')


def _fontes_pulse_por_card() -> dict[int, str]:
    """Mapeia indice de placa ALSA -> nome da fonte no PulseAudio."""
    saida = _rodar(["pactl", "list", "sources"])
    mapa: dict[int, str] = {}
    # Os blocos comecam em "Source #N"; separar por eles mantem cada nome junto
    # das suas propriedades.
    for bloco in re.split(r"\n(?=Source\s+#)", saida):
        nome = _RE_PACTL_NOME.search(bloco)
        card = _RE_PACTL_CARD.search(bloco)
        if nome and card and not nome.group(1).endswith(".monitor"):
            mapa.setdefault(int(card.group(1)), nome.group(1))
    return mapa


def _parear_linux(resultado: Dispositivos) -> None:
    if not resultado.video or not resultado.audio:
        return

    usa_pulse = formato_entrada_audio() == "pulse"
    por_card = _fontes_pulse_por_card() if usa_pulse else {}

    for dispositivo in resultado.video:
        card = _card_alsa_do_video(dispositivo.caminho)
        if card is None:
            continue
        alvo = por_card.get(card) if usa_pulse else f"hw:{card},0"
        if not alvo:
            continue
        for audio in resultado.audio:
            if audio.caminho == alvo:
                dispositivo.audio_associado = audio.caminho
                break


# --------------------------------------------------------------------------
# Linux / V4L2 + PulseAudio
# --------------------------------------------------------------------------

_RE_V4L2_FORMATO = re.compile(r"\[\d+\]:\s+'(\w+)'")
_RE_V4L2_TAMANHO = re.compile(r"Size:\s+Discrete\s+(\d+)x(\d+)")
_RE_V4L2_INTERVALO = re.compile(r"Interval:\s+Discrete\s+[\d.]+s\s+\(([\d.]+)\s+fps\)")

# fourcc do V4L2 -> nome que o ffmpeg entende em -input_format
_FOURCC = {
    "MJPG": "mjpeg", "JPEG": "mjpeg", "H264": "h264", "HEVC": "hevc",
    "YUYV": "yuyv422", "UYVY": "uyvy422", "NV12": "nv12",
    "YU12": "yuv420p", "RGB3": "rgb24", "BGR3": "bgr24",
}


def _listar_linux() -> Dispositivos:
    resultado = Dispositivos()

    for caminho in sorted(glob.glob("/dev/video*")):
        nome = _nome_v4l2(caminho)
        modos = _modos_video_linux(caminho)
        # /dev/video1 costuma ser um nó só de metadados no mesmo hardware;
        # sem modos de captura ele não serve para nada aqui.
        if not modos:
            continue
        resultado.video.append(
            DispositivoVideo(nome=f"{nome} ({caminho})", caminho=caminho, modos=modos)
        )

    if not _tem("v4l2-ctl") and resultado.video:
        resultado.aviso = (
            "v4l2-ctl nao encontrado: a lista de formatos esta usando valores "
            "genericos.\nInstale com:  sudo apt install v4l-utils"
        )

    resultado.audio = _audio_linux()
    return resultado


def _nome_v4l2(caminho: str) -> str:
    no = Path("/sys/class/video4linux") / Path(caminho).name / "name"
    try:
        return no.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return Path(caminho).name


def _modos_video_linux(caminho: str) -> list[ModoVideo]:
    if not _tem("v4l2-ctl"):
        # Sem a ferramenta nao da para descobrir nada; oferece um conjunto
        # comum para o usuario escolher manualmente.
        return _dedup_modos([
            ModoVideo("mjpeg", l, a, f)
            for l, a in ((1920, 1080), (1280, 720), (640, 480))
            for f in (60.0, 30.0)
        ])

    saida = _rodar(["v4l2-ctl", "--device", caminho, "--list-formats-ext"])
    modos: list[ModoVideo] = []
    codec: str | None = None
    largura = altura = 0

    for linha in saida.splitlines():
        achado = _RE_V4L2_FORMATO.search(linha)
        if achado:
            fourcc = achado.group(1).upper()
            codec = _FOURCC.get(fourcc, fourcc.lower())
            continue
        achado = _RE_V4L2_TAMANHO.search(linha)
        if achado:
            largura, altura = int(achado.group(1)), int(achado.group(2))
            continue
        achado = _RE_V4L2_INTERVALO.search(linha)
        if achado and codec and largura:
            modos.append(ModoVideo(codec, largura, altura, round(float(achado.group(1)), 3)))

    return _dedup_modos(modos)


_RE_PACTL = re.compile(r"^\d+\s+(\S+)\s")


def _audio_linux() -> list[DispositivoAudio]:
    padrao_taxas = [48000, 44100]
    dispositivos: list[DispositivoAudio] = []

    # Os nomes precisam casar com o backend escolhido: fontes do PulseAudio nao
    # sao aceitas pelo demuxer ALSA e vice-versa.
    if formato_entrada_audio() == "pulse":
        saida = _rodar(["pactl", "list", "short", "sources"])
        for linha in saida.splitlines():
            achado = _RE_PACTL.match(linha)
            if not achado:
                continue
            fonte = achado.group(1)
            # Monitor e a saida do proprio PC — exatamente o que se quer ao
            # gravar a tela, e exatamente o que causa eco se for reproduzido de
            # volta. Ele entra na lista marcado como loopback; quem impede o
            # eco e a interface, que desliga a monitoracao para essas fontes.
            dispositivos.append(
                DispositivoAudio(nome=fonte, caminho=fonte,
                                 taxas=padrao_taxas, canais=[2, 1],
                                 loopback=fonte.endswith(".monitor"))
            )

    if not dispositivos:
        # Sem PulseAudio: cai para ALSA lendo as placas registradas no kernel.
        dispositivos.append(
            DispositivoAudio("default (ALSA)", "default", padrao_taxas, [2, 1])
        )
        try:
            texto = Path("/proc/asound/cards").read_text(encoding="utf-8", errors="replace")
        except OSError:
            texto = ""
        for achado in re.finditer(r"^\s*(\d+)\s+\[([^\]]+)\]", texto, re.MULTILINE):
            indice, etiqueta = achado.group(1), achado.group(2).strip()
            dispositivos.append(
                DispositivoAudio(f"{etiqueta} (hw:{indice},0)", f"hw:{indice},0",
                                 padrao_taxas, [2, 1])
            )

    return dispositivos


# --------------------------------------------------------------------------
# API publica
# --------------------------------------------------------------------------

def listar() -> Dispositivos:
    """Enumera o que da para capturar nesta maquina. Rapido (~1 s).

    Nao faz o pareamento video/audio: no Windows ele depende de uma consulta ao
    PowerShell que leva varios segundos, e travar a interface por isso seria pior
    que mostrar a lista imediatamente. Chame `parear()` em segundo plano.
    """
    return _listar_windows() if WINDOWS else _listar_linux()


def parear(resultado: Dispositivos) -> bool:
    """Associa cada placa de video a entrada de audio do mesmo aparelho.

    Preenche `DispositivoVideo.audio_associado` no lugar. Feito para rodar numa
    thread: so escreve um campo por dispositivo e nunca levanta excecao — sem
    pareamento a aplicacao continua util, apenas sem a selecao automatica.

    Devolve True se algum par foi encontrado.
    """
    try:
        if WINDOWS:
            _aplicar_containers(resultado, _containers_windows())
        else:
            _parear_linux(resultado)
    except Exception:
        return False
    return any(d.audio_associado for d in resultado.video)


def pasta_videos_padrao() -> Path:
    """Pasta de videos do usuario, com queda para a home."""
    for nome in ("Videos", "Vídeos", "Movies"):
        candidato = Path.home() / nome
        if candidato.is_dir():
            return candidato
    return Path.home()
