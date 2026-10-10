"""Janela de pos-producao: converter, cortar e juntar, marcando pelo olho.

Vive numa janela propria, e nao num cartao do painel lateral, porque nao
participa da captura: e o que se faz **depois**, com arquivos que ja existem.

A previa nao e enfeite. Marcar um corte digitando segundos exige adivinhar onde
o assunto comeca, conferir noutro programa e voltar para corrigir — o trabalho
que a ferramenta deveria poupar. Aqui a barra percorre o arquivo, a imagem
acompanha, e «Marcar inicio»/«Marcar fim» fixam o ponto que esta na tela.

A lista embaixo e o resto da historia: cada linha e um trecho com as suas
marcas. Uma linha inteira converte; com marcas, corta; varias linhas juntam
([0026](../docs/adr/0026-pos-producao-copia-ou-recompressao.md)).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import edicao, tema
from .dispositivos import pasta_videos_padrao
from .janela import TelaVideo

_FILTRO = "Vídeos (*.mkv *.mp4 *.mov *.avi *.webm *.m4v);;Todos os arquivos (*)"

_COL_ARQUIVO, _COL_INICIO, _COL_FIM, _COL_DURACAO = range(4)

# Espera entre o ultimo movimento da barra e o pedido do quadro. Arrastar emite
# dezenas de eventos por segundo; decodificar todos deixaria a barra travada
# atras do ponteiro. 40 ms e curto o bastante para parecer continuo.
_ATRASO_PREVIA_MS = 40


def _mmss(segundos: float) -> str:
    minutos, resto = divmod(max(0.0, segundos), 60)
    return f"{int(minutos):d}:{resto:05.2f}"


class FaixaTrecho(QWidget):
    """Barra fina que mostra, do arquivo inteiro, qual pedaco sera guardado.

    Serve para a resposta «o que sobra?» ser visivel sem ler numero nenhum: o
    aceso e o que fica, o apagado e o que sai.
    """

    def __init__(self, modo_tema: str = tema.AUTO,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(10)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # O tema vem de quem abriu a janela: `AUTO` aqui pintaria pelo esquema
        # do sistema mesmo quando o usuario forcou claro ou escuro no programa.
        self._modo_tema = modo_tema
        self._duracao = 0.0
        self._inicio = 0.0
        self._fim = 0.0
        self._agora = 0.0

    def definir(self, duracao: float, inicio: float, fim: float,
                agora: float) -> None:
        self._duracao, self._inicio = duracao, inicio
        self._fim, self._agora = fim, agora
        self.update()

    def paintEvent(self, evento) -> None:  # noqa: N802
        pintor = QPainter(self)
        fichas = tema.fichas(self._modo_tema)
        largura = self.width()
        pintor.fillRect(self.rect(), QColor(fichas["borda"]))
        if self._duracao <= 0:
            return

        def x(segundos: float) -> int:
            return int(largura * max(0.0, min(segundos, self._duracao)) / self._duracao)

        esquerda = x(self._inicio)
        direita = x(self._fim if self._fim > 0 else self._duracao)
        pintor.fillRect(esquerda, 0, max(1, direita - esquerda), self.height(),
                        QColor(fichas["destaque"]))
        pintor.fillRect(x(self._agora) - 1, 0, 2, self.height(),
                        QColor(fichas["texto"]))


class _Trabalho(QThread):
    """Roda a montagem fora da thread da interface.

    Mesma razao do [0014](../docs/adr/0014-trabalho-demorado-em-qthread.md):
    converter um arquivo longo leva minutos, e uma janela congelada nesse tempo
    parece travada.
    """

    progrediu = Signal(float)
    terminou = Signal(object)

    def __init__(self, trechos, saida, receita, parent=None) -> None:
        super().__init__(parent)
        self._trechos = trechos
        self._saida = saida
        self._receita = receita
        self._parar = False

    def cancelar(self) -> None:
        self._parar = True

    def run(self) -> None:  # noqa: D102
        self.terminou.emit(edicao.montar(
            self._trechos, self._saida, self._receita,
            progresso=self.progrediu.emit, cancelar=lambda: self._parar))


class JanelaEdicao(QDialog):
    """Converter, cortar e juntar, com a imagem na frente para marcar."""

    def __init__(self, codificadores, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pós-produção — converter, cortar e juntar")
        self.resize(1180, 760)

        self._modo_tema = getattr(parent, "_modo_tema", tema.AUTO)
        self._trabalho: _Trabalho | None = None
        self._leitor: edicao.Leitor | None = None
        self._linha_previa = -1
        self._duracoes: list[float] = []
        # Marcas por linha, em segundos. Fora da tabela porque a tabela guarda
        # texto e aqui o que vale e o numero.
        self._marcas: list[list[float]] = []

        self._relogio = QTimer(self)
        self._relogio.setSingleShot(True)
        self._relogio.setInterval(_ATRASO_PREVIA_MS)
        self._relogio.timeout.connect(self._mostrar_quadro)

        self._montar_interface(codificadores)
        self._atalhos()
        self._atualizar_estado()

    # -- construcao --------------------------------------------------------

    def _montar_interface(self, codificadores) -> None:
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(16, 16, 16, 16)
        coluna.setSpacing(10)

        divisor = QSplitter(Qt.Horizontal)
        divisor.addWidget(self._painel_previa())
        divisor.addWidget(self._painel_lista())
        divisor.setStretchFactor(0, 3)
        divisor.setStretchFactor(1, 2)
        coluna.addWidget(divisor, 1)

        coluna.addLayout(self._linha_saida(codificadores))

        self.barra = QProgressBar()
        self.barra.setRange(0, 1000)
        self.barra.hide()
        coluna.addWidget(self.barra)

        self.rodape = QLabel("")
        self.rodape.setWordWrap(True)
        self.rodape.setObjectName("dica")
        coluna.addWidget(self.rodape)

        coluna.addLayout(self._linha_acoes())

    def _painel_previa(self) -> QWidget:
        caixa = QWidget()
        coluna = QVBoxLayout(caixa)
        coluna.setContentsMargins(0, 0, 8, 0)
        coluna.setSpacing(8)

        self.tela = TelaVideo()
        self.tela.limpar("Adicione um vídeo e escolha-o na lista")
        coluna.addWidget(self.tela, 1)

        self.barra_posicao = QSlider(Qt.Horizontal)
        self.barra_posicao.setRange(0, 0)
        self.barra_posicao.setEnabled(False)
        self.barra_posicao.valueChanged.connect(self._posicao_mudou)
        coluna.addWidget(self.barra_posicao)

        self.faixa = FaixaTrecho(self._modo_tema)
        coluna.addWidget(self.faixa)

        tempos = QHBoxLayout()
        self.rotulo_tempo = QLabel("—")
        self.rotulo_tempo.setObjectName("dica")
        tempos.addWidget(self.rotulo_tempo)
        tempos.addStretch(1)
        self.rotulo_marcas = QLabel("")
        self.rotulo_marcas.setObjectName("dica")
        tempos.addWidget(self.rotulo_marcas)
        coluna.addLayout(tempos)

        coluna.addLayout(self._linha_transporte())
        coluna.addLayout(self._linha_marcacao())
        return caixa

    def _linha_transporte(self) -> QHBoxLayout:
        linha = QHBoxLayout()
        linha.setSpacing(4)
        for rotulo, passo, dica in (
            ("−5s", -5.0, "cinco segundos atrás"),
            ("−1s", -1.0, "um segundo atrás"),
            ("−1q", -0.04, "um quadro atrás"),
            ("+1q", 0.04, "um quadro à frente"),
            ("+1s", 1.0, "um segundo à frente"),
            ("+5s", 5.0, "cinco segundos à frente"),
        ):
            botao = QPushButton(rotulo)
            botao.setObjectName("discreto")
            botao.setToolTip(f"Avança {dica}")
            botao.clicked.connect(lambda _=False, p=passo: self._passo(p))
            linha.addWidget(botao)
        linha.addStretch(1)
        return linha

    def _linha_marcacao(self) -> QHBoxLayout:
        linha = QHBoxLayout()
        self.botao_marcar_inicio = QPushButton("Marcar início  (I)")
        self.botao_marcar_inicio.setToolTip(
            "Descarta tudo o que vem antes do quadro na tela.")
        self.botao_marcar_inicio.clicked.connect(lambda: self._marcar(0))
        self.botao_marcar_fim = QPushButton("Marcar fim  (O)")
        self.botao_marcar_fim.setToolTip(
            "Descarta tudo o que vem depois do quadro na tela.")
        self.botao_marcar_fim.clicked.connect(lambda: self._marcar(1))
        self.botao_limpar_marcas = QPushButton("Limpar marcas")
        self.botao_limpar_marcas.setObjectName("discreto")
        self.botao_limpar_marcas.clicked.connect(self._limpar_marcas)
        for widget in (self.botao_marcar_inicio, self.botao_marcar_fim,
                       self.botao_limpar_marcas):
            linha.addWidget(widget)
        linha.addStretch(1)
        return linha

    def _painel_lista(self) -> QWidget:
        caixa = QWidget()
        coluna = QVBoxLayout(caixa)
        coluna.setContentsMargins(8, 0, 0, 0)
        coluna.setSpacing(8)

        explicacao = QLabel(
            "Os arquivos são juntados na ordem da lista. Escolha uma linha "
            "para vê-la na tela ao lado e marcar onde ela começa e termina."
        )
        explicacao.setWordWrap(True)
        explicacao.setObjectName("dica")
        coluna.addWidget(explicacao)

        self.tabela = QTableWidget(0, 4)
        self.tabela.setHorizontalHeaderLabels(["Arquivo", "Início", "Fim", "Fica"])
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.NoEditTriggers)
        cabecalho = self.tabela.horizontalHeader()
        cabecalho.setSectionResizeMode(_COL_ARQUIVO, QHeaderView.Stretch)
        for col in (_COL_INICIO, _COL_FIM, _COL_DURACAO):
            cabecalho.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.tabela.itemSelectionChanged.connect(self._linha_escolhida)
        coluna.addWidget(self.tabela, 1)

        linha = QHBoxLayout()
        self.botao_adicionar = QPushButton("Adicionar…")
        self.botao_adicionar.clicked.connect(self._adicionar)
        self.botao_remover = QPushButton("Remover")
        self.botao_remover.setObjectName("discreto")
        self.botao_remover.clicked.connect(self._remover)
        self.botao_subir = QPushButton("↑")
        self.botao_subir.setObjectName("discreto")
        self.botao_subir.clicked.connect(lambda: self._mover(-1))
        self.botao_descer = QPushButton("↓")
        self.botao_descer.setObjectName("discreto")
        self.botao_descer.clicked.connect(lambda: self._mover(1))
        for widget in (self.botao_adicionar, self.botao_remover,
                       self.botao_subir, self.botao_descer):
            linha.addWidget(widget)
        linha.addStretch(1)
        coluna.addLayout(linha)
        return caixa

    def _linha_saida(self, codificadores) -> QHBoxLayout:
        linha = QHBoxLayout()
        linha.setSpacing(12)

        self.check_recomprimir = QCheckBox("Recomprimir")
        self.check_recomprimir.setToolTip(
            "Desmarcado: copia os quadros como estão. Instantâneo e sem perda, "
            "mas o corte só cai em quadro-chave e todos os arquivos precisam "
            "ter o mesmo codec e tamanho.\n\n"
            "Marcado: recodifica tudo. Demora, corta no quadro exato, encolhe "
            "o arquivo e junta origens diferentes."
        )
        self.check_recomprimir.toggled.connect(self._atualizar_estado)
        linha.addWidget(self.check_recomprimir)

        self.combo_codificador = QComboBox()
        for nome, rotulo in codificadores:
            self.combo_codificador.addItem(rotulo, nome)
        linha.addWidget(QLabel("Codificador"))
        linha.addWidget(self.combo_codificador, 1)

        self.spin_qualidade = QSpinBox()
        self.spin_qualidade.setRange(0, 51)
        self.spin_qualidade.setValue(23)
        self.spin_qualidade.setToolTip(
            "Menor = melhor imagem e arquivo maior. 18 é quase transparente, "
            "23 é o padrão.")
        linha.addWidget(QLabel("Qualidade"))
        linha.addWidget(self.spin_qualidade)
        return linha

    def _linha_acoes(self) -> QHBoxLayout:
        linha = QHBoxLayout()
        self.botao_fechar = QPushButton("Fechar")
        self.botao_fechar.setObjectName("discreto")
        self.botao_fechar.clicked.connect(self.reject)
        linha.addWidget(self.botao_fechar)
        linha.addStretch(1)
        self.botao_cancelar = QPushButton("Cancelar")
        self.botao_cancelar.setObjectName("discreto")
        self.botao_cancelar.clicked.connect(self._cancelar)
        self.botao_cancelar.hide()
        linha.addWidget(self.botao_cancelar)
        self.botao_salvar = QPushButton("Salvar como…")
        self.botao_salvar.clicked.connect(self._salvar)
        linha.addWidget(self.botao_salvar)
        return linha

    def _atalhos(self) -> None:
        # I e O sao as teclas que todo editor usa para entrada e saida; quem ja
        # mexeu com video procura por elas antes de procurar o botao.
        QShortcut(QKeySequence("I"), self, lambda: self._marcar(0))
        QShortcut(QKeySequence("O"), self, lambda: self._marcar(1))
        QShortcut(QKeySequence(Qt.Key_Left), self, lambda: self._passo(-0.04))
        QShortcut(QKeySequence(Qt.Key_Right), self, lambda: self._passo(0.04))

    # -- previa ------------------------------------------------------------

    @Slot()
    def _linha_escolhida(self) -> None:
        linhas = {i.row() for i in self.tabela.selectedIndexes()}
        linha = next(iter(linhas)) if len(linhas) == 1 else -1
        if linha == self._linha_previa:
            self._atualizar_estado()
            return

        self._linha_previa = linha
        if self._leitor is not None:
            self._leitor.fechar()
            self._leitor = None

        if linha < 0:
            self.tela.limpar("Escolha uma linha da lista")
            self.barra_posicao.setEnabled(False)
            self.barra_posicao.setRange(0, 0)
            self.rotulo_tempo.setText("—")
            self.faixa.definir(0, 0, 0, 0)
            self._atualizar_estado()
            return

        caminho = Path(self.tabela.item(linha, _COL_ARQUIVO).data(Qt.UserRole))
        leitor = edicao.Leitor(caminho)
        if not leitor.valido:
            self.tela.limpar(f"Não deu para abrir: {leitor.erro[:60]}")
            self._atualizar_estado()
            return

        self._leitor = leitor
        self.barra_posicao.blockSignals(True)
        self.barra_posicao.setRange(0, max(1, int(leitor.duracao * 1000)))
        self.barra_posicao.setValue(int(self._marcas[linha][0] * 1000))
        self.barra_posicao.blockSignals(False)
        self.barra_posicao.setEnabled(True)
        self._mostrar_quadro()
        self._atualizar_estado()

    @Slot()
    def _posicao_mudou(self) -> None:
        # Reinicia a espera a cada movimento: so o ultimo pedido e atendido.
        self._relogio.start()
        self._atualizar_tempos()

    @Slot()
    def _mostrar_quadro(self) -> None:
        if self._leitor is None:
            return
        quadro = self._leitor.quadro(self.barra_posicao.value() / 1000.0)
        if quadro is None:
            self.tela.limpar("Sem imagem neste ponto")
        else:
            self.tela.definir_quadro(quadro)
        self._atualizar_tempos()

    def _passo(self, segundos: float) -> None:
        if not self.barra_posicao.isEnabled():
            return
        self.barra_posicao.setValue(
            self.barra_posicao.value() + int(segundos * 1000))

    def _atualizar_tempos(self) -> None:
        if self._leitor is None:
            self.rotulo_tempo.setText("—")
            self.rotulo_marcas.setText("")
            return
        agora = self.barra_posicao.value() / 1000.0
        self.rotulo_tempo.setText(
            f"{_mmss(agora)}  /  {_mmss(self._leitor.duracao)}")
        inicio, fim = self._marcas[self._linha_previa]
        fim_real = fim if fim > 0 else self._leitor.duracao
        self.rotulo_marcas.setText(
            f"início {_mmss(inicio)}   fim {_mmss(fim_real)}   "
            f"fica {_mmss(max(0.0, fim_real - inicio))}")
        self.faixa.definir(self._leitor.duracao, inicio, fim, agora)

    # -- marcacao ----------------------------------------------------------

    def _marcar(self, qual: int) -> None:
        """0 = inicio, 1 = fim. O ponto e o quadro que esta na tela."""
        if self._leitor is None or self._linha_previa < 0:
            return
        agora = self.barra_posicao.value() / 1000.0
        marcas = self._marcas[self._linha_previa]

        if qual == 0:
            # Marcar o inicio depois do fim deixaria o trecho vazio; em vez de
            # recusar, o fim volta a valer "ate o final", que e o que a pessoa
            # quer dizer ao remarcar o comeco mais para a frente.
            marcas[0] = agora
            if marcas[1] and marcas[1] <= agora:
                marcas[1] = 0.0
        else:
            if agora <= marcas[0]:
                QMessageBox.information(
                    self, "Fim antes do início",
                    "Este ponto vem antes do início marcado. Mova a barra para "
                    "depois dele, ou marque o início de novo.")
                return
            marcas[1] = agora

        self._recalcular()

    @Slot()
    def _limpar_marcas(self) -> None:
        if self._linha_previa < 0:
            return
        self._marcas[self._linha_previa] = [0.0, 0.0]
        self._recalcular()

    # -- lista -------------------------------------------------------------

    @Slot()
    def _adicionar(self) -> None:
        caminhos, _ = QFileDialog.getOpenFileNames(
            self, "Escolher vídeos", str(pasta_videos_padrao()), _FILTRO)
        primeira = self.tabela.rowCount()
        for caminho in caminhos:
            self._acrescentar_linha(Path(caminho))
        if self.tabela.rowCount() > primeira:
            self.tabela.selectRow(primeira)
        self._recalcular()

    def _acrescentar_linha(self, caminho: Path, marcas=None) -> None:
        info = edicao.informacoes(caminho)
        if info["erro"]:
            QMessageBox.warning(
                self, "Arquivo não pôde ser lido",
                f"«{caminho.name}» não abriu:\n\n{info['erro']}")
            return

        linha = self.tabela.rowCount()
        self.tabela.insertRow(linha)
        self._duracoes.append(info["duracao"])
        self._marcas.append(list(marcas) if marcas else [0.0, 0.0])

        item = QTableWidgetItem(caminho.name)
        item.setData(Qt.UserRole, str(caminho))
        item.setToolTip(
            f"{caminho}\n{info['largura']}x{info['altura']} "
            f"{info['codec_video']}/{info['codec_audio'] or 'sem áudio'}\n"
            f"{_mmss(info['duracao'])}  ·  {info['bytes'] / 1e6:.1f} MB")
        self.tabela.setItem(linha, _COL_ARQUIVO, item)
        for coluna in (_COL_INICIO, _COL_FIM, _COL_DURACAO):
            self.tabela.setItem(linha, coluna, QTableWidgetItem(""))

    @Slot()
    def _remover(self) -> None:
        for linha in sorted({i.row() for i in self.tabela.selectedIndexes()},
                            reverse=True):
            self.tabela.removeRow(linha)
            del self._duracoes[linha]
            del self._marcas[linha]
        self._linha_previa = -1
        self._linha_escolhida()
        self._recalcular()

    def _mover(self, passo: int) -> None:
        linhas = sorted({i.row() for i in self.tabela.selectedIndexes()})
        if len(linhas) != 1:
            return
        origem = linhas[0]
        destino = origem + passo
        if not 0 <= destino < self.tabela.rowCount():
            return
        for lista in (self._duracoes, self._marcas):
            lista[origem], lista[destino] = lista[destino], lista[origem]
        item_o = self.tabela.takeItem(origem, _COL_ARQUIVO)
        item_d = self.tabela.takeItem(destino, _COL_ARQUIVO)
        self.tabela.setItem(origem, _COL_ARQUIVO, item_d)
        self.tabela.setItem(destino, _COL_ARQUIVO, item_o)
        self._linha_previa = -1
        self.tabela.selectRow(destino)
        self._recalcular()

    # -- estado ------------------------------------------------------------

    def _recalcular(self) -> None:
        for linha in range(self.tabela.rowCount()):
            inicio, fim = self._marcas[linha]
            duracao = self._duracoes[linha]
            fim_real = fim if fim > 0 else duracao
            self.tabela.item(linha, _COL_INICIO).setText(
                _mmss(inicio) if inicio > 0 else "—")
            self.tabela.item(linha, _COL_FIM).setText(
                _mmss(fim) if fim > 0 else "—")
            self.tabela.item(linha, _COL_DURACAO).setText(
                _mmss(max(0.0, fim_real - inicio)))
        self._atualizar_tempos()
        self._atualizar_estado()

    def _trechos(self) -> list[edicao.Trecho]:
        trechos = []
        for linha in range(self.tabela.rowCount()):
            caminho = Path(self.tabela.item(linha, _COL_ARQUIVO).data(Qt.UserRole))
            inicio, fim = self._marcas[linha]
            trechos.append(edicao.Trecho(caminho, inicio, fim if fim > 0 else None))
        return trechos

    @Slot()
    def _atualizar_estado(self) -> None:
        total = self.tabela.rowCount()
        rodando = self._trabalho is not None
        recomprimir = self.check_recomprimir.isChecked()
        tem_previa = self._leitor is not None

        self.combo_codificador.setEnabled(recomprimir and not rodando)
        self.spin_qualidade.setEnabled(recomprimir and not rodando)
        self.botao_salvar.setEnabled(total > 0 and not rodando)
        for widget in (self.botao_adicionar, self.botao_remover,
                       self.botao_subir, self.botao_descer,
                       self.check_recomprimir, self.tabela,
                       self.barra_posicao):
            widget.setEnabled(not rodando and (widget is not self.barra_posicao
                                               or tem_previa))
        for widget in (self.botao_marcar_inicio, self.botao_marcar_fim,
                       self.botao_limpar_marcas):
            widget.setEnabled(tem_previa and not rodando)

        if rodando:
            return
        if total == 0:
            self.rodape.setText("")
            return

        soma = sum(max(0.0, (f if f > 0 else d) - i)
                   for (i, f), d in zip(self._marcas, self._duracoes))
        partes = [f"{total} trecho(s)  ·  {_mmss(soma)} no total."]
        if recomprimir:
            partes.append("Recomprimindo: corte no quadro exato, arquivo menor, "
                          "demora.")
        else:
            partes.append("Sem recomprimir: instantâneo e sem perda, mas o corte "
                          "cai no quadro-chave mais próximo.")
            impedimento = edicao.compativeis(self._trechos()) if total > 1 else ""
            if impedimento:
                partes.append("\n⚠  " + impedimento.split("\n")[0])
        self.rodape.setText("  ".join(partes))

    # -- execucao ----------------------------------------------------------

    @Slot()
    def _salvar(self) -> None:
        trechos = self._trechos()
        if not trechos:
            return

        recomprimir = self.check_recomprimir.isChecked()
        if not recomprimir:
            impedimento = edicao.compativeis(trechos)
            if impedimento:
                resposta = QMessageBox.question(
                    self, "Não dá para juntar sem recomprimir",
                    impedimento + "\n\nRecomprimir agora?",
                    QMessageBox.Yes | QMessageBox.No)
                if resposta != QMessageBox.Yes:
                    return
                self.check_recomprimir.setChecked(True)
                recomprimir = True

        sugerido = trechos[0].caminho
        extensao = ".mp4" if recomprimir else sugerido.suffix
        alvo, _ = QFileDialog.getSaveFileName(
            self, "Salvar resultado como",
            str(sugerido.with_name(f"{sugerido.stem}_editado{extensao}")),
            _FILTRO)
        if not alvo:
            return

        saida = Path(alvo)
        if saida in {t.caminho for t in trechos}:
            QMessageBox.warning(
                self, "Escolha outro nome",
                "O arquivo de saída é um dos arquivos de entrada. Gravar por "
                "cima dele destruiria o material enquanto ele ainda está sendo "
                "lido.")
            return

        self._iniciar(trechos, saida, edicao.Receita(
            modo=edicao.MODO_RECOMPRIMIR if recomprimir else edicao.MODO_COPIA,
            codificador=self.combo_codificador.currentData() or "libx264",
            qualidade=self.spin_qualidade.value(),
        ))

    def _iniciar(self, trechos, saida, receita) -> None:
        self.barra.setValue(0)
        self.barra.show()
        self.botao_cancelar.show()
        self.rodape.setText(f"Escrevendo {saida.name}…")

        trabalho = _Trabalho(trechos, saida, receita, self)
        trabalho.progrediu.connect(lambda f: self.barra.setValue(int(f * 1000)))
        trabalho.terminou.connect(self._terminou)
        trabalho.finished.connect(trabalho.deleteLater)
        self._trabalho = trabalho
        self._atualizar_estado()
        trabalho.start()

    @Slot()
    def _cancelar(self) -> None:
        if self._trabalho is not None:
            self._trabalho.cancelar()
            self.rodape.setText("Cancelando…")

    @Slot(object)
    def _terminou(self, resultado) -> None:
        self._trabalho = None
        self.barra.hide()
        self.botao_cancelar.hide()
        self._atualizar_estado()

        if resultado.cancelado:
            self.rodape.setText("Cancelado. O arquivo pela metade foi apagado.")
            return
        if resultado.erro:
            QMessageBox.critical(self, "Não deu certo", resultado.erro)
            self.rodape.setText("")
            return

        info = edicao.informacoes(resultado.saida)
        linhas = [
            f"{resultado.saida.name}  ·  {_mmss(info['duracao'])}  ·  "
            f"{info['bytes'] / 1e6:.1f} MB",
            f"{info['largura']}x{info['altura']}  "
            f"{info['codec_video']}/{info['codec_audio'] or 'sem áudio'}  ·  "
            f"{resultado.quadros} quadros",
        ]
        # Honestidade sobre o corte: sem recompressao o inicio real e o do
        # quadro-chave, e esconder isso faria o usuario duvidar da propria marca.
        if resultado.desvio_maximo > 0.05:
            linhas.append(
                f"O corte caiu {resultado.desvio_maximo:.2f} s antes do que você "
                "marcou — é o quadro-chave mais próximo. Marque «Recomprimir» "
                "para o corte exato.")
        texto = "\n".join(linhas)
        self.rodape.setText(texto)
        QMessageBox.information(self, "Pronto", texto)

    # -- encerramento ------------------------------------------------------

    def reject(self) -> None:  # noqa: D102
        if self._trabalho is not None:
            resposta = QMessageBox.question(
                self, "Parar o trabalho?",
                "Ainda está escrevendo o arquivo. Fechar cancela e apaga o "
                "que foi escrito até agora.",
                QMessageBox.Yes | QMessageBox.No)
            if resposta != QMessageBox.Yes:
                return
            self._trabalho.cancelar()
            self._trabalho.wait(5000)
        if self._leitor is not None:
            self._leitor.fechar()
            self._leitor = None
        super().reject()
