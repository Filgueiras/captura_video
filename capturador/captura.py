"""Motor de captura: le a placa, entrega quadros para a tela e grava em disco.

Decisoes centrais:

* Video e audio sao abertos como dois containers independentes, cada um na sua
  thread. Isso vale para Windows e Linux igualmente (no Linux nem existe a
  opcao de juntar os dois numa entrada so).
* A sincronia entre eles vem de uma ancora de relogio comum tomada no instante
  em que a gravacao comeca, e nao de carimbos de tempo por pacote. Assim os
  tempos suaves que a placa gera sao preservados e mesmo assim os dois fluxos
  comecam alinhados.
* No perfil "original" os pacotes da placa sao remultiplexados sem tocar nos
  bits: nada de decodificar e recodificar, entao o arquivo tem exatamente a
  qualidade que o hardware produziu, com custo de CPU proximo de zero.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import av
import av.error
import numpy as np
from PySide6.QtCore import QObject, Signal

from .dispositivos import (
    BACKEND_WASAPI,
    ModoVideo,
    formato_entrada_audio,
    formato_entrada_video,
)

# Tamanho do bloco lido do loopback WASAPI. Igual ao `audio_buffer_size` do
# dshow: curto o bastante para a monitoracao nao atrasar em relacao a imagem,
# longo o bastante para nao virar uma chamada de sistema a cada milissegundo.
_BLOCO_WASAPI_S = 0.08

PERFIL_ORIGINAL = "original"
PERFIL_H264 = "h264"

# Formato fixo da monitoracao de audio: e o que a saida do sistema aceita sem
# discussao e evita reamostragens surpresa no meio do caminho.
TAXA_MONITOR = 48000
CANAIS_MONITOR = 2

# Teto do buffer de monitoracao (~1 s). Se a interface parar de drenar, o audio
# antigo e descartado em vez de acumular memoria indefinidamente.
_MAX_BLOCOS_AUDIO = 64

# Varias placas anunciam uma taxa de quadros que nao conseguem sustentar e
# completam a diferenca com quadros JPEG vazios de 4 bytes (so os marcadores
# SOI+EOI). O MS2109 faz isso: diz 60 fps e alterna um quadro real com um vazio,
# entregando 30 fps de verdade. Esses quadros nao decodificam e, se forem
# gravados, deixam o arquivo cheio de erros. Nenhum JPEG de imagem real chega
# perto desse tamanho, entao o corte separa os dois casos sem ambiguidade.
_MIN_BYTES_JPEG = 256


def opcoes_codificador(codificador: str, qualidade: int,
                       ao_vivo: bool) -> dict[str, str]:
    """Ajustes do codificador de video, por familia.

    Cada uma chama o mesmo botao por um nome diferente: CRF no x264, CQ no
    NVENC, global_quality no QuickSync e no AMF. Menor = melhor imagem.

    `ao_vivo` separa os dois usos. Capturando, perder um quadro e pior que um
    arquivo maior, entao o x264 vai de `veryfast`/`zerolatency`. Convertendo um
    arquivo que ja existe nao ha quadro a perder — so tempo —, entao vale um
    preset mais lento, que e o que de fato entrega arquivo menor com a mesma
    qualidade.
    """
    if "nvenc" in codificador:
        return {
            "preset": "p5" if ao_vivo else "p6",
            "tune": "hq", "rc": "vbr",
            "cq": str(qualidade), "b:v": "0",
        }
    if "qsv" in codificador or "amf" in codificador:
        return {"global_quality": str(qualidade)}
    if ao_vivo:
        return {
            "crf": str(qualidade),
            "preset": "veryfast",
            "tune": "zerolatency",
        }
    return {"crf": str(qualidade), "preset": "medium"}


def _com_extras(formato: str, opcoes: dict[str, str]) -> dict[str, str]:
    """Acrescenta opcoes que so existem em demuxers especificos.

    `rtbufsize` e do DirectShow; passa-la ao V4L2, gdigrab ou lavfi seria uma
    opcao desconhecida, entao ela so entra onde e valida.
    """
    finais = dict(opcoes)
    if formato == "dshow":
        # Sem folga de buffer o dshow descarta quadros e enche o log de
        # "real-time buffer too full" assim que o disco engasga.
        finais["rtbufsize"] = "512M"
    return finais


@dataclass
class Configuracao:
    """Tudo que define uma sessao de captura."""

    caminho_video: str
    modo: ModoVideo
    formato_video: str = ""      # vazio => demuxer padrao da plataforma
    opcoes_video: dict = field(default_factory=dict)
    caminho_audio: str | None = None
    taxa_audio: int = 48000
    canais_audio: int = 2
    backend_audio: str = ""      # vazio => demuxer do FFmpeg; ver dispositivos

    perfil: str = PERFIL_ORIGINAL
    codificador: str = "libx264"
    qualidade: int = 20          # CRF (x264) ou CQ (NVENC): menor = melhor
    pasta_saida: Path = field(default_factory=Path.home)

    @classmethod
    def de_fonte(cls, dispositivo, modo: ModoVideo, cursor: bool = True,
                 **extras) -> "Configuracao":
        """Monta a configuracao perguntando a fonte como ela quer ser aberta."""
        caminho, formato, opcoes = dispositivo.entrada(modo, cursor)
        return cls(caminho_video=caminho, modo=modo, formato_video=formato,
                   opcoes_video=opcoes, **extras)

    def resolver(self) -> tuple[str, str, dict[str, str]]:
        formato = self.formato_video or formato_entrada_video()
        opcoes = self.opcoes_video or self.modo.opcoes_ffmpeg()
        return self.caminho_video, formato, _com_extras(formato, opcoes)

    @property
    def extensao(self) -> str:
        # MKV aguenta MJPEG + PCM e sobrevive a um travamento no meio da
        # gravacao; MP4 so fecha direito se o cabecalho for finalizado.
        return ".mkv" if self.perfil == PERFIL_ORIGINAL else ".mp4"

    @property
    def audio_por_wasapi(self) -> bool:
        """Se o audio vem do loopback do sistema, e nao de um demuxer.

        Muda duas coisas no gravador: nao existe fluxo de entrada para servir de
        molde, e nao existe pacote comprimido para copiar — o que chega ja e
        PCM cru saido do misturador do Windows.
        """
        return bool(self.caminho_audio) and self.backend_audio == BACKEND_WASAPI


# Vereditos do teste de equipamento, do melhor para o pior.
VEREDITO_FLUIDO = "fluido"
VEREDITO_APERTADO = "apertado"
VEREDITO_INSUFICIENTE = "insuficiente"
VEREDITO_ERRO = "erro"

_ROTULO_VEREDITO = {
    VEREDITO_FLUIDO: "Fluido",
    VEREDITO_APERTADO: "No limite",
    VEREDITO_INSUFICIENTE: "Vai engasgar",
    VEREDITO_ERRO: "Não abriu",
}


@dataclass
class Medicao:
    """Resultado de testar um modo contra o hardware E contra esta maquina."""

    modo: ModoVideo
    quadros_reais: int = 0
    quadros_vazios: int = 0
    duracao: float = 0.0
    octetos: int = 0
    erro: str = ""
    # Custo de processar um quadro nesta maquina: decodificar o JPEG e reduzir
    # ao tamanho da tela. E o trabalho que precisa caber no intervalo entre
    # quadros, senao a previa engasga.
    ms_por_quadro: float = 0.0
    quadros_processados: int = 0

    @property
    def fps_real(self) -> float:
        return self.quadros_reais / self.duracao if self.duracao else 0.0

    @property
    def fps_bruto(self) -> float:
        """Inclui os quadros de enchimento — e o numero que os players mostram."""
        total = self.quadros_reais + self.quadros_vazios
        return total / self.duracao if self.duracao else 0.0

    @property
    def mbits(self) -> float:
        return self.octetos * 8 / self.duracao / 1e6 if self.duracao else 0.0

    @property
    def honesto(self) -> bool:
        return self.quadros_vazios == 0

    @property
    def intervalo_ms(self) -> float:
        return 1000.0 / self.fps_real if self.fps_real else 0.0

    @property
    def uso(self) -> float:
        """Fracao do intervalo entre quadros gasta processando (0..1+)."""
        return self.ms_por_quadro / self.intervalo_ms if self.intervalo_ms else 0.0

    @property
    def veredito(self) -> str:
        if self.erro or not self.fps_real:
            return VEREDITO_ERRO
        if not self.quadros_processados:
            return VEREDITO_FLUIDO  # sem medicao de custo, nada a objetar
        if self.uso < 0.6:
            return VEREDITO_FLUIDO
        if self.uso < 0.9:
            return VEREDITO_APERTADO
        return VEREDITO_INSUFICIENTE

    @property
    def rotulo_veredito(self) -> str:
        return _ROTULO_VEREDITO[self.veredito]

    @property
    def resumo(self) -> str:
        if self.erro:
            return self.erro
        partes = [f"{self.fps_real:.0f} fps reais"]
        if not self.honesto:
            partes.append(f"{self.modo.fps:.0f} anunciados")
        partes.append(f"{self.mbits:.0f} Mbit/s")
        if self.quadros_processados:
            partes.append(f"CPU {self.uso*100:.0f}% do intervalo")
        return " · ".join(partes)


def medir_modo(dispositivo, modo: ModoVideo, duracao: float = 4.0,
               decodificar: bool = False, largura_preview: int = 1280) -> Medicao:
    """Abre um modo e mede o que ele entrega de verdade.

    Duas perguntas de uma vez: quantos quadros com imagem a placa realmente
    manda (a taxa anunciada nao e confiavel) e, com `decodificar`, quanto tempo
    esta maquina gasta preparando cada quadro para a tela. O segundo numero e o
    que separa um modo que roda liso de um que vai engasgar aqui.
    """
    medicao = Medicao(modo=modo)
    caminho, formato, opcoes = dispositivo.entrada(modo)
    try:
        container = av.open(caminho, format=formato,
                            options=_com_extras(formato, opcoes))
    except (av.error.FFmpegError, ValueError) as exc:
        medicao.erro = _resumir_erro(exc)
        return medicao

    try:
        fluxo = container.streams.video[0]
        fluxo.thread_type = "AUTO"
        mjpeg = fluxo.codec_context.name == "mjpeg"
        inicio = None
        gasto = 0.0

        for pacote in container.demux(fluxo):
            if pacote.pts is None and pacote.dts is None:
                continue
            if inicio is None:
                # Primeiro pacote so marca o inicio: a latencia de abertura do
                # dispositivo nao deve entrar na conta.
                inicio = time.monotonic()
                continue
            if mjpeg and pacote.size < _MIN_BYTES_JPEG:
                medicao.quadros_vazios += 1
            else:
                medicao.quadros_reais += 1
                medicao.octetos += pacote.size
                if decodificar:
                    gasto += _cronometrar_quadro(pacote, largura_preview, medicao)
            if time.monotonic() - inicio >= duracao:
                break

        medicao.duracao = (time.monotonic() - inicio) if inicio else 0.0
        if medicao.quadros_processados:
            medicao.ms_por_quadro = gasto * 1000 / medicao.quadros_processados
    except (av.error.FFmpegError, ValueError) as exc:
        medicao.erro = _resumir_erro(exc)
    finally:
        try:
            container.close()
        except (av.error.FFmpegError, ValueError):
            pass

    return medicao


def _cronometrar_quadro(pacote, largura: int, medicao: Medicao) -> float:
    """Executa o mesmo trabalho da previa e devolve quanto tempo levou."""
    marca = time.perf_counter()
    try:
        for quadro in pacote.decode():
            altura = max(2, int(round(quadro.height * largura / quadro.width)))
            quadro.reformat(width=largura - largura % 2, height=altura - altura % 2,
                            format="rgb24").to_ndarray()
            medicao.quadros_processados += 1
    except (av.error.FFmpegError, ValueError):
        return 0.0
    return time.perf_counter() - marca


def resumir_gravacao(caminho: Path) -> dict:
    """Abre um arquivo gravado e confere o que de fato ficou nele.

    Serve para a gravacao de amostra: em vez de dizer "pronto", mostra quantos
    quadros sobreviveram, a taxa efetiva e o desencontro entre as trilhas.

    A sincronia e medida por FIM DE CONTEUDO, nao pelo carimbo do ultimo pacote.
    Pacotes de audio duram ~80 ms e quadros ~33 ms; comparar os inicios dos
    ultimos pacotes traria dezenas de milissegundos de puro erro de arredondamento.
    """
    resumo: dict = {"caminho": caminho, "bytes": 0, "erro": ""}
    try:
        resumo["bytes"] = caminho.stat().st_size
    except OSError:
        pass

    try:
        container = av.open(str(caminho))
    except (av.error.FFmpegError, ValueError, OSError) as exc:
        resumo["erro"] = _resumir_erro(exc)
        return resumo

    try:
        fv = container.streams.video[0]
        fa = container.streams.audio[0] if container.streams.audio else None
        resumo["codec_video"] = fv.codec_context.name
        resumo["largura"] = fv.codec_context.width
        resumo["altura"] = fv.codec_context.height
        resumo["codec_audio"] = fa.codec_context.name if fa else ""

        nv = 0
        primeiro_v = ultimo_v = None
        amostras = 0
        ultimo_a = None
        dur_pacote_a = 0.0
        taxa_a = fa.codec_context.sample_rate if fa else 0
        fluxos = [f for f in (fv, fa) if f is not None]

        for pacote in container.demux(*fluxos):
            if pacote.stream is fv:
                if pacote.pts is None:
                    continue
                ts = float(pacote.pts * pacote.time_base)
                # Extremos por comparacao, e nao "o primeiro e o ultimo que
                # passaram": o demuxer entrega em ordem de decodificacao, e com
                # quadros B o pacote final nao e o de maior pts. Pegar o ultimo
                # encurtaria o video e jogaria a diferenca dentro do
                # desencontro, como se fosse o audio que estivesse sobrando.
                primeiro_v = ts if primeiro_v is None else min(primeiro_v, ts)
                ultimo_v = ts if ultimo_v is None else max(ultimo_v, ts)
                nv += 1
            elif taxa_a:
                # Quantas amostras este pacote carrega. O tamanho em bytes so
                # responde isso em PCM; em AAC ele e o tamanho COMPRIMIDO e nao
                # guarda relacao nenhuma com a duracao — era essa conta que
                # fazia o relatorio anunciar 0,4 s de audio num arquivo com 6 s.
                # Decodificar responde para qualquer codec: da a contagem exata
                # no PCM (a duracao declarada pelo Matroska e arredondada para
                # milissegundos e acumula ~90 ms de erro em 6 s) e ja desconta
                # as amostras de priming que o codificador AAC acrescenta.
                try:
                    n = sum(quadro.samples for quadro in pacote.decode())
                except av.error.FFmpegError:
                    n = 0
                amostras += n
                if pacote.pts is None:
                    continue
                ultimo_a = float(pacote.pts * pacote.time_base)
                if n:
                    dur_pacote_a = n / taxa_a
                elif pacote.duration:
                    # O decodificador segurou este pacote; a duracao declarada
                    # e a melhor estimativa que sobra para o fim do conteudo.
                    dur_pacote_a = float(pacote.duration * pacote.time_base)

        resumo["quadros"] = nv
        if primeiro_v is not None and ultimo_v is not None and nv > 1:
            span = ultimo_v - primeiro_v
            fps = (nv - 1) / span if span else 0.0
            resumo["fps"] = fps
            fim_video = ultimo_v + (1 / fps if fps else 0.0)
            resumo["duracao"] = fim_video
            if ultimo_a is not None:
                fim_audio = ultimo_a + dur_pacote_a
                resumo["desencontro_ms"] = (fim_audio - fim_video) * 1000
                resumo["duracao_audio"] = amostras / taxa_a
    except (av.error.FFmpegError, ValueError) as exc:
        resumo["erro"] = _resumir_erro(exc)
    finally:
        try:
            container.close()
        except (av.error.FFmpegError, ValueError):
            pass

    return resumo


def _resumir_erro(exc: Exception) -> str:
    texto = str(exc).split("\n")[0]
    if "I/O error" in texto or "already in use" in texto:
        return "dispositivo ocupado por outro programa"
    if "Permission denied" in texto:
        return "sem permissão para abrir o dispositivo"
    return texto


# Estado da trilha de audio numa sessao de captura. Existe porque "gravar sem
# som" tem varias causas diferentes e cada uma pede uma frase diferente para o
# usuario: ele escolheu nao ter audio, o audio ainda nao chegou, ele escolheu
# uma entrada que nao funciona, ou a entrada funciona e entrega silencio.
AUDIO_DESLIGADO = "desligado"
AUDIO_ESPERANDO = "esperando"
AUDIO_ATIVO = "ativo"
AUDIO_FALHOU = "falhou"
AUDIO_MUDO = "mudo"

# Pico abaixo do qual o bloco conta como silencio (~-54 dBFS). Silencio digital
# e exatamente zero, mas entradas analogicas sempre trazem um chiado de fundo:
# um limiar em zero acusaria "tem sinal" onde nao ha nada audivel.
LIMIAR_SINAL = 0.002

# Quanto de silencio seguido antes de declarar a entrada muda. Longo o bastante
# para uma pausa natural na fala, ou um trecho sem trilha, nao acender o aviso.
SEGUNDOS_SILENCIO = 8.0


@dataclass
class Estatisticas:
    largura: int = 0
    altura: int = 0
    fps: float = 0.0
    quadros: int = 0
    perdidos: int = 0
    gravando: bool = False
    arquivo: str = ""
    duracao: float = 0.0
    bytes_gravados: int = 0
    nivel_audio: float = 0.0


# --------------------------------------------------------------------------
# Gravador
# --------------------------------------------------------------------------

class Gravador:
    """Container de saida. Protegido por lock: duas threads escrevem nele."""

    def __init__(self, caminho: Path, config: Configuracao,
                 fluxo_video, fluxo_audio) -> None:
        self.caminho = caminho
        self.inicio = time.monotonic()
        self._lock = threading.Lock()
        self._fechado = False

        self._saida = av.open(str(caminho), mode="w")
        self._fifo_audio = None
        self._reamostrador = None
        # Fluxos que sao codificadores nossos e por isso precisam ser drenados
        # no fim. Copia remultiplexada nao entra: nao ha nada retido nela.
        self._codificados: list = []

        tem_audio = fluxo_audio is not None or config.audio_por_wasapi

        if config.perfil == PERFIL_ORIGINAL:
            self._video = self._saida.add_stream_from_template(fluxo_video)
            if config.audio_por_wasapi:
                # "Sem recompressao" nao pode ser cumprido copiando: o loopback
                # nao entrega pacote nenhum, entrega amostras. PCM e o
                # equivalente honesto — e exatamente o que o misturador do
                # sistema produziu, e o MKV do perfil Original ja o aceita.
                self._audio = self._criar_codificador_audio(config, cru=True)
            elif fluxo_audio is not None:
                self._audio = self._saida.add_stream_from_template(fluxo_audio)
            else:
                self._audio = None
        else:
            self._video = self._criar_codificador_video(config)
            self._audio = self._criar_codificador_audio(config) if tem_audio else None

    # -- montagem dos codificadores ---------------------------------------

    def _criar_codificador_video(self, config: Configuracao):
        modo = config.modo
        fluxo = self._saida.add_stream(config.codificador, rate=Fraction(modo.fps).limit_denominator(1000))
        fluxo.width = modo.largura
        fluxo.height = modo.altura
        fluxo.pix_fmt = "yuv420p"
        # Milissegundos, no fluxo E no codec. So no fluxo nao basta: sem isto o
        # libavcodec deriva o time_base do codec de `rate` (1/30), e dois
        # quadros a 33 ms e 66 ms viram o mesmo pts depois da conversao. O
        # Matroska tolera pts repetido, o MP4 recusa com EINVAL — o que produz
        # uma falha intermitente que depende de onde os quadros caem.
        fluxo.time_base = Fraction(1, 1000)
        fluxo.codec_context.time_base = Fraction(1, 1000)

        fluxo.options = opcoes_codificador(config.codificador, config.qualidade,
                                           ao_vivo=True)
        self._codificados.append(fluxo)
        return fluxo

    def _criar_codificador_audio(self, config: Configuracao, cru: bool = False):
        if cru:
            fluxo = self._saida.add_stream("pcm_s16le", rate=TAXA_MONITOR)
            formato = "s16"
        else:
            fluxo = self._saida.add_stream("aac", rate=TAXA_MONITOR)
            fluxo.bit_rate = 192_000
            formato = "fltp"
        self._reamostrador = av.AudioResampler(
            format=formato, layout="stereo", rate=TAXA_MONITOR
        )
        self._fifo_audio = av.audio.fifo.AudioFifo()
        self._codificados.append(fluxo)
        return fluxo

    # -- escrita -----------------------------------------------------------

    def copiar_video(self, pacote, ts: float) -> None:
        self._mux_copia(pacote, self._video, ts)

    def copiar_audio(self, pacote, ts: float) -> None:
        self._mux_copia(pacote, self._audio, ts)

    def _mux_copia(self, pacote, fluxo, ts: float) -> None:
        if fluxo is None or ts < 0:
            return
        marca = int(round(ts / float(pacote.time_base)))
        pacote.pts = marca
        pacote.dts = marca
        pacote.stream = fluxo
        with self._lock:
            if not self._fechado:
                self._saida.mux(pacote)

    def codificar_video(self, quadro, ts: float) -> None:
        if self._video is None or ts < 0:
            return
        quadro = quadro.reformat(format="yuv420p")
        quadro.pts = int(round(ts * 1000))
        quadro.time_base = Fraction(1, 1000)
        with self._lock:
            if self._fechado:
                return
            for pacote in self._video.encode(quadro):
                self._saida.mux(pacote)

    def codificar_audio(self, quadro, ts: float) -> None:
        if self._audio is None or ts < 0:
            return
        with self._lock:
            if self._fechado:
                return
            # O AAC exige blocos de tamanho exato, entao a FIFO junta as
            # sobras entre uma chamada e a proxima.
            for convertido in self._reamostrador.resample(quadro):
                convertido.pts = None
                self._fifo_audio.write(convertido)
            tamanho = self._audio.codec_context.frame_size or 1024
            while (bloco := self._fifo_audio.read(tamanho)) is not None:
                for pacote in self._audio.encode(bloco):
                    self._saida.mux(pacote)

    # -- encerramento ------------------------------------------------------

    def fechar(self) -> None:
        with self._lock:
            if self._fechado:
                return
            self._fechado = True
            # A FIFO retem o que sobrou do ultimo bloco inteiro — ate um quadro
            # de codificador, ~21 ms a 48 kHz. Sem esta leitura parcial essas
            # amostras morrem na memoria, e a trilha sai curta por um pedaco
            # que cresce com o tamanho do quadro do codec.
            if self._fifo_audio is not None and self._audio is not None:
                try:
                    resto = self._fifo_audio.read(partial=True)
                    if resto is not None:
                        for pacote in self._audio.encode(resto):
                            self._saida.mux(pacote)
                except (av.error.FFmpegError, ValueError):
                    pass
            # Drena o que ficou dentro dos codificadores, senao os ultimos
            # quadros/amostras nao chegam ao arquivo. A lista, em vez de um
            # teste de perfil: o perfil Original tambem codifica audio quando
            # ele vem do loopback, e esquecer disso truncaria a trilha.
            for fluxo in self._codificados:
                try:
                    for pacote in fluxo.encode(None):
                        self._saida.mux(pacote)
                except (av.error.FFmpegError, ValueError):
                    pass
            try:
                self._saida.close()
            except (av.error.FFmpegError, ValueError):
                pass

    @property
    def duracao(self) -> float:
        return time.monotonic() - self.inicio

    @property
    def bytes_escritos(self) -> int:
        try:
            return self.caminho.stat().st_size
        except OSError:
            return 0


# --------------------------------------------------------------------------
# Ancora de tempo
# --------------------------------------------------------------------------

class _Ancora:
    """Converte carimbos de tempo da placa em segundos desde o inicio da gravacao.

    O primeiro pacote de cada fluxo fixa a referencia: o tempo do dispositivo
    naquele pacote passa a valer o tempo de relogio decorrido desde que a
    gravacao comecou. Como video e audio usam o mesmo `t0`, os dois arquivos
    saem alinhados mesmo vindo de containers separados.
    """

    __slots__ = ("t0", "base", "deslocamento")

    def __init__(self, t0: float) -> None:
        self.t0 = t0
        self.base: float | None = None
        self.deslocamento = 0.0

    def converter(self, ts_dispositivo: float | None, atraso: float = 0.0) -> float:
        """`atraso` e quanto o conteudo ja envelheceu quando chega aqui.

        Um bloco de audio so fica pronto depois de gravado inteiro: quando ele
        chega, o som que ele carrega comecou um bloco atras. Sem descontar
        isso, a trilha inteira entra deslocada por essa constante — e como o
        video nao tem o mesmo atraso, a diferenca vira desencontro.
        """
        agora = time.monotonic() - self.t0 - atraso
        if ts_dispositivo is None:
            return agora
        if self.base is None:
            self.base = ts_dispositivo
            self.deslocamento = agora
        return (ts_dispositivo - self.base) + self.deslocamento


# --------------------------------------------------------------------------
# Motor
# --------------------------------------------------------------------------

class MotorCaptura(QObject):
    """Gerencia as threads de leitura e o estado compartilhado com a interface."""

    erro = Signal(str)
    aviso = Signal(str)
    gravacao_alterada = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config: Configuracao | None = None
        self._rodando = False

        self._lock = threading.Lock()
        self._quadro: np.ndarray | None = None
        self._quadro_serie = 0
        self._largura_preview = 1280

        # A tela recebe quadros reduzidos ao tamanho da janela; a foto avulsa
        # precisa da resolucao nativa, entao ela e pedida sob demanda.
        self._pedido_cheio = False
        self._quadro_cheio: np.ndarray | None = None

        self._gravador: Gravador | None = None
        self._lock_gravacao = threading.Lock()
        self._ancora_video: _Ancora | None = None
        self._ancora_audio: _Ancora | None = None

        self._fluxo_video = None
        self._fluxo_audio = None
        self._pronto_video = threading.Event()
        self._pronto_audio = threading.Event()
        self._audio_falhou = False

        self.audio_monitor: deque[bytes] = deque(maxlen=_MAX_BLOCOS_AUDIO)
        self._nivel_audio = 0.0
        # Instante do ultimo bloco com sinal de verdade. Zero enquanto nenhum
        # bloco chegou; a partir do primeiro, e o relogio que decide entre
        # "esta entrando som" e "esta entrando silencio".
        self._marca_som = 0.0
        self._monitorar = True

        self._threads: list[threading.Thread] = []
        self._stats = Estatisticas()
        self._marca_fps = time.monotonic()
        self._contador_fps = 0

    # -- ciclo de vida ------------------------------------------------------

    @property
    def rodando(self) -> bool:
        return self._rodando

    def iniciar(self, config: Configuracao) -> None:
        if self._rodando:
            self.parar()

        self._config = config
        self._rodando = True
        self._stats = Estatisticas(largura=config.modo.largura, altura=config.modo.altura)
        self._pronto_video.clear()
        self._pronto_audio.clear()
        self._audio_falhou = False
        self._marca_som = 0.0
        self._nivel_audio = 0.0
        # Os fluxos sao os moldes do arquivo de saida no perfil Original. Deixar
        # os da sessao anterior aqui faria a proxima gravacao abrir uma trilha
        # de audio de um container ja fechado — e a interface acharia que ha som.
        self._fluxo_video = None
        self._fluxo_audio = None
        self._marca_fps = time.monotonic()
        self._contador_fps = 0

        self._threads = [
            threading.Thread(target=self._laco_video, name="captura-video", daemon=True)
        ]
        if config.caminho_audio:
            laco = self._laco_wasapi if config.audio_por_wasapi else self._laco_audio
            self._threads.append(
                threading.Thread(target=laco, name="captura-audio", daemon=True)
            )
        for t in self._threads:
            t.start()

    def parar(self) -> None:
        self.parar_gravacao()
        self._rodando = False
        for t in self._threads:
            t.join(timeout=3.0)
        self._threads = []
        with self._lock:
            self._quadro = None
        self.audio_monitor.clear()

    # -- gravacao -----------------------------------------------------------

    def caminho_sugerido(self) -> Path | None:
        """Nome com data e hora dentro da pasta configurada."""
        if self._config is None:
            return None
        carimbo = time.strftime("%Y-%m-%d_%H-%M-%S")
        return (Path(self._config.pasta_saida)
                / f"captura_{carimbo}{self._config.extensao}")

    def iniciar_gravacao(self, caminho: Path | None = None) -> Path | None:
        """Comeca a gravar. Sem `caminho`, usa o nome sugerido."""
        if not self._rodando or self._config is None or self._gravador is not None:
            return None

        # Sem o cabecalho do fluxo de entrada nao da para remultiplexar; espera
        # o primeiro pacote chegar antes de abrir o arquivo.
        if not self._pronto_video.wait(timeout=5.0):
            self.erro.emit("A placa nao entregou nenhum quadro; gravacao cancelada.")
            return None
        # Com a entrada de audio ja em falha nao ha o que esperar: a interface
        # cuida do aviso, aqui so nao se perde 2 s a toa.
        if (self._config.caminho_audio and not self._audio_falhou
                and not self._pronto_audio.wait(timeout=2.0)):
            self.aviso.emit("O áudio não respondeu a tempo; esta gravação sai só com vídeo.")

        caminho = Path(caminho) if caminho else self.caminho_sugerido()
        try:
            caminho.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.erro.emit(f"Não foi possível usar a pasta de destino:\n{exc}")
            return None

        try:
            gravador = Gravador(caminho, self._config, self._fluxo_video, self._fluxo_audio)
        except (av.error.FFmpegError, ValueError, OSError) as exc:
            self.erro.emit(f"Nao foi possivel abrir o arquivo de gravacao:\n{exc}")
            return None

        t0 = time.monotonic()
        with self._lock_gravacao:
            self._ancora_video = _Ancora(t0)
            self._ancora_audio = _Ancora(t0)
            self._gravador = gravador

        self.gravacao_alterada.emit(True)
        return caminho

    def parar_gravacao(self) -> Path | None:
        with self._lock_gravacao:
            gravador = self._gravador
            self._gravador = None
        if gravador is None:
            return None
        gravador.fechar()
        self.gravacao_alterada.emit(False)
        return gravador.caminho

    @property
    def gravando(self) -> bool:
        return self._gravador is not None

    @property
    def estado_audio(self) -> str:
        """Se existe som chegando de verdade nesta sessao.

        A pergunta que interessa nao e "o usuario escolheu uma entrada?", nem
        sequer "chegou algum bloco?". Uma entrada escolhida pode nao abrir, ou
        abrir e parar no meio — nos dois casos a gravacao sai muda.

        E ha um caso que so contar blocos nao pega: a fonte de audio do
        computador entrega blocos sem parar, mesmo com o PC em silencio
        absoluto, porque silencio digital tambem e bloco. Contar blocos ali
        diria "ativo" com o arquivo saindo mudo — exatamente o desastre que
        este estado existe para evitar. Por isso o teste final e nas amostras.
        """
        if self._config is None or not self._config.caminho_audio:
            return AUDIO_DESLIGADO
        if self._audio_falhou:
            return AUDIO_FALHOU
        if not self._pronto_audio.is_set():
            return AUDIO_ESPERANDO
        marca = self._marca_som
        if marca and time.monotonic() - marca >= SEGUNDOS_SILENCIO:
            return AUDIO_MUDO
        return AUDIO_ATIVO

    # -- estado para a interface -------------------------------------------

    def definir_largura_preview(self, largura: int) -> None:
        """A interface informa o tamanho util; a conversao ja sai nesse tamanho."""
        self._largura_preview = max(320, min(int(largura), 3840))

    def definir_monitoracao(self, ligada: bool) -> None:
        self._monitorar = ligada
        if not ligada:
            self.audio_monitor.clear()

    def obter_quadro(self, serie_vista: int) -> tuple[np.ndarray | None, int]:
        """Devolve o quadro mais recente, ou None se ja foi visto."""
        with self._lock:
            if self._quadro is None or self._quadro_serie == serie_vista:
                return None, self._quadro_serie
            return self._quadro, self._quadro_serie

    def solicitar_quadro_cheio(self) -> None:
        self._pedido_cheio = True

    def obter_quadro_cheio(self) -> np.ndarray | None:
        quadro, self._quadro_cheio = self._quadro_cheio, None
        return quadro

    def estatisticas(self) -> Estatisticas:
        s = self._stats
        gravador = self._gravador
        s.gravando = gravador is not None
        s.arquivo = gravador.caminho.name if gravador else ""
        s.duracao = gravador.duracao if gravador else 0.0
        s.bytes_gravados = gravador.bytes_escritos if gravador else 0
        s.nivel_audio = self._nivel_audio
        return s

    # -- threads ------------------------------------------------------------

    def _abrir(self, caminho: str, formato: str, opcoes: dict[str, str]):
        return av.open(caminho, format=formato, options=opcoes,
                       metadata_errors="ignore")

    def _laco_video(self) -> None:
        config = self._config
        assert config is not None

        caminho, formato, opcoes = config.resolver()
        try:
            container = self._abrir(caminho, formato, opcoes)
        except (av.error.FFmpegError, ValueError) as exc:
            self._rodando = False
            self.erro.emit(_mensagem_abertura(config.caminho_video, exc))
            return

        try:
            fluxo = container.streams.video[0]
            fluxo.thread_type = "AUTO"  # decodificacao MJPEG em varios nucleos
            self._fluxo_video = fluxo

            mjpeg = fluxo.codec_context.name == "mjpeg"

            for pacote in container.demux(fluxo):
                if not self._rodando:
                    break
                if pacote.dts is None and pacote.pts is None:
                    continue
                if mjpeg and pacote.size < _MIN_BYTES_JPEG:
                    # Quadro de enchimento da placa: nao conta como perdido
                    # porque nunca houve imagem nele.
                    continue
                self._pronto_video.set()

                bruto = pacote.pts if pacote.pts is not None else pacote.dts
                ts_dispositivo = float(bruto * pacote.time_base) if bruto is not None else None

                # Decodifica antes de gravar: o mux se apropria do buffer do
                # pacote e o esvazia, entao decodificar depois devolveria nada
                # e a previa ficaria preta durante a gravacao.
                try:
                    quadros = pacote.decode()
                except av.error.FFmpegError:
                    self._stats.perdidos += 1
                    quadros = []

                gravador = self._gravador
                if gravador is not None and config.perfil == PERFIL_ORIGINAL:
                    ancora = self._ancora_video
                    if ancora is not None:
                        try:
                            gravador.copiar_video(pacote, ancora.converter(ts_dispositivo))
                        except (av.error.FFmpegError, ValueError) as exc:
                            self._falha_gravacao(exc)

                for quadro in quadros:
                    self._registrar_quadro(quadro)

                    gravador = self._gravador
                    if gravador is not None and config.perfil == PERFIL_H264:
                        ancora = self._ancora_video
                        if ancora is not None:
                            try:
                                gravador.codificar_video(quadro, ancora.converter(ts_dispositivo))
                            except (av.error.FFmpegError, ValueError) as exc:
                                self._falha_gravacao(exc)
        except (av.error.FFmpegError, ValueError) as exc:
            if self._rodando:
                self.erro.emit(f"A captura de video parou:\n{exc}")
        finally:
            self._rodando = False
            try:
                container.close()
            except (av.error.FFmpegError, ValueError):
                pass

    def _registrar_quadro(self, quadro) -> None:
        if self._pedido_cheio:
            self._pedido_cheio = False
            try:
                self._quadro_cheio = quadro.to_ndarray(format="rgb24")
            except (av.error.FFmpegError, ValueError):
                self._quadro_cheio = None

        largura = self._largura_preview
        altura = max(2, int(round(quadro.height * largura / quadro.width)))
        # Alinhamento par: o swscale reclama de dimensoes impares em varios formatos.
        largura -= largura % 2
        altura -= altura % 2

        try:
            imagem = quadro.reformat(width=largura, height=altura,
                                     format="rgb24").to_ndarray()
        except (av.error.FFmpegError, ValueError):
            self._stats.perdidos += 1
            return

        with self._lock:
            self._quadro = imagem
            self._quadro_serie += 1

        self._stats.quadros += 1
        self._contador_fps += 1
        agora = time.monotonic()
        decorrido = agora - self._marca_fps
        if decorrido >= 1.0:
            self._stats.fps = self._contador_fps / decorrido
            self._contador_fps = 0
            self._marca_fps = agora

    def _laco_audio(self) -> None:
        config = self._config
        assert config is not None

        opcoes = {
            "sample_rate": str(config.taxa_audio),
            "channels": str(config.canais_audio),
        }
        if formato_entrada_audio() == "dshow":
            # Padrao do dshow e meio segundo, o que deixa a monitoracao
            # perceptivelmente atrasada em relacao a imagem.
            opcoes["audio_buffer_size"] = "80"
            opcoes["rtbufsize"] = "64M"

        try:
            container = self._abrir(config.caminho_audio, formato_entrada_audio(), opcoes)
        except (av.error.FFmpegError, ValueError) as exc:
            self._audio_falhou = True
            self.aviso.emit(
                f"Áudio indisponível, seguindo só com vídeo:\n{exc}"
            )
            return

        reamostrador = av.AudioResampler(
            format="s16", layout="stereo", rate=TAXA_MONITOR
        )

        try:
            fluxo = container.streams.audio[0]
            self._fluxo_audio = fluxo

            for pacote in container.demux(fluxo):
                if not self._rodando:
                    break
                if pacote.dts is None and pacote.pts is None:
                    continue
                self._pronto_audio.set()
                if not self._marca_som:
                    # A carencia do silencio conta a partir do primeiro bloco:
                    # antes dele o estado ainda e "esperando", e cobrar sinal
                    # de uma entrada que nem comecou seria falso alarme.
                    self._marca_som = time.monotonic()

                bruto = pacote.pts if pacote.pts is not None else pacote.dts
                ts_dispositivo = float(bruto * pacote.time_base) if bruto is not None else None

                gravador = self._gravador

                # Decodificar sempre, mesmo sem monitoracao e sem gravar: e o
                # unico jeito de olhar as amostras e distinguir uma entrada que
                # funciona de uma que entrega silencio. Sao blocos de 80 ms de
                # PCM estereo — custo irrisorio perto do caminho do video.
                #
                # Mesma regra do video: decodificar tem que vir antes do mux,
                # que consome o pacote.
                try:
                    quadros = pacote.decode()
                except av.error.FFmpegError:
                    quadros = []

                if gravador is not None and config.perfil == PERFIL_ORIGINAL:
                    ancora = self._ancora_audio
                    if ancora is not None:
                        try:
                            gravador.copiar_audio(pacote, ancora.converter(ts_dispositivo))
                        except (av.error.FFmpegError, ValueError) as exc:
                            self._falha_gravacao(exc)

                for quadro in quadros:
                    gravador = self._gravador
                    if gravador is not None and config.perfil == PERFIL_H264:
                        ancora = self._ancora_audio
                        if ancora is not None:
                            try:
                                gravador.codificar_audio(quadro, ancora.converter(ts_dispositivo))
                            except (av.error.FFmpegError, ValueError) as exc:
                                self._falha_gravacao(exc)
                    self._processar_monitor(quadro, reamostrador)
        except (av.error.FFmpegError, ValueError) as exc:
            if self._rodando:
                self.aviso.emit(f"A captura de áudio parou:\n{exc}")
        finally:
            # Sair daqui com a captura ainda em pe significa que so o audio
            # acabou: o video segue, e o que for gravado daqui em diante fica
            # mudo. E exatamente o caso que o selo da janela precisa mostrar.
            if self._rodando:
                self._audio_falhou = True
            try:
                container.close()
            except (av.error.FFmpegError, ValueError):
                pass

    def _laco_wasapi(self) -> None:
        """Le a saida do sistema em modo loopback, sem passar por container.

        A diferenca para `_laco_audio` e a fonte, nao o destino: aqui chegam
        blocos de PCM em vez de pacotes, e a partir do `av.AudioFrame` montado
        o caminho e exatamente o mesmo — mesmo gravador, mesma ancora, mesma
        medicao de nivel e de silencio.

        O relogio tambem sai daqui: em vez de carimbos do dispositivo, a
        posicao vem da contagem de amostras entregues. E um relogio melhor que
        o do dshow, porque nao tem jitter nenhum — cada bloco vale exatamente
        os seus quadros, e o WASAPI ja repoe com silencio o que faltar.
        """
        import soundcard

        config = self._config
        assert config is not None
        taxa = config.taxa_audio
        canais = config.canais_audio
        quadros_bloco = max(1, int(taxa * _BLOCO_WASAPI_S))

        try:
            microfone = soundcard.get_microphone(config.caminho_audio,
                                                 include_loopback=True)
        except Exception as exc:
            self._audio_falhou = True
            self.aviso.emit(f"Áudio indisponível, seguindo só com vídeo:\n{exc}")
            return

        reamostrador = av.AudioResampler(
            format="s16", layout="stereo", rate=TAXA_MONITOR
        )
        base_tempo = Fraction(1, taxa)
        entregues = 0

        try:
            with microfone.recorder(samplerate=taxa, channels=canais,
                                    blocksize=quadros_bloco) as fonte:
                while self._rodando:
                    bloco = fonte.record(numframes=quadros_bloco)
                    if bloco is None or not len(bloco):
                        continue

                    self._pronto_audio.set()
                    if not self._marca_som:
                        self._marca_som = time.monotonic()

                    quadro = av.AudioFrame.from_ndarray(
                        # A SoundCard devolve (amostras, canais) em float32; o
                        # formato planar do PyAV quer (canais, amostras), e a
                        # transposta precisa ser contigua para virar buffer.
                        np.ascontiguousarray(bloco.T, dtype=np.float32),
                        format="fltp",
                        layout="stereo" if canais == 2 else "mono",
                    )
                    quadro.sample_rate = taxa
                    quadro.pts = entregues
                    quadro.time_base = base_tempo
                    ts_dispositivo = entregues / taxa
                    entregues += len(bloco)
                    # O bloco so retorna depois de completo: o som que ele
                    # carrega comecou `duracao` atras.
                    duracao = len(bloco) / taxa

                    gravador = self._gravador
                    if gravador is not None:
                        ancora = self._ancora_audio
                        if ancora is not None:
                            try:
                                gravador.codificar_audio(
                                    quadro,
                                    ancora.converter(ts_dispositivo, duracao))
                            except (av.error.FFmpegError, ValueError) as exc:
                                self._falha_gravacao(exc)

                    self._processar_monitor(quadro, reamostrador)
        except Exception as exc:
            # A SoundCard fala COM direto: uma saida que some no meio (monitor
            # desligado, fone desconectado) sobe como erro nativo, e nao como
            # excecao do PyAV.
            if self._rodando:
                self.aviso.emit(f"A captura de áudio parou:\n{exc}")
        finally:
            if self._rodando:
                self._audio_falhou = True

    def _processar_monitor(self, quadro, reamostrador) -> None:
        try:
            convertidos = reamostrador.resample(quadro)
        except (av.error.FFmpegError, ValueError):
            return

        for convertido in convertidos:
            amostras = convertido.to_ndarray()
            if amostras.size:
                pico = float(np.abs(amostras).max()) / 32768.0
                # Descida suave para o medidor nao piscar a cada bloco.
                self._nivel_audio = max(pico, self._nivel_audio * 0.75)
                if pico >= LIMIAR_SINAL:
                    self._marca_som = time.monotonic()
            if self._monitorar:
                self.audio_monitor.append(convertido.to_ndarray().tobytes())

    def _falha_gravacao(self, exc: Exception) -> None:
        gravador = self.parar_gravacao()
        alvo = f"\nArquivo: {gravador}" if gravador else ""
        self.erro.emit(f"A gravacao foi interrompida por um erro:\n{exc}{alvo}")


def _mensagem_abertura(caminho: str, exc: Exception) -> str:
    """Traduz o erro cru do FFmpeg para algo acionavel."""
    texto = str(exc)
    dica = ""
    if "I/O error" in texto or "already in use" in texto:
        dica = (
            "\n\nA placa aceita um programa por vez. Feche o VLC, o OBS ou "
            "qualquer outro aplicativo que esteja usando a captura e tente de novo."
        )
    elif "Permission denied" in texto:
        dica = (
            "\n\nSem permissao para abrir o dispositivo. No Linux, adicione seu "
            "usuario ao grupo video:  sudo usermod -aG video $USER"
        )
    return f"Nao foi possivel abrir {caminho}:\n{texto}{dica}"
