"""Interface grafica.

Organizacao pensada para o layout ser facil de mexer depois:

* Toda cor e medida vem de `tema.py`. Nada de valores soltos aqui.
* O painel lateral e montado a partir da lista `_CARTOES`, onde cada item e o
  nome de um metodo que devolve o conteudo do cartao. Reordenar a lista
  reordena a interface; remover um item remove o cartao.
* Trabalho demorado (enumerar, parear, testar) roda em QThread e volta por
  sinal — a janela nunca congela.
"""

from __future__ import annotations

import time
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from PySide6.QtCore import Qt, QSettings, QThread, QTimer, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
)
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import dispositivos as disp
from . import tema
from .captura import (
    AUDIO_ATIVO,
    AUDIO_DESLIGADO,
    AUDIO_ESPERANDO,
    AUDIO_FALHOU,
    AUDIO_MUDO,
    CANAIS_MONITOR,
    PERFIL_H264,
    PERFIL_ORIGINAL,
    TAXA_MONITOR,
    VEREDITO_ERRO,
    VEREDITO_FLUIDO,
    VEREDITO_INSUFICIENTE,
    Configuracao,
    MotorCaptura,
    medir_modo,
    resumir_gravacao,
)

SEGUNDOS_AMOSTRA = 10
# O QCheckBox nao elide nem quebra o proprio rotulo: a largura minima dele e o
# texto inteiro. Por isso os rotulos de caixa de selecao aqui sao curtos, com a
# explicacao numa etiqueta separada que quebra linha. Sem esse cuidado o painel
# estoura em telas com escala 125% ou fonte grande.
LARGURA_PAINEL = 360

CODIFICADORES = [
    ("h264_nvenc", "NVIDIA NVENC (GPU)"),
    ("h264_qsv", "Intel Quick Sync (GPU)"),
    ("h264_amf", "AMD AMF (GPU)"),
    ("libx264", "libx264 (CPU)"),
]

# Selo do cabecalho para cada estado de audio, com a explicacao no tooltip.
# `AUDIO_ATIVO` nao aparece aqui de proposito: o normal nao merece selo.
_SELO_AUDIO = {
    AUDIO_DESLIGADO: (
        "SEM ÁUDIO",
        "Nenhuma entrada de áudio escolhida — o que for gravado sai mudo.\n"
        "Escolha uma entrada no cartão Fonte.",
    ),
    AUDIO_FALHOU: (
        "ÁUDIO FALHOU",
        "A entrada de áudio não abriu ou parou no meio da captura.\n"
        "O vídeo continua, mas a gravação sai muda.",
    ),
    AUDIO_ESPERANDO: (
        "ÁUDIO SEM SINAL",
        "A entrada de áudio abriu mas nenhum bloco chegou ainda.\n"
        "Confira o cabo e se a fonte está mesmo emitindo som.",
    ),
    AUDIO_MUDO: (
        "ÁUDIO EM SILÊNCIO",
        "A entrada está funcionando, mas só chega silêncio.\n"
        "Gravando o áudio do computador: confira se algo está mesmo tocando e "
        "se o volume do sistema não está no mudo.",
    ),
}

# Quanto esperar antes de acusar silencio na entrada. O primeiro bloco leva um
# instante para chegar; acusar na hora faria o selo piscar em toda captura.
SEGUNDOS_ESPERA_AUDIO = 3.0

# Marcador visual do veredito do teste, na frente do nome do modo.
_SINAL = {
    VEREDITO_FLUIDO: "●",
    "apertado": "●",
    VEREDITO_INSUFICIENTE: "●",
    VEREDITO_ERRO: "✕",
}


def codificadores_disponiveis() -> list[tuple[str, str]]:
    """Lista apenas os codificadores que abrem de verdade nesta maquina.

    Nao basta o codificador estar compilado no FFmpeg: uma GPU antiga ou um
    driver desatualizado fazem o `open()` falhar. Testar aqui e a diferenca
    entre oferecer uma opcao que funciona e uma que so quebra na hora de gravar.
    """
    achados = []
    for nome, rotulo in CODIFICADORES:
        try:
            contexto = av.codec.CodecContext.create(nome, "w")
            contexto.width, contexto.height = 640, 480
            contexto.pix_fmt = "yuv420p"
            contexto.time_base = Fraction(1, 30)
            contexto.open()
            contexto.close()
        except Exception:
            continue
        achados.append((nome, rotulo))
    return achados or [("libx264", "libx264 (CPU)")]


def _bytes_legivel(quantidade: float) -> str:
    for unidade in ("B", "KB", "MB", "GB"):
        if quantidade < 1024 or unidade == "GB":
            return f"{quantidade:.1f} {unidade}"
        quantidade /= 1024
    return f"{quantidade:.1f} GB"


def _duracao_legivel(segundos: float) -> str:
    total = int(segundos)
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def _parece_captura(nome: str) -> bool:
    minusculo = nome.lower()
    return any(p in minusculo for p in
               ("digital", "usb video", "capture", "captura", "hdmi", "hd cam"))


# --------------------------------------------------------------------------
# Widgets de apoio
# --------------------------------------------------------------------------

class TelaVideo(QWidget):
    """Desenha o quadro mantendo a proporcao, com barras nas sobras."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._buffer: np.ndarray | None = None
        self._imagem: QImage | None = None
        self._mensagem = "Escolha a placa e clique em Iniciar"

    def definir_quadro(self, quadro: np.ndarray) -> None:
        # O QImage nao copia os bytes: o array precisa continuar vivo enquanto
        # a imagem existir, por isso ele fica guardado no atributo.
        self._buffer = np.ascontiguousarray(quadro)
        altura, largura, _ = self._buffer.shape
        self._imagem = QImage(self._buffer.data, largura, altura,
                              3 * largura, QImage.Format_RGB888)
        self.update()

    def limpar(self, mensagem: str = "Parado") -> None:
        self._buffer = None
        self._imagem = None
        self._mensagem = mensagem
        self.update()

    def paintEvent(self, evento) -> None:  # noqa: N802
        pintor = QPainter(self)
        pintor.fillRect(self.rect(), QColor(tema.LONA_VIDEO))

        if self._imagem is None:
            pintor.setPen(QPen(QColor("#79808d")))
            fonte = QFont()
            fonte.setPointSize(11)
            pintor.setFont(fonte)
            pintor.drawText(self.rect(), Qt.AlignCenter, self._mensagem)
            return

        proporcao = self._imagem.width() / self._imagem.height()
        largura = self.width()
        altura = int(largura / proporcao)
        if altura > self.height():
            altura = self.height()
            largura = int(altura * proporcao)

        pintor.setRenderHint(QPainter.SmoothPixmapTransform, True)
        pintor.drawImage(
            (self.width() - largura) // 2, (self.height() - altura) // 2,
            self._imagem.scaled(largura, altura, Qt.IgnoreAspectRatio,
                                Qt.SmoothTransformation),
        )


class MedidorAudio(QWidget):
    """Barra de nivel com zona alta destacada."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(6)
        self.setMinimumWidth(100)
        self._nivel = 0.0
        self._fichas = tema.fichas(tema.AUTO)

    def definir_fichas(self, fichas: dict[str, str]) -> None:
        self._fichas = fichas
        self.update()

    def definir_nivel(self, nivel: float) -> None:
        novo = max(0.0, min(1.0, nivel))
        if abs(novo - self._nivel) > 0.01:
            self._nivel = novo
            self.update()

    def paintEvent(self, evento) -> None:  # noqa: N802
        pintor = QPainter(self)
        pintor.setPen(Qt.NoPen)
        pintor.setBrush(QColor(self._fichas["borda"]))
        pintor.drawRoundedRect(self.rect(), 3, 3)
        if self._nivel <= 0:
            return
        cor = self._fichas["sucesso"] if self._nivel < 0.85 else self._fichas["perigo"]
        pintor.setBrush(QColor(cor))
        largura = max(6, int(self.width() * self._nivel))
        pintor.drawRoundedRect(0, 0, largura, self.height(), 3, 3)


class Cartao(QFrame):
    """Bloco titulado do painel lateral."""

    def __init__(self, titulo: str, corpo: QWidget) -> None:
        super().__init__()
        self.setObjectName("cartao")
        coluna = QVBoxLayout(self)
        margem = tema.METRICA["margem"]
        coluna.setContentsMargins(margem, margem - 2, margem, margem)
        coluna.setSpacing(tema.METRICA["espaco"])

        rotulo = QLabel(titulo.upper())
        rotulo.setObjectName("tituloCartao")
        coluna.addWidget(rotulo)
        coluna.addWidget(corpo)


