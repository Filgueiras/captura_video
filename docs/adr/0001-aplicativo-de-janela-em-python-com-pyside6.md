# ADR-0001 — Aplicativo de janela em Python com PySide6

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

O problema a resolver é estreito: ver e gravar o que chega numa placa de captura
HDMI→USB. O OBS resolve isso e mais quinhentas coisas, ao custo de uma curva de
aprendizado que não se justifica para "abrir e ver". Players genéricos (VLC,
câmera do Windows) abrem, mas negociam com a placa o primeiro formato oferecido
— normalmente cru e de baixa resolução — e entregam imagem borrada a 5 fps.

O programa precisa, ao mesmo tempo:

- desenhar vídeo ao vivo com latência baixa;
- tocar áudio ao vivo em sincronia razoável com a imagem;
- rodar igual em Windows 10 e em Ubuntu/Zorin, sem duas bases de código;
- ser distribuível para quem não tem nada instalado.

## Decisão

Aplicativo **desktop nativo** escrito em Python, com a interface em **PySide6**
(binding oficial do Qt 6).

Qt entra por três motivos concretos, e não por preferência: desenha em widget
nativo com repintura barata (`QPainter` sobre `QImage`, ver
[0015](0015-previa-por-polling.md)), traz saída de áudio de baixo nível pronta
(`QAudioSink`, sem dependência extra) e é o único conjunto que se comporta igual
nos dois sistemas-alvo sem código condicional na camada visual.

## Consequências

- Uma base de código só. A única parte que sabe qual sistema está rodando é
  [`dispositivos.py`](../../capturador/dispositivos.py) — ver
  [0003](0003-fronteira-de-plataforma-em-dispositivos.md).
- O empacotamento fica pesado: Qt + FFmpeg são ~200 MB no executável final. Para
  um programa que grava arquivos de 150 MB por minuto, o disco não é o gargalo.
- `QAudioSink` resolve a monitoração sem trazer PortAudio, sounddevice ou
  PyAudio para o projeto.
- Fica-se preso ao ciclo de vida do Qt: nada de trabalho demorado na thread da
  interface, sob pena de a janela congelar — o que gera
  [0014](0014-trabalho-demorado-em-qthread.md).
- Licença: o PySide6 é LGPL, o que permite distribuir o executável sem abrir o
  código, desde que as bibliotecas Qt continuem substituíveis (o modo pasta do
  [0018](0018-empacotar-com-pyinstaller-em-modo-pasta.md) satisfaz isso
  naturalmente).

## Alternativas consideradas

**Interface web local (Flask/FastAPI + navegador).** Instalação trivial e visual
moderno de graça. Descartada por dois motivos: streaming de vídeo ao vivo para o
navegador exige recodificar tudo em MJPEG ou WebRTC — justamente a recompressão
que o [0006](0006-dois-perfis-de-gravacao.md) existe para evitar — e o acesso a
dispositivos de captura pelo navegador é limitado por sandbox. Um usuário
esperando uma janela também não espera abrir o Chrome.

**Tkinter.** Já vem com o Python. Mas não tem saída de áudio, o desenho de vídeo
a 60 fps é sofrível e a aparência denuncia a idade em qualquer sistema.

**Escrever em C++ direto no Qt.** Ganharia desempenho na parte que não é o
gargalo (o gargalo é decodificar JPEG, que o FFmpeg já faz em C) e perderia a
velocidade de iteração que este projeto precisou para descobrir empiricamente o
comportamento das placas — ver [0009](0009-medir-em-vez-de-confiar.md).

**Electron / Tauri.** Mesmo problema do caminho web, com um runtime a mais.
