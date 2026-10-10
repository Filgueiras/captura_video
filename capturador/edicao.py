"""Pos-producao: converter formato, cortar pontas e juntar trechos.

As tres operacoes que a captura deixa pendentes sao, no fundo, **a mesma
operacao**: pegar N trechos de arquivo, cada um com um inicio e um fim, e
escrever um arquivo so. Converter e um trecho inteiro com recompressao; cortar
e um trecho com pontas; juntar sao varios trechos em sequencia. Por isso existe
uma funcao — `montar` — e nao tres, e por isso os tres recursos nascem com o
mesmo tratamento de tempo, de audio e de cancelamento.

Como na captura, o FFmpeg vem embutido no PyAV
([0002](../docs/adr/0002-ffmpeg-embutido-via-pyav.md)): nada de subprocesso, e
o progresso e o cancelamento sao do nosso lado.

Dois caminhos de saida, e a escolha entre eles e a decisao que mais importa
para quem usa. Ver [0026](../docs/adr/0026-pos-producao-copia-ou-recompressao.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import av
import av.error

from .captura import opcoes_codificador

# Base de tempo da saida recomprimida: milissegundos, no fluxo e no codec, pelo
# mesmo motivo do [0007](../docs/adr/0007-base-de-tempo-em-milissegundos.md).
_BASE_MS = Fraction(1, 1000)

MODO_COPIA = "copia"
MODO_RECOMPRIMIR = "recomprimir"

# Silencio entre trechos juntados nao existe: eles sao encostados. Mas um
# trecho pode terminar no meio de um pacote de audio, e o proximo comeca no
# zero dele. Essa juncao e a unica costura audivel, e e de milissegundos.


@dataclass(frozen=True)
class Trecho:
    """Um pedaco de um arquivo: do `inicio` ao `fim`, em segundos.

    `fim=None` significa "ate onde o arquivo for". `inicio=0` com `fim=None` e
    o arquivo inteiro, que e o caso da conversao pura.
    """

    caminho: Path
    inicio: float = 0.0
    fim: float | None = None

    @property
    def duracao(self) -> float | None:
        if self.fim is None:
            return None
        return max(0.0, self.fim - self.inicio)


@dataclass
class Receita:
    """Como escrever a saida."""

    modo: str = MODO_COPIA
    codificador: str = "libx264"
    qualidade: int = 23
    # So vale recomprimindo. Vazio = mantem a resolucao do primeiro trecho.
    largura: int = 0
    altura: int = 0


@dataclass
class Resultado:
    saida: Path
    trechos: int = 0
    duracao: float = 0.0
    quadros: int = 0
    cancelado: bool = False
    erro: str = ""
    # Cortando sem recomprimir, o inicio real e o quadro-chave anterior ao
    # pedido. Guardar a diferenca permite a interface dizer isso em vez de
    # fingir precisao que nao houve.
    desvio_inicio: list[float] = field(default_factory=list)

    @property
    def desvio_maximo(self) -> float:
        return max(self.desvio_inicio) if self.desvio_inicio else 0.0


class Cancelado(Exception):
    """Levantada internamente quando quem chamou pediu para parar."""


# --------------------------------------------------------------------------
# Leitura
# --------------------------------------------------------------------------

def informacoes(caminho: Path) -> dict:
    """Duracao, codecs e dimensoes de um arquivo. Nunca levanta excecao."""
    info: dict = {
        "caminho": caminho, "erro": "", "duracao": 0.0, "bytes": 0,
        "codec_video": "", "codec_audio": "", "largura": 0, "altura": 0,
        "fps": 0.0, "tem_audio": False,
    }
    try:
        info["bytes"] = caminho.stat().st_size
    except OSError:
        pass

    try:
        container = av.open(str(caminho))
    except (av.error.FFmpegError, ValueError, OSError) as exc:
        info["erro"] = str(exc)
        return info

    try:
        if container.duration:
            info["duracao"] = container.duration / av.time_base
        if container.streams.video:
            v = container.streams.video[0]
            info["codec_video"] = v.codec_context.name
            info["largura"] = v.codec_context.width
            info["altura"] = v.codec_context.height
            taxa = v.average_rate or v.guessed_rate
            info["fps"] = float(taxa) if taxa else 0.0
            # Container sem duracao declarada (acontece em MKV interrompido):
            # a duracao do fluxo ainda costuma estar la.
            if not info["duracao"] and v.duration and v.time_base:
                info["duracao"] = float(v.duration * v.time_base)
        if container.streams.audio:
            info["tem_audio"] = True
            info["codec_audio"] = container.streams.audio[0].codec_context.name
    except (av.error.FFmpegError, ValueError, IndexError) as exc:
        info["erro"] = str(exc)
    finally:
        container.close()
    return info


class Leitor:
    """Entrega o quadro de qualquer instante de um arquivo, para a previa.

    Mantem o container aberto entre as chamadas: reabrir a cada movimento da
    barra custaria mais que decodificar, e a barra se move muito.

    O custo de um salto depende do codec. Em MJPEG, que e o que a placa entrega,
    todo quadro e chave e a resposta e imediata. Num H.264 com GOP de dois
    segundos, o decodificador precisa percorrer ate dois segundos de quadros
    antes de mostrar o pedido — dai a previa ser pedida com atraso pela
    interface, e nao a cada pixel arrastado.
    """

    def __init__(self, caminho: Path) -> None:
        self.caminho = caminho
        self.erro = ""
        self.duracao = 0.0
        self._container = None
        self._fluxo = None
        try:
            self._container = av.open(str(caminho))
            self._fluxo = self._container.streams.video[0]
            self._fluxo.thread_type = "AUTO"
            info = informacoes(caminho)
            self.duracao = info["duracao"]
            self.erro = info["erro"]
        except (av.error.FFmpegError, ValueError, OSError, IndexError) as exc:
            self.erro = str(exc)
            self.fechar()

    @property
    def valido(self) -> bool:
        return self._fluxo is not None and not self.erro

    def quadro(self, segundos: float):
        """Imagem RGB do instante pedido, ou None se nao der para ler."""
        if not self.valido:
            return None
        alvo = max(0.0, min(segundos, max(0.0, self.duracao - 0.05)))
        try:
            self._container.seek(int(alvo / self._fluxo.time_base),
                                 stream=self._fluxo, backward=True)
            ultimo = None
            for quadro in self._container.decode(self._fluxo):
                ultimo = quadro
                # Para no primeiro quadro que alcanca o alvo. O anterior fica
                # guardado porque num salto para tras do fim do arquivo pode
                # nao existir nenhum quadro depois do alvo.
                if quadro.time is not None and quadro.time >= alvo:
                    break
            if ultimo is None:
                return None
            return ultimo.to_ndarray(format="rgb24")
        except (av.error.FFmpegError, ValueError, StopIteration):
            return None

    def fechar(self) -> None:
        if self._container is not None:
            try:
                self._container.close()
            except (av.error.FFmpegError, ValueError):
                pass
        self._container = None
        self._fluxo = None


def compativeis(trechos: list[Trecho]) -> str:
    """Se estes trechos podem ser juntados sem recomprimir; "" quando podem.

    Copiar so funciona se os pacotes forem intercambiaveis: mesmo codec, mesmas
    dimensoes. Juntar 1080p com 720p por copia produz um arquivo que a maioria
    dos reprodutores mostra quebrado a partir da emenda — melhor recusar e
    explicar do que entregar isso.
    """
    if len(trechos) < 2:
        return ""
    base = None
    for trecho in trechos:
        info = informacoes(trecho.caminho)
        if info["erro"]:
            return f"Não foi possível ler {trecho.caminho.name}: {info['erro']}"
        assinatura = (info["codec_video"], info["largura"], info["altura"])
        if base is None:
            base = (assinatura, trecho.caminho.name)
            continue
        if assinatura != base[0]:
            return (
                f"«{trecho.caminho.name}» é {assinatura[1]}x{assinatura[2]} "
                f"[{assinatura[0]}] e «{base[1]}» é {base[0][1]}x{base[0][2]} "
                f"[{base[0][0]}].\n\nJuntar sem recomprimir exige o mesmo codec "
                "e as mesmas dimensões. Escolha «recomprimir» para juntar mesmo "
                "assim — vai demorar, e o resultado é um arquivo só, uniforme."
            )
    return ""


# --------------------------------------------------------------------------
# Escrita
# --------------------------------------------------------------------------

def montar(trechos: list[Trecho], saida: Path, receita: Receita,
           progresso=None, cancelar=None) -> Resultado:
    """Escreve `trechos`, em ordem, num arquivo so.

    `progresso` recebe uma fracao de 0 a 1; `cancelar` e chamado sem argumentos
    e devolve True para interromper. Os dois sao opcionais.

    Cancelar apaga a saida pela metade: um arquivo truncado com nome de video
    pronto e uma armadilha para quem for procura-lo depois.
    """
    resultado = Resultado(saida=saida, trechos=len(trechos))
    if not trechos:
        resultado.erro = "Nenhum trecho para montar."
        return resultado

    # Medido uma vez por trecho, aqui. `informacoes` abre o arquivo, e chamar
    # isso a cada aviso de progresso custaria mais que a propria conversao.
    duracoes = [_duracao_efetiva(trecho) for trecho in trechos]
    total = sum(duracoes) or 1.0
    saida.parent.mkdir(parents=True, exist_ok=True)

    destino = None
    try:
        destino = av.open(str(saida), mode="w")
        escritor = (_EscritorCopia(destino) if receita.modo == MODO_COPIA
                    else _EscritorRecompressao(destino, receita))
        decorrido = 0.0
        for trecho, duracao in zip(trechos, duracoes):
            gasto = escritor.acrescentar(
                trecho, duracao, resultado,
                lambda fracao, base=decorrido, d=duracao: _avisar(
                    progresso, total, base, fracao, d),
                cancelar,
            )
            decorrido += gasto
        escritor.encerrar()
        resultado.duracao = decorrido
        resultado.quadros = escritor.quadros
    except Cancelado:
        resultado.cancelado = True
    except (av.error.FFmpegError, ValueError, OSError) as exc:
        resultado.erro = str(exc)
    finally:
        if destino is not None:
            try:
                destino.close()
            except (av.error.FFmpegError, ValueError):
                pass

    if resultado.cancelado or resultado.erro:
        saida.unlink(missing_ok=True)
    if progresso is not None and not resultado.cancelado and not resultado.erro:
        progresso(1.0)
    return resultado


def _duracao_efetiva(trecho: Trecho) -> float:
    """Quanto este trecho vai render, mesmo sem `fim` declarado."""
    if trecho.duracao is not None:
        return trecho.duracao
    info = informacoes(trecho.caminho)
    return max(0.0, info["duracao"] - trecho.inicio)


def _avisar(progresso, total: float, base: float, fracao: float,
            duracao: float) -> None:
    if progresso is None or total <= 0:
        return
    progresso(min(1.0, (base + fracao * duracao) / total))


def _conferir(cancelar) -> None:
    if cancelar is not None and cancelar():
        raise Cancelado()


def _abrir_trecho(trecho: Trecho):
    """Abre o arquivo e posiciona no quadro-chave anterior ao inicio pedido."""
    container = av.open(str(trecho.caminho))
    video = container.streams.video[0] if container.streams.video else None
    audio = container.streams.audio[0] if container.streams.audio else None
    if trecho.inicio > 0 and video is not None:
        # `backward` garante cair num quadro-chave IGUAL OU ANTERIOR ao alvo.
        # Cair depois deixaria o inicio sem referencia e o video abriria com
        # blocos corrompidos ate o proximo quadro-chave.
        alvo = int(trecho.inicio / video.time_base)
        container.seek(alvo, stream=video, backward=True)
    return container, video, audio


# --------------------------------------------------------------------------
# Caminho 1: copia, sem tocar nos bits
# --------------------------------------------------------------------------

class _EscritorCopia:
    """Remultiplexa os pacotes. Instantaneo, e a qualidade e a do original.

    O preco esta no corte: um pacote de video so e decodificavel a partir do
    quadro-chave que o precede, entao o inicio real e o do quadro-chave, nao o
    que foi pedido. A diferenca vai para `Resultado.desvio_inicio`.
    """

    def __init__(self, destino) -> None:
        self.destino = destino
        self.quadros = 0
        self._video = None
        self._audio = None
        self._offset = 0.0  # onde, na saida, este proximo trecho comeca

    def _preparar(self, video, audio) -> None:
        if self._video is None and video is not None:
            self._video = self.destino.add_stream_from_template(video)
        if self._audio is None and audio is not None:
            self._audio = self.destino.add_stream_from_template(audio)

    def acrescentar(self, trecho: Trecho, duracao: float, resultado: Resultado,
                    progresso, cancelar) -> float:
        container, video, audio = _abrir_trecho(trecho)
        try:
            self._preparar(video, audio)
            fluxos = [f for f in (video, audio) if f is not None]
            inicio_real = None
            ultimo = 0.0

            for pacote in container.demux(*fluxos):
                _conferir(cancelar)
                if pacote.pts is None or pacote.dts is None:
                    continue
                ts = float(pacote.pts * pacote.time_base)

                if pacote.stream is video:
                    # Descarta tudo antes do primeiro quadro-chave util: o
                    # `seek` pode ter parado antes, e pacotes a mais no inicio
                    # apareceriam como um pedaco extra no comeco do trecho.
                    if inicio_real is None:
                        if not pacote.is_keyframe:
                            continue
                        inicio_real = ts
                        resultado.desvio_inicio.append(
                            max(0.0, trecho.inicio - inicio_real))
                    if trecho.fim is not None and ts > trecho.fim:
                        break
                    self.quadros += 1
                    destino_fluxo = self._video
                else:
                    # Audio antes do inicio do video nao tem par na imagem.
                    if inicio_real is None or ts < inicio_real:
                        continue
                    if trecho.fim is not None and ts > trecho.fim:
                        continue
                    destino_fluxo = self._audio

                if destino_fluxo is None:
                    continue
                self._mux(pacote, destino_fluxo, inicio_real)
                ultimo = max(ultimo, ts - inicio_real)
                if progresso is not None and duracao > 0:
                    progresso(min(1.0, ultimo / duracao))

            self._offset += ultimo
            return ultimo
        finally:
            container.close()

    def _mux(self, pacote, fluxo, inicio_real: float) -> None:
        """Reescreve os carimbos para a linha do tempo da saida.

        pts e dts andam juntos, deslocados pela mesma quantidade: mexer so no
        pts inverteria a relacao entre eles e quebraria a decodificacao onde ha
        quadros B.
        """
        base = fluxo.time_base or pacote.time_base
        deslocamento = self._offset - inicio_real
        passos = int(round(deslocamento / base))
        origem = pacote.time_base

        pacote.pts = int(round(pacote.pts * origem / base)) + passos
        pacote.dts = int(round(pacote.dts * origem / base)) + passos
        if pacote.duration:
            pacote.duration = int(round(pacote.duration * origem / base))
        pacote.time_base = base
        pacote.stream = fluxo
        self.destino.mux(pacote)

    def encerrar(self) -> None:
        pass  # copia nao retem nada: nao ha o que drenar


# --------------------------------------------------------------------------
# Caminho 2: recompressao
# --------------------------------------------------------------------------

class _EscritorRecompressao:
    """Decodifica e codifica de novo. Lento, exato no corte, e uniformiza.

    E o unico caminho quando os trechos nao combinam entre si, e o unico que
    corta no quadro exato — porque aqui todo quadro e recriado, entao nao
    existe a amarra do quadro-chave.
    """

    def __init__(self, destino, receita: Receita) -> None:
        self.destino = destino
        self.receita = receita
        self.quadros = 0
        self._video = None
        self._audio = None
        self._fifo = None
        self._reamostrador = None
        self._taxa_saida = 48000
        # (formato, disposicao, taxa) do ultimo quadro de entrada, para
        # perceber quando um trecho novo chega noutro formato.
        self._assinatura_audio = None
        self._largura = receita.largura
        self._altura = receita.altura
        self._offset = 0.0

    def _preparar_video(self, quadro) -> None:
        if self._video is not None:
            return
        # A primeira imagem decide as dimensoes da saida quando a receita nao
        # manda. Os trechos seguintes sao ajustados a ela, que e o que permite
        # juntar gravacoes de tamanhos diferentes num arquivo unico.
        self._largura = self._largura or quadro.width
        self._altura = self._altura or quadro.height
        fluxo = self.destino.add_stream(self.receita.codificador)
        fluxo.width = self._largura
        fluxo.height = self._altura
        fluxo.pix_fmt = "yuv420p"
        fluxo.time_base = _BASE_MS
        fluxo.codec_context.time_base = _BASE_MS
        fluxo.options = opcoes_codificador(
            self.receita.codificador, self.receita.qualidade, ao_vivo=False)
        self._video = fluxo

    def _preparar_audio(self, quadro) -> None:
        """Cria a trilha de saida e o reamostrador que alimenta o codificador.

        O `AudioResampler` do PyAV se amarra ao formato do primeiro quadro que
        recebe e **recusa** um quadro diferente depois ("Frame does not match
        AudioResampler setup"). Juntando trechos de origens diferentes isso
        acontece na primeira emenda: um vem em PCM s16 da placa, o outro em
        fltp de um MP4. Por isso a assinatura da entrada e vigiada, e o
        reamostrador refeito quando ela muda — a saida continua a mesma, que e
        o que mantem a trilha uniforme do inicio ao fim.
        """
        assinatura = (quadro.format.name, quadro.layout.name, quadro.sample_rate)
        if self._audio is None:
            # A taxa do primeiro trecho define a trilha inteira; os seguintes
            # sao reamostrados para ela.
            taxa = quadro.sample_rate or 48000
            fluxo = self.destino.add_stream("aac", rate=taxa)
            fluxo.bit_rate = 192_000
            self._audio = fluxo
            self._taxa_saida = taxa
            self._fifo = av.audio.fifo.AudioFifo()
        elif assinatura == self._assinatura_audio:
            return
        else:
            # Drena o que o reamostrador antigo ainda segurava, senao o fim de
            # cada trecho perderia alguns milissegundos na emenda.
            try:
                for resto in self._reamostrador.resample(None):
                    resto.pts = None
                    self._fifo.write(resto)
            except (av.error.FFmpegError, ValueError):
                pass

        self._assinatura_audio = assinatura
        self._reamostrador = av.AudioResampler(
            format="fltp", layout="stereo", rate=self._taxa_saida)

    def acrescentar(self, trecho: Trecho, duracao: float, resultado: Resultado,
                    progresso, cancelar) -> float:
        container, video, audio = _abrir_trecho(trecho)
        try:
            fluxos = [f for f in (video, audio) if f is not None]
            ultimo = 0.0
            for pacote in container.demux(*fluxos):
                _conferir(cancelar)
                for quadro in pacote.decode():
                    if quadro.time is None:
                        continue
                    # Aqui o corte e exato: quadros antes do inicio sao
                    # simplesmente descartados depois de decodificados.
                    if quadro.time < trecho.inicio:
                        continue
                    if trecho.fim is not None and quadro.time > trecho.fim:
                        raise _FimDoTrecho()
                    relativo = quadro.time - trecho.inicio
                    ultimo = max(ultimo, relativo)
                    if pacote.stream is video:
                        self._escrever_video(quadro, relativo)
                    else:
                        self._escrever_audio(quadro)
                    if progresso is not None and duracao > 0:
                        progresso(min(1.0, relativo / duracao))
        except _FimDoTrecho:
            pass
        finally:
            container.close()

        self._offset += ultimo
        return ultimo

    def _escrever_video(self, quadro, relativo: float) -> None:
        self._preparar_video(quadro)
        if quadro.width != self._largura or quadro.height != self._altura:
            quadro = quadro.reformat(width=self._largura, height=self._altura,
                                     format="yuv420p")
        else:
            quadro = quadro.reformat(format="yuv420p")
        quadro.pts = int(round((self._offset + relativo) * 1000))
        quadro.time_base = _BASE_MS
        self.quadros += 1
        for pacote in self._video.encode(quadro):
            self.destino.mux(pacote)

    def _escrever_audio(self, quadro) -> None:
        self._preparar_audio(quadro)
        # Sem carimbo: a FIFO entrega blocos em sequencia e o codificador
        # numera sozinho a partir da contagem de amostras. Carimbo por carimbo,
        # a emenda entre dois trechos deixaria buraco ou sobreposicao.
        for convertido in self._reamostrador.resample(quadro):
            convertido.pts = None
            self._fifo.write(convertido)
        tamanho = self._audio.codec_context.frame_size or 1024
        while (bloco := self._fifo.read(tamanho)) is not None:
            for pacote in self._audio.encode(bloco):
                self.destino.mux(pacote)

    def encerrar(self) -> None:
        # A sobra da FIFO e ate um quadro de codificador; sem esta leitura
        # parcial a trilha sai curta, o mesmo cuidado do Gravador.
        if self._fifo is not None and self._audio is not None:
            try:
                resto = self._fifo.read(partial=True)
                if resto is not None:
                    for pacote in self._audio.encode(resto):
                        self.destino.mux(pacote)
            except (av.error.FFmpegError, ValueError):
                pass
        for fluxo in (self._video, self._audio):
            if fluxo is None:
                continue
            try:
                for pacote in fluxo.encode(None):
                    self.destino.mux(pacote)
            except (av.error.FFmpegError, ValueError):
                pass


class _FimDoTrecho(Exception):
    """Sai dos dois lacos aninhados quando o trecho acabou."""


# --------------------------------------------------------------------------
# Atalhos: as tres operacoes, em nome proprio
# --------------------------------------------------------------------------

def converter(entrada: Path, saida: Path, codificador: str = "libx264",
              qualidade: int = 23, progresso=None, cancelar=None) -> Resultado:
    """Reescreve um arquivo inteiro noutro formato/codec."""
    return montar([Trecho(entrada)], saida,
                  Receita(MODO_RECOMPRIMIR, codificador, qualidade),
                  progresso, cancelar)


def cortar(entrada: Path, saida: Path, inicio: float, fim: float | None,
           recomprimir: bool = False, codificador: str = "libx264",
           qualidade: int = 23, progresso=None, cancelar=None) -> Resultado:
    """Guarda so o trecho entre `inicio` e `fim`, descartando as pontas."""
    receita = Receita(MODO_RECOMPRIMIR if recomprimir else MODO_COPIA,
                      codificador, qualidade)
    return montar([Trecho(entrada, inicio, fim)], saida, receita,
                  progresso, cancelar)


def juntar(trechos: list[Trecho], saida: Path, recomprimir: bool = False,
           codificador: str = "libx264", qualidade: int = 23,
           progresso=None, cancelar=None) -> Resultado:
    """Emenda varios trechos num arquivo so, na ordem dada."""
    receita = Receita(MODO_RECOMPRIMIR if recomprimir else MODO_COPIA,
                      codificador, qualidade)
    return montar(trechos, saida, receita, progresso, cancelar)