def _combo() -> QComboBox:
    """QComboBox que aceita ser mais estreito que o seu conteudo.

    Por padrao o QComboBox exige a largura do item mais longo, e nomes de
    dispositivo sao compridos ("Interface de áudio digital (2- USB Digital
    Audio)"). Num painel de largura fixa isso empurra o conteudo para fora e
    ele acaba cortado. Aqui a caixa encolhe e elide o texto; a lista suspensa
    continua mostrando o nome inteiro.
    """
    combo = QComboBox()
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(8)
    combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    return combo


class RotuloElidido(QLabel):
    """Mostra texto longo cortado no meio, com o valor inteiro no tooltip.

    Caminhos de pasta nao tem espacos, entao `wordWrap` nao ajuda: o QLabel
    passa a exigir a largura da maior 'palavra' e empurra o painel inteiro para
    fora da janela. Elidir resolve mantendo o inicio e o fim visiveis, que e o
    que identifica um caminho.
    """

    def __init__(self, texto: str = "") -> None:
        super().__init__(texto)
        self._completo = texto
        self.setMinimumWidth(1)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def definir_texto(self, texto: str) -> None:
        self._completo = texto
        self.setToolTip(texto)
        self._reelidir()

    def _reelidir(self) -> None:
        largura = max(1, self.width() - 2)
        super().setText(self.fontMetrics().elidedText(
            self._completo, Qt.ElideMiddle, largura))

    def resizeEvent(self, evento) -> None:  # noqa: N802
        super().resizeEvent(evento)
        self._reelidir()


def _campo(rotulo: str, widget: QWidget) -> QWidget:
    """Rotulo em cima, controle embaixo — ocupa menos largura que lado a lado."""
    caixa = QWidget()
    coluna = QVBoxLayout(caixa)
    coluna.setContentsMargins(0, 0, 0, 0)
    coluna.setSpacing(3)
    texto = QLabel(rotulo)
    texto.setObjectName("rotuloCampo")
    coluna.addWidget(texto)
    coluna.addWidget(widget)
    return caixa


# --------------------------------------------------------------------------
# Trabalho em segundo plano
# --------------------------------------------------------------------------

class TrabalhoEnumeracao(QThread):
    """Lista dispositivos e, em seguida, descobre os pares video/audio."""

    listou = Signal(object)
    pareou = Signal(object)

    def run(self) -> None:
        try:
            resultado = disp.listar()
        except Exception as exc:
            resultado = disp.Dispositivos(aviso=f"Falha ao listar dispositivos:\n{exc}")
            self.listou.emit(resultado)
            return

        self.listou.emit(resultado)
        # O pareamento e lento no Windows (consulta ao PowerShell). Sai depois,
        # para a lista aparecer imediatamente.
        if disp.parear(resultado):
            self.pareou.emit(resultado)


class TrabalhoTeste(QThread):
    """Mede cada modo contra o hardware e contra a capacidade desta maquina."""

    progresso = Signal(int, int, str)
    concluiu = Signal(object)

    def __init__(self, dispositivo, modos: list, segundos: float,
                 largura_preview: int) -> None:
        super().__init__()
        self._dispositivo = dispositivo
        self._modos = modos
        self._segundos = segundos
        self._largura = largura_preview
        self._cancelar = False

    def cancelar(self) -> None:
        self._cancelar = True

    def run(self) -> None:
        medicoes: dict = {}
        total = len(self._modos)
        for indice, modo in enumerate(self._modos):
            if self._cancelar:
                break
            self.progresso.emit(indice, total, modo.rotulo)
            if indice:
                # A placa leva um instante para ser liberada; reabrir na hora
                # devolve "I/O error" de vez em quando.
                self.msleep(500)
            m = medir_modo(self._dispositivo, modo, self._segundos,
                           decodificar=True, largura_preview=self._largura)
            if m.erro:
                self.msleep(1000)
                m = medir_modo(self._dispositivo, modo, self._segundos,
                               decodificar=True, largura_preview=self._largura)
            medicoes[modo] = m
        self.concluiu.emit(medicoes)


# --------------------------------------------------------------------------
# Janela principal
# --------------------------------------------------------------------------

