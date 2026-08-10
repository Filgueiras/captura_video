# Documentação

| Documento | Para quê |
|---|---|
| [COMO_RODAR.md](COMO_RODAR.md) | instalar as dependências e abrir o programa nos dois sistemas |
| [COMO_GERAR_EXECUTAVEL.md](COMO_GERAR_EXECUTAVEL.md) | empacotar num executável que roda sem Python instalado |
| [adr/](adr/) | as decisões de arquitetura e por que cada uma foi tomada |

Para o que o programa faz e como usar a interface, veja o
[README](../README.md) na raiz. Para diagnosticar uma placa que não aparece,
[COMO_ENCONTRAR_A_PLACA.md](../COMO_ENCONTRAR_A_PLACA.md).

---

## As decisões (ADRs)

Um ADR (*Architecture Decision Record*) registra **uma** decisão: o problema
que existia, o que foi escolhido, e o que se ganhou e perdeu com isso. Serve
para quem chegar depois — inclusive nós, daqui a seis meses — não desfazer sem
querer algo que foi decidido por um motivo que não está mais óbvio no código.

Regra prática: se alguém pode olhar uma linha e pensar *"isso está errado, vou
simplificar"*, e estiver enganado, essa linha merece um ADR.

### Base

| # | Decisão |
|---|---|
| [0001](adr/0001-aplicativo-de-janela-em-python-com-pyside6.md) | Aplicativo de janela em Python com PySide6 |
| [0002](adr/0002-ffmpeg-embutido-via-pyav.md) | FFmpeg embutido via PyAV, não subprocessos do `ffmpeg.exe` |
| [0003](adr/0003-fronteira-de-plataforma-em-dispositivos.md) | Todo código específico de sistema operacional em `dispositivos.py` |
| [0020](adr/0020-reparar-o-alsa-embutido-no-pyav.md) | Reparar o ALSA embutido no PyAV, que sobe sem configuração no Linux |

### Captura e gravação

| # | Decisão |
|---|---|
| [0004](adr/0004-video-e-audio-em-containers-separados.md) | Vídeo e áudio como containers independentes, uma thread cada |
| [0005](adr/0005-sincronia-por-ancora-de-relogio.md) | Sincronia por âncora de relógio comum |
| [0006](adr/0006-dois-perfis-de-gravacao.md) | Dois perfis: Original (remux, MKV) e H.264 (MP4) |
| [0007](adr/0007-base-de-tempo-em-milissegundos.md) | Base de tempo em milissegundos no fluxo *e* no codec |
| [0008](adr/0008-descartar-quadros-de-enchimento.md) | Descartar os quadros de enchimento que a placa emite |
| [0021](adr/0021-estado-do-audio-pelas-amostras.md) | Julgar o áudio pelas amostras, não pela chegada de blocos |
| [0022](adr/0022-audio-do-computador-por-wasapi.md) | Gravar o áudio do computador por WASAPI, sem filtro de terceiros |

### Descoberta de hardware

| # | Decisão |
|---|---|
| [0009](adr/0009-medir-em-vez-de-confiar.md) | Medir o que a placa e a máquina entregam |
| [0010](adr/0010-duas-recomendacoes.md) | Apresentar duas recomendações em vez de uma "melhor" |
| [0011](adr/0011-parear-video-e-audio-pelo-aparelho.md) | Parear vídeo e áudio pelo aparelho físico |
| [0012](adr/0012-ecra-por-ddagrab-janela-por-gdigrab.md) | Ecrã pelo `ddagrab`, janela pelo `gdigrab` |
| [0013](adr/0013-so-codificadores-que-abrem.md) | Oferecer só os codificadores que abrem nesta máquina |

### Interface

| # | Decisão |
|---|---|
| [0014](adr/0014-trabalho-demorado-em-qthread.md) | Trabalho demorado em `QThread`: listar primeiro, parear depois |
| [0015](adr/0015-previa-por-polling.md) | Prévia por polling, com o quadro já reduzido na thread de captura |
| [0016](adr/0016-aparencia-centralizada-e-paineis-por-lista.md) | Aparência centralizada em `tema.py`, painel montado por lista |
| [0017](adr/0017-preferencias-em-qsettings.md) | Preferências do usuário em `QSettings` |

### Entrega

| # | Decisão |
|---|---|
| [0018](adr/0018-empacotar-com-pyinstaller-em-modo-pasta.md) | Empacotar com PyInstaller em modo pasta |
| [0019](adr/0019-portugues-no-codigo-e-na-interface.md) | Português no código, nos comentários e na interface |

---

## Escrevendo um ADR novo

Copie [adr/modelo.md](adr/modelo.md), use o próximo número livre e acrescente a
linha na tabela acima. ADRs não se editam depois de aceitos: quando uma decisão
muda, escreve-se um ADR novo que a substitui e marca-se o antigo como
**Substituído por 00NN**. O histórico é metade do valor.
