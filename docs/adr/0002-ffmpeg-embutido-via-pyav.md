# ADR-0002 — FFmpeg embutido via PyAV, não subprocessos do `ffmpeg.exe`

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

Ler de uma placa de captura, decodificar, mostrar na tela e gravar em disco é
tudo trabalho do FFmpeg. Existem duas formas de usá-lo a partir do Python:

1. **Pilotar o binário** — montar uma linha de comando, abrir o processo e ler
   quadros crus do `stdout`.
2. **Ligar-se à biblioteca** — usar as `libav*` diretamente, via
   [PyAV](https://pyav.org).

A escolha decide quase tudo o que vem depois, porque define o que o programa
consegue *saber* sobre o que está acontecendo.

## Decisão

**PyAV** para toda a captura, decodificação, remultiplexação e codificação.
O binário `ffmpeg` continua sendo usado, mas para **uma única coisa** no
Windows: enumerar os formatos que a placa aceita
(`ffmpeg -f dshow -list_options`), porque essa listagem não é exposta pela API
das bibliotecas.

## Consequências

- Acesso a cada **pacote** individualmente. Sem isso, nada de descartar quadros
  de enchimento pelo tamanho ([0008](0008-descartar-quadros-de-enchimento.md)),
  nada de remultiplexar sem recodificar
  ([0006](0006-dois-perfis-de-gravacao.md)) e nada de medir taxa real e custo de
  CPU por quadro ([0009](0009-medir-em-vez-de-confiar.md)). Essas três coisas
  são o que distingue este programa de um player qualquer, e todas dependem
  desta decisão.
- Erros chegam como exceções Python com mensagem, e não como texto solto em
  `stderr` para adivinhar por expressão regular. Isso torna possível traduzir
  "I/O error" em *"a placa aceita um programa por vez, feche o VLC"* —
  `_mensagem_abertura` em [`captura.py`](../../capturador/captura.py).
- Sem processo filho: nenhuma janela de console piscando, nenhum processo órfão
  se o aplicativo morrer, nenhum custo de copiar quadros crus por um pipe.
- Em troca, ficamos presos ao FFmpeg **compilado dentro do wheel do PyAV**. Nem
  todo wheel traz os mesmos demuxers — no Linux, `pulse` pode simplesmente não
  existir. Por isso `formato_entrada_audio()` consulta `av.formats_available`
  antes de escolher o backend, em vez de assumir que ter o `pactl` instalado
  basta.
- No Windows resta uma dependência externa (`winget install Gyan.FFmpeg`) só
  para a enumeração. É um incômodo real de instalação, aceito porque a
  alternativa é não saber que formatos a placa aceita — e escolher o formato
  certo é metade do valor do programa.

## Alternativas consideradas

**Pilotar o `ffmpeg.exe` por pipe.** Mais simples de começar e evita a
dependência de compilação do PyAV. Descartada porque quadros chegariam já
decodificados em BGRA (1080p60 = ~500 MB/s por um pipe), a gravação sem
recompressão exigiria um *segundo* processo lendo a mesma placa — que só aceita
um cliente por vez — e qualquer diagnóstico viraria raspagem de `stderr`.

**OpenCV (`cv2.VideoCapture`).** Ótimo para visão computacional, péssimo aqui:
entrega quadros já decodificados, não dá acesso ao pacote comprimido original,
não grava áudio e a escolha de formato do dispositivo é justamente o que ele
esconde.

**API nativa de cada sistema (Media Foundation no Windows, V4L2 direto no
Linux).** Duas implementações completas para manter, em troca de nada que o
FFmpeg já não faça.