class JanelaPrincipal(QMainWindow):

    # Ordem dos cartoes no painel. Reordenar aqui reordena a interface.
    _CARTOES = [
        ("Fonte", "_cartao_fonte"),
        ("Gravação", "_cartao_gravacao"),
        ("Monitoração", "_cartao_audio"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Captura USB")
        self.resize(1360, 800)

        self.config = QSettings("capturador", "CapturaUSB")
        self._modo_tema = self.config.value("tema", tema.AUTO)

        self.motor = MotorCaptura(self)
        self.motor.erro.connect(self._erro)
        self.motor.aviso.connect(self._aviso)
        self.motor.gravacao_alterada.connect(self._gravacao_alterada)

        self._serie_quadro = -1
        self._saida_audio: QAudioSink | None = None
        self._canal_audio = None
        self._dispositivos = disp.Dispositivos()
        self._medicoes: dict = {}
        self._trabalho: QThread | None = None
        self._amostra_ate = 0.0
        self._inicio_captura = 0.0
        self._audio_tocado_pelo_usuario = False
        self._pasta = Path(self.config.value("pasta", str(disp.pasta_videos_padrao())))

        self._montar()
        self._aplicar_tema()
        self._atalhos()

        self._timer_video = QTimer(self); self._timer_video.timeout.connect(self._tick_video)
        self._timer_audio = QTimer(self); self._timer_audio.timeout.connect(self._tick_audio)
        self._timer_estado = QTimer(self); self._timer_estado.timeout.connect(self._tick_estado)
        self._timer_video.start(8)
        self._timer_audio.start(10)
        self._timer_estado.start(300)

        QTimer.singleShot(0, self.procurar_dispositivos)

    # -- construcao --------------------------------------------------------

    def _montar(self) -> None:
        central = QWidget()
        raiz = QVBoxLayout(central)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        raiz.addWidget(self._cabecalho())

        corpo = QHBoxLayout()
        corpo.setContentsMargins(0, 0, 0, 0)
        corpo.setSpacing(0)
        self.tela = TelaVideo()
        corpo.addWidget(self.tela, stretch=1)
        corpo.addWidget(self._painel())
        raiz.addLayout(corpo, stretch=1)

        self.setCentralWidget(central)
        self._barra_estado()
        # Deixa os controles no estado coerente com "parado" antes do primeiro
        # ciclo — inclui desabilitar a escolha de áudio quando ela está vinculada.
        self._travar(False)

    def _cabecalho(self) -> QWidget:
        barra = QFrame()
        barra.setObjectName("cabecalho")
        barra.setFixedHeight(48)
        linha = QHBoxLayout(barra)
        linha.setContentsMargins(16, 0, 12, 0)
        linha.setSpacing(8)

        marca = QLabel("Captura USB")
        marca.setObjectName("marca")
        linha.addWidget(marca)

        self.rotulo_fonte = QLabel("")
        self.rotulo_fonte.setObjectName("dica")
        linha.addWidget(self.rotulo_fonte)

        self.selo_audio = QLabel("")
        self.selo_audio.setObjectName("seloAviso")
        self.selo_audio.hide()
        linha.addWidget(self.selo_audio)
        linha.addStretch(1)

        self._grupo_tema = QButtonGroup(self)
        self._grupo_tema.setExclusive(True)
        for modo, texto, dica in (
            (tema.AUTO, "Auto", "Segue o tema do sistema"),
            (tema.CLARO_, "Claro", "Sempre claro"),
            (tema.ESCURO_, "Escuro", "Sempre escuro"),
        ):
            botao = QPushButton(texto)
            botao.setObjectName("discreto")
            botao.setCheckable(True)
            botao.setToolTip(dica)
            botao.setChecked(modo == self._modo_tema)
            botao.clicked.connect(lambda _=False, m=modo: self._trocar_tema(m))
            self._grupo_tema.addButton(botao)
            linha.addWidget(botao)

        return barra

    def _painel(self) -> QWidget:
        interno = QWidget()
        coluna = QVBoxLayout(interno)
        margem = tema.METRICA["margem"]
        coluna.setContentsMargins(margem, margem, margem, margem)
        coluna.setSpacing(tema.METRICA["espaco"])

        for titulo, metodo in self._CARTOES:
            coluna.addWidget(Cartao(titulo, getattr(self, metodo)()))

        coluna.addWidget(self._acoes())
        coluna.addStretch(1)

        rolagem = QScrollArea()
        rolagem.setWidget(interno)
        rolagem.setWidgetResizable(True)
        rolagem.setFixedWidth(LARGURA_PAINEL)
        # Rede de seguranca: se alguma fonte ou escala inesperada empurrar o
        # conteudo para alem do painel, aparece a barra em vez de o controle
        # sumir cortado sem aviso.
        rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        return rolagem

    # -- cartoes -----------------------------------------------------------

    def _cartao_fonte(self) -> QWidget:
        caixa = QWidget()
        coluna = QVBoxLayout(caixa)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(tema.METRICA["espaco"])

        self.combo_tipo = _combo()
        self.combo_tipo.addItem("Placa de captura", disp.TIPO_PLACA)
        self.combo_tipo.addItem("Ecrã (desktop)", disp.TIPO_TELA)
        self.combo_tipo.addItem("Janela específica", disp.TIPO_JANELA)
        self.combo_tipo.setCurrentIndex(
            max(0, self.combo_tipo.findData(
                self.config.value("tipo_fonte", disp.TIPO_PLACA))))
        self.combo_tipo.currentIndexChanged.connect(self._tipo_mudou)
        coluna.addWidget(_campo("Tipo de fonte", self.combo_tipo))

        self.combo_video = _combo()
        self.combo_video.currentIndexChanged.connect(self._video_mudou)
        self.campo_video = _campo("Fonte", self.combo_video)
        coluna.addWidget(self.campo_video)

        self.check_cursor = QCheckBox("Mostrar o cursor")
        self.check_cursor.setChecked(self.config.value("cursor", True, type=bool))
        self.check_cursor.toggled.connect(
            lambda v: self.config.setValue("cursor", v))
        self.check_cursor.hide()
        coluna.addWidget(self.check_cursor)

        self.combo_modo = _combo()
        self.combo_modo.currentIndexChanged.connect(self._modo_mudou)
        coluna.addWidget(_campo("Qualidade", self.combo_modo))

        self.rotulo_modo = QLabel("Clique em Testar para medir o que esta máquina aguenta.")
        self.rotulo_modo.setObjectName("dica")
        self.rotulo_modo.setWordWrap(True)
        coluna.addWidget(self.rotulo_modo)

        # Empilhados, e nao lado a lado: num painel estreito dois botoes com
        # texto longo somam mais que a largura disponivel e o cartao vaza.
        self.botao_testar = QPushButton("Testar equipamento")
        self.botao_testar.setToolTip(
            "Abre cada modo por alguns segundos e mede a taxa real e o custo de CPU.\n"
            "A prévia é interrompida durante o teste."
        )
        self.botao_testar.clicked.connect(self._testar_equipamento)
        coluna.addWidget(self.botao_testar)

        self.botao_procurar = QPushButton("Procurar dispositivos")
        self.botao_procurar.setObjectName("discreto")
        self.botao_procurar.clicked.connect(self.procurar_dispositivos)
        coluna.addWidget(self.botao_procurar)

        self.barra_teste = QProgressBar()
        self.barra_teste.setTextVisible(False)
        self.barra_teste.hide()
        coluna.addWidget(self.barra_teste)

        self.check_vincular = QCheckBox("Áudio da placa")
        self.check_vincular.setChecked(
            self.config.value("vincular_audio", True, type=bool))
        self.check_vincular.toggled.connect(self._vincular_mudou)
        coluna.addWidget(self.check_vincular)

        self.campo_audio_dica = QLabel("Usa a entrada de áudio do mesmo aparelho. "
                                       "Desmarque para escolher outra fonte.")
        self.campo_audio_dica.setObjectName("dica")
        self.campo_audio_dica.setWordWrap(True)
        coluna.addWidget(self.campo_audio_dica)

        # So aparece quando a maquina nao tem como capturar a saida de audio.
        # Sem ele o usuario ve a opcao desabilitada e nao tem para onde ir.
        self.botao_dica_loopback = QPushButton("Como habilitar o áudio do computador")
        self.botao_dica_loopback.setObjectName("discreto")
        self.botao_dica_loopback.clicked.connect(self._explicar_loopback)
        self.botao_dica_loopback.hide()
        coluna.addWidget(self.botao_dica_loopback)

        self.combo_audio = _combo()
        self.combo_audio.currentIndexChanged.connect(self._audio_mudou)
        coluna.addWidget(_campo("Entrada de áudio", self.combo_audio))

        self.combo_taxa = _combo()
        coluna.addWidget(_campo("Taxa de amostragem", self.combo_taxa))
        return caixa

    def _cartao_gravacao(self) -> QWidget:
        caixa = QWidget()
        coluna = QVBoxLayout(caixa)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(tema.METRICA["espaco"])

        self.combo_perfil = _combo()
        self.combo_perfil.addItem("Original — sem recompressão (.mkv)", PERFIL_ORIGINAL)
        self.combo_perfil.addItem("H.264 — arquivo compacto (.mp4)", PERFIL_H264)
        self.combo_perfil.setCurrentIndex(
            1 if self.config.value("perfil", PERFIL_ORIGINAL) == PERFIL_H264 else 0)
        self.combo_perfil.currentIndexChanged.connect(self._perfil_mudou)
        coluna.addWidget(_campo("Perfil", self.combo_perfil))

        self.combo_codificador = _combo()
        for nome, rotulo in codificadores_disponiveis():
            self.combo_codificador.addItem(rotulo, nome)
        coluna.addWidget(_campo("Codificador", self.combo_codificador))

        self.spin_qualidade = QSpinBox()
        self.spin_qualidade.setRange(0, 51)
        self.spin_qualidade.setValue(int(self.config.value("qualidade", 20)))
        self.spin_qualidade.setToolTip("Menor = melhor imagem e arquivo maior. 18 é quase transparente.")
        coluna.addWidget(_campo("Fator de qualidade", self.spin_qualidade))

        self.check_perguntar = QCheckBox("Escolher ao gravar")
        self.check_perguntar.setChecked(
            self.config.value("perguntar_destino", True, type=bool))
        self.check_perguntar.toggled.connect(
            lambda v: self.config.setValue("perguntar_destino", v))
        coluna.addWidget(self.check_perguntar)

        dica = QLabel("Marcado, abre a caixa de salvar a cada gravação. "
                      "Desmarcado, salva direto na pasta abaixo com nome "
                      "de data e hora.")
        dica.setObjectName("dica")
        dica.setWordWrap(True)
        coluna.addWidget(dica)

        self.check_avisar_audio = QCheckBox("Avisar se faltar áudio")
        self.check_avisar_audio.setChecked(
            self.config.value("avisar_sem_audio", True, type=bool))
        self.check_avisar_audio.setToolTip(
            "Pergunta antes de começar uma gravação que sairia muda.")
        self.check_avisar_audio.toggled.connect(
            lambda v: self.config.setValue("avisar_sem_audio", v))
        coluna.addWidget(self.check_avisar_audio)

        self.rotulo_pasta = RotuloElidido()
        self.rotulo_pasta.setObjectName("dica")
        coluna.addWidget(_campo("Pasta padrão", self.rotulo_pasta))

        botao_pasta = QPushButton("Alterar pasta")
        botao_pasta.setObjectName("discreto")
        botao_pasta.clicked.connect(self._escolher_pasta)
        coluna.addWidget(botao_pasta)

        self._perfil_mudou()
        self._mostrar_pasta()
        return caixa

    def _cartao_audio(self) -> QWidget:
        caixa = QWidget()
        coluna = QVBoxLayout(caixa)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(tema.METRICA["espaco"])

        self.check_monitor = QCheckBox("Ouvir o áudio")
        self.check_monitor.setChecked(self.config.value("monitorar", True, type=bool))
        self.check_monitor.toggled.connect(self._monitor_mudou)
        coluna.addWidget(self.check_monitor)

        linha = QHBoxLayout()
        linha.setSpacing(8)
        linha.addWidget(QLabel("Volume"))
        self.slider_volume = QSlider(Qt.Horizontal)
        self.slider_volume.setRange(0, 100)
        self.slider_volume.setValue(int(self.config.value("volume", 80)))
        self.slider_volume.valueChanged.connect(self._volume_mudou)
        linha.addWidget(self.slider_volume, stretch=1)
        coluna.addLayout(linha)

        self.medidor = MedidorAudio()
        coluna.addWidget(self.medidor)
        return caixa

    def _acoes(self) -> QWidget:
        caixa = QWidget()
        grade = QGridLayout(caixa)
        grade.setContentsMargins(0, 4, 0, 0)
        grade.setSpacing(6)

        self.botao_iniciar = QPushButton("Iniciar")
        self.botao_iniciar.setObjectName("primario")
        self.botao_iniciar.setMinimumHeight(40)
        self.botao_iniciar.clicked.connect(self._alternar_captura)
        grade.addWidget(self.botao_iniciar, 0, 0, 1, 2)

        self.botao_gravar = QPushButton("Gravar")
        self.botao_gravar.setMinimumHeight(38)
        self.botao_gravar.setEnabled(False)
        self.botao_gravar.clicked.connect(self._alternar_gravacao)
        grade.addWidget(self.botao_gravar, 1, 0, 1, 2)

        self.botao_amostra = QPushButton(f"Gravar amostra ({SEGUNDOS_AMOSTRA}s)")
        self.botao_amostra.setEnabled(False)
        self.botao_amostra.setToolTip(
            "Grava um trecho curto e mostra um relatório do que ficou no arquivo.")
        self.botao_amostra.clicked.connect(self._gravar_amostra)
        grade.addWidget(self.botao_amostra, 2, 0, 1, 2)

        self.botao_foto = QPushButton("Foto")
        self.botao_foto.setEnabled(False)
        self.botao_foto.clicked.connect(self._tirar_foto)
        grade.addWidget(self.botao_foto, 3, 0)

        botao_tela = QPushButton("Tela cheia")
        botao_tela.clicked.connect(self._alternar_tela_cheia)
        grade.addWidget(botao_tela, 3, 1)
        return caixa

    @staticmethod
    def _embrulhar(layout) -> QWidget:
        caixa = QWidget()
        caixa.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        return caixa

    def _barra_estado(self) -> None:
        barra = self.statusBar()
        self.est_resolucao = QLabel("—")
        self.est_taxa = QLabel("")
        self.est_gravacao = QLabel("")
        barra.addWidget(self.est_resolucao)
        barra.addWidget(self.est_taxa)
        barra.addPermanentWidget(self.est_gravacao)

    def _atalhos(self) -> None:
        for chave, alvo in (
            (QKeySequence(Qt.Key_F11), self._alternar_tela_cheia),
            (QKeySequence(Qt.Key_F12), self._tirar_foto),
            (QKeySequence(Qt.Key_Escape), self._sair_tela_cheia),
            (QKeySequence("Ctrl+R"), self._alternar_gravacao),
            (QKeySequence("Ctrl+T"), self._testar_equipamento),
        ):
            acao = QAction(self)
            acao.setShortcut(chave)
            acao.triggered.connect(alvo)
            self.addAction(acao)

    # -- tema --------------------------------------------------------------

    def _trocar_tema(self, modo: str) -> None:
        self._modo_tema = modo
        self.config.setValue("tema", modo)
        self._aplicar_tema()

    def _aplicar_tema(self) -> None:
        from PySide6.QtWidgets import QApplication

        tema.aplicar(QApplication.instance(), self._modo_tema)
        self.medidor.definir_fichas(tema.fichas(self._modo_tema))
        self._pintar_modos()

    # -- dispositivos ------------------------------------------------------

    @Slot()
    def procurar_dispositivos(self) -> None:
        if self._trabalho is not None and self._trabalho.isRunning():
            return
        self.botao_procurar.setEnabled(False)
        self.botao_procurar.setText("…")
        self.rotulo_fonte.setText("procurando dispositivos…")

        trabalho = TrabalhoEnumeracao(self)
        trabalho.listou.connect(self._recebeu_dispositivos)
        trabalho.pareou.connect(self._recebeu_pares)
        trabalho.finished.connect(lambda: (
            self.botao_procurar.setEnabled(True),
            self.botao_procurar.setText("Procurar"),
        ))
        self._trabalho = trabalho
        trabalho.start()

    @Slot(object)
    def _recebeu_dispositivos(self, resultado) -> None:
        self._dispositivos = resultado
        self._medicoes.clear()
        # Antes de `_preencher_fontes`, que ja monta a lista de audio e precisa
        # saber que nenhuma escolha do usuario sobreviveu a esta enumeracao.
        self._audio_tocado_pelo_usuario = False
        self._preencher_fontes()
        self._video_mudou()

        if resultado.aviso:
            self._aviso(resultado.aviso)
        elif not resultado.video:
            self.rotulo_fonte.setText("nenhuma placa encontrada")
            self._aviso(
                "Nenhuma placa de captura encontrada.\n\n"
                "Verifique se ela está conectada e se nenhum outro programa "
                "(VLC, OBS, navegador) está usando ela."
            )
        else:
            self.rotulo_fonte.setText(f"{len(resultado.video)} placa(s)")

    @Slot(object)
    def _recebeu_pares(self, resultado) -> None:
        """O pareamento chega depois da lista; so age se o usuario nao mexeu.

        O vínculo é entre placa de vídeo e placa de áudio: aplicá-lo com a fonte
        em tela trocaria o áudio do computador — já escolhido — pela entrada de
        uma placa que nem está sendo gravada.
        """
        self._dispositivos = resultado
        if (self.combo_tipo.currentData() == disp.TIPO_PLACA
                and self.check_vincular.isChecked()
                and not self._audio_tocado_pelo_usuario):
            self._selecionar_audio_vinculado()

    def _fontes_do_tipo(self) -> list:
        tipo = self.combo_tipo.currentData()
        if tipo == disp.TIPO_TELA:
            return disp.listar_telas()
        if tipo == disp.TIPO_JANELA:
            return disp.listar_janelas()
        return list(self._dispositivos.video)

    def _preencher_fontes(self) -> None:
        tipo = self.combo_tipo.currentData()
        fontes = self._fontes_do_tipo()

        self.combo_video.blockSignals(True)
        self.combo_video.clear()
        for fonte in fontes:
            self.combo_video.addItem(fonte.nome, fonte)
        self.combo_video.blockSignals(False)

        de_tela = tipo != disp.TIPO_PLACA
        self.check_cursor.setVisible(de_tela)
        # Testar equipamento percorre modos de hardware; para tela o que
        # limita e a maquina, e isso o proprio contador de fps ja mostra.
        self.botao_testar.setVisible(not de_tela)
        self.check_vincular.setVisible(not de_tela)
        self._preencher_audio()

        if de_tela and not fontes:
            self.rotulo_modo.setText(
                "Nenhuma janela encontrada."
                if tipo == disp.TIPO_JANELA else
                "Não foi possível enumerar os ecrãs neste sistema."
            )

        self._ajustar_perfil_para_fonte()
        self._video_mudou()

    def _ajustar_perfil_para_fonte(self) -> None:
        """Copia sem recompressao so faz sentido vindo de uma placa.

        Tela e janela chegam como quadros crus — 1080p60 em BGRA sao ~500 MB/s.
        Gravar isso "sem perda" encheria o disco em segundos, entao o perfil
        Original fica indisponivel e o H.264 vira o padrao.
        """
        fonte = self.combo_video.currentData()
        permite = fonte is None or fonte.permite_copia
        indice_original = self.combo_perfil.findData(PERFIL_ORIGINAL)

        item = self.combo_perfil.model().item(indice_original)
        if item is not None:
            item.setEnabled(permite)
        self.combo_perfil.setItemData(
            indice_original,
            "Disponível apenas para placas de captura: a tela chega sem "
            "compressão e copiá-la geraria centenas de MB por segundo."
            if not permite else "",
            Qt.ToolTipRole,
        )
        if not permite and self.combo_perfil.currentData() == PERFIL_ORIGINAL:
            self.combo_perfil.setCurrentIndex(self.combo_perfil.findData(PERFIL_H264))

    @Slot()
    def _tipo_mudou(self) -> None:
        self.config.setValue("tipo_fonte", self.combo_tipo.currentData())
        self._medicoes.clear()
        # Trocar de placa para tela (ou o contrário) muda qual entrada de áudio
        # é a certa, então a escolha anterior deixa de valer como escolha.
        self._audio_tocado_pelo_usuario = False
        self._preencher_fontes()

    @Slot()
    def _video_mudou(self) -> None:
        dispositivo = self.combo_video.currentData()
        self.combo_modo.blockSignals(True)
        self.combo_modo.clear()
        if dispositivo is not None:
            melhor = dispositivo.melhor_modo()
            for indice, modo in enumerate(dispositivo.modos):
                self.combo_modo.addItem(modo.rotulo, modo)
                if modo == melhor:
                    self.combo_modo.setCurrentIndex(indice)
        self.combo_modo.blockSignals(False)
        self._pintar_modos()
        self._modo_mudou()
        self._ajustar_perfil_para_fonte()

        if (self.combo_tipo.currentData() == disp.TIPO_PLACA
                and self.check_vincular.isChecked()
                and not self._audio_tocado_pelo_usuario):
            self._selecionar_audio_vinculado()

    def _preencher_audio(self) -> None:
        """Monta a lista de entradas de áudio para o tipo de fonte atual.

        A ordem muda com o tipo, porque a resposta certa muda com ele. Gravando
        a tela, a fonte natural é o que sai pelas caixas e ela vem primeiro;
        gravando uma placa, essa mesma fonte é justamente a errada — ela
        continua na lista, mas no fim.
        """
        de_tela = self.combo_tipo.currentData() != disp.TIPO_PLACA
        entradas = [d for d in self._dispositivos.audio if not d.loopback]
        monitores = [d for d in self._dispositivos.audio if d.loopback]
        anterior = self.combo_audio.currentData()

        self.combo_audio.blockSignals(True)
        self.combo_audio.clear()
        self.combo_audio.addItem("Sem áudio", None)

        if de_tela and not monitores:
            # Item desabilitado em vez de item ausente: sem ele o usuário
            # conclui que o programa não sabe gravar o som do PC, quando o que
            # falta é um dispositivo no sistema. O botão de dica diz qual.
            self.combo_audio.addItem("Áudio do computador (indisponível)", None)
            indice = self.combo_audio.count() - 1
            item = self.combo_audio.model().item(indice)
            if item is not None:
                item.setEnabled(False)
            self.combo_audio.setItemData(indice, disp.dica_loopback(), Qt.ToolTipRole)

        for dispositivo in (monitores + entradas if de_tela else entradas + monitores):
            rotulo = (f"Áudio do computador — {dispositivo.nome}"
                      if dispositivo.loopback else dispositivo.nome)
            self.combo_audio.addItem(rotulo, dispositivo)
        self.combo_audio.blockSignals(False)

        self._explicar_fonte_audio(de_tela, bool(monitores))
        self._aplicar_audio_padrao(anterior)

    def _explicar_fonte_audio(self, de_tela: bool, tem_loopback: bool) -> None:
        if not de_tela:
            self.campo_audio_dica.setText(
                "Usa a entrada de áudio do mesmo aparelho. "
                "Desmarque para escolher outra fonte.")
            self.campo_audio_dica.setToolTip("")
            self.botao_dica_loopback.hide()
            return

        if tem_loopback:
            self.campo_audio_dica.setText(
                "«Áudio do computador» grava o que sai pelas caixas. "
                "Microfones e entradas de linha continuam na lista.")
            self.campo_audio_dica.setToolTip("")
            self.botao_dica_loopback.hide()
        else:
            self.campo_audio_dica.setText(
                "Esta máquina ainda não consegue gravar o som do computador: "
                "falta um dispositivo que capture a saída de áudio.")
            self.campo_audio_dica.setToolTip(disp.dica_loopback())
            self.botao_dica_loopback.show()

    @Slot()
    def _explicar_loopback(self) -> None:
        caixa = QMessageBox(self)
        caixa.setIcon(QMessageBox.Information)
        caixa.setWindowTitle("Áudio do computador")
        caixa.setText("Como gravar o som que sai pelas caixas")
        caixa.setInformativeText(disp.dica_loopback())
        caixa.exec()

    def _aplicar_audio_padrao(self, anterior) -> None:
        """Escolhe a entrada que faz sentido para o tipo de fonte atual.

        Uma escolha explícita do usuário sobrevive a uma nova enumeração de
        dispositivos. Trocar o tipo de fonte é que zera isso — passar de placa
        para tela muda qual é a resposta certa, e insistir na anterior deixaria
        o usuário gravando a placa desligada enquanto filma a tela.
        """
        if self._audio_tocado_pelo_usuario and anterior is not None:
            indice = self._indice_audio(anterior.caminho)
            if indice > 0:
                self._definir_audio(indice)
                return

        if self.combo_tipo.currentData() == disp.TIPO_PLACA:
            return  # quem resolve o vínculo com a placa é _video_mudou

        escolha = disp.escolher_loopback(self._dispositivos.audio)
        self._definir_audio(self._indice_audio(escolha.caminho) if escolha else 0)

    def _indice_audio(self, caminho: str) -> int:
        """Posição do dispositivo com este caminho, ou 0 («Sem áudio»)."""
        for indice in range(1, self.combo_audio.count()):
            dado = self.combo_audio.itemData(indice)
            if dado is not None and dado.caminho == caminho:
                return indice
        return 0

    def _selecionar_audio_vinculado(self) -> None:
        dispositivo = self.combo_video.currentData()
        alvo = dispositivo.audio_associado if dispositivo else None
        if not alvo:
            # Sem pareamento confirmado, o nome ainda dá uma pista razoável.
            for indice in range(1, self.combo_audio.count()):
                if _parece_captura(self.combo_audio.itemText(indice)):
                    self._definir_audio(indice)
                    return
            return
        indice = self._indice_audio(alvo)
        if indice > 0:
            self._definir_audio(indice)

    def _definir_audio(self, indice: int) -> None:
        self.combo_audio.blockSignals(True)
        self.combo_audio.setCurrentIndex(indice)
        self.combo_audio.blockSignals(False)
        self._preencher_taxas()
        self._ajustar_monitoracao()

    @Slot()
    def _audio_mudou(self) -> None:
        self._audio_tocado_pelo_usuario = True
        self._preencher_taxas()
        self._ajustar_monitoracao()

    def _ajustar_monitoracao(self) -> None:
        """Ouvir o áudio do próprio PC realimentaria a captura; aqui isso trava.

        A fonte de loopback grava o que sai pelas caixas. Reproduzir nela o que
        acabou de ser capturado devolve o som para dentro da captura, e cada
        volta soma em cima da anterior — em segundos vira um uivo. E não há o
        que ouvir de todo modo: esse som já está saindo pelas caixas.
        """
        dispositivo = self.combo_audio.currentData()
        permitida = not (dispositivo is not None and dispositivo.loopback)
        self.check_monitor.setEnabled(permitida)
        self.check_monitor.setToolTip(
            "" if permitida else
            "Indisponível com o áudio do computador: você já está ouvindo esse "
            "som, e reproduzi-lo de volta realimentaria a captura."
        )
        if not permitida:
            self.motor.definir_monitoracao(False)
            self._fechar_saida_audio()

    def _monitorando(self) -> bool:
        """Se a monitoração está ligada E é permitida para a fonte atual."""
        return self.check_monitor.isChecked() and self.check_monitor.isEnabled()

    @Slot(bool)
    def _vincular_mudou(self, ligado: bool) -> None:
        self.config.setValue("vincular_audio", ligado)
        self.combo_audio.setEnabled(not ligado)
        if ligado:
            self._audio_tocado_pelo_usuario = False
            self._selecionar_audio_vinculado()

    def _preencher_taxas(self) -> None:
        dispositivo = self.combo_audio.currentData()
        self.combo_taxa.clear()
        self.combo_taxa.setEnabled(dispositivo is not None)
        if dispositivo is None:
            return
        preferida = dispositivo.melhor_taxa()
        for indice, taxa in enumerate(dispositivo.taxas or [48000]):
            self.combo_taxa.addItem(f"{taxa} Hz", taxa)
            if taxa == preferida:
                self.combo_taxa.setCurrentIndex(indice)

    @Slot()
    def _modo_mudou(self) -> None:
        modo = self.combo_modo.currentData()
        medicao = self._medicoes.get(modo)
        if medicao is None:
            self.rotulo_modo.setText(
                "Taxa anunciada pela placa — nem sempre é a real. "
                "Use Testar equipamento para medir."
            )
        else:
            self.rotulo_modo.setText(f"{medicao.rotulo_veredito} — {medicao.resumo}")

    def _pintar_modos(self) -> None:
        """Marca cada modo com a cor do veredito medido."""
        if not self._medicoes:
            return
        fichas = tema.fichas(self._modo_tema)
        cores = {
            VEREDITO_FLUIDO: fichas["sucesso"],
            "apertado": fichas["aviso"],
            VEREDITO_INSUFICIENTE: fichas["perigo"],
            VEREDITO_ERRO: fichas["texto_suave"],
        }
        for indice in range(self.combo_modo.count()):
            modo = self.combo_modo.itemData(indice)
            medicao = self._medicoes.get(modo)
            if medicao is None:
                continue
            self.combo_modo.setItemData(indice, QColor(cores[medicao.veredito]),
                                        Qt.ForegroundRole)
            rotulo = modo.rotulo
            if medicao.veredito == VEREDITO_ERRO:
                texto = f"{_SINAL[medicao.veredito]}  {rotulo} — não abriu"
            else:
                texto = (f"{_SINAL[medicao.veredito]}  {modo.largura}x{modo.altura}"
                         f"  {medicao.fps_real:.0f} fps reais  [{modo.codec}]")
            self.combo_modo.setItemText(indice, texto)

    # -- teste de equipamento ----------------------------------------------

    @Slot()
    def _testar_equipamento(self) -> None:
        dispositivo = self.combo_video.currentData()
        if dispositivo is None or not dispositivo.modos:
            self._aviso("Escolha uma placa de captura primeiro.")
            return
        if self._trabalho is not None and self._trabalho.isRunning():
            return

        modos = [m for m in dispositivo.modos if m.comprimido] or dispositivo.modos
        segundos = 3.0
        estimativa = int(len(modos) * (segundos + 1.2))

        resposta = QMessageBox.question(
            self, "Testar equipamento",
            f"Vou abrir {len(modos)} modos por {segundos:g}s cada e medir a taxa "
            f"real e o custo de processamento.\n\n"
            f"Leva cerca de {estimativa} segundos e a prévia fica parada "
            f"durante o teste.\n\nComeçar?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if resposta != QMessageBox.Yes:
            return

        estava_rodando = self.motor.rodando
        if estava_rodando:
            self._parar_captura()

        self.botao_testar.setEnabled(False)
        self.botao_testar.setText("Testando…")
        self.barra_teste.setRange(0, len(modos))
        self.barra_teste.setValue(0)
        self.barra_teste.show()

        trabalho = TrabalhoTeste(dispositivo, modos, segundos,
                                 max(640, self.tela.width()), )
        trabalho.setParent(self)
        trabalho.progresso.connect(self._teste_progresso)
        trabalho.concluiu.connect(self._teste_concluiu)
        self._trabalho = trabalho
        trabalho.start()

    @Slot(int, int, str)
    def _teste_progresso(self, indice: int, total: int, rotulo: str) -> None:
        self.barra_teste.setValue(indice)
        self.rotulo_modo.setText(f"Testando {rotulo}  ({indice + 1}/{total})")

    @Slot(object)
    def _teste_concluiu(self, medicoes: dict) -> None:
        self._medicoes = medicoes
        self.barra_teste.hide()
        self.botao_testar.setEnabled(True)
        self.botao_testar.setText("Testar equipamento")
        self._pintar_modos()
        self._modo_mudou()
        self._relatorio_teste(medicoes)

    @staticmethod
    def _recomendacoes(medicoes: dict):
        """Os dois modos que valem a pena, um para cada objetivo.

        Nao existe "o melhor" universal: mais quadros por segundo e mais pixels
        por quadro competem pelo mesmo orcamento. Placas costumam ter um ponto
        de corte onde subir a resolucao derruba a taxa pela metade, entao o
        certo e apresentar as duas pontas e deixar o usuario decidir pelo uso.
        """
        viaveis = [(m, med) for m, med in medicoes.items()
                   if med.veredito in (VEREDITO_FLUIDO, "apertado")]
        if not viaveis:
            return None, None

        def faixa(medicao) -> int:
            # Comparar a taxa medida crua faria 59,85 ganhar de 59,70 e o
            # ruido da medicao escolher a resolucao. Agrupar em degraus de
            # 5 fps torna "praticamente a mesma taxa" um empate, e ai quem
            # decide e a resolucao — que e o que o usuario percebe.
            return round(medicao.fps_real / 5) * 5

        def folgado(medicao) -> int:
            return 1 if medicao.veredito == VEREDITO_FLUIDO else 0

        movimento = max(viaveis,
                        key=lambda p: (faixa(p[1]), p[0].pixels, folgado(p[1])))[0]
        detalhe = max(viaveis,
                      key=lambda p: (p[0].pixels, faixa(p[1]), folgado(p[1])))[0]
        return movimento, detalhe

    def _selecionar_modo(self, alvo) -> None:
        for indice in range(self.combo_modo.count()):
            if self.combo_modo.itemData(indice) == alvo:
                self.combo_modo.setCurrentIndex(indice)
                return

    def _relatorio_teste(self, medicoes: dict) -> None:
        if not medicoes:
            return

        linhas = []
        for modo, m in sorted(medicoes.items(),
                              key=lambda p: (p[0].pixels, p[0].fps), reverse=True):
            if m.erro:
                linhas.append(f"{modo.largura}x{modo.altura} — {m.erro}")
                continue
            anuncio = "" if m.honesto else f" (anuncia {modo.fps:.0f})"
            linhas.append(
                f"{modo.largura}x{modo.altura}  →  {m.fps_real:.0f} fps reais{anuncio}"
                f"  ·  CPU {m.uso*100:.0f}%  ·  {m.rotulo_veredito}"
            )

        movimento, detalhe = self._recomendacoes(medicoes)
        caixa = QMessageBox(self)
        caixa.setWindowTitle("Resultado do teste")
        caixa.setInformativeText("\n".join(linhas))
        caixa.setStandardButtons(QMessageBox.Close)

        botao_movimento = botao_detalhe = None
        if movimento is not None and movimento == detalhe:
            caixa.setText(
                f"Um modo se destaca: {movimento.largura}x{movimento.altura} a "
                f"{medicoes[movimento].fps_real:.0f} fps reais."
            )
            botao_movimento = caixa.addButton("Usar esse modo", QMessageBox.AcceptRole)
        elif movimento is not None:
            caixa.setText(
                "Dois modos valem a pena, e a escolha depende do que você grava:\n\n"
                f"• Movimento (jogos, vídeo): {movimento.largura}x{movimento.altura} "
                f"a {medicoes[movimento].fps_real:.0f} fps\n"
                f"• Detalhe (slides, texto): {detalhe.largura}x{detalhe.altura} "
                f"a {medicoes[detalhe].fps_real:.0f} fps"
            )
            botao_movimento = caixa.addButton("Usar o de movimento", QMessageBox.AcceptRole)
            botao_detalhe = caixa.addButton("Usar o de detalhe", QMessageBox.AcceptRole)
        else:
            caixa.setText("Nenhum modo passou no teste nesta máquina.")

        caixa.exec()
        escolhido = caixa.clickedButton()
        if escolhido is not None and escolhido is botao_movimento:
            self._selecionar_modo(movimento)
        elif escolhido is not None and escolhido is botao_detalhe:
            self._selecionar_modo(detalhe)

    # -- captura -----------------------------------------------------------

    @Slot()
    def _alternar_captura(self) -> None:
        self._parar_captura() if self.motor.rodando else self._iniciar_captura()

    def _iniciar_captura(self) -> bool:
        dispositivo = self.combo_video.currentData()
        modo = self.combo_modo.currentData()
        if dispositivo is None or modo is None:
            self._aviso("Escolha uma placa de captura primeiro.")
            return False

        audio = self.combo_audio.currentData()
        configuracao = Configuracao.de_fonte(
            dispositivo, modo, cursor=self.check_cursor.isChecked(),
            caminho_audio=audio.caminho if audio else None,
            taxa_audio=self.combo_taxa.currentData() or 48000,
            canais_audio=audio.melhor_canais() if audio else 2,
            backend_audio=audio.backend if audio else "",
            perfil=self.combo_perfil.currentData(),
            codificador=self.combo_codificador.currentData() or "libx264",
            qualidade=self.spin_qualidade.value(),
            pasta_saida=self._pasta,
        )

        self.motor.definir_largura_preview(max(640, self.tela.width()))
        self.motor.definir_monitoracao(self._monitorando())
        self.tela.limpar("Conectando…")
        self._inicio_captura = time.monotonic()
        self.motor.iniciar(configuracao)

        if audio and self._monitorando():
            self._abrir_saida_audio()

        self.botao_iniciar.setText("Parar")
        for botao in (self.botao_gravar, self.botao_foto, self.botao_amostra):
            botao.setEnabled(True)
        self._travar(True)
        return True

    def _parar_captura(self) -> None:
        self.motor.parar()
        self._fechar_saida_audio()
        self.selo_audio.hide()
        self._inicio_captura = 0.0
        self._serie_quadro = -1
        self.tela.limpar("Parado")
        self.botao_iniciar.setText("Iniciar")
        for botao in (self.botao_gravar, self.botao_foto, self.botao_amostra):
            botao.setEnabled(False)
        self.est_taxa.setText("")
        self.medidor.definir_nivel(0.0)
        self._travar(False)

    def _travar(self, travado: bool) -> None:
        # Trocar de dispositivo ou formato exige reabrir a placa; travar evita
        # um estado em que a tela mostra uma coisa e a gravacao usa outra.
        for widget in (self.combo_tipo, self.combo_video, self.combo_modo, self.combo_perfil,
                       self.combo_codificador, self.botao_procurar,
                       self.botao_testar, self.check_vincular, self.combo_taxa):
            widget.setEnabled(not travado)
        self.combo_audio.setEnabled(
            not travado and not self.check_vincular.isChecked())

    # -- gravacao ----------------------------------------------------------

    @Slot()
    def _alternar_gravacao(self) -> None:
        if not self.motor.rodando:
            return
        if self.motor.gravando:
            caminho = self.motor.parar_gravacao()
            if caminho:
                self.statusBar().showMessage(f"Gravado: {caminho}", 8000)
            return

        if not self._confirmar_sem_audio():
            return

        destino = self._pedir_destino()
        if destino is False:  # cancelado na caixa de diálogo
            return
        self.motor.iniciar_gravacao(destino)

    def _confirmar_sem_audio(self) -> bool:
        """Avisa antes de gravar mudo. Devolve False se o usuário desistiu.

        O aviso vem antes da caixa de salvar de propósito: descobrir que a
        gravação seria muda depois de escolher pasta e nome é tarde demais, e
        um arquivo mudo só costuma dar as caras quando já não dá para regravar.
        """
        estado = self.motor.estado_audio
        if estado == AUDIO_ATIVO or not self.check_avisar_audio.isChecked():
            return True

        if estado == AUDIO_ESPERANDO:
            # A entrada abriu e o primeiro bloco pode estar a caminho. Só vira
            # aviso depois da carência; antes disso o motor ainda espera por ele.
            if time.monotonic() - self._inicio_captura < SEGUNDOS_ESPERA_AUDIO:
                return True
            detalhe = ("A entrada de áudio escolhida abriu, mas nenhum som "
                       "chegou até agora.")
        elif estado == AUDIO_MUDO:
            dispositivo = self.combo_audio.currentData()
            detalhe = ("A entrada de áudio está funcionando, mas só chega "
                       "silêncio há vários segundos.")
            if dispositivo is not None and dispositivo.loopback:
                # Aqui o alarme é quase sempre certeiro: o loopback entrega
                # blocos mesmo em silêncio, então só há duas explicações — nada
                # está tocando, ou o volume do sistema está no zero.
                detalhe += (" Confira se algo está mesmo tocando e se o volume "
                            "do sistema não está no mudo.")
        elif estado == AUDIO_FALHOU:
            detalhe = ("A entrada de áudio escolhida não está funcionando: ela "
                       "não abriu ou parou durante a captura.")
        else:
            detalhe = ("A entrada de áudio está em «Sem áudio» no cartão Fonte.")

        # Silêncio numa entrada que funciona é diferente de não ter trilha: se o
        # som voltar, ele entra na gravação. Prometer "mudo — sem conserto" aqui
        # seria mentira, e mentira no aviso é o que faz o usuário parar de ler.
        if estado == AUDIO_MUDO:
            resumo = "Esta gravação está começando em silêncio."
            fecho = ("A trilha de áudio existe e vai capturar o que vier a "
                     "tocar; se nada tocar, o trecho fica mudo.")
        else:
            resumo = "Esta gravação vai sair sem som."
            fecho = ("O vídeo será gravado normalmente, mas o arquivo ficará "
                     "mudo — e isso não tem conserto depois.")

        caixa = QMessageBox(self)
        caixa.setIcon(QMessageBox.Warning)
        caixa.setWindowTitle("Gravar sem áudio?")
        caixa.setText(resumo)
        caixa.setInformativeText(f"{detalhe}\n\n{fecho}")
        lembrete = QCheckBox("Não avisar mais")
        caixa.setCheckBox(lembrete)
        gravar = caixa.addButton("Gravar mesmo assim", QMessageBox.AcceptRole)
        caixa.addButton("Cancelar", QMessageBox.RejectRole)
        caixa.setDefaultButton(gravar)
        caixa.exec()

        if lembrete.isChecked():
            # Reflete na caixa do cartão para o usuário conseguir voltar atrás.
            self.check_avisar_audio.setChecked(False)
        return caixa.clickedButton() is gravar

    def _pedir_destino(self):
        """Destino da próxima gravação.

        Devolve `None` para usar o nome automático, um `Path` escolhido pelo
        usuário, ou `False` se ele cancelou — que é diferente de "use o padrão"
        e precisa abortar a gravação.
        """
        if not self.check_perguntar.isChecked():
            return None

        sugerido = self.motor.caminho_sugerido()
        if sugerido is None:
            return None

        extensao = sugerido.suffix
        filtro = ("Matroska (*.mkv)" if extensao == ".mkv" else "MPEG-4 (*.mp4)")
        escolha, _ = QFileDialog.getSaveFileName(
            self, "Salvar gravação como", str(sugerido),
            f"{filtro};;Todos os arquivos (*)")
        if not escolha:
            return False

        destino = Path(escolha)
        if not destino.suffix:
            # O usuário digitou só o nome; sem extensão o muxer não sabe que
            # formato escrever.
            destino = destino.with_suffix(extensao)
        self._pasta = destino.parent
        self.config.setValue("pasta", str(self._pasta))
        self._mostrar_pasta()
        return destino

    @Slot(bool)
    def _gravacao_alterada(self, gravando: bool) -> None:
        e_amostra = self._amostra_ate > 0
        if gravando:
            self.botao_gravar.setText("Parar gravação")
            self.botao_gravar.setObjectName("gravando")
        else:
            self.botao_gravar.setText("Gravar")
            self.botao_gravar.setObjectName("")
        # Trocar objectName exige reaplicar o estilo para o seletor pegar.
        self.botao_gravar.style().unpolish(self.botao_gravar)
        self.botao_gravar.style().polish(self.botao_gravar)
        self.botao_gravar.setEnabled(self.motor.rodando and not e_amostra)
        self.botao_amostra.setEnabled(self.motor.rodando and not gravando)

    @Slot()
    def _gravar_amostra(self) -> None:
        if not self.motor.rodando or self.motor.gravando:
            return
        caminho = self.motor.iniciar_gravacao()
        if caminho is None:
            return
        self._amostra_ate = time.monotonic() + SEGUNDOS_AMOSTRA
        self.botao_amostra.setEnabled(False)
        self.botao_gravar.setEnabled(False)

    def _encerrar_amostra(self) -> None:
        self._amostra_ate = 0.0
        caminho = self.motor.parar_gravacao()
        self.botao_amostra.setEnabled(self.motor.rodando)
        self.botao_gravar.setEnabled(self.motor.rodando)
        if caminho is None:
            return
        self._mostrar_relatorio_amostra(resumir_gravacao(caminho))

    def _mostrar_relatorio_amostra(self, resumo: dict) -> None:
        if resumo.get("erro"):
            self._erro(f"A amostra foi gravada mas não pôde ser lida:\n{resumo['erro']}")
            return

        linhas = [
            f"Arquivo:     {resumo['caminho'].name}",
            f"Tamanho:     {_bytes_legivel(resumo.get('bytes', 0))}",
            f"Duração:     {resumo.get('duracao', 0):.2f} s",
            f"Vídeo:       {resumo.get('largura')}x{resumo.get('altura')}"
            f"  {resumo.get('codec_video', '')}  ·  {resumo.get('fps', 0):.1f} fps",
            f"Quadros:     {resumo.get('quadros', 0)}",
        ]
        if resumo.get("codec_audio"):
            linhas.append(f"Áudio:       {resumo['codec_audio']}"
                          f"  ·  {resumo.get('duracao_audio', 0):.2f} s de conteúdo")
            desencontro = resumo.get("desencontro_ms")
            if desencontro is not None:
                estado = "dentro do imperceptível" if abs(desencontro) < 45 else "verificar"
                linhas.append(f"Sincronia:   {desencontro:+.0f} ms ({estado})")
        else:
            linhas.append("Áudio:       nenhum — o arquivo ficou mudo")

        taxa = resumo.get("bytes", 0) / max(resumo.get("duracao", 1), 0.1)
        linhas.append(f"Consumo:     {_bytes_legivel(taxa * 60)} por minuto")

        caixa = QMessageBox(self)
        caixa.setWindowTitle("Amostra gravada")
        caixa.setText("A amostra foi gravada e conferida:")
        caixa.setInformativeText("\n".join(linhas))
        caixa.setStandardButtons(QMessageBox.Ok)
        abrir = caixa.addButton("Abrir pasta", QMessageBox.ActionRole)
        caixa.exec()
        if caixa.clickedButton() is abrir:
            self._abrir_pasta()

    def _abrir_pasta(self) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._pasta)))

    @Slot()
    def _perfil_mudou(self) -> None:
        h264 = self.combo_perfil.currentData() == PERFIL_H264
        self.combo_codificador.setEnabled(h264)
        self.spin_qualidade.setEnabled(h264)
        self.config.setValue("perfil", self.combo_perfil.currentData())

    @Slot()
    def _escolher_pasta(self) -> None:
        escolha = QFileDialog.getExistingDirectory(
            self, "Onde salvar as gravações", str(self._pasta))
        if escolha:
            self._pasta = Path(escolha)
            self.config.setValue("pasta", escolha)
            self._mostrar_pasta()

    def _mostrar_pasta(self) -> None:
        self.rotulo_pasta.definir_texto(str(self._pasta))

    @Slot()
    def _tirar_foto(self) -> None:
        if not self.motor.rodando:
            return
        self.motor.solicitar_quadro_cheio()
        # O quadro cheio so existe depois que a placa entregar o proximo.
        QTimer.singleShot(200, self._salvar_foto)

    def _salvar_foto(self) -> None:
        quadro = self.motor.obter_quadro_cheio()
        if quadro is None:
            self.statusBar().showMessage("Não deu para capturar a foto.", 4000)
            return
        altura, largura, _ = quadro.shape
        imagem = QImage(np.ascontiguousarray(quadro).data, largura, altura,
                        3 * largura, QImage.Format_RGB888).copy()
        destino = self._pasta / f"foto_{time.strftime('%Y-%m-%d_%H-%M-%S')}.png"
        destino.parent.mkdir(parents=True, exist_ok=True)
        pronto = imagem.save(str(destino))
        self.statusBar().showMessage(
            f"Foto salva: {destino}" if pronto else "Falha ao salvar a foto.", 5000)

    # -- audio -------------------------------------------------------------

    def _abrir_saida_audio(self) -> None:
        self._fechar_saida_audio()
        formato = QAudioFormat()
        formato.setSampleRate(TAXA_MONITOR)
        formato.setChannelCount(CANAIS_MONITOR)
        formato.setSampleFormat(QAudioFormat.Int16)

        saida = QMediaDevices.defaultAudioOutput()
        if saida.isNull():
            self._aviso("Nenhuma saída de áudio disponível para monitoração.")
            return
        self._saida_audio = QAudioSink(saida, formato, self)
        self._saida_audio.setVolume(self.slider_volume.value() / 100.0)
        self._canal_audio = self._saida_audio.start()

    def _fechar_saida_audio(self) -> None:
        if self._saida_audio is not None:
            self._saida_audio.stop()
            self._saida_audio = None
        self._canal_audio = None

    @Slot(bool)
    def _monitor_mudou(self, ligado: bool) -> None:
        # A preferencia e gravada mesmo quando a fonte atual nao permite ouvir:
        # desabilitar a caixa nao pode apagar o que o usuario escolheu, senao
        # trocar para a tela e voltar deixaria a monitoracao desligada sozinha.
        self.config.setValue("monitorar", ligado)
        efetiva = ligado and self._monitorando()
        self.motor.definir_monitoracao(efetiva)
        if not self.motor.rodando:
            return
        if efetiva and self.combo_audio.currentData() is not None:
            self._abrir_saida_audio()
        else:
            self._fechar_saida_audio()

    @Slot(int)
    def _volume_mudou(self, valor: int) -> None:
        self.config.setValue("volume", valor)
        if self._saida_audio is not None:
            self._saida_audio.setVolume(valor / 100.0)

    # -- laços -------------------------------------------------------------

    def _tick_video(self) -> None:
        quadro, serie = self.motor.obter_quadro(self._serie_quadro)
        if quadro is not None:
            self._serie_quadro = serie
            self.tela.definir_quadro(quadro)

    def _tick_audio(self) -> None:
        if self._canal_audio is None or self._saida_audio is None:
            return
        buffer = self.motor.audio_monitor
        while buffer:
            livre = self._saida_audio.bytesFree()
            if livre <= 0 or len(buffer[0]) > livre:
                # Saida cheia: espera o proximo tick em vez de partir o bloco,
                # o que geraria estalos.
                return
            self._canal_audio.write(buffer.popleft())

    def _tick_estado(self) -> None:
        if self._amostra_ate and time.monotonic() >= self._amostra_ate:
            self._encerrar_amostra()

        if not self.motor.rodando:
            if self.botao_iniciar.text() == "Parar":
                self._parar_captura()  # a thread caiu sozinha
            return

        e = self.motor.estatisticas()
        self.est_resolucao.setText(f"{e.largura}×{e.altura}")
        perdidos = f"   ·   {e.perdidos} perdidos" if e.perdidos else ""
        self.est_taxa.setText(f"   ·   {e.fps:.1f} fps{perdidos}")
        self.medidor.definir_nivel(e.nivel_audio)

        estado_audio = self.motor.estado_audio
        self._atualizar_selo_audio(estado_audio)

        if e.gravando:
            restante = ""
            if self._amostra_ate:
                restante = f"  (amostra: {max(0, self._amostra_ate - time.monotonic()):.0f}s)"
            if estado_audio == AUDIO_ATIVO:
                mudo = ""
            elif estado_audio == AUDIO_MUDO:
                mudo = "   ·   silêncio"
            else:
                mudo = "   ·   sem áudio"
            self.est_gravacao.setText(
                f"● REC  {_duracao_legivel(e.duracao)}   "
                f"{_bytes_legivel(e.bytes_gravados)}{mudo}{restante}")
        else:
            self.est_gravacao.setText("")

    def _atualizar_selo_audio(self, estado: str) -> None:
        """Mostra no cabeçalho, durante toda a captura, que não há som."""
        selo = _SELO_AUDIO.get(estado)
        cedo = (estado == AUDIO_ESPERANDO
                and time.monotonic() - self._inicio_captura < SEGUNDOS_ESPERA_AUDIO)
        if selo is None or cedo:
            self.selo_audio.hide()
            return
        texto, dica = selo
        self.selo_audio.setText(texto)
        self.selo_audio.setToolTip(dica)
        self.selo_audio.show()

    # -- janela ------------------------------------------------------------

    @Slot()
    def _alternar_tela_cheia(self) -> None:
        if self.isFullScreen():
            self._sair_tela_cheia()
        else:
            self.statusBar().hide()
            self.showFullScreen()

    @Slot()
    def _sair_tela_cheia(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.statusBar().show()

    def resizeEvent(self, evento) -> None:  # noqa: N802
        super().resizeEvent(evento)
        # Converter direto no tamanho util evita reescalar 1080p a cada quadro.
        self.motor.definir_largura_preview(max(640, self.tela.width()))

    def mouseDoubleClickEvent(self, evento) -> None:  # noqa: N802
        self._alternar_tela_cheia()

    def closeEvent(self, evento) -> None:  # noqa: N802
        for timer in (self._timer_video, self._timer_audio, self._timer_estado):
            timer.stop()
        if self._trabalho is not None and self._trabalho.isRunning():
            if isinstance(self._trabalho, TrabalhoTeste):
                self._trabalho.cancelar()
            self._trabalho.wait(3000)
        self.config.setValue("qualidade", self.spin_qualidade.value())
        self.motor.parar()
        self._fechar_saida_audio()
        super().closeEvent(evento)

    # -- mensagens ---------------------------------------------------------

    @Slot(str)
    def _erro(self, texto: str) -> None:
        QMessageBox.critical(self, "Erro", texto)

    @Slot(str)
    def _aviso(self, texto: str) -> None:
        QMessageBox.warning(self, "Atenção", texto)
